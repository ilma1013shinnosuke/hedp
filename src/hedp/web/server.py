"""Small standard-library server for the local HESTIA dashboard."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .read_model import (
    read_only_dashboard_snapshot_provider,
    unavailable_dashboard_snapshot,
)


_ASSET_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}


_PERIODS = {"day", "7d", "30d"}


def demonstration_snapshot(*, period: str = "day") -> dict[str, Any]:
    """Return value-free sample data for the first visual interface."""

    return {
        "schema": "hestia.interface.demo.v1",
        "mode": "shadow",
        "period": period,
        "observed_at": None,
        "quality": {"status": "good", "reason": "anonymous_demo"},
        "home": {"status": "comfortable", "alerts": 0},
        "energy": {
            "solar_kw": 4.8,
            "home_kw": 2.1,
            "battery_percent": 78,
            "grid_kw": -1.4,
            "today_kwh": 18.6,
            "self_consumption_percent": 91,
            "observations": {},
            "history": [
                {"time": "05:00", "solar_kw": 0.0},
                {"time": "06:00", "solar_kw": 0.2},
                {"time": "07:00", "solar_kw": 1.1},
                {"time": "08:00", "solar_kw": 2.8},
                {"time": "09:00", "solar_kw": 4.1},
                {"time": "10:00", "solar_kw": 5.8},
                {"time": "11:00", "solar_kw": 6.7},
                {"time": "12:00", "solar_kw": 7.2},
                {"time": "13:00", "solar_kw": 6.4},
                {"time": "14:00", "solar_kw": 5.1},
                {"time": "15:00", "solar_kw": 3.8},
                {"time": "16:00", "solar_kw": 2.3},
                {"time": "17:00", "solar_kw": 1.0},
                {"time": "18:00", "solar_kw": 0.2},
            ],
            "battery_history": [
                {"time": "05:00", "battery_percent": 42},
                {"time": "08:00", "battery_percent": 36},
                {"time": "11:00", "battery_percent": 53},
                {"time": "14:00", "battery_percent": 71},
                {"time": "18:00", "battery_percent": 78},
            ],
        },
        "climate": {
            "temperature_c": 23.8,
            "humidity_percent": 48,
            "co2_ppm": 612,
        },
        "devices": [
            {"kind": "light", "label": "照明", "state": "12 / 18"},
            {"kind": "lock", "label": "玄関", "state": "施錠"},
            {"kind": "bath", "label": "給湯", "state": "420 L"},
            {"kind": "washer", "label": "家電", "state": "待機"},
        ],
    }


def _asset(name: str) -> bytes:
    if name not in _ASSET_TYPES:
        raise FileNotFoundError(name)
    return files("hedp.web.static").joinpath(name).read_bytes()


class _DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HESTIA"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = urlsplit(self.path)
        path = request.path
        if path == "/api/summary":
            values = parse_qs(request.query).get("period", ["day"])
            period = values[-1]
            if period not in _PERIODS:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            provider = getattr(self.server, "summary_provider", demonstration_snapshot)
            try:
                summary = _summary_for_period(provider, period)
            except Exception:
                summary = unavailable_dashboard_snapshot(period=period)
            self._send_json(summary)
            return
        asset_name = "index.html" if path in {"/", "/index.html"} else path[1:]
        try:
            payload = _asset(asset_name)
            content_type = _ASSET_TYPES[asset_name]
        except (FileNotFoundError, KeyError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Avoid retaining household access details in ordinary logs."""

    def _send_json(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


def create_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    summary_provider: Callable[..., dict[str, Any]] = demonstration_snapshot,
) -> ThreadingHTTPServer:
    """Create, but do not start, the local dashboard server."""

    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    server = ThreadingHTTPServer((host, port), _DashboardHandler)
    server.summary_provider = summary_provider  # type: ignore[attr-defined]
    return server


def _summary_for_period(
    provider: Callable[..., dict[str, Any]],
    period: str,
) -> dict[str, Any]:
    """Keep zero-argument providers compatible for the default day view."""

    if period == "day":
        return provider()
    return provider(period=period)


def serve_dashboard(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    database_path: str | Path | None = None,
) -> None:
    """Serve until interrupted, optionally using a read-only database view."""

    provider = (
        demonstration_snapshot
        if database_path is None
        else read_only_dashboard_snapshot_provider(database_path)
    )
    server = create_dashboard_server(host, port, summary_provider=provider)
    try:
        print(f"HESTIA interface: http://{host}:{server.server_port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
