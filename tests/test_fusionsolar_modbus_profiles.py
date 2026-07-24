from hedp.adapters.fusionsolar.modbus_profiles import decode_sun2000_jpl1


def test_decodes_confirmed_jpl1_fields_without_serial_number():
    identity = list(b"SUN2000-4.95KTL-JPL1".ljust(30, b"\0"))
    identity_words = [
        (identity[index] << 8) | identity[index + 1]
        for index in range(0, 30, 2)
    ]
    realtime = [0] * 52
    realtime[0:2] = [0, 6318]
    realtime[16:18] = [0, 3292]
    realtime[21] = 5997
    realtime[23] = 572
    realtime[25] = 0x0200
    realtime[42:44] = [2, 8719]
    realtime[50:52] = [0, 1446]
    storage = [2, 0, 3000, 0, 550]

    result = decode_sun2000_jpl1(
        [
            {"start_address": 30000, "registers": identity_words},
            {"start_address": 32064, "registers": realtime},
            {"start_address": 37000, "registers": storage},
        ]
    )

    assert result["model"] == "SUN2000-4.95KTL-JPL1"
    assert result["input_power_kw"] == 6.318
    assert result["active_power_kw"] == 3.292
    assert result["grid_frequency_hz"] == 59.97
    assert result["internal_temperature_c"] == 57.2
    assert result["device_status"] == "on_grid"
    assert result["total_yield_kwh"] == 1397.91
    assert result["daily_yield_kwh"] == 14.46
    assert result["storage_power_kw"] == 3.0
    assert result["storage_soc_percent"] == 55.0
    assert "serial" not in result
