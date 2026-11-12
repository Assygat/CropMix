"""Тесты src/etc.py: ETc = ET0 × Kc, пересчёт мм -> м³/га, полнота результата."""

import numpy as np
import pandas as pd
import pytest

from src import etc


def _series(start, values):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def test_et0_5_kc_1_100_days_is_500mm_5000m3():
    # Критерий модуля 2 (docs/plan.md): ET0 = 5 мм, Kc = 1, 100 дней -> 500 мм = 5000 м³/га
    day = etc.daily_etc(_series("2020-05-01", [5.0] * 100), _series("2020-05-01", [1.0] * 100))
    totals = etc.season_totals(day)
    assert totals["days"] == 100
    assert totals["etc_mm"] == pytest.approx(500.0)
    assert totals["etc_m3_ha"] == pytest.approx(5000.0)
    assert totals["et0_m3_ha"] == pytest.approx(5000.0)


def test_hand_example_varying_kc():
    # Ручной пример: ET0 = 4, 6, 8 мм; Kc = 0.5, 1.0, 1.2 -> ETc = 2 + 6 + 9.6 = 17.6 мм = 176 м³/га
    day = etc.daily_etc(_series("2020-07-01", [4, 6, 8]), _series("2020-07-01", [0.5, 1.0, 1.2]))
    assert list(day["etc_mm"]) == pytest.approx([2.0, 6.0, 9.6])
    totals = etc.season_totals(day)
    assert totals["etc_mm"] == pytest.approx(17.6)
    assert totals["etc_m3_ha"] == pytest.approx(176.0)
    assert totals["et0_mm"] == pytest.approx(18.0)


def test_et0_only_on_season_days_and_missing_day_raises():
    # ET0 шире сезона — берутся только дни сезона
    et0 = _series("2020-04-01", [3.0] * 60)
    kc = _series("2020-04-11", [1.0] * 10)
    assert etc.season_totals(etc.daily_etc(et0, kc))["etc_mm"] == pytest.approx(30.0)
    # день сезона без ET0 — ошибка, а не ноль
    with pytest.raises(ValueError, match="Нет ET0"):
        etc.daily_etc(et0.drop(pd.Timestamp("2020-04-15")), kc)


def _synthetic_inputs():
    """Две культуры (фиксированный календарь и сезон по заморозкам) и климат 2020–2021."""
    crops = pd.DataFrame([
        ("a", "kc_ini", 0.5), ("a", "kc_mid", 1.0), ("a", "kc_end", 0.5), ("a", "max_height", 1.0),
        ("a", "l_ini", 10), ("a", "l_dev", 10), ("a", "l_mid", 10), ("a", "l_late", 10), ("a", "plant_doy", 121),
        ("b", "kc_ini", 0.4), ("b", "kc_mid", 0.95), ("b", "kc_end", 0.9), ("b", "max_height", 0.7),
        ("b", "l_ini", 10), ("b", "l_dev", 30), ("b", "l_late", 30),
    ], columns=["entity", "param", "value"])
    idx = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    tmin = np.where((idx.month < 4) | (idx.month > 10), -10.0, 12.0)
    wide = {"tmax": 28.0, "tmin": tmin, "rh_mean": 40.0, "u2": 2.5, "rs": 22.0}
    rows = []
    for p, v in wide.items():
        vals = np.broadcast_to(v, len(idx))
        rows += [{"entity": etc.NASA_ENTITY, "param": p, "date": d.strftime("%Y-%m-%d"), "value": float(x)}
                 for d, x in zip(idx, vals)]
    return crops, pd.DataFrame(rows)


def _sites(entity=etc.NASA_ENTITY, lat=44.8, elevation=122.27):
    return pd.DataFrame({"entity": entity, "param": ["lat", "elevation"], "value": [lat, elevation]})


def test_site_coords_from_data_and_missing_entity():
    assert etc.site_coords(_sites(), etc.NASA_ENTITY) == (44.8, 122.27)
    # для другого источника координаты NASA не подставляются молча
    with pytest.raises(ValueError, match="climate_sites"):
        etc.site_coords(_sites(), "gsod_38062_kyzylorda")


def test_real_climate_sites_have_source_and_status():
    # data/climate_sites.csv проходит загрузчик (real -> запись с цитатой в SOURCES.md)
    from src.data_loader import load_all
    sites = load_all()["climate_sites"]
    nasa = sites[sites["entity"] == etc.NASA_ENTITY]
    assert set(nasa["param"]) >= {"lat", "elevation"}
    assert set(nasa["status"]) == {"real"} and set(nasa["source"]) == {"S088"}
    assert etc.site_coords(sites, etc.NASA_ENTITY) == pytest.approx((44.8, 122.27))


def test_latitude_from_sites_changes_et0():
    # Широта действительно берётся из climate_sites: севернее летом Ra и ET0 другие
    crops, climate = _synthetic_inputs()
    s1, _ = etc.crop_water_tables(crops, climate, _sites(lat=44.8), years=[2020])
    s2, _ = etc.crop_water_tables(crops, climate, _sites(lat=30.0), years=[2020])
    assert not np.allclose(s1["et0_mm"], s2["et0_mm"])


def test_crop_water_tables_complete_and_consistent():
    crops, climate = _synthetic_inputs()
    season, daily = etc.crop_water_tables(crops, climate, _sites(), years=[2020, 2021])
    # ни одна культура и ни один год не пропали
    assert sorted(season["crop"].unique()) == ["a", "b"]
    assert len(season) == 4
    # сезонная сумма = сумма суточной таблицы, м³/га = мм × 10
    for (crop, year), g in daily.groupby(["crop", "year"]):
        row = season[(season["crop"] == crop) & (season["year"] == year)].iloc[0]
        assert row["etc_mm"] == pytest.approx(g["etc_mm"].sum())
        assert row["etc_m3_ha"] == pytest.approx(10 * g["etc_mm"].sum())
        assert row["days"] == len(g)
    # культура "a": 40 дней с 1 мая (doy 121, 2021 г.)
    a21 = season[(season["crop"] == "a") & (season["year"] == 2021)].iloc[0]
    assert a21["days"] == 40 and a21["start"] == pd.Timestamp("2021-05-01")


def test_wind_factor_lowers_etc():
    # Диагностика: меньше ветра при сухом воздухе -> меньше ET0 и Kc -> меньше ETc
    crops, climate = _synthetic_inputs()
    base, _ = etc.crop_water_tables(crops, climate, _sites(), years=[2020])
    calm, _ = etc.crop_water_tables(crops, climate, _sites(), years=[2020], wind_factor=0.84)
    assert (calm["etc_mm"].to_numpy() < base["etc_mm"].to_numpy()).all()
