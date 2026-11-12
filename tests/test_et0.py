"""Тесты src/et0.py на примерах из FAO-56 и ручных расчётах.

Эталонные числа сверены с документом (data/raw/, цитаты в data/SOURCES.md):
глава 3 — S084 (примеры 2, 3, 5, 8, 9, 10, 14), глава 4 — S085 (пример 18),
приложение 2 — S086 (табл. 2.4).
"""

import numpy as np
import pandas as pd
import pytest

from src import et0


# --- Промежуточные величины: примеры и таблицы FAO-56 ---

def test_example2_pressure_and_gamma_at_1800m():
    # FAO-56, пример 2: z = 1800 м -> P = 81.8 кПа, γ = 0.054 кПа/°C
    p = et0.atmospheric_pressure(1800)
    assert p == pytest.approx(81.8, abs=0.05)
    assert et0.psychrometric_constant(p) == pytest.approx(0.054, abs=0.0005)


def test_example3_mean_saturation_vapour_pressure():
    # FAO-56, пример 3: Tmax 24.5, Tmin 15 -> e° 3.075 и 1.705, es = 2.39 кПа
    assert et0.sat_vapour_pressure(24.5) == pytest.approx(3.075, abs=0.001)
    assert et0.sat_vapour_pressure(15.0) == pytest.approx(1.705, abs=0.001)
    assert et0.mean_sat_vapour_pressure(24.5, 15.0) == pytest.approx(2.39, abs=0.005)


def test_example5_ea_from_rh_minmax():
    # FAO-56, пример 5: Tmin 18, Tmax 25, RHmax 82, RHmin 54 -> ea = 1.70 кПа
    assert et0.actual_vapour_pressure_rh_minmax(25, 18, 82, 54) == pytest.approx(1.70, abs=0.01)


def test_example5_ea_from_rh_mean_eq19():
    # FAO-56, пример 5, примечание: «when using Eq. 19: ea = 1.78 kPa»;
    # RHmean = (82 + 54) / 2 = 68 %. Этот путь используется для данных NASA POWER.
    assert et0.actual_vapour_pressure_rh_mean(25, 18, 68) == pytest.approx(1.78, abs=0.01)


def test_ea_from_rh_mean_hand_example():
    # Ручной пример ур. 19: RHmean 50 % при Tmax = Tmin = 20 °C -> 0.5 * e°(20) = 0.5 * 2.338
    assert et0.actual_vapour_pressure_rh_mean(20, 20, 50) == pytest.approx(1.169, abs=0.001)


def test_table24_slope_at_20c():
    # FAO-56, табл. 2.4 (приложение 2): Δ(20 °C) = 0.145 кПа/°C
    assert et0.slope_vapour_pressure(20.0) == pytest.approx(0.145, abs=0.0005)


def test_examples8_9_radiation_20s_3sept():
    # FAO-56, примеры 8–9: 3 сентября (J = 246), 20° ю. ш.: Ra = 32.2 МДж/м²/сут, N = 11.7 ч
    assert et0.extraterrestrial_radiation(-20, 246) == pytest.approx(32.2, abs=0.1)
    assert et0.daylight_hours(-20, 246) == pytest.approx(11.7, abs=0.05)


def test_example10_rs_from_sunshine_rio_may():
    # FAO-56, пример 10: Рио-де-Жанейро, 22°54' ю. ш., 15 мая (J = 135), n = 7.1 ч:
    # Ra = 25.1, N = 10.9 ч, Rs = 14.5 МДж/м²/сут
    lat = -(22 + 54 / 60)
    assert et0.extraterrestrial_radiation(lat, 135) == pytest.approx(25.1, abs=0.1)
    assert et0.daylight_hours(lat, 135) == pytest.approx(10.9, abs=0.05)
    assert et0.solar_radiation_from_sunshine(7.1, lat, 135) == pytest.approx(14.5, abs=0.1)


def test_wind_conversion_10m_to_2m():
    # FAO-56, пример 14: 3.2 м/с на 10 м -> 2.4 м/с на 2 м
    assert et0.wind_at_2m(3.2, 10) == pytest.approx(2.4, abs=0.05)


# --- Главный тест: пример 18 FAO-56 (Брюссель, 6 июля) ---

BRUSSELS = dict(lat=50.8, elev=100.0, doy=187, tmax=21.5, tmin=12.3,
                rh_max=84.0, rh_min=63.0, u10_kmh=10.0, sunshine=9.25)


