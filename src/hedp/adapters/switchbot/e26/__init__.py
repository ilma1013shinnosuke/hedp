"""Formal SwitchBot E26 reader and operation adapter."""

from .operation import (
    E26Capability,
    E26CapabilityStatus,
    E26OpenApiReader,
    E26OperationAdapter,
    E26ReadError,
    E26State,
    e26_capabilities,
    parse_e26_status,
)

__all__ = [
    "E26Capability",
    "E26CapabilityStatus",
    "E26OpenApiReader",
    "E26OperationAdapter",
    "E26ReadError",
    "E26State",
    "e26_capabilities",
    "parse_e26_status",
]
