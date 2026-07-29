"""Compatibility names for the shared low-latency Execution session."""

from __future__ import annotations

from hedp.operations.immediate import (
    ImmediateExecutionSession,
    PreparedOperation,
)


PreparedLightOperation = PreparedOperation


class FastLightControlSession(ImmediateExecutionSession):
    """SwitchBot-compatible name for the shared immediate session."""
