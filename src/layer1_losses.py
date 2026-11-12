"""Слой 1: эффективные осадки, КПД полива и потери в каналах.

Три величины на культуру × год (мм, затем м³/га только через src.units.mm_to_m3):
- «у растения» (plant) — чистая оросительная норма NIR = max(ETc − Pe, 0)
  по каждому месяцу сезона (FAO TM3, раздел 4.3: IN = ET crop − Pe);
- «на поле» (field) — NIR / КПД полива (eff_field);
- «из реки» (river) — «на поле» / КПД каналов (eff_canal).

Рис (решение автора 2026-11-12, docs/plan.md, модуль 3; FAO TM3, раздел 4.4, Step 8):
  «на поле» = ETc + SAT + WL + PERC × дни затопления − Pe (по месяцам, не меньше 0);
  SAT и WL — один раз за сезон (в первый месяц сезона); дни затопления = дни сезона;
  КПД полива к рису не применяется (потери на чеке уже в PERC); «из реки» = / КПД каналов.
  Для риса «у растения» = max(ETc − Pe, 0), как у остальных культур (для сравнимости).

Эффективные осадки — метод USDA SCS (решение плана, слой 1), месячная формула (S090):
  Pe = P (125 − 0.2 P) / 125 при P < 250 мм/мес; Pe = 125 + 0.1 P при P ≥ 250 мм/мес.
  P — сумма осадков за весь календарный месяц; если сезон занимает часть месяца,
  Pe месяца делится пропорционально дням сезона в этом месяце.

Все КПД и параметры риса берутся из data/efficiency.csv и data/rice_water.csv
(колонка measure: low / base / high / pessimistic), здесь не зашиты.
"""

import numpy as np
import pandas as pd

from src.units import mm_to_m3

# Константа метода USDA SCS (S090; первоисточник — FAO Irrigation and Drainage Paper 46, с. 23–24)
USDA_P_LIMIT_MM = 250.0

FIELD_ENTITY = "kyzylorda_fields"
CANAL_ENTITY = "kyzylorda_canals"
RICE_PARAMS = {"sat": "rice_saturation", "wl": "rice_water_layer", "perc": "rice_percolation"}

MONTH_COLUMNS = ["crop", "year", "month", "days", "etc_mm", "p_month_mm", "pe_mm",
                 "sat_mm", "wl_mm", "perc_mm", "nir_mm", "field_need_mm"]
SEASON_COLUMNS = ["crop", "year", "days", "etc_mm", "pe_mm", "nir_mm", "field_mm", "river_mm",
                  "plant_m3_ha", "field_m3_ha", "river_m3_ha", "eff_field", "eff_canal", "flooded"]


# --- Эффективные осадки ---

def pe_usda_scs(p_month_mm):
    """Эффективные осадки за месяц, мм (USDA SCS, S090). Число -> число, массив -> массив."""
    p = np.asarray(p_month_mm, dtype=float)
    if (p < 0).any():
        raise ValueError("Осадки не могут быть отрицательными")
    pe = np.where(p < USDA_P_LIMIT_MM, p * (125.0 - 0.2 * p) / 125.0, 125.0 + 0.1 * p)
    return float(pe) if pe.ndim == 0 else pe


def monthly_precip(precip_daily):
    """Сумма осадков за каждый календарный месяц (Series, индекс — Period 'M').

    Месяц с пропущенными днями — ошибка: неполная сумма занизила бы Pe.
    """
    p = precip_daily.sort_index()
    by_month = p.groupby(p.index.to_period("M"))
    counts = by_month.size()
    expected = pd.Series(counts.index.days_in_month, index=counts.index)
    incomplete = counts[counts != expected]
    if len(incomplete):
        raise ValueError(f"Неполные месяцы осадков: {[str(m) for m in incomplete.index[:5]]}")
    return by_month.sum()


# --- Параметры из data/ ---

def scenario_value(table, entity, param, measure):
    """Одно число из efficiency.csv или rice_water.csv по (entity, param, measure)."""
    sub = table[(table["entity"] == entity) & (table["param"] == param) & (table["measure"] == measure)]
    if len(sub) != 1:
        raise ValueError(f"Ожидалось одно значение {entity}/{param}/{measure}, найдено {len(sub)}")
    return float(sub["value"].iloc[0])


def efficiencies(efficiency, field_measure="base", canal_measure="base"):
    """(КПД полива, КПД каналов) из efficiency.csv; оба в (0, 1]."""
    e_field = scenario_value(efficiency, FIELD_ENTITY, "eff_field", field_measure)
    e_canal = scenario_value(efficiency, CANAL_ENTITY, "eff_canal", canal_measure)
    for name, v in (("eff_field", e_field), ("eff_canal", e_canal)):
        if not 0 < v <= 1:
            raise ValueError(f"{name} должен быть в (0, 1], получено {v}")
    return e_field, e_canal