def test_example18_brussels_et0_3_9():
    b = BRUSSELS
    u2 = et0.wind_at_2m(b["u10_kmh"] / 3.6, 10)
    ea = et0.actual_vapour_pressure_rh_minmax(b["tmax"], b["tmin"], b["rh_max"], b["rh_min"])
    rs = et0.solar_radiation_from_sunshine(b["sunshine"], b["lat"], b["doy"])
    # Промежуточные значения из примера 18
    assert u2 == pytest.approx(2.078, abs=0.01)
    assert ea == pytest.approx(1.409, abs=0.005)
    assert et0.extraterrestrial_radiation(b["lat"], b["doy"]) == pytest.approx(41.09, abs=0.1)
    assert rs == pytest.approx(22.07, abs=0.1)
    rso = et0.clear_sky_radiation(b["lat"], b["doy"], b["elev"])
    assert et0.net_longwave_radiation(b["tmax"], b["tmin"], ea, rs, rso) == pytest.approx(3.71, abs=0.05)
    # Итог: ET0 = 3.9 мм/сут (критерий модуля 2 в docs/plan.md: ±0.1)
    value = et0.et0_penman_monteith(b["tmax"], b["tmin"], ea, rs, u2, b["lat"], b["doy"], b["elev"])
    assert value == pytest.approx(3.9, abs=0.1)


# --- Hargreaves ---

def test_hargreaves_hand_example():
    # Ручной расчёт ур. 52: Tmax 30, Tmin 16 (Tmean 23), 20° ю. ш., J = 246 (Ra = 32.2 из примера 8)
    ra = et0.extraterrestrial_radiation(-20, 246)
    expected = 0.0023 * (23 + 17.8) * np.sqrt(14) * 0.408 * ra  # ≈ 4.6 мм/сут
    assert et0.et0_hargreaves(30, 16, -20, 246) == pytest.approx(expected, rel=1e-9)
    assert expected == pytest.approx(4.6, abs=0.1)


def test_hargreaves_zero_when_no_daily_range():
    # Tmax = Tmin -> sqrt(0) = 0 -> ET0 = 0
    assert et0.et0_hargreaves(20, 20, 45, 180) == 0.0


# --- Работа с таблицей climate_daily ---

def _long_climate(rows):
    return pd.DataFrame(
        [{"entity": "x", "param": p, "date": d, "value": v} for d, p, v in rows]
    )


def test_et0_from_climate_matches_direct_call_and_skips_gaps():
    rows = []
    for d in ["2020-07-01", "2020-07-02"]:
        rows += [(d, "tmax", 35.0), (d, "tmin", 20.0), (d, "rh_mean", 30.0),
                 (d, "u2", 3.0), (d, "rs", 28.0)]
    rows += [("2020-07-03", "tmax", 35.0)]  # неполный день — должен быть пропущен
    s = et0.et0_from_climate(_long_climate(rows), "x", lat_deg=44.8, elevation_m=122.27)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2020-07-01", "2020-07-02"]
    ea = et0.actual_vapour_pressure_rh_mean(35, 20, 30)
    direct = et0.et0_penman_monteith(35, 20, ea, 28, 3, 44.8, 183, 122.27)
    assert s.iloc[0] == pytest.approx(float(direct))


def test_et0_from_climate_errors():
    rows = [("2020-07-01", "tmax", 30.0), ("2020-07-01", "tmin", 15.0)]
    df = _long_climate(rows)
    with pytest.raises(ValueError, match="нет параметров"):
        et0.et0_from_climate(df, "x", 44.8, 122.27, method="pm")
    with pytest.raises(ValueError, match="нет источника"):
        et0.et0_from_climate(df, "y", 44.8, 122.27)
    assert len(et0.et0_from_climate(df, "x", 44.8, 122.27, method="hargreaves")) == 1


def test_et0_from_climate_rejects_wrong_units():
    # Радиация в Вт/м² вместо МДж/м²/сут или ветер без пересчёта на 2 м (другая единица) — ошибка, а не тихий расчёт
    rows = [("2020-07-01", "tmax", 35.0), ("2020-07-01", "tmin", 20.0), ("2020-07-01", "rh_mean", 30.0),
            ("2020-07-01", "u2", 3.0), ("2020-07-01", "rs", 320.0)]
    df = _long_climate(rows)
    df["unit"] = df["param"].map({"tmax": "degC", "tmin": "degC", "rh_mean": "%", "u2": "m/s", "rs": "W/m2"})
    with pytest.raises(ValueError, match="rs"):
        et0.et0_from_climate(df, "x", 44.8, 122.27)
    df.loc[df["param"] == "rs", "unit"] = "MJ/m2/day"
    df.loc[df["param"] == "rs", "value"] = 27.6
    assert len(et0.et0_from_climate(df, "x", 44.8, 122.27)) == 1
