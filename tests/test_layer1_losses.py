"""Тесты src/layer1_losses.py: эффективные осадки, КПД, вода риса, единицы."""

import numpy as np
import pandas as pd
import pytest

from src import layer1_losses as l1


# --- Эффективные осадки USDA SCS (S090) ---

def test_pe_usda_scs_hand_values():
    assert l1.pe_usda_scs(0.0) == 0.0
    # P = 100: 100 × (125 − 20) / 125 = 84
    assert l1.pe_usda_scs(100.0) == pytest.approx(84.0)
    # P = 10: 10 × (125 − 2) / 125 = 9.84
    assert l1.pe_usda_scs(10.0) == pytest.approx(9.84)
    # P = 300: 125 + 30 = 155
    assert l1.pe_usda_scs(300.0) == pytest.approx(155.0)


def test_pe_usda_scs_continuous_at_250_and_bounded():
    # Обе ветви дают 150 мм при P = 250 (проверка правильной расстановки скобок, см. S090)
    assert l1.pe_usda_scs(250.0) == pytest.approx(150.0)
    assert l1.pe_usda_scs(249.999) == pytest.approx(150.0, abs=1e-3)
    p = np.linspace(0, 600, 61)
    pe = l1.pe_usda_scs(p)
    assert (pe <= p + 1e-9).all() and (pe >= 0).all()
    with pytest.raises(ValueError):
        l1.pe_usda_scs(-1.0)


# --- Ручные примеры баланса ---

def _season(start, n, etc_per_day):
    dates = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame({"date": dates, "etc_mm": etc_per_day})


def _precip(start, end, per_day):
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(per_day, index=idx, dtype=float)


def test_zero_rain_gives_zero_pe_and_nir_equals_etc():
    daily = _season("2021-05-01", 61, 5.0)  # май + июнь, 305 мм
    months = l1.monthly_balance(daily, l1.monthly_precip(_precip("2021-05-01", "2021-06-30", 0.0)))
    assert months["pe_mm"].sum() == 0.0
    assert months["nir_mm"].sum() == pytest.approx(305.0)


def test_nir_never_negative_when_rain_exceeds_etc():
    # 10 мм/сут дождя (310 мм за май -> Pe = 125 + 31 = 156) при ETc 1 мм/сут -> NIR = 0, а не минус
    daily = _season("2021-05-01", 31, 1.0)
    months = l1.monthly_balance(daily, l1.monthly_precip(_precip("2021-05-01", "2021-05-31", 10.0)))
    assert months["pe_mm"].iloc[0] == pytest.approx(156.0)
    assert (months["nir_mm"] >= 0).all() and months["nir_mm"].sum() == 0.0


def test_pe_prorated_by_season_days_in_month():
    # Сезон занимает 15 из 30 дней июня; P июня = 30 мм -> Pe месяца = 30 × 119 / 125 = 28.56 -> половина
    daily = _season("2021-06-16", 15, 2.0)
    months = l1.monthly_balance(daily, l1.monthly_precip(_precip("2021-06-01", "2021-06-30", 1.0)))
    assert months["pe_mm"].iloc[0] == pytest.approx(28.56 / 2)


def test_hand_example_600mm_eff_075_06_is_13333_m3():
    # Критерий модуля 3 (docs/plan.md): 600 мм, КПД полива 0.75, КПД каналов 0.6 -> 13 333 м³/га
    months = pd.DataFrame({"days": [100], "etc_mm": [600.0], "pe_mm": [0.0],
                           "nir_mm": [600.0], "field_need_mm": [600.0]})
    w = l1.season_water(months, eff_field=0.75, eff_canal=0.6, flooded=False)
    assert w["plant_m3_ha"] == pytest.approx(6000.0)
    assert w["field_m3_ha"] == pytest.approx(8000.0)
    assert w["river_m3_ha"] == pytest.approx(13333.333, abs=0.01)


