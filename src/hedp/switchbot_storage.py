from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2


class SwitchBotStorage:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self.connection: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.migrate()
        return self.connection

    def connect_readonly(self) -> sqlite3.Connection:
        path = Path(self.database_path).resolve()
        self.connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        return self.connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def migrate(self) -> None:
        connection = self._connection()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS switchbot_schema (
                version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS switchbot_devices (
                device_id TEXT PRIMARY KEY,
                current_api_name TEXT NOT NULL,
                device_type TEXT NOT NULL,
                hub_device_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                current_status TEXT,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS switchbot_device_names (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                api_name TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                source TEXT NOT NULL,
                UNIQUE(device_id, api_name, valid_from)
            );
            CREATE TABLE IF NOT EXISTS switchbot_device_locations (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                location TEXT NOT NULL,
                purpose TEXT,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                effective_time_precision TEXT NOT NULL,
                source TEXT NOT NULL,
                notes TEXT,
                UNIQUE(device_id, location, valid_from)
            );
            CREATE TABLE IF NOT EXISTS switchbot_observations (
                observation_id INTEGER PRIMARY KEY,
                canonical_key TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL,
                observed_at_utc TEXT NOT NULL,
                observed_at_local TEXT NOT NULL,
                timezone TEXT NOT NULL,
                observation_kind TEXT NOT NULL,
                temperature_c REAL,
                relative_humidity_percent REAL,
                co2_ppm REAL,
                battery_percent REAL,
                absolute_humidity_g_m3 REAL,
                dew_point_c REAL,
                vpd_kpa REAL,
                power_state TEXT,
                electric_current_ma REAL,
                voltage_v REAL,
                power_consumed_daily_w REAL,
                usage_minutes_of_day REAL,
                online_status TEXT,
                working_status TEXT,
                source TEXT NOT NULL,
                source_file TEXT,
                source_row_number INTEGER,
                source_precision TEXT NOT NULL,
                expected_interval_seconds INTEGER,
                collection_method TEXT NOT NULL,
                measurement_status TEXT NOT NULL,
                raw_payload_json TEXT,
                calculation_method TEXT,
                calculation_version TEXT,
                calculated_from TEXT,
                imported_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS switchbot_observations_device_time
                ON switchbot_observations(device_id, observed_at_utc);
            CREATE TABLE IF NOT EXISTS switchbot_collection_events (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                success INTEGER NOT NULL,
                status_body_empty INTEGER NOT NULL,
                error_type TEXT,
                raw_payload_json TEXT,
                UNIQUE(device_id, collected_at)
            );
            CREATE TABLE IF NOT EXISTS switchbot_import_runs (
                import_id INTEGER PRIMARY KEY,
                source_file TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                rows_read INTEGER NOT NULL DEFAULT 0,
                rows_inserted INTEGER NOT NULL DEFAULT 0,
                exact_duplicates_skipped INTEGER NOT NULL DEFAULT 0,
                timestamp_conflicts INTEGER NOT NULL DEFAULT 0,
                invalid_rows INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS switchbot_import_conflicts (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                existing_payload TEXT NOT NULL,
                incoming_payload TEXT NOT NULL,
                existing_source TEXT NOT NULL,
                incoming_source TEXT NOT NULL,
                resolution TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS switchbot_data_gaps (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                gap_start TEXT NOT NULL,
                gap_end TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                expected_interval_seconds INTEGER NOT NULL,
                previous_observation_at TEXT NOT NULL,
                next_observation_at TEXT NOT NULL,
                likely_reason TEXT NOT NULL,
                status TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                notes TEXT,
                UNIQUE(device_id, gap_start, gap_end, expected_interval_seconds)
            );
            CREATE TABLE IF NOT EXISTS switchbot_hourly_summary (
                device_id TEXT NOT NULL,
                hour_start TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                temperature_min REAL,
                temperature_max REAL,
                temperature_avg REAL,
                humidity_min REAL,
                humidity_max REAL,
                humidity_avg REAL,
                co2_min REAL,
                co2_max REAL,
                co2_avg REAL,
                first_observation_at TEXT NOT NULL,
                last_observation_at TEXT NOT NULL,
                completeness_ratio REAL,
                PRIMARY KEY(device_id, hour_start)
            );
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO switchbot_schema VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
        )
        event_columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(switchbot_collection_events)"
            )
        }
        if "raw_payload_json" not in event_columns:
            connection.execute(
                "ALTER TABLE switchbot_collection_events "
                "ADD COLUMN raw_payload_json TEXT"
            )
        connection.commit()

    def upsert_device(self, device: dict[str, Any], seen_at: datetime) -> None:
        connection = self._connection()
        device_id = str(device["deviceId"])
        name = str(device.get("deviceName", ""))
        existing = connection.execute(
            "SELECT current_api_name FROM switchbot_devices WHERE device_id=?",
            (device_id,),
        ).fetchone()
        timestamp = seen_at.astimezone(timezone.utc).isoformat()
        if existing and existing[0] != name:
            connection.execute(
                "UPDATE switchbot_device_names SET valid_to=? "
                "WHERE device_id=? AND valid_to IS NULL",
                (timestamp, device_id),
            )
        connection.execute(
            """
            INSERT INTO switchbot_devices
              (device_id,current_api_name,device_type,hub_device_id,
               first_seen_at,last_seen_at,current_status)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(device_id) DO UPDATE SET
              current_api_name=excluded.current_api_name,
              device_type=excluded.device_type,
              hub_device_id=excluded.hub_device_id,
              last_seen_at=excluded.last_seen_at,
              current_status=excluded.current_status
            """,
            (device_id, name, str(device.get("deviceType", "")),
             device.get("hubDeviceId"), timestamp, timestamp, "present"),
        )
        if not existing or existing[0] != name:
            connection.execute(
                "INSERT OR IGNORE INTO switchbot_device_names "
                "(device_id,api_name,valid_from,source) VALUES (?,?,?,?)",
                (device_id, name, timestamp, "switchbot_api_v1_1"),
            )
        connection.commit()

    def set_location(
        self, device_id: str, location: str, purpose: str, valid_from: str,
        *, valid_to: str | None = None, precision: str = "day",
        source: str = "user", notes: str | None = None,
    ) -> None:
        self._connection().execute(
            """INSERT OR IGNORE INTO switchbot_device_locations
            (device_id,location,purpose,valid_from,valid_to,
             effective_time_precision,source,notes) VALUES (?,?,?,?,?,?,?,?)""",
            (device_id, location, purpose, valid_from, valid_to, precision,
             source, notes),
        )
        self._connection().commit()

    def set_name_history(
        self, device_id: str, api_name: str, valid_from: str,
        *, valid_to: str | None = None, source: str = "user",
    ) -> None:
        self._connection().execute(
            """INSERT OR IGNORE INTO switchbot_device_names
            (device_id,api_name,valid_from,valid_to,source) VALUES (?,?,?,?,?)""",
            (device_id, api_name, valid_from, valid_to, source),
        )
        self._connection().commit()

    def reconcile_devices(self, present_ids: set[str]) -> None:
        connection = self._connection()
        rows = connection.execute(
            "SELECT device_id FROM switchbot_devices WHERE enabled=1"
        ).fetchall()
        for row in rows:
            if row[0] not in present_ids:
                connection.execute(
                    "UPDATE switchbot_devices SET current_status='missing' "
                    "WHERE device_id=?", (row[0],)
                )
        connection.commit()

    def record_collection_event(
        self, device_id: str, collected_at: datetime, *, success: bool,
        status_body_empty: bool, error_type: str | None,
        raw_payload_json: str | None,
    ) -> None:
        self._connection().execute(
            """INSERT OR IGNORE INTO switchbot_collection_events
            (device_id,collected_at,success,status_body_empty,error_type,
             raw_payload_json) VALUES (?,?,?,?,?,?)""",
            (device_id, collected_at.isoformat(), int(success),
             int(status_body_empty), error_type, raw_payload_json),
        )
        self._connection().commit()

    @staticmethod
    def canonical_key(observation: dict[str, Any]) -> str:
        identity = {
            key: observation.get(key)
            for key in (
                "device_id", "observed_at_utc", "observation_kind",
                "temperature_c", "relative_humidity_percent", "co2_ppm",
                "battery_percent", "absolute_humidity_g_m3", "dew_point_c",
                "vpd_kpa", "power_state", "electric_current_ma", "voltage_v",
                "power_consumed_daily_w", "usage_minutes_of_day", "online_status",
                "working_status", "source_precision",
            )
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def insert_observation(self, observation: dict[str, Any]) -> str:
        connection = self._connection()
        canonical = self.canonical_key(observation)
        if connection.execute(
            "SELECT 1 FROM switchbot_observations WHERE canonical_key=?",
            (canonical,),
        ).fetchone():
            return "duplicate"
        conflict = connection.execute(
            "SELECT * FROM switchbot_observations WHERE device_id=? "
            "AND observed_at_utc=? AND observation_kind=? LIMIT 1",
            (observation["device_id"], observation["observed_at_utc"],
             observation["observation_kind"]),
        ).fetchone()
        if conflict:
            connection.execute(
                """INSERT INTO switchbot_import_conflicts
                (device_id,observed_at,existing_payload,incoming_payload,
                 existing_source,incoming_source,resolution,detected_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (observation["device_id"], observation["observed_at_utc"],
                 json.dumps(dict(conflict), ensure_ascii=False),
                 json.dumps(observation, ensure_ascii=False), conflict["source"],
                 observation["source"], "kept_both", self._now()),
            )
        columns = [
            "canonical_key", "device_id", "observed_at_utc",
            "observed_at_local", "timezone", "observation_kind",
            "temperature_c", "relative_humidity_percent", "co2_ppm",
            "battery_percent", "absolute_humidity_g_m3", "dew_point_c",
            "vpd_kpa", "power_state", "electric_current_ma", "voltage_v",
            "power_consumed_daily_w", "usage_minutes_of_day", "online_status",
            "source", "source_file", "source_row_number", "source_precision",
            "expected_interval_seconds", "collection_method",
            "measurement_status", "raw_payload_json", "calculation_method",
            "calculation_version", "calculated_from", "imported_at", "created_at",
        ]
        values = {**observation, "canonical_key": canonical}
        now = self._now()
        values.setdefault("imported_at", now)
        values.setdefault("created_at", now)
        connection.execute(
            f"INSERT INTO switchbot_observations ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            [values.get(column) for column in columns],
        )
        return "conflict" if conflict else "inserted"

    def commit(self) -> None:
        self._connection().commit()

    def devices(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._connection().execute(
            "SELECT * FROM switchbot_devices ORDER BY current_api_name, device_id"
        )]

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        self._connection().execute(
            "UPDATE switchbot_devices SET enabled=? WHERE device_id=?",
            (int(enabled), device_id),
        )
        self._connection().commit()

    def rows(self, query: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self._connection().execute(query, parameters)]

    def rebuild_hourly(self) -> int:
        connection = self._connection()
        connection.execute("DELETE FROM switchbot_hourly_summary")
        connection.execute(
            """INSERT INTO switchbot_hourly_summary
            SELECT device_id, substr(observed_at_utc,1,13)||':00:00+00:00',
              count(*), min(temperature_c), max(temperature_c), avg(temperature_c),
              min(relative_humidity_percent), max(relative_humidity_percent),
              avg(relative_humidity_percent), min(co2_ppm), max(co2_ppm),
              avg(co2_ppm), min(observed_at_utc), max(observed_at_utc),
              CASE WHEN min(expected_interval_seconds)<=60
                   THEN min(1.0,count(*)/60.0) ELSE min(1.0,count(*)/1.0) END
            FROM switchbot_observations
            GROUP BY device_id, substr(observed_at_utc,1,13)"""
        )
        connection.commit()
        return int(connection.execute(
            "SELECT count(*) FROM switchbot_hourly_summary"
        ).fetchone()[0])

    def rebuild_gaps(self) -> int:
        connection = self._connection()
        connection.execute("DELETE FROM switchbot_data_gaps")
        connection.execute(
            """INSERT INTO switchbot_data_gaps
            (device_id,gap_start,gap_end,duration_seconds,
             expected_interval_seconds,previous_observation_at,
             next_observation_at,likely_reason,status,detected_at,notes)
            SELECT device_id,previous_at,observed_at_utc,
              round((julianday(observed_at_utc)-julianday(previous_at))*86400),
              expected_interval_seconds,previous_at,observed_at_utc,
              'unknown','open',?,NULL
            FROM (
              SELECT device_id,observed_at_utc,expected_interval_seconds,
                lag(observed_at_utc) OVER (
                  PARTITION BY device_id,source ORDER BY observed_at_utc
                ) previous_at
              FROM switchbot_observations
            ) WHERE previous_at IS NOT NULL AND
              (julianday(observed_at_utc)-julianday(previous_at))*86400
              > expected_interval_seconds*2""",
            (self._now(),),
        )
        connection.commit()
        return int(connection.execute(
            "SELECT count(*) FROM switchbot_data_gaps"
        ).fetchone()[0])

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("SwitchBotStorage is not connected")
        return self.connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
