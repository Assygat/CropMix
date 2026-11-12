"""Эталонная эвапотранспирация ET0 (мм/сут) по FAO-56 (Allen et al., 1998).

Основной метод — Penman–Monteith (ур. 6), запасной — Hargreaves (ур. 52),
когда есть только температура (например, станция GSOD).
Номера уравнений — по FAO Irrigation and Drainage Paper No. 56, глава 3.

Единицы: температура °C, давление кПа, радиация МДж/м²/сут, ветер м/с на 2 м,
влажность %, высота м, широта в градусах (север > 0). ET0 — мм/сут.
Все функции векторные (принимают числа или массивы numpy).
"""

import numpy as np
import pandas as pd

SOLAR_CONSTANT = 0.0820  # Gsc, МДж/м²/мин (ур. 21)
STEFAN_BOLTZMANN = 4.903e-9  # σ, МДж/К⁴/м²/сут (ур. 39)
ALBEDO = 0.23  # α для эталонной травы (ур. 38)
MJ_TO_MM = 0.408  # 1 МДж/м² испаряет 0.408 мм воды (ур. 20)


def _arr(x):
    return np.asarray(x, dtype=float)


# --- Атмосферные параметры ---

def atmospheric_pressure(elevation_m):
    """P, кПа, по высоте над уровнем моря (ур. 7)."""
    z = _arr(elevation_m)
    return 101.3 * ((293.0 - 0.0065 * z) / 293.0) ** 5.26


def psychrometric_constant(pressure_kpa):
    """γ, кПа/°C (ур. 8)."""
    return 0.665e-3 * _arr(pressure_kpa)


def sat_vapour_pressure(t_c):
    """e°(T), кПа (ур. 11)."""
    t = _arr(t_c)
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def mean_sat_vapour_pressure(tmax, tmin):
    """es, кПа — среднее e° по Tmax и Tmin (ур. 12)."""
    return (sat_vapour_pressure(tmax) + sat_vapour_pressure(tmin)) / 2.0


def slope_vapour_pressure(t_c):
    """Δ, кПа/°C — наклон кривой давления насыщенного пара (ур. 13)."""
    t = _arr(t_c)
    return 4098.0 * sat_vapour_pressure(t) / (t + 237.3) ** 2


def actual_vapour_pressure_rh_minmax(tmax, tmin, rh_max, rh_min):
    """ea, кПа, по RHmax и RHmin (ур. 17) — предпочтительный вариант FAO-56."""
    return (sat_vapour_pressure(tmin) * _arr(rh_max) / 100.0
            + sat_vapour_pressure(tmax) * _arr(rh_min) / 100.0) / 2.0


def actual_vapour_pressure_rh_mean(tmax, tmin, rh_mean):
    """ea, кПа, по средней RH (ур. 19). FAO-56 считает его менее точным, чем ур. 17."""
    return _arr(rh_mean) / 100.0 * mean_sat_vapour_pressure(tmax, tmin)


def wind_at_2m(u_z, z_m):
    """Пересчёт скорости ветра с высоты z на 2 м (ур. 47)."""
    return _arr(u_z) * 4.87 / np.log(67.8 * _arr(z_m) - 5.42)


# --- Радиация ---

def _sunset_hour_angle(lat_rad, decl):
    # ωs (ур. 25); аргумент обрезается до [-1, 1] для полярного дня/ночи
    return np.arccos(np.clip(-np.tan(lat_rad) * np.tan(decl), -1.0, 1.0))


def _solar_geometry(lat_deg, doy):
    lat = np.deg2rad(_arr(lat_deg))
    j = _arr(doy)
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)  # ур. 23
    decl = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)  # ур. 24
    ws = _sunset_hour_angle(lat, decl)
    return lat, dr, decl, ws


def extraterrestrial_radiation(lat_deg, doy):
    """Ra, МДж/м²/сут (ур. 21)."""
    lat, dr, decl, ws = _solar_geometry(lat_deg, doy)
    return (24.0 * 60.0 / np.pi) * SOLAR_CONSTANT * dr * (
        ws * np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.sin(ws)
    )


def daylight_hours(lat_deg, doy):
    """N, ч — астрономическая длина дня (ур. 34)."""
    _, _, _, ws = _solar_geometry(lat_deg, doy)
    return 24.0 / np.pi * ws


def solar_radiation_from_sunshine(sunshine_h, lat_deg, doy, a_s=0.25, b_s=0.50):
    """Rs, МДж/м²/сут, по часам солнца (формула Ангстрема, ур. 35)."""
    n_max = daylight_hours(lat_deg, doy)
    return (a_s + b_s * _arr(sunshine_h) / n_max) * extraterrestrial_radiation(lat_deg, doy)


def clear_sky_radiation(lat_deg, doy, elevation_m):
    """Rso, МДж/м²/сут (ур. 37)."""
    return (0.75 + 2e-5 * _arr(elevation_m)) * extraterrestrial_radiation(lat_deg, doy)


def net_shortwave_radiation(rs):
    """Rns, МДж/м²/сут (ур. 38)."""
    return (1.0 - ALBEDO) * _arr(rs)


