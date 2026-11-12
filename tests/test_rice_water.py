"""Проверки настоящего файла data/rice_water.csv (пункт 9: водный баланс риса)."""

import pytest

from src.data_loader import DATA_DIR, load_table
from src.units import mm_to_m3


@pytest.fixture(scope="module")
def rice():
    df = load_table(DATA_DIR / "rice_water.csv")
    return {(r.param, r.measure): r for r in df.itertuples()}


def test_all_eleven_values_load_and_none_is_real(rice):
    # Литературные и сценарные значения — только assumed, не real.
    assert len(rice) == 11
    assert {r.status for r in rice.values()} == {"assumed"}


def test_fao_values_and_units(rice):
    # FAO Training manual no. 3, раздел 4.4: SAT = 200 мм, WL = 100 мм, PERC = 4 / 6 / 8 мм/сут.
    assert (rice["rice_saturation", "base"].value, rice["rice_saturation", "base"].unit) == (200, "mm")
    assert (rice["rice_water_layer", "base"].value, rice["rice_water_layer", "base"].unit) == (100, "mm")
    perc = [rice["rice_percolation", m] for m in ("low", "base", "high")]
    assert [p.value for p in perc] == [4, 6, 8]
    assert {p.unit for p in perc} == {"mm/day"}
    for param in ("rice_seasonal_et", "rice_field_supply"):
        assert {r.unit for (p, _), r in rice.items() if p == param} == {"m3/ha"}


def test_ranges_are_ordered_and_hand_check_fits_literature(rice):
    v = {k: r.value for k, r in rice.items()}
    assert v["rice_seasonal_et", "low"] <= v["rice_seasonal_et", "high"]
    assert v["rice_field_supply", "improved_low"] <= v["rice_field_supply", "improved_high"]
    assert v["rice_field_supply", "improved_high"] < v["rice_field_supply", "existing_low"]
    assert v["rice_field_supply", "existing_low"] <= v["rice_field_supply", "existing_high"]

    # Ручной пример: SAT и WL однократно, PERC × 150 дней, плюс ET 10–11 тыс. м³/га (без вычета Pe).
    days = 150
    once = v["rice_saturation", "base"] + v["rice_water_layer", "base"]  # 300 мм, один раз
    low = mm_to_m3(once + v["rice_percolation", "low"] * days) + v["rice_seasonal_et", "low"]
    high = mm_to_m3(once + v["rice_percolation", "high"] * days) + v["rice_seasonal_et", "high"]
    assert low == pytest.approx(19_000)   # (300 + 600) мм = 9000 м³/га + 10 000
    assert high == pytest.approx(26_000)  # (300 + 1200) мм = 15 000 м³/га + 11 000
    # Диапазон пересекается с «улучшенной» нормой САНИИРИ и лежит ниже «существующей».
    assert low <= v["rice_field_supply", "improved_high"]
    assert high < v["rice_field_supply", "existing_low"]
