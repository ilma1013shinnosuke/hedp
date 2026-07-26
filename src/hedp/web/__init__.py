"""Local, read-only HESTIA web interface."""

from .server import create_dashboard_server, serve_dashboard

__all__ = ["create_dashboard_server", "serve_dashboard"]
