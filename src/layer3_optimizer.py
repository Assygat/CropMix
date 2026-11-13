"""Слой 3: оптимизатор структуры посевов (линейное программирование, scipy.optimize.linprog).

Решения автора 2026-11-13 (docs/plan.md, модуль 6):
1. Цель — минимум воды «из реки» (м³). Доход не используется: нет затрат и части цен
   и урожайностей; цель «максимум дохода» и ограничение «доход ≥ минимума» — позже.
2. Лимит воды — два режима:
   - относительный (основной): лимит = модельная потребность базовой структуры × (1 − r),
     r — цель снижения из data/optimizer_presets.csv;
   - абсолютный (диагностика): реальный лимит из слоя 2 (сейчас 3.7 км³, многоводный класс).
   При цели «минимум воды» лимит не меняет оптимальную структуру, он лишь проверяет,
   достижим ли он при данных ограничениях; если нет — сообщается минимально достижимый объём.
3. Ограничения — предустановки из data/optimizer_presets.csv (все assumed):
   - коридор: x0·(1 − d) ≤ x ≤ x0·(1 + d) для каждой культуры;
   - продовольственные культуры: Σ x_food ≥ f · Σ x0_food;
   - общая площадь: a · Σ x0 ≤ Σ x ≤ Σ x0 (a = 1: та же земля, другая структура).

Переменные — площади культур, га; коэффициенты — м³/га «из реки» из слоя 1; вода — м³.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import linprog

PRESET_PARAMS = ["area_change_max", "food_area_min_share", "total_area_min_share"]
TOL = 1e-6  # относительный допуск для «активного» ограничения


@dataclass
class OptResult:
    status: str                     # "optimal" | "infeasible"
    message: str
    areas: dict = field(default_factory=dict)        # га по культурам
    water_m3: float = float("nan")
    base_water_m3: float = float("nan")
    limit_m3: float | None = None
    min_achievable_m3: float = float("nan")          # минимум без лимита при тех же ограничениях
    active: list = field(default_factory=list)       # активные ограничения (названия)

    @property
    def saving_m3(self):
        return self.base_water_m3 - self.water_m3

    @property
    def saving_pct(self):
        return 100.0 * self.saving_m3 / self.base_water_m3


# --- Данные ---

def load_presets(presets_df):
    """{preset_id: {area_change_max, food_area_min_share, total_area_min_share}} из optimizer_presets.csv."""
    sub = presets_df[(presets_df["entity"] == "preset") & presets_df["param"].isin(PRESET_PARAMS)]
    out = {}
    for (m, p), v in sub.groupby(["measure", "param"])["value"]:
        if len(v) != 1:
            raise ValueError(f"Повтор параметра {p} в предустановке {m}")
        out.setdefault(m, {})[p] = float(v.iloc[0])
    for m, d in out.items():
        missing = [p for p in PRESET_PARAMS if p not in d]
        if missing:
            raise ValueError(f"В предустановке {m} нет {missing}")
    return out


def load_targets(presets_df):
    """{target_id: r} — относительные цели снижения забора из реки."""
    sub = presets_df[presets_df["param"] == "water_reduction_target"]
    return dict(zip(sub["measure"], sub["value"].astype(float)))


def food_crops(presets_df, crops):
    """Множество продовольственных культур (food_crop = 1). Каждая культура должна быть размечена."""
    sub = presets_df[presets_df["param"] == "food_crop"]
    flags = dict(zip(sub["entity"], sub["value"].astype(float)))
    missing = [c for c in crops if c not in flags]
    if missing:
        raise ValueError(f"Нет отметки food_crop для {missing}")
    return {c for c in crops if flags[c] == 1.0}


def river_coefficients(layer1_scenarios, field="base", canal="base", perc="base", climate="mean"):
    """м³/га «из реки» по культурам для сценария КПД и климата (среднее 2010–2025 или год)."""
    s = layer1_scenarios[(layer1_scenarios["eff_field_measure"] == field)
                         & (layer1_scenarios["eff_canal_measure"] == canal)
                         & (layer1_scenarios["perc_measure"] == perc)]
    if s.empty:
        raise ValueError(f"Нет сценария {field}|{canal}|{perc}")
    if climate == "mean":
        return s.groupby("crop")["river_m3_ha"].mean().to_dict()
    s = s[s["year"] == int(climate)]
    if s.empty:
        raise ValueError(f"Нет года {climate}")
    return dict(zip(s["crop"], s["river_m3_ha"]))


# --- Оптимизация ---

def _build(coef, base, preset, food):
    crops = list(base)
    missing = [k for k in crops if k not in coef]
    if missing:
        raise ValueError(f"Нет коэффициентов воды для {missing}")
    c = np.array([coef[k] for k in crops], dtype=float)
    x0 = np.array([base[k] for k in crops], dtype=float)
    if (c < 0).any() or (x0 < 0).any():
        raise ValueError("Коэффициенты и площади должны быть неотрицательными")
    d, f, a = preset["area_change_max"], preset["food_area_min_share"], preset["total_area_min_share"]
    bounds = [(xi * (1 - d), xi * (1 + d)) for xi in x0]
    is_food = np.array([1.0 if k in food else 0.0 for k in crops])
    A, b, names = [], [], []
    A.append(np.ones(len(crops))); b.append(x0.sum()); names.append("total area ≤ current")
    A.append(-np.ones(len(crops))); b.append(-a * x0.sum()); names.append("total area ≥ share of current")
    if is_food.any():
        A.append(-is_food); b.append(-f * (is_food * x0).sum()); names.append("food crops ≥ share of current")
    return crops, c, x0, bounds, A, b, names


def optimize(coef, base, preset, food, limit_m3=None):
    """Минимум воды «из реки» при ограничениях предустановки и (необязательно) лимите воды, м³.

    coef: {культура: м³/га}; base: {культура: га} — текущая структура; food: множество культур.
    """
    crops, c, x0, bounds, A, b, names = _build(coef, base, preset, food)
    base_water = float(c @ x0)

    # Минимум без лимита — он же оптимум при любом достижимом лимите (цель — минимум воды)
    free = linprog(c, A_ub=np.array(A), b_ub=np.array(b), bounds=bounds, method="highs")
    if free.status != 0:
        return OptResult("infeasible", "Ограничения предустановки противоречат друг другу: "
                         "решения нет даже без лимита воды (" + free.message + ")",
                         base_water_m3=base_water, limit_m3=limit_m3)
    min_water = float(free.fun)
    if limit_m3 is not None and min_water > limit_m3 * (1 + TOL):
        return OptResult("infeasible",
                         f"Лимит {limit_m3 / 1e9:.2f} км³ недостижим при этих ограничениях: "
                         f"минимум {min_water / 1e9:.2f} км³ (не хватает {(min_water - limit_m3) / 1e9:.2f} км³)",
                         base_water_m3=base_water, limit_m3=limit_m3, min_achievable_m3=min_water)

    x = free.x
    active = []
    slack = np.array(b) - np.array(A) @ x
    scale = max(1.0, x0.sum())
    for name, s in zip(names, slack):
        if s <= TOL * scale:
            active.append(name)
    for k, xi, (lo, hi) in zip(crops, x, bounds):
        if abs(xi - lo) <= TOL * max(1.0, lo):
            active.append(f"{k} at lower bound")
        elif abs(xi - hi) <= TOL * max(1.0, hi):
            active.append(f"{k} at upper bound")
    if limit_m3 is not None and limit_m3 - min_water <= TOL * limit_m3:
        active.append("water limit")
    msg = "Оптимум найден" + ("" if limit_m3 is None else f"; лимит {limit_m3 / 1e9:.2f} км³ выполнен")
    return OptResult("optimal", msg, areas=dict(zip(crops, map(float, x))), water_m3=min_water,
                     base_water_m3=base_water, limit_m3=limit_m3, min_achievable_m3=min_water, active=active)


# --- Сводка для run_all ---

def run_presets(coef, base, presets, food, targets, absolute_limit_m3=None):
    """Результаты по всем предустановкам: оптимальная структура и выполнимость лимитов.

    Возвращает (structures, feasibility) — два DataFrame.
    """
    rows, feas = [], []
    for pid, preset in presets.items():
        r = optimize(coef, base, preset, food)
        if r.status != "optimal":
            feas.append({"preset": pid, "limit_kind": "none", "limit_id": "-", "limit_m3": None,
                         "feasible": False, "message": r.message})
            continue
        for k in base:
            rows.append({"preset": pid, "crop": k, "base_ha": base[k], "opt_ha": r.areas[k],
                         "change_ha": r.areas[k] - base[k],
                         "change_pct": 100 * (r.areas[k] / base[k] - 1) if base[k] else None,
                         "river_m3_ha": coef[k]})
        limits = [("relative", tid, r.base_water_m3 * (1 - rv)) for tid, rv in targets.items()]
        if absolute_limit_m3 is not None:
            limits.append(("absolute", "layer2_high", absolute_limit_m3))
        for kind, lid, lim in limits:
            rr = optimize(coef, base, preset, food, lim)
            feas.append({"preset": pid, "limit_kind": kind, "limit_id": lid, "limit_m3": lim,
                         "feasible": rr.status == "optimal", "min_achievable_m3": r.water_m3,
                         "base_m3": r.base_water_m3, "saving_pct_max": r.saving_pct, "message": rr.message})
    return pd.DataFrame(rows), pd.DataFrame(feas)
