from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from hedp.adapters.fusionsolar.energy_balance_record_builder import FusionSolarEnergyBalanceRecordBuilder
from hedp.storage import RawData


def make_raw():
    start = datetime(2026, 7, 19)
    x_axis = [(start + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(288)]
    data = {metric: ["1.250"] * 288 for metric in FusionSolarEnergyBalanceRecordBuilder.SERIES}
    data["productPower"][0] = "--"
    data["productPower"][1] = None
    data["xAxis"] = x_axis
    data["totalProductPower"] = "12.50"
    return RawData("fusionsolar_energy_balance", datetime.now(timezone.utc), {"data": data}, date(2026, 7, 19))


def test_build_preserves_raw_and_builds_series_and_daily():
    raw = make_raw()
    before = deepcopy(raw.payload)
    records = FusionSolarEnergyBalanceRecordBuilder().build(raw)
    product = [record for record in records if record.metric == "productPower"]
    assert len(product) == 286
    assert product[0].timestamp == datetime(2026, 7, 18, 15, 10, tzinfo=timezone.utc)
    assert product[0].value == 1.25
    assert any(record.metric == "totalProductPower" for record in records)
    assert raw.payload == before


def test_build_rejects_array_length_mismatch():
    raw = make_raw()
    raw.payload["data"]["usePower"].pop()
    with pytest.raises(ValueError, match="length"):
        FusionSolarEnergyBalanceRecordBuilder().build(raw)
