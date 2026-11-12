"""Эвапотранспирация культуры ETc = ET0 × Kc (FAO-56, ур. 56) по дням и за сезон.

- ET0 — src/et0.py (Penman–Monteith по NASA POWER, решение автора 1).
- Kc — src/kc.py (кривая по 4 стадиям с климатической поправкой, решения 2, 3, 5).
- Итог: культура × год -> ET0 и ETc за сезон в мм и м³/га (пересчёт только через
  src.units.mm_to_m3: 1 мм на 1 га = 10 м³) и суточная таблица для слоя 1.

Это вода «у растения» (потребность культуры без потерь и без вычета осадков).
"""

import pandas as pd

from src.et0 import et0_from_climate, pivot_daily
from src.kc import crop_params, daily_kc
from src.units import mm_to_m3

# Основной источник климата (решение автора 1). Его широта и высота — не здесь,
# а в data/climate_sites.csv (S088).
NASA_ENTITY = "nasa_power_44.8N_65.5E"
YEARS = range(2010, 2026)

DAILY_COLUMNS = ["crop", "year", "date", "et0_mm", "kc", "etc_mm"]
SEASON_COLUMNS = ["crop", "year", "start", "end", "days", "et0_mm", "etc_mm", "et0_m3_ha", "etc_m3_ha"]


def daily_etc(et0, kc):
    """ETc по дням: DataFrame с колонками et0_mm, kc, etc_mm на даты сезона (индекс kc).

    et0 и kc — Series с индексом-датой. Если на какой-то день сезона нет ET0,
    это ошибка (день не выкидывается и не считается нулём).
    """
    missing = kc.index.difference(et0.index)
    if len(missing):
        raise ValueError(f"Нет ET0 за {len(missing)} дн. сезона, первый: {missing[0].date()}")
    e = et0.loc[kc.index].to_numpy(dtype=float)
    k = kc.to_numpy(dtype=float)
    return pd.DataFrame({"et0_mm": e, "kc": k, "etc_mm": e * k}, index=kc.index)


def season_totals(daily):
    """Сумма за сезон из суточной таблицы одной культуры и года: ET0 и ETc в мм и м³/га."""
    et0_mm = float(daily["et0_mm"].sum())
    etc_mm = float(daily["etc_mm"].sum())
    return {"start": daily.index[0], "end": daily.index[-1], "days": len(daily),
            "et0_mm": et0_mm, "etc_mm": etc_mm,
            "et0_m3_ha": float(mm_to_m3(et0_mm)), "etc_m3_ha": float(mm_to_m3(etc_mm))}


def climate_wide(climate, entity=NASA_ENTITY):
    """Суточный климат одного источника в «широком» виде (индекс-дата, колонки — параметры)."""
    sub = climate[climate["entity"] == entity]
    if sub.empty:
        raise ValueError(f"В климатических данных нет источника {entity!r}")
    return pivot_daily(sub)


def site_coords(sites, entity):
    """(широта °, высота м) точки климата из data/climate_sites.csv.

    Нет записи для entity — ошибка: координаты одной точки нельзя молча
    подставить для другой.
    """
    sub = sites[sites["entity"] == entity]
    values = dict(zip(sub["param"], sub["value"].astype(float)))
    missing = [p for p in ("lat", "elevation") if p not in values]
    if missing:
        raise ValueError(f"В climate_sites нет {missing} для {entity!r}")
    return values["lat"], values["elevation"]


def crop_water_tables(crops, climate, sites, years=YEARS, entity=NASA_ENTITY, wind_factor=1.0):
    """ETc для всех культур из crops_fao56 за годы years.

    sites — таблица data/climate_sites.csv (широта и высота точки климата entity).

    Возвращает (season, daily):
      season — строка на культуру × год (SEASON_COLUMNS);
      daily — строка на культуру × день сезона (DAILY_COLUMNS), вход для слоя 1.
    Любая ошибка по культуре или году поднимается, а не пропускается: в результате
    обязаны быть все культуры из crops за все годы.
    wind_factor — множитель ветра u2 (только для диагностики чувствительности;
    в модели всегда 1.0). Действует и на ET0, и на поправку Kc.
    """
    years = list(years)
    lat_deg, elevation_m = site_coords(sites, entity)
    clim_long = climate
    if wind_factor != 1.0:
        mask = (climate["entity"] == entity) & (climate["param"] == "u2")
        clim_long = climate.copy()
        clim_long.loc[mask, "value"] = clim_long.loc[mask, "value"] * wind_factor
    wide = climate_wide(clim_long, entity)
    et0 = et0_from_climate(clim_long, entity, lat_deg, elevation_m, method="pm")

    season_rows, daily_parts = [], []
    for crop in crops["entity"].drop_duplicates():
        params = crop_params(crops, crop)
        for year in years:
            kc, _ = daily_kc(params, year, wide)
            day = daily_etc(et0, kc)
            season_rows.append({"crop": crop, "year": year, **season_totals(day)})
            part = day.reset_index(names="date")
            part.insert(0, "year", year)
            part.insert(0, "crop", crop)
            daily_parts.append(part)

    season = pd.DataFrame(season_rows, columns=SEASON_COLUMNS)
    daily = pd.concat(daily_parts, ignore_index=True)[DAILY_COLUMNS]
    expected = set(crops["entity"])
    if set(season["crop"]) != expected or len(season) != len(expected) * len(years):
        raise RuntimeError("Результат ETc неполный: пропали культуры или годы")
    return season, daily
