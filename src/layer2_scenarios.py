"""Слой 2: сценарии водности (маловодный / средний / многоводный год).

Решения автора 2026-11-13 (docs/plan.md, модуль 5):
1. Классы лет — по годовому стоку бассейна Сырдарьи (river_flow.csv,
   measure = annual_runoff_basin_total), перцентили ряда:
   сток < P25 -> маловодный, сток > P75 -> многоводный, иначе средний
   (граничные значения — средний). P25/P75 — numpy.percentile, метод linear.
   Ряд сейчас 2020–2024 (5 лет), поэтому классификация грубая.
2. Лимит воды «из реки» — только реальный лимит на вегетацию (water_withdrawal.csv,
   measure = limit_vegetation) того года, класс которого известен по стоку.
   Классам без такого лимита лимит не задаётся (None, флаг no_data) —
   значения не придумываются и не масштабируются.
3. Климатический год для всех классов — среднее 2010–2025 (ключ "mean" модуля 4).

Ничего не калибруется: лимиты и сток — данные (real), классы — модельный результат.
"""

import numpy as np
import pandas as pd

RUNOFF_ENTITY = "syrdarya_basin"
RUNOFF_MEASURE = "annual_runoff_basin_total"
LIMIT_ENTITY = "kyzylorda_irrigation"
LIMIT_MEASURE = "limit_vegetation"
CLASSES = ["low", "average", "high"]  # маловодный, средний, многоводный
CLASS_RU = {"low": "маловодный", "average": "средний", "high": "многоводный"}
LOW_PERCENTILE, HIGH_PERCENTILE = 25.0, 75.0
MIN_YEARS = 3  # меньше трёх лет — перцентили не имеют смысла
CLIMATE_KEY = "mean"  # решение 3: средний климат 2010–2025 для всех классов


def runoff_series(river_flow):
    """Годовой сток бассейна (м³) по годам из river_flow.csv; пропуски не заполняются."""
    sub = river_flow[(river_flow["entity"] == RUNOFF_ENTITY) & (river_flow["measure"] == RUNOFF_MEASURE)]
    sub = sub.dropna(subset=["year", "value"])
    if sub["year"].duplicated().any():
        raise ValueError("Повтор года в ряду стока")
    if "unit" in sub.columns and set(sub["unit"]) - {"m3"}:
        raise ValueError(f"Сток: единицы {sorted(set(sub['unit']))}, нужны 'm3'")
    s = pd.Series(sub["value"].to_numpy(dtype=float), index=sub["year"].astype(int).to_numpy(), name="runoff_m3")
    if (s <= 0).any():
        raise ValueError("Сток должен быть больше нуля")
    return s.sort_index()


def classify_years(runoff):
    """Класс каждого года по перцентилям ряда. Возвращает DataFrame year, runoff_m3, water_class и пороги."""
    r = runoff.dropna()
    if len(r) < MIN_YEARS:
        raise ValueError(f"Для перцентилей нужно не меньше {MIN_YEARS} лет стока, есть {len(r)}")
    p_low = float(np.percentile(r.to_numpy(), LOW_PERCENTILE))
    p_high = float(np.percentile(r.to_numpy(), HIGH_PERCENTILE))
    cls = np.where(r < p_low, "low", np.where(r > p_high, "high", "average"))
    return pd.DataFrame({"year": r.index, "runoff_m3": r.to_numpy(), "water_class": cls,
                         "p25_m3": p_low, "p75_m3": p_high, "n_years": len(r)})


def class_limits(years, withdrawal):
    """Лимит «из реки» (м³) для каждого класса — только реальный лимит года с известным классом.

    Если у класса больше одного такого лимита — ошибка (нужно решение автора, как их совместить).
    """
    lim = withdrawal[(withdrawal["entity"] == LIMIT_ENTITY) & (withdrawal["param"] == "water_withdrawal")
                     & (withdrawal["measure"] == LIMIT_MEASURE)].dropna(subset=["year"])
    year_class = dict(zip(years["year"], years["water_class"]))
    out = {c: None for c in CLASSES}
    for r in lim.itertuples():
        c = year_class.get(int(r.year))
        if c is None:
            continue  # класс года неизвестен (нет стока) — лимит не привязывается
        if out[c] is not None:
            raise ValueError(f"У класса {c} несколько лимитов ({out[c]['year']}, {int(r.year)}) — нужно решение")
        out[c] = {"limit_m3": float(r.value), "year": int(r.year), "source": r.source, "status": r.status}
    return out


def check_limit_order(scenarios):
    """Лимит маловодного ≤ среднего ≤ многоводного — среди классов, у которых лимит есть."""
    s = scenarios.set_index("water_class")
    known = [(c, s.loc[c, "limit_m3"]) for c in CLASSES if pd.notna(s.loc[c, "limit_m3"])]
    for (c1, v1), (c2, v2) in zip(known, known[1:]):
        if v1 > v2:
            raise ValueError(f"Лимит класса {c1} ({v1}) больше лимита класса {c2} ({v2})")
    return True


def build_scenarios(river_flow, withdrawal):
    """Таблица лет с классами и таблица сценариев (строка на класс)."""
    years = classify_years(runoff_series(river_flow))
    limits = class_limits(years, withdrawal)
    rows = []
    for c in CLASSES:
        ys = years[years["water_class"] == c]
        lim = limits[c]
        rows.append({
            "water_class": c, "name_ru": CLASS_RU[c],
            "years": ",".join(map(str, ys["year"])),
            "runoff_min_m3": float(ys["runoff_m3"].min()) if len(ys) else None,
            "runoff_max_m3": float(ys["runoff_m3"].max()) if len(ys) else None,
            "limit_m3": None if lim is None else lim["limit_m3"],
            "limit_year": None if lim is None else lim["year"],
            "limit_source": None if lim is None else lim["source"],
            "limit_status": "no_data" if lim is None else lim["status"],
            "climate_key": CLIMATE_KEY,
            "classification": f"model: percentiles of {int(years['n_years'].iloc[0])} years",
        })
    scenarios = pd.DataFrame(rows)
    check_limit_order(scenarios)
    return years, scenarios
