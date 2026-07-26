"""Normalize ECHONET Lite Get/INF frames into common observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hedp.observations import ObservationTime, ObservedValue, Quality

from .echonet import (
    INFORMATION,
    PROPERTY_MAP_EPCS,
    EchonetFrame,
    EchonetProperty,
    FrameError,
    confirmed_property_name,
    decode_known_property,
    decode_property_map,
)


class ObservationSource(str, Enum):
    PERIODIC = "periodic"
    EVENT = "event"


@dataclass(frozen=True)
class PropertyObservation:
    epc: int
    name: str | None
    reading: ObservedValue[object]


@dataclass(frozen=True)
class EcoCuteObservation:
    """One partial or complete water-heater observation.

    An INF event normally includes only changed properties.  Missing properties
    therefore are not fabricated.  A later periodic Get reconciles the full
    requested state.
    """

    source: ObservationSource
    properties: tuple[PropertyObservation, ...]
    time: ObservationTime
    transaction_id: int = field(repr=False)
    quality: Quality = Quality.GOOD


def normalize_observation(
    frame: EchonetFrame,
    *,
    time: ObservationTime,
) -> EcoCuteObservation:
    if not frame.is_water_heater_response:
        raise FrameError("frame is not a water-heater Get/INF response")
    epcs = tuple(prop.epc for prop in frame.properties)
    if len(epcs) != len(set(epcs)):
        raise FrameError("response contains duplicate EPCs")
    source = (
        ObservationSource.EVENT
        if frame.service == INFORMATION
        else ObservationSource.PERIODIC
    )
    properties = tuple(_normalize_property(prop) for prop in frame.properties)
    quality = (
        Quality.GOOD
        if all(prop.reading.quality == Quality.GOOD for prop in properties)
        else Quality.UNKNOWN
    )
    return EcoCuteObservation(
        source,
        properties,
        time,
        frame.transaction_id,
        quality,
    )


def normalize_requested_observation(
    frame: EchonetFrame,
    *,
    requested_epcs: tuple[int, ...],
    time: ObservationTime,
) -> EcoCuteObservation:
    """Normalize a Get response and make a partial response explicit.

    ECHONET devices may return fewer properties than requested.  The omitted
    EPCs are represented as missing values rather than being silently dropped
    or filled from a previous poll.  Extra EPCs are ignored at this boundary:
    some observed devices return a stable status subset with every Get, and
    only the properties in the correlated request belong to this batch.
    """

    if len(requested_epcs) != len(set(requested_epcs)):
        raise ValueError("requested_epcs must not contain duplicates")
    observation = normalize_observation(frame, time=time)
    if observation.source is not ObservationSource.PERIODIC:
        raise FrameError("requested observation must be a Get response")
    requested = set(requested_epcs)
    by_epc = {
        prop.epc: prop for prop in observation.properties if prop.epc in requested
    }
    properties = tuple(
        by_epc.get(
            epc,
            PropertyObservation(
                epc,
                confirmed_property_name(epc),
                ObservedValue(None, Quality.MISSING, "requested_property_missing"),
            ),
        )
        for epc in requested_epcs
    )
    quality = (
        Quality.GOOD
        if all(prop.reading.quality == Quality.GOOD for prop in properties)
        else Quality.UNKNOWN
    )
    return EcoCuteObservation(
        observation.source,
        properties,
        time,
        observation.transaction_id,
        quality,
    )


def _normalize_property(prop: EchonetProperty) -> PropertyObservation:
    name = confirmed_property_name(prop.epc)
    if not prop.data:
        return PropertyObservation(
            prop.epc,
            name,
            ObservedValue(None, Quality.MISSING, "property_value_missing"),
        )
    if prop.epc in PROPERTY_MAP_EPCS:
        try:
            property_map = decode_property_map(prop)
        except FrameError:
            return PropertyObservation(
                prop.epc,
                name,
                ObservedValue(None, Quality.INVALID, "property_map_invalid"),
            )
        return PropertyObservation(
            prop.epc,
            name,
            ObservedValue(tuple(sorted(property_map.properties)), Quality.GOOD),
        )

    try:
        value = decode_known_property(prop)
    except FrameError:
        return PropertyObservation(
            prop.epc,
            name,
            ObservedValue(None, Quality.INVALID, "property_value_invalid"),
        )
    if value is None:
        return PropertyObservation(
            prop.epc,
            name,
            ObservedValue(None, Quality.UNKNOWN, "property_not_normalized"),
        )
    if value == "unknown":
        return PropertyObservation(
            prop.epc,
            name,
            ObservedValue(None, Quality.UNKNOWN, "property_value_unknown"),
        )
    return PropertyObservation(
        prop.epc,
        name,
        ObservedValue(value, Quality.GOOD),
    )