def net_longwave_radiation(tmax, tmin, ea, rs, rso):
    """Rnl, МДж/м²/сут (ур. 39). Отношение Rs/Rso ограничено сверху 1.0."""
    tk4 = ((_arr(tmax) + 273.16) ** 4 + (_arr(tmin) + 273.16) ** 4) / 2.0
    rel = np.minimum(_arr(rs) / _arr(rso), 1.0)
    return STEFAN_BOLTZMANN * tk4 * (0.34 - 0.14 * np.sqrt(_arr(ea))) * (1.35 * rel - 0.35)


# --- ET0 ---

def et0_penman_monteith(tmax, tmin, ea, rs, u2, lat_deg, doy, elevation_m, g=0.0):
    """ET0, мм/сут, Penman–Monteith FAO-56 (ур. 6) для суточного шага.

    ea — фактическое давление пара, кПа (ур. 17 или 19); rs — суммарная радиация,
    МДж/м²/сут; u2 — ветер на 2 м, м/с; g — поток тепла в почву (для суток ≈ 0, ур. 42).
    Отрицательные значения (бывают зимой) обрезаются до 0.
    """
    tmax, tmin, ea, rs, u2 = map(_arr, (tmax, tmin, ea, rs, u2))
    tmean = (tmax + tmin) / 2.0  # ур. 9
    delta = slope_vapour_pressure(tmean)
    gamma = psychrometric_constant(atmospheric_pressure(elevation_m))
    es = mean_sat_vapour_pressure(tmax, tmin)
    rso = clear_sky_radiation(lat_deg, doy, elevation_m)
    rn = net_shortwave_radiation(rs) - net_longwave_radiation(tmax, tmin, ea, rs, rso)
    num = MJ_TO_MM * delta * (rn - g) + gamma * 900.0 / (tmean + 273.0) * u2 * (es - ea)
    den = delta + gamma * (1.0 + 0.34 * u2)
    return np.maximum(num / den, 0.0)


def et0_hargreaves(tmax, tmin, lat_deg, doy):
    """ET0, мм/сут, по Hargreaves (ур. 52): только температура и Ra.

    Запасной метод; FAO-56 советует проверять его по Penman–Monteith для региона.
    """
    tmax, tmin = _arr(tmax), _arr(tmin)
    tmean = (tmax + tmin) / 2.0
    ra_mm = MJ_TO_MM * extraterrestrial_radiation(lat_deg, doy)
    return np.maximum(0.0023 * (tmean + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0.0)) * ra_mm, 0.0)


# --- Применение к data/climate_daily.csv ---

PM_PARAMS = ["tmax", "tmin", "rh_mean", "u2", "rs"]
# Единицы, в которых формулы FAO-56 ждут входы (совпадают с реестром src.data_loader.PARAMS).
# u2 — ветер именно на 2 м: другая высота пересчитывается wind_at_2m до записи в данные.
EXPECTED_UNITS = {"tmax": "degC", "tmin": "degC", "rh_mean": "%", "u2": "m/s", "rs": "MJ/m2/day"}


def et0_from_climate(climate, entity, lat_deg, elevation_m, method="pm"):
    """Суточный ET0 для одного источника климата из «длинной» таблицы climate_daily.

    climate — DataFrame с колонками entity, param, date, value.
    lat_deg и elevation_m передаёт вызывающий код (со ссылкой на источник),
    здесь они не зашиты. method: "pm" (Penman–Monteith) или "hargreaves".
    Возвращает Series ET0 (мм/сут) с индексом по дате. Дни, где не хватает
    какого-либо входа, не считаются (их нет в результате, а не ноль).
    """
    need = PM_PARAMS if method == "pm" else ["tmax", "tmin"]
    sub = climate[climate["entity"] == entity]
    if sub.empty:
        raise ValueError(f"В климатических данных нет источника {entity!r}")
    if "unit" in sub.columns:
        for param in need:
            units = set(sub.loc[sub["param"] == param, "unit"])
            if units and units != {EXPECTED_UNITS[param]}:
                raise ValueError(f"{param}: единицы {sorted(units)}, нужны {EXPECTED_UNITS[param]!r}")
    wide = sub.pivot_table(index="date", columns="param", values="value", aggfunc="first")
    missing = [p for p in need if p not in wide.columns]
    if missing:
        raise ValueError(f"Для метода {method!r} у {entity!r} нет параметров: {missing}")
    wide = wide[need].dropna()
    wide.index = pd.to_datetime(wide.index)
    doy = wide.index.day_of_year.to_numpy()

    if method == "pm":
        ea = actual_vapour_pressure_rh_mean(wide["tmax"], wide["tmin"], wide["rh_mean"])
        values = et0_penman_monteith(wide["tmax"], wide["tmin"], ea, wide["rs"], wide["u2"],
                                     lat_deg, doy, elevation_m)
    elif method == "hargreaves":
        values = et0_hargreaves(wide["tmax"], wide["tmin"], lat_deg, doy)
    else:
        raise ValueError(f"Неизвестный метод {method!r}: нужен 'pm' или 'hargreaves'")
    return pd.Series(values, index=wide.index, name="et0_mm_day")