def rice_parameters(rice_water, crop="rice", perc_measure="base"):
    """SAT (мм), WL (мм), PERC (мм/сут) для затопляемой культуры из rice_water.csv."""
    return {"sat": scenario_value(rice_water, crop, RICE_PARAMS["sat"], "base"),
            "wl": scenario_value(rice_water, crop, RICE_PARAMS["wl"], "base"),
            "perc": scenario_value(rice_water, crop, RICE_PARAMS["perc"], perc_measure)}


# --- Баланс по месяцам сезона ---

def monthly_balance(daily, p_month, rice=None):
    """Месячный баланс одного сезона (одна культура, один год).

    daily — суточные строки etc.crop_water_tables для этой культуры и года
    (колонки date, etc_mm); p_month — monthly_precip(...); rice — rice_parameters(...)
    для затопляемой культуры или None.
    """
    d = daily.sort_values("date")
    months = d["date"].dt.to_period("M")
    rows = []
    for i, (month, g) in enumerate(d.groupby(months, sort=True)):
        if month not in p_month.index:
            raise ValueError(f"Нет осадков за {month}")
        days = len(g)
        p_full = float(p_month[month])
        pe = pe_usda_scs(p_full) * days / month.days_in_month
        etc_mm = float(g["etc_mm"].sum())
        sat = wl = perc = 0.0
        if rice is not None:
            if i == 0:
                sat, wl = rice["sat"], rice["wl"]
            perc = rice["perc"] * days
        nir = max(etc_mm - pe, 0.0)
        field_need = max(etc_mm + sat + wl + perc - pe, 0.0) if rice is not None else nir
        rows.append({"month": str(month), "days": days, "etc_mm": etc_mm, "p_month_mm": p_full,
                     "pe_mm": pe, "sat_mm": sat, "wl_mm": wl, "perc_mm": perc,
                     "nir_mm": nir, "field_need_mm": field_need})
    return pd.DataFrame(rows)


def season_water(months, eff_field, eff_canal, flooded):
    """Три величины за сезон из месячного баланса, мм и м³/га."""
    nir = float(months["nir_mm"].sum())
    need = float(months["field_need_mm"].sum())
    field = need if flooded else need / eff_field
    river = field / eff_canal
    return {"days": int(months["days"].sum()), "etc_mm": float(months["etc_mm"].sum()),
            "pe_mm": float(months["pe_mm"].sum()), "nir_mm": nir, "field_mm": field, "river_mm": river,
            "plant_m3_ha": float(mm_to_m3(nir)), "field_m3_ha": float(mm_to_m3(field)),
            "river_m3_ha": float(mm_to_m3(river)),
            "eff_field": None if flooded else eff_field, "eff_canal": eff_canal, "flooded": flooded}


# --- Все культуры и годы ---

def precip_series(climate, entity):
    """Суточные осадки (мм) одного источника из climate_daily; единица и повторы проверяются."""
    sub = climate[(climate["entity"] == entity) & (climate["param"] == "precip")]
    if sub.empty:
        raise ValueError(f"Нет осадков (precip) у {entity!r}")
    if "unit" in sub.columns and set(sub["unit"]) != {"mm"}:
        raise ValueError(f"precip: единицы {sorted(set(sub['unit']))}, нужны 'mm'")
    if sub["date"].duplicated().any():
        raise ValueError("Повтор дат в осадках")
    return pd.Series(sub["value"].to_numpy(dtype=float), index=pd.to_datetime(sub["date"])).sort_index()


def layer1_tables(daily, precip_daily, efficiency, rice_water,
                  field_measure="base", canal_measure="base", perc_measure="base"):
    """Слой 1 для всех культур и лет из суточной таблицы ETc.

    Возвращает (season, months). Культура считается затопляемой, если для неё есть
    параметры в rice_water.csv. Ни одна культура и ни один год не пропускаются молча.
    """
    p_month = monthly_precip(precip_daily)
    e_field, e_canal = efficiencies(efficiency, field_measure, canal_measure)
    flooded_crops = set(rice_water["entity"])
    season_rows, month_parts = [], []
    for (crop, year), g in daily.groupby(["crop", "year"], sort=False):
        rice = rice_parameters(rice_water, crop, perc_measure) if crop in flooded_crops else None
        months = monthly_balance(g, p_month, rice)
        months.insert(0, "year", year)
        months.insert(0, "crop", crop)
        month_parts.append(months)
        season_rows.append({"crop": crop, "year": year,
                            **season_water(months, e_field, e_canal, rice is not None)})
    season = pd.DataFrame(season_rows, columns=SEASON_COLUMNS)
    months = pd.concat(month_parts, ignore_index=True)[MONTH_COLUMNS]
    if len(season) != daily.groupby(["crop", "year"]).ngroups:
        raise RuntimeError("Слой 1 неполный: пропали культуры или годы")
    return season, months
