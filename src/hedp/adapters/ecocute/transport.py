"""Read-only ECHONET Lite UDP transport for an EcoCute water heater."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import Callable

from .echonet import (
    CONTROLLER_OBJECT,
    GET_RESPONSE,
    WATER_HEATER_CLASS,
    EchonetFrame,
    FrameError,
    SET_RESPONSE,
    build_set_request,
    build_get_request,
    parse_frame,
)


ECHONET_LITE_PORT = 3610
GET_SERVICE_NOT_AVAILABLE = 0x52
SET_SERVICE_NOT_AVAILABLE = 0x51


class EchonetTransportError(RuntimeError):
    """A safe network error that does not include an address or packet."""


class EchonetResponseError(RuntimeError):
    """A safe protocol error that does not include device-provided values."""


@dataclass(frozen=True)
class EchonetExchange:
    request: bytes
    response: bytes
    frame: EchonetFrame


@dataclass(frozen=True)
class EcoCuteSetExchange:
    """Privacy-safe successful Set exchange.

    Raw request/response bytes intentionally stay out of operation receipts.
    """

    frame: EchonetFrame


class _PrivateUdpTransportBase:
    """Shared private-target validation without exposing Get or Set."""

    def __init__(
        self,
        host: str,
        *,
        port: int = ECHONET_LITE_PORT,
        timeout_seconds: float = 3.0,
        maximum_datagrams: int = 32,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        if not host:
            raise ValueError("host must not be empty")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        if not 1 <= maximum_datagrams <= 256:
            raise ValueError("maximum_datagrams must be between 1 and 256")
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.maximum_datagrams = maximum_datagrams
        self._socket_factory = socket_factory

    def _private_target_addresses(self) -> set[str]:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    self.host,
                    self.port,
                    family=socket.AF_INET,
                    type=socket.SOCK_DGRAM,
                )
            }
        except OSError as error:
            raise EchonetTransportError(
                "EcoCute target name cannot be resolved"
            ) from error
        if not addresses:
            raise EchonetTransportError("EcoCute target name cannot be resolved")
        if any(
            not (
                ipaddress.ip_address(address).is_private
                or ipaddress.ip_address(address).is_link_local
            )
            for address in addresses
        ):
            raise EchonetTransportError("EcoCute target must be on a private network")
        return addresses


class EcoCuteReadOnlyUdpTransport(_PrivateUdpTransportBase):
    """Unicast UDP transport whose public API can only issue Get requests."""

    def get(
        self,
        *,
        transaction_id: int,
        epcs: tuple[int, ...],
        instance_code: int = 1,
    ) -> EchonetExchange:
        request = build_get_request(
            transaction_id=transaction_id,
            epcs=epcs,
            instance_code=instance_code,
        )
        addresses = self._private_target_addresses()
        target = next(iter(sorted(addresses)))
        connection = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            connection.settimeout(self.timeout_seconds)
            connection.sendto(request, (target, self.port))
            for _ in range(self.maximum_datagrams):
                raw, sender = connection.recvfrom(65_535)
                if sender[0] not in addresses:
                    continue
                try:
                    frame = parse_frame(raw)
                except FrameError:
                    continue
                if frame.transaction_id != transaction_id:
                    continue
                if frame.source_object != WATER_HEATER_CLASS + bytes((instance_code,)):
                    continue
                if frame.destination_object != CONTROLLER_OBJECT:
                    continue
                if frame.service == GET_SERVICE_NOT_AVAILABLE:
                    raise EchonetResponseError(
                        "EcoCute rejected the read-only Get request"
                    )
                if frame.service != GET_RESPONSE:
                    continue
                return EchonetExchange(request, raw, frame)
        except EchonetResponseError:
            raise
        except (OSError, TimeoutError) as error:
            raise EchonetTransportError("EcoCute is unavailable") from error
        finally:
            connection.close()
        raise EchonetResponseError("matching EcoCute Get response was not received")


class EcoCuteSetUdpTransport(_PrivateUdpTransportBase):
    """Unicast SetC transport with one attempt and no automatic retry."""

    def set(
        self,
        *,
        transaction_id: int,
        epc: int,
        data: bytes,
        instance_code: int = 1,
    ) -> EcoCuteSetExchange:
        request = build_set_request(
            transaction_id=transaction_id,
            epc=epc,
            data=data,
            instance_code=instance_code,
        )
        return self._exchange_set(
            request=request,
            transaction_id=transaction_id,
            expected_epcs=(epc,),
            instance_code=instance_code,
        )

    def _exchange_set(
        self,
        *,
        request: bytes,
        transaction_id: int,
        expected_epcs: tuple[int, ...],
        instance_code: int,
    ) -> EcoCuteSetExchange:
        addresses = self._private_target_addresses()
        target = next(iter(sorted(addresses)))
        connection = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            connection.settimeout(self.timeout_seconds)
            connection.sendto(request, (target, self.port))
            for _ in range(self.maximum_datagrams):
                raw, sender = connection.recvfrom(65_535)
                if sender[0] not in addresses:
                    continue
                try:
                    frame = parse_frame(raw)
                except FrameError:
                    continue
                if frame.transaction_id != transaction_id:
                    continue
                if frame.source_object != WATER_HEATER_CLASS + bytes((instance_code,)):
                    continue
                if frame.destination_object != CONTROLLER_OBJECT:
                    continue
                if frame.service == SET_SERVICE_NOT_AVAILABLE:
                    raise EchonetResponseError("EcoCute rejected the Set request")
                if frame.service != SET_RESPONSE:
                    continue
                if tuple(prop.epc for prop in frame.properties) != expected_epcs or any(
                    prop.data for prop in frame.properties
                ):
                    raise EchonetResponseError(
                        "EcoCute returned an invalid Set response"
                    )
                return EcoCuteSetExchange(frame)
        except EchonetResponseError:
            raise
        except socket.timeout as error:
            raise TimeoutError("EcoCute Set result is unknown") from error
        except OSError as error:
            raise EchonetTransportError("EcoCute is unavailable") from error
        finally:
            connection.close()
        raise EchonetResponseError("matching EcoCute Set response was not received")
