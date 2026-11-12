"""Тесты src/kc.py: кривая Kc (ур. 66), климатическая поправка (ур. 62/65), сезон люцерны.

Эталоны FAO-56 сверены с документом data/raw/fao56_chapter6_x0490e0b.htm (S087):
пример 27 (поправка Kc_mid для кукурузы) и пример 28 (Kc по ур. 66 для фасоли).
"""

import numpy as np
import pandas as pd
import pytest

from src import kc
from src.et0 import sat_vapour_pressure


# --- Кривая Kc (ур. 66) ---

def test_example28_dry_bean_curve():
    # FAO-56, пример 28: стадии 25/25/30/20, Kc 0.15 / 1.19 / 0.35;
    # день 20 -> 0.15, день 40 -> 0.77, день 70 -> 1.19, день 95 -> 0.56
    curve = kc.kc_curve(0.15, 1.19, 0.35, 25, 25, 30, 20)
    assert len(curve) == 100
    assert curve[20 - 1] == pytest.approx(0.15)
    assert curve[40 - 1] == pytest.approx(0.77, abs=0.005)
    assert curve[70 - 1] == pytest.approx(1.19)
    assert curve[95 - 1] == pytest.approx(0.56, abs=0.005)


def test_hand_interpolation_simple_numbers():
    # Ручной пример: стадии 2/4/3/2, Kc 0.2 / 1.0 / 0.6.
    # Развитие: шаг (1.0 - 0.2)/4 = 0.2 -> 0.4, 0.6, 0.8, 1.0; поздняя: шаг -0.2 -> 0.8, 0.6
    curve = kc.kc_curve(0.2, 1.0, 0.6, 2, 4, 3, 2)
    expected = [0.2, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, 0.8, 0.6]
    assert curve == pytest.approx(expected)


def test_zero_length_stages():
    # l_dev = 0: скачок с Kc_ini сразу на Kc_mid, без деления на ноль
    curve = kc.kc_curve(0.3, 1.1, 0.5, 2, 0, 2, 1)
    assert curve == pytest.approx([0.3, 0.3, 1.1, 1.1, 0.5])
    # l_late = 0: сезон кончается на Kc_mid; Kc_end не используется
    curve = kc.kc_curve(0.3, 1.1, 0.5, 1, 1, 2, 0)
    assert curve == pytest.approx([0.3, 1.1, 1.1, 1.1])
    assert not np.isnan(curve).any()


