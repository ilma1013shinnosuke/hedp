from __future__ import annotations

import csv
import hashlib
import json
from itertools import zip_longest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
import unicodedata
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ElementTree
import zipfile

from hedp.switchbot_storage import SwitchBotStorage


CSV_COLUMNS = (
    "Timestamp",
    "Temperature_Celsius(°C)",
    "Relative_Humidity(%)",
    "Absolute_Humidity(g/m³)",
    "DPT_Celsius(°C)",
    "VPD(kPa)",
)
DEVICE_BY_FILENAME = {
    "2Fトイレ": "D508ED4BD39F",
    "クローゼット": "E2042421588D",
    "バスルーム": "F7F4263069C0",
    "フリースペース": "F6AB0E1D5517",
    "リビング": "E888C195493C",
    "外気温": "D9CF767A857F",
    "玄関": "EA56DAD63611",
    "車内": "C1BD4CEC2D7B",
    "書斎": "D064886F78EF",
    "洗面": "E11EBC4B5382",
    "寝室": "E4BD97F06AB2",
}
TOKYO = ZoneInfo("Asia/Tokyo")


class SwitchBotImporter:
    def __init__(self, storage: SwitchBotStorage) -> None:
        self.storage = storage

    def inspect(self, path: Path) -> dict[str, Any]:
        files = self._files(path)
        return {
            "files": [self._inspect_file(item) for item in files],
            "comparisons": self._comparisons(files),
        }

    def run(self, path: Path, *, dry_run: bool = False) -> dict[str, Any]:
        files = self._files(path)
        comparisons = self._comparisons(files)
        if any(not item["identical"] for item in comparisons):
            return {"files": [], "comparisons": comparisons, "status": "blocked"}
        reports = []
        for file_path in files:
            report = self._import_file(file_path, dry_run=dry_run)
            reports.append(report)
        return {"files": reports, "comparisons": comparisons}

    def _comparisons(self, files: list[Path]) -> list[dict[str, Any]]:
        by_stem: dict[str, dict[str, Path]] = {}
        for path in files:
            stem = path.stem.removesuffix("分")
            by_stem.setdefault(stem, {})[path.suffix.casefold()] = path
        comparisons = []
        for values in by_stem.values():
            if ".csv" not in values or ".xlsx" not in values:
                continue
            differences = rows = 0
            for csv_row, xlsx_row in zip_longest(
                self._rows(values[".csv"]), self._rows(values[".xlsx"])
            ):
                rows += 1
                if csv_row is None or xlsx_row is None:
                    differences += 1
                    continue
                try:
                    csv_value = (
                        self._timestamp(csv_row[1]["Timestamp"]),
                        self._float_values(csv_row[1]),
                    )
                    xlsx_value = (
                        self._timestamp(xlsx_row[1]["Timestamp"]),
                        self._float_values(xlsx_row[1]),
                    )
                except (KeyError, ValueError):
                    differences += 1
                    continue
                if csv_value != xlsx_value:
                    differences += 1
            comparisons.append({
                "csv": str(values[".csv"]), "xlsx": str(values[".xlsx"]),
                "rows_compared": rows, "differences": differences,
                "identical": differences == 0,
            })
        return comparisons

    def _inspect_file(self, path: Path) -> dict[str, Any]:
        device_id = self._device_id(path)
        rows = duplicates = conflicts = invalid = reversed_timestamps = 0
        first = last = None
        previous_timestamp = None
        previous_values = None
        for row_number, row in self._rows(path):
            rows += 1
            try:
                timestamp = row["Timestamp"]
                values = tuple(row.get(column, "") for column in CSV_COLUMNS[1:])
                parsed = self._timestamp(timestamp)
                if previous_timestamp is not None and parsed < previous_timestamp:
                    reversed_timestamps += 1
                if parsed == previous_timestamp:
                    if previous_values == values:
                        duplicates += 1
                    else:
                        conflicts += 1
                previous_timestamp = parsed
                previous_values = values
                first = min(first, parsed) if first else parsed
                last = max(last, parsed) if last else parsed
                self._float_values(row)
            except (KeyError, ValueError):
                invalid += 1
        return {
            "path": str(path), "device_id": device_id, "rows": rows,
            "exact_or_same_value_duplicates": duplicates,
            "timestamp_conflicts": conflicts, "invalid_rows": invalid,
            "reversed_timestamps": reversed_timestamps,
            "first_timestamp": first.isoformat() if first else None,
            "last_timestamp": last.isoformat() if last else None,
            "sha256": self._hash(path),
        }

    def _import_file(self, path: Path, *, dry_run: bool) -> dict[str, Any]:
        inspection = self._inspect_file(path)
        if (inspection["timestamp_conflicts"] or inspection["invalid_rows"]
                or inspection["reversed_timestamps"]):
            return {**inspection, "status": "blocked", "rows_inserted": 0}
        if dry_run:
            return {**inspection, "status": "dry_run", "rows_inserted": 0}
        connection = self.storage._connection()
        started = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            "INSERT INTO switchbot_import_runs "
            "(source_file,file_hash,started_at,status) VALUES (?,?,?,?)",
            (path.name, inspection["sha256"], started, "running"),
        )
        import_id = cursor.lastrowid
        inserted = duplicates = conflicts = invalid = 0
        for row_number, row in self._rows(path):
            try:
                observation = self._observation(path, row_number, row)
                result = self.storage.insert_observation(observation)
                if result == "duplicate":
                    duplicates += 1
                else:
                    inserted += 1
                    conflicts += result == "conflict"
                if (inserted + duplicates) % 10_000 == 0:
                    connection.commit()
            except (KeyError, ValueError):
                invalid += 1
        completed = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """UPDATE switchbot_import_runs SET completed_at=?,rows_read=?,
            rows_inserted=?,exact_duplicates_skipped=?,timestamp_conflicts=?,
            invalid_rows=?,status=? WHERE import_id=?""",
            (completed, inspection["rows"], inserted, duplicates, conflicts,
             invalid, "completed", import_id),
        )
        connection.commit()
        return {**inspection, "status": "completed", "rows_inserted": inserted,
                "duplicates_skipped": duplicates}

    def _observation(
        self, path: Path, row_number: int, row: dict[str, str]
    ) -> dict[str, Any]:
        local = self._timestamp(row["Timestamp"])
        values = self._float_values(row)
        return {
            "device_id": self._device_id(path),
            "observed_at_utc": local.astimezone(timezone.utc).isoformat(),
            "observed_at_local": local.isoformat(), "timezone": "Asia/Tokyo",
            "observation_kind": "environment",
            "temperature_c": values[0],
            "relative_humidity_percent": values[1],
            "absolute_humidity_g_m3": values[2], "dew_point_c": values[3],
            "vpd_kpa": values[4],
            "source": (
                "switchbot_xlsx_export"
                if path.suffix.casefold() == ".xlsx"
                else "switchbot_csv_export"
            ),
            "source_file": path.name, "source_row_number": row_number,
            "source_precision": "second", "expected_interval_seconds": 60,
            "collection_method": "historical_export_import",
            "measurement_status": "observed",
            "raw_payload_json": json.dumps(row, ensure_ascii=False),
            "calculation_method": "source_file_value",
            "calculation_version": "export",
            "calculated_from": "source_file",
        }

    @staticmethod
    def _timestamp(value: str) -> datetime:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=TOKYO)

    @staticmethod
    def _float_values(row: dict[str, str]) -> tuple[float | None, ...]:
        result = []
        for column in CSV_COLUMNS[1:]:
            value = row[column].strip()
            result.append(float(value) if value else None)
        return tuple(result)

    @staticmethod
    def _rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
        if path.suffix.casefold() == ".xlsx":
            yield from SwitchBotImporter._xlsx_rows(path)
            return
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                raise ValueError(f"Unexpected columns in {path.name}")
            yield from enumerate(reader, 2)

    @staticmethod
    def _xlsx_rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
        namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ElementTree.parse(
                    archive.open("xl/sharedStrings.xml")
                ).getroot()
                for item in root.findall(f"{namespace}si"):
                    shared.append("".join(
                        node.text or "" for node in item.iter(f"{namespace}t")
                    ))
            with archive.open("xl/worksheets/sheet1.xml") as stream:
                header: list[str] | None = None
                output_row = 1
                for _, element in ElementTree.iterparse(stream, events=("end",)):
                    if element.tag != f"{namespace}row":
                        continue
                    values: list[str] = []
                    for cell in element.findall(f"{namespace}c"):
                        reference = cell.get("r", "A1")
                        letters = "".join(
                            character for character in reference
                            if character.isalpha()
                        )
                        column_index = 0
                        for character in letters:
                            column_index = column_index * 26 + ord(character) - 64
                        while len(values) < column_index - 1:
                            values.append("")
                        cell_type = cell.get("t")
                        value_node = cell.find(f"{namespace}v")
                        if cell_type == "inlineStr":
                            value = "".join(
                                node.text or ""
                                for node in cell.iter(f"{namespace}t")
                            )
                        elif value_node is None:
                            value = ""
                        elif cell_type == "s":
                            value = shared[int(value_node.text or "0")]
                        else:
                            value = value_node.text or ""
                        values.append(value)
                    if header is None:
                        header = values
                        if tuple(header) != CSV_COLUMNS and (
                            len(header) == len(CSV_COLUMNS)
                            and header[0] == "Timestamp"
                            and header[1].startswith("Temperature_Celsius(")
                            and header[2] == "Relative_Humidity(%)"
                            and header[3].startswith("Absolute_Humidity(")
                            and header[4].startswith("DPT_Celsius(")
                            and header[5] == "VPD(kPa)"
                        ):
                            header = list(CSV_COLUMNS)
                        elif tuple(header) != CSV_COLUMNS:
                            raise ValueError(f"Unexpected columns in {path.name}")
                    else:
                        if values and values[0] and "-" not in values[0]:
                            serial = float(values[0])
                            values[0] = (
                                datetime(1899, 12, 30) + timedelta(days=serial)
                            ).strftime("%Y-%m-%d %H:%M:%S")
                        values.extend([""] * (len(header) - len(values)))
                        output_row += 1
                        yield output_row, dict(zip(header, values))
                    element.clear()

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _files(path: Path) -> list[Path]:
        if path.is_file():
            return [path]
        return sorted(
            item for item in path.iterdir()
            if item.suffix.casefold() in {".csv", ".xlsx"}
        )

    @staticmethod
    def _device_id(path: Path) -> str:
        filename = unicodedata.normalize("NFC", path.name)
        for prefix, device_id in DEVICE_BY_FILENAME.items():
            if filename.startswith(prefix):
                return device_id
        raise ValueError(f"Unknown SwitchBot history filename: {path.name}")