def test_rice_tm3_april_example():
    # FAO TM3, раздел 4.4 (S082): ETo 6 × Kc 1.1 × 30 дн. = 198, SAT 0, PERC 5 мм/сут × 30 = 150,
    # WL 100, Pe 135 -> IN = 313 мм. Без дождя наша формула даёт 198 + 0 + 100 + 150 = 448 = 313 + 135.
    daily = _season("2021-04-01", 30, 6.6)
    p = l1.monthly_precip(_precip("2021-04-01", "2021-04-30", 0.0))
    row = l1.monthly_balance(daily, p, rice={"sat": 0.0, "wl": 100.0, "perc": 5.0}).iloc[0]
    assert row["etc_mm"] == pytest.approx(198.0)
    assert row["field_need_mm"] == pytest.approx(448.0)
    assert row["field_need_mm"] - 135.0 == pytest.approx(313.0)


def test_rice_field_has_no_field_efficiency_and_sat_wl_once():
    # Рис: 61 день (май–июнь), ETc 5 мм/сут = 305 мм, SAT 200 + WL 100 один раз, PERC 6 × 61 = 366, Pe = 0
    daily = _season("2021-05-01", 61, 5.0)
    p = l1.monthly_precip(_precip("2021-05-01", "2021-06-30", 0.0))
    months = l1.monthly_balance(daily, p, rice={"sat": 200.0, "wl": 100.0, "perc": 6.0})
    assert list(months["sat_mm"]) == [200.0, 0.0] and list(months["wl_mm"]) == [100.0, 0.0]
    w = l1.season_water(months, eff_field=0.6, eff_canal=0.5, flooded=True)
    assert w["field_mm"] == pytest.approx(305 + 200 + 100 + 366)  # 971 мм, без деления на 0.6
    assert w["river_m3_ha"] == pytest.approx(9710 / 0.5)
    assert w["plant_m3_ha"] == pytest.approx(3050.0)
    assert w["eff_field"] is None


# --- Данные и защита от ошибок ---

EFF = pd.DataFrame([
    ("kyzylorda_fields", "eff_field", "base", 0.6), ("kyzylorda_fields", "eff_field", "low", 0.5),
    ("kyzylorda_canals", "eff_canal", "base", 0.575), ("kyzylorda_canals", "eff_canal", "pessimistic", 0.4),
], columns=["entity", "param", "measure", "value"])


def test_efficiencies_from_data_and_errors():
    assert l1.efficiencies(EFF) == (0.6, 0.575)
    assert l1.efficiencies(EFF, "low", "pessimistic") == (0.5, 0.4)
    with pytest.raises(ValueError, match="найдено 0"):
        l1.efficiencies(EFF, "high")
    bad = EFF.copy()
    bad.loc[0, "value"] = 1.5
    with pytest.raises(ValueError, match="eff_field"):
        l1.efficiencies(bad)


def test_incomplete_precip_month_raises():
    p = _precip("2021-05-01", "2021-05-31", 1.0).drop(pd.Timestamp("2021-05-10"))
    with pytest.raises(ValueError, match="Неполные"):
        l1.monthly_precip(p)


def test_layer1_tables_all_crops_and_units():
    rice_water = pd.DataFrame([
        ("rice", "rice_saturation", "base", 200.0), ("rice", "rice_water_layer", "base", 100.0),
        ("rice", "rice_percolation", "base", 6.0),
    ], columns=["entity", "param", "measure", "value"])
    daily = pd.concat([_season("2021-05-01", 61, 5.0).assign(crop=c, year=2021) for c in ("rice", "wheat")])
    season, _ = l1.layer1_tables(daily, _precip("2021-01-01", "2021-12-31", 0.0), EFF, rice_water)
    assert sorted(season["crop"]) == ["rice", "wheat"]
    wheat = season[season["crop"] == "wheat"].iloc[0]
    assert wheat["field_m3_ha"] == pytest.approx(3050 / 0.6)
    assert wheat["river_m3_ha"] == pytest.approx(3050 / 0.6 / 0.575)
    # м³/га = мм × 10 во всех трёх величинах
    for mm, m3 in (("nir_mm", "plant_m3_ha"), ("field_mm", "field_m3_ha"), ("river_mm", "river_m3_ha")):
        assert season[m3].to_numpy() == pytest.approx(season[mm].to_numpy() * 10)