def test_invalid_stage_lengths():
    with pytest.raises(ValueError):
        kc.kc_curve(0.3, 1.1, 0.5, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        kc.kc_curve(0.3, 1.1, 0.5, 10, -1, 10, 10)


# --- Климатическая поправка (ур. 62, 65) ---

@pytest.mark.parametrize("h", [0.4, 1.0, 2.0, 10.0])
def test_standard_climate_no_change(h):
    # При u2 = 2 м/с и RHmin = 45 % (стандарт табл. 12) поправка равна нулю
    assert kc.adjust_kc_mid(1.15, 2.0, 45.0, h) == pytest.approx(1.15)
    assert kc.adjust_kc_end(0.90, 2.0, 45.0, h) == pytest.approx(0.90)


def test_example27_maize_taipei_mocha():
    # FAO-56, пример 27: кукуруза Kc_mid(Tab) = 1.20, h = 2 м;
    # Тайбэй u2 = 1.3, RHmin = 75 -> 1.07; Моха u2 = 4.6, RHmin = 44 -> 1.30
    assert kc.adjust_kc_mid(1.20, 1.3, 75, 2.0) == pytest.approx(1.07, abs=0.005)
    assert kc.adjust_kc_mid(1.20, 4.6, 44, 2.0) == pytest.approx(1.30, abs=0.005)


def test_kc_end_below_045_not_adjusted_and_limits_clipped():
    # Ур. 65 не применяется при Kc_end(Tab) < 0.45
    assert kc.adjust_kc_end(0.35, 5.0, 20.0, 1.0) == 0.35
    # u2 и RHmin вне пределов применимости обрезаются: u2 = 9 как 6, RHmin = 10 как 20
    assert kc.adjust_kc_mid(1.0, 9.0, 10.0, 3.0) == pytest.approx(kc.adjust_kc_mid(1.0, 6.0, 20.0, 3.0))
    with pytest.raises(ValueError):
        kc.climate_adjustment(2.0, 45.0, 0.05)


def test_rh_min_from_ea():
    # ea = e°(Tmax) -> RHmin = 100 %; ea = половина e°(30) -> 50 %
    e30 = float(sat_vapour_pressure(30.0))
    assert kc.rh_min_from_ea(e30, 30.0) == pytest.approx(100.0)
    assert kc.rh_min_from_ea(e30 / 2, 30.0) == pytest.approx(50.0)


# --- Люцерна: сезон по заморозкам -4 °C ---

ALFALFA = {"kc_ini": 0.40, "kc_mid": 0.95, "kc_end": 0.90, "max_height": 0.7,
           "l_ini": 10, "l_dev": 30, "l_late": 30}


def _climate(year, last_spring_frost, first_autumn_frost):
    """Синтетический год: Tmin = -10 до last_spring_frost и с first_autumn_frost, иначе +10.
    Стандартный климат (u2 = 2 м/с, RHmin = 45 %), чтобы поправка Kc была нулевой."""
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    tmin = np.where((idx <= last_spring_frost) | (idx >= first_autumn_frost), -10.0, 10.0)
    tmax = np.full(len(idx), 25.0)
    # RHmean подобрана так, чтобы ea / e°(Tmax) = 0.45, где ea = RHmean/100 * (e°(Tmax) + e°(Tmin)) / 2
    es = (sat_vapour_pressure(tmax) + sat_vapour_pressure(tmin)) / 2
    rh_mean = 0.45 * sat_vapour_pressure(tmax) / es * 100
    return pd.DataFrame({"tmax": tmax, "tmin": tmin, "rh_mean": rh_mean, "u2": 2.0}, index=idx)


def test_alfalfa_early_and_late_frost_years():
    # Короткий сезон: последний весенний заморозок 10 апреля, первый осенний 1 октября
    s1, info1 = kc.daily_kc(ALFALFA, 2020, _climate(2020, "2020-04-10", "2020-10-01"))
    assert info1["start"] == pd.Timestamp("2020-04-11")
    assert info1["end"] == pd.Timestamp("2020-09-30")
    assert info1["stages"] == [10, 30, 173 - 70, 30]  # 11.04–30.09 = 173 дня
    # Длинный сезон: заморозки 10 марта и 20 ноября
    s2, info2 = kc.daily_kc(ALFALFA, 2021, _climate(2021, "2021-03-10", "2021-11-20"))
    assert info2["start"] == pd.Timestamp("2021-03-11")
    assert info2["end"] == pd.Timestamp("2021-11-19")
    assert info2["stages"] == [10, 30, 254 - 70, 30]  # 11.03–19.11 = 254 дня
    for s, info in [(s1, info1), (s2, info2)]:
        assert len(s) == sum(info["stages"])
        assert info["rh_min_mid"] == pytest.approx(45.0)
        # стандартный климат -> без поправки: 0.40 -> 0.95 после развития -> 0.90 в последний день
        assert s.iloc[0] == pytest.approx(0.40)
        assert s.iloc[40] == pytest.approx(0.95)
        assert s.iloc[-31] == pytest.approx(0.95)
        assert s.iloc[-1] == pytest.approx(0.90)


def test_alfalfa_season_shorter_than_stages_raises():
    # Окно без заморозков 50 дней < 10 + 30 + 30 -> понятная ошибка
    with pytest.raises(ValueError, match="короче"):
        kc.daily_kc(ALFALFA, 2022, _climate(2022, "2022-06-01", "2022-07-21"))


@pytest.mark.parametrize("year", [2019, 2020, 2021, 2024])
def test_sowing_date_same_calendar_day_in_leap_and_normal_years(year):
    # plant_doy — номер дня невисокосного года: 135 = 15 мая, 74 = 15 марта, 121 = 1 мая
    assert kc.sowing_date(135, year) == pd.Timestamp(year, 5, 15)
    assert kc.sowing_date(74, year) == pd.Timestamp(year, 3, 15)
    assert kc.sowing_date(121, year) == pd.Timestamp(year, 5, 1)


def test_leap_year_season_same_dates_and_length():
    # Рис: сев 15 мая и конец 11 октября (150 дней) и в 2020 (високосный), и в 2021
    rice = {"kc_ini": 1.05, "kc_mid": 1.20, "kc_end": 0.75, "max_height": 1.0,
            "l_ini": 30, "l_dev": 30, "l_mid": 60, "l_late": 30, "plant_doy": 135}
    for year in (2020, 2021):
        s, info = kc.daily_kc(rice, year, _climate(year, f"{year}-03-10", f"{year}-11-20"))
        assert info["start"] == pd.Timestamp(year, 5, 15)
        assert info["end"] == pd.Timestamp(year, 10, 11)
        assert len(s) == 150


def test_invalid_plant_doy_and_fractional_stage():
    with pytest.raises(ValueError, match="plant_doy"):
        kc.sowing_date(366, 2020)
    with pytest.raises(ValueError, match="plant_doy"):
        kc.sowing_date(135.5, 2021)
    # дробная длина стадии — ошибка, а не усечение 30.9 -> 30
    with pytest.raises(ValueError, match="l_dev"):
        kc.kc_curve(0.3, 1.1, 0.5, 10, 30.9, 10, 10)


def test_fixed_calendar_crop_uses_plant_doy():
    # Культура с plant_doy: сев doy 135 = 15 мая (невисокосный год), стадии 30/30/60/30 = 150 дней
    rice = {"kc_ini": 1.05, "kc_mid": 1.20, "kc_end": 0.75, "max_height": 1.0,
            "l_ini": 30, "l_dev": 30, "l_mid": 60, "l_late": 30, "plant_doy": 135}
    s, info = kc.daily_kc(rice, 2021, _climate(2021, "2021-03-10", "2021-11-20"))
    assert info["start"] == pd.Timestamp("2021-05-15")
    assert info["end"] == pd.Timestamp("2021-10-11")
    assert len(s) == 150
