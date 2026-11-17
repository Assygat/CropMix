"""Расширенный оптимизатор структуры посевов (Decision Lab), 2026-11-17.

Отдельный модуль: НЕ заменяет src/layer3_optimizer.py (модуль 6). Предустановки модуля 6
(минимум воды при Σx = Σx0) и их результаты в outputs/ остаются эталоном и не меняются.

Постановка — линейное программирование (scipy.optimize.linprog, метод HiGHS):
  переменные   x_c ≥ 0 — площадь культуры c, га;
  коэффициенты w_c — забор «из реки», м³/га (слой 1), y_c — урожайность, т/га, v_c — стоимость, тенге/га;
  ограничения  l_c ≤ x_c ≤ u_c                      (границы по культурам)
               Σ w_c·x_c ≤ B                         (водный бюджет, м³)            — если задан
               Σ x_c ≤ L  или  Σ x_c = L             (земля, га)                    — если задана
               Σ_{c∈food} x_c ≥ F                    (площадь продовольственных, га) — если задана
               y_c·x_c ≥ Q_c                         (минимум производства, т)       — для заданных культур
               Σ v_c·x_c ≥ V                         (минимум стоимости, тенге)      — если задан
  цели         min_water: min Σ w·x;  max_area: max Σ x;  max_food_area: max Σ_food x;
               max_value: max Σ v·x (только если v задана для ВСЕХ культур).
Лексикографическая доводка: при равных значениях основной цели выбирается решение с меньшей
водой (для min_water — с большей площадью). Двойственные оценки берутся из ОСНОВНОЙ задачи.

Двойственная оценка (shadow price) — на сколько улучшится основная цель при ослаблении
ограничения на 1 единицу (м³, га, т, тенге). Это локальная производная: она верна, пока
не сменится набор активных ограничений; в вырожденной точке оценка может быть неединственной.

Ничего не придумывается: если коэффициента нет, цель/ограничение недоступны, а не обнуляются.
"""

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd
from scipy.optimize import linprog

OBJECTIVES = ("min_water", "max_area", "max_food_area", "max_value")
OBJECTIVE_UNITS = {"min_water": "m3", "max_area": "ha", "max_food_area": "ha", "max_value": "KZT"}
REL_TOL = 1e-7     # относительный допуск активности ограничения
TIE_TOL = 1e-9     # допуск основной цели при лексикографической доводке


@dataclass(frozen=True)
class Portfolio:
    """Описание задачи. Все словари — по культурам из crops; единицы: га, м³, т, тенге."""
    crops: tuple
    water_m3_ha: dict
    base_ha: dict
    lower_ha: dict
    upper_ha: dict
    water_budget_m3: float | None = None
    land_max_ha: float | None = None
    land_equal_ha: float | None = None
    food: frozenset = frozenset()
    food_min_ha: float | None = None
    yields_t_ha: dict = field(default_factory=dict)
    production_min_t: dict = field(default_factory=dict)
    value_kzt_ha: dict = field(default_factory=dict)
    value_min_kzt: float | None = None

    def check(self):
        errs = []
        for c in self.crops:
            for name, d in (("water_m3_ha", self.water_m3_ha), ("base_ha", self.base_ha),
                            ("lower_ha", self.lower_ha), ("upper_ha", self.upper_ha)):
                if c not in d:
                    errs.append(f"{name}: нет культуры {c}")
                elif not np.isfinite(d[c]) or d[c] < 0:
                    errs.append(f"{name}[{c}] должно быть конечным и ≥ 0, получено {d[c]}")
        if self.land_max_ha is not None and self.land_equal_ha is not None:
            errs.append("Задайте землю либо как ≤ (land_max_ha), либо как = (land_equal_ha)")
        for c in self.production_min_t:
            if c not in self.yields_t_ha:
                errs.append(f"Минимум производства для {c} задан, но урожайности нет")
        if errs:
            raise ValueError("; ".join(errs))

    def vec(self, d):
        return np.array([float(d[c]) for c in self.crops])

    @property
    def value_complete(self):
        return all(c in self.value_kzt_ha and np.isfinite(self.value_kzt_ha[c]) for c in self.crops)


@dataclass
class Solution:
    status: str                       # optimal | infeasible | unavailable
    objective: str
    message: str
    areas: dict = field(default_factory=dict)
    objective_value: float = float("nan")
    water_m3: float = float("nan")
    area_ha: float = float("nan")
    food_ha: float = float("nan")
    value_kzt: float | None = None
    production_t: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)   # dict: name, kind, lhs, rhs, slack, binding, shadow, shadow_unit
    bounds: list = field(default_factory=list)        # dict: crop, side, value_ha, reduced_cost
    diagnosis: list = field(default_factory=list)     # при infeasible: что ослабить


# --- Сборка матриц ---

def _rows(p):
    """Ограничения-неравенства в виде A_ub·x ≤ b_ub с описанием (имя, вид, единица, знак)."""
    n = len(p.crops)
    A, b, meta = [], [], []
    if p.water_budget_m3 is not None:
        A.append(p.vec(p.water_m3_ha)); b.append(float(p.water_budget_m3))
        meta.append(("water budget", "water", "m3", +1))
    if p.land_max_ha is not None:
        A.append(np.ones(n)); b.append(float(p.land_max_ha))
        meta.append(("land available", "land", "ha", +1))
    if p.food_min_ha is not None and p.food:
        is_food = np.array([1.0 if c in p.food else 0.0 for c in p.crops])
        A.append(-is_food); b.append(-float(p.food_min_ha))
        meta.append(("food-crop area minimum", "food", "ha", -1))
    for c, q in p.production_min_t.items():
        row = np.zeros(n); row[p.crops.index(c)] = -float(p.yields_t_ha[c])
        A.append(row); b.append(-float(q))
        meta.append((f"{c} production minimum", "production", "t", -1))
    if p.value_min_kzt is not None:
        if not p.value_complete:
            raise ValueError("Минимум стоимости задан, но стоимость известна не для всех культур")
        A.append(-p.vec(p.value_kzt_ha)); b.append(-float(p.value_min_kzt))
        meta.append(("value minimum", "value", "KZT", -1))
    return A, b, meta


def _objective(p, objective):
    if objective == "min_water":
        return p.vec(p.water_m3_ha), +1
    if objective == "max_area":
        return -np.ones(len(p.crops)), -1
    if objective == "max_food_area":
        return -np.array([1.0 if c in p.food else 0.0 for c in p.crops]), -1
    if objective == "max_value":
        return -p.vec(p.value_kzt_ha), -1
    raise ValueError(f"Неизвестная цель {objective!r}; доступны {OBJECTIVES}")


def _lp(p, c, A, b, extra=None):
    A_ub, b_ub = list(A), list(b)
    if extra is not None:
        A_ub.append(extra[0]); b_ub.append(extra[1])
    A_eq = b_eq = None
    if p.land_equal_ha is not None:
        A_eq, b_eq = np.ones((1, len(p.crops))), np.array([float(p.land_equal_ha)])
    bounds = [(float(p.lower_ha[k]), float(p.upper_ha[k])) for k in p.crops]
    return linprog(c, A_ub=np.array(A_ub) if A_ub else None, b_ub=np.array(b_ub) if b_ub else None,
                   A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")


# --- Решение ---

def solve(p, objective="min_water", tie_break=True):
    """Решает задачу p с целью objective. Невыполнимость возвращается со статусом и диагнозом."""
    p.check()
    if objective == "max_value" and not p.value_complete:
        missing = [c for c in p.crops if c not in p.value_kzt_ha]
        return Solution("unavailable", objective,
                        f"Objective max_value is unavailable: no value per hectare for {missing}. "
                        "Values are never filled in automatically — enter them explicitly.")
    bad = [c for c in p.crops if p.lower_ha[c] > p.upper_ha[c] * (1 + 1e-12)]
    if bad:
        return Solution("infeasible", objective, f"Lower bound above upper bound for {bad}",
                        diagnosis=[f"lower bound above upper bound: {bad}"])
    A, b, meta = _rows(p)
    c, sign = _objective(p, objective)
    res = _lp(p, c, A, b)
    if res.status == 2:
        return Solution("infeasible", objective, "No feasible allocation: the constraints conflict",
                        diagnosis=diagnose(p))
    if res.status != 0:
        raise RuntimeError(f"linprog: {res.message}")
    x = res.x
    if tie_break and not (objective == "min_water" and p.land_equal_ha is not None):   # там площадь задана
        # Доводка: основная цель не хуже оптимума, вторичная — минимум воды (или максимум площади).
        opt = float(res.fun)
        tol = TIE_TOL * max(1.0, abs(opt))
        sec = -np.ones(len(p.crops)) if objective == "min_water" else p.vec(p.water_m3_ha)
        r2 = _lp(p, sec, A, b, extra=(c, opt + tol))
        if r2.status == 0:
            x = r2.x
    return _describe(p, objective, x, res, A, b, meta, sign)


def _describe(p, objective, x, primary, A, b, meta, sign):
    x = np.clip(x, [p.lower_ha[k] for k in p.crops], [p.upper_ha[k] for k in p.crops])
    areas = dict(zip(p.crops, map(float, x)))
    w = p.vec(p.water_m3_ha)
    is_food = np.array([1.0 if c in p.food else 0.0 for c in p.crops])
    sol = Solution("optimal", objective, "Optimal allocation found", areas=areas,
                   objective_value=sign * float(primary.fun), water_m3=float(w @ x),
                   area_ha=float(x.sum()), food_ha=float(is_food @ x))
    if p.value_complete:
        sol.value_kzt = float(p.vec(p.value_kzt_ha) @ x)
    sol.production_t = {c: areas[c] * p.yields_t_ha[c] for c in p.crops if c in p.yields_t_ha}
    marg = primary.ineqlin.marginals if len(A) else []
    unit = OBJECTIVE_UNITS[objective]
    for i, (name, kind, cunit, ge) in enumerate(meta):
        lhs_raw = float(np.asarray(A[i]) @ x)
        slack = float(b[i]) - lhs_raw                      # ≥ 0 при выполнении
        lhs, rhs = (lhs_raw, float(b[i])) if ge > 0 else (-lhs_raw, -float(b[i]))
        binding = slack <= REL_TOL * max(1.0, abs(float(b[i])))
        # улучшение цели на единицу ослабления; ослабление = рост b_ub, поэтому shadow = −marginal
        shadow = -float(marg[i]) if len(marg) else float("nan")
        sol.constraints.append({"name": name, "kind": kind, "lhs": lhs, "rhs": rhs, "unit": cunit,
                                "slack": slack, "binding": bool(binding),
                                "shadow": shadow if abs(shadow) > 1e-12 else 0.0,
                                "shadow_unit": f"{unit} per {cunit}"})
    if p.land_equal_ha is not None:
        m = float(primary.eqlin.marginals[0])
        sol.constraints.append({"name": "land fixed", "kind": "land", "lhs": float(x.sum()),
                                "rhs": float(p.land_equal_ha), "unit": "ha", "slack": 0.0, "binding": True,
                                "shadow": sign * m, "shadow_unit": f"{unit} per ha (d objective / d land)"})
    for k, xi, rl, ru in zip(p.crops, x, primary.lower.marginals, primary.upper.marginals):
        lo, hi = p.lower_ha[k], p.upper_ha[k]
        if hi - lo <= REL_TOL * max(1.0, hi):
            sol.bounds.append({"crop": k, "side": "fixed", "value_ha": float(xi), "reduced_cost": 0.0})
        elif xi - lo <= REL_TOL * max(1.0, lo):
            sol.bounds.append({"crop": k, "side": "lower", "value_ha": float(xi), "reduced_cost": float(rl)})
        elif hi - xi <= REL_TOL * max(1.0, hi):
            sol.bounds.append({"crop": k, "side": "upper", "value_ha": float(xi), "reduced_cost": float(ru)})
    return sol


# --- Диагностика невыполнимости ---

def diagnose(p):
    """Что мешает решению и насколько надо ослабить каждое ограничение (с числами). Ничего не ослабляет молча."""
    out = []
    lo = sum(p.lower_ha[c] for c in p.crops)
    hi = sum(p.upper_ha[c] for c in p.crops)
    land = p.land_equal_ha if p.land_equal_ha is not None else p.land_max_ha
    if land is not None and lo > land * (1 + 1e-12):
        out.append(f"minimum areas sum to {lo:,.0f} ha, more than the land limit {land:,.0f} ha")
    if p.land_equal_ha is not None and hi < p.land_equal_ha:
        out.append(f"maximum areas sum to {hi:,.0f} ha, less than the required total {p.land_equal_ha:,.0f} ha")
    if p.food_min_ha is not None:
        food_hi = sum(p.upper_ha[c] for c in p.food if c in p.upper_ha)
        if p.food_min_ha > food_hi:
            out.append(f"food-crop minimum {p.food_min_ha:,.0f} ha exceeds the food crops' upper bounds {food_hi:,.0f} ha")
    for c, q in p.production_min_t.items():
        if q > p.yields_t_ha[c] * p.upper_ha[c]:
            out.append(f"{c} production minimum {q:,.0f} t exceeds yield × upper bound "
                       f"{p.yields_t_ha[c] * p.upper_ha[c]:,.0f} t")
    if p.water_budget_m3 is not None:
        r = _try(replace(p, water_budget_m3=None), "min_water")
        if r is None:
            out.append("the problem is infeasible even with unlimited water (land, area bounds or minimums conflict)")
        elif r.water_m3 > p.water_budget_m3:
            out.append(f"water: these constraints need at least {r.water_m3 / 1e9:.3f} km³ but the budget is "
                       f"{p.water_budget_m3 / 1e9:.3f} km³ — raise the budget by "
                       f"{(r.water_m3 - p.water_budget_m3) / 1e9:.3f} km³ or relax the minimums below")
            if p.food_min_ha is not None:
                rf = _try(replace(p, food_min_ha=None), "max_food_area")
                if rf is None:
                    out.append("food: even without the food minimum the water budget cannot cover the minimum areas")
                elif rf.food_ha < p.food_min_ha:
                    out.append(f"food: within this budget the food-crop area can be at most {rf.food_ha:,.0f} ha "
                               f"(minimum asked: {p.food_min_ha:,.0f} ha)")
            rmin = _try(replace(p, water_budget_m3=None, food_min_ha=None, production_min_t={}), "min_water")
            if rmin is not None and rmin.water_m3 > p.water_budget_m3:
                out.append(f"the minimum retained area of each crop alone needs {rmin.water_m3 / 1e9:.3f} km³ — "
                           "lower the minimum retained share")
    return out or ["constraints conflict (no single simple cause found)"]


def _try(p, objective):
    try:
        A, b, meta = _rows(p)
        c, sign = _objective(p, objective)
        res = _lp(p, c, A, b)
    except ValueError:
        return None
    if res.status != 0:
        return None
    return _describe(p, objective, res.x, res, A, b, meta, sign)


# --- Производные анализы ---

def resolve_marginal(p, objective, field_name, delta):
    """Конечная разность для проверки двойственных оценок: улучшение цели на единицу изменения параметра.

    delta задаётся в направлении ОСЛАБЛЕНИЯ (бюджет: +, минимум: −); результат делится на |delta|.
    """
    a = solve(p, objective, tie_break=False)
    b = solve(replace(p, **{field_name: getattr(p, field_name) + delta}), objective, tie_break=False)
    if a.status != "optimal" or b.status != "optimal":
        return float("nan")
    gain = (b.objective_value - a.objective_value) / abs(delta)
    return -gain if objective == "min_water" else gain


def pareto(p, objective, budgets_m3):
    """Эпсилон-ограничение: для каждого водного бюджета — лучшая цель и фактически использованная вода.

    Каждая точка — эффективный компромисс «вода ↔ цель» (доводка по минимуму воды убирает слабо
    эффективные точки): улучшить цель без увеличения воды нельзя.
    """
    rows = []
    for bud in budgets_m3:
        s = solve(replace(p, water_budget_m3=float(bud)), objective)
        ok = s.status == "optimal"
        wrow = next((c for c in s.constraints if c["kind"] == "water"), None) if ok else None
        rows.append({"budget_m3": float(bud), "status": s.status,
                     "objective": s.objective_value if ok else None,
                     "water_m3": s.water_m3 if ok else None,
                     "area_ha": s.area_ha if ok else None,
                     "food_ha": s.food_ha if ok else None,
                     "water_binding": bool(wrow["binding"]) if wrow else None,
                     "water_shadow": wrow["shadow"] if wrow else None,
                     **{f"area_{c}": s.areas.get(c) for c in p.crops}})
    return pd.DataFrame(rows)


def explain(base, sol, p):
    """Таблица изменений по культурам и текстовое объяснение (английский — для сайта)."""
    rows = []
    for c in p.crops:
        b0, x = float(base[c]), sol.areas.get(c, float("nan"))
        rows.append({"crop": c, "base_ha": b0, "opt_ha": x, "change_ha": x - b0,
                     "change_pct": 100 * (x / b0 - 1) if b0 else None,
                     "water_m3_ha": p.water_m3_ha[c], "base_water_m3": b0 * p.water_m3_ha[c],
                     "opt_water_m3": x * p.water_m3_ha[c]})
    df = pd.DataFrame(rows)
    if sol.status != "optimal":
        return df, [sol.message] + sol.diagnosis
    lines = []
    w0 = float(df["base_water_m3"].sum())
    lines.append(f"Water: {w0 / 1e9:.3f} → {sol.water_m3 / 1e9:.3f} km³ "
                 f"({(sol.water_m3 - w0) / 1e9:+.3f} km³, {100 * (sol.water_m3 / w0 - 1):+.1f} %).")
    a0 = float(df["base_ha"].sum())
    lines.append(f"Cropped area: {a0:,.0f} → {sol.area_ha:,.0f} ha ({100 * (sol.area_ha / a0 - 1):+.1f} %).")
    gain = df[df["change_ha"] > 1].sort_values("change_ha", ascending=False)
    loss = df[df["change_ha"] < -1].sort_values("change_ha")
    if len(gain):
        lines.append("Gained area: " + ", ".join(f"{r.crop} {r.change_ha:+,.0f} ha" for r in gain.itertuples()) + ".")
    if len(loss):
        lines.append("Lost area: " + ", ".join(f"{r.crop} {r.change_ha:+,.0f} ha" for r in loss.itertuples()) + ".")
    for c in sol.constraints:
        if c["binding"]:
            lines.append(f"Binding: {c['name']} (shadow value {c['shadow']:.4g} {c['shadow_unit']}).")
        elif c["kind"] == "water":
            lines.append(f"Water budget not fully used: {c['slack'] / 1e9:.3f} km³ left.")
    for bd in sol.bounds:
        lines.append(f"{bd['crop']} is at its {bd['side']} area bound ({bd['value_ha']:,.0f} ha).")
    return df, lines


# --- Построение задач из данных проекта ---

def emergency_problem(coef, base, preset, food, supply_share, yields=None, value=None, base_water_m3=None):
    """Режим дефицита: бюджет = доля × модельная потребность базовой структуры; часть земли может остаться
    без посева (Σx ≤ Σx0); каждая культура ≥ min_retained_share·x0 и ≤ (1 + area_change_max)·x0;
    продовольственные ≥ food_area_min_share·Σx0_food."""
    crops = tuple(base)
    w0 = base_water_m3 if base_water_m3 is not None else sum(coef[c] * base[c] for c in crops)
    return Portfolio(
        crops=crops, water_m3_ha=dict(coef), base_ha=dict(base),
        lower_ha={c: base[c] * preset["min_retained_share"] for c in crops},
        upper_ha={c: base[c] * (1 + preset["area_change_max"]) for c in crops},
        water_budget_m3=supply_share * w0, land_max_ha=float(sum(base.values())),
        food=frozenset(food), food_min_ha=preset["food_area_min_share"] * sum(base[c] for c in crops if c in food),
        yields_t_ha=dict(yields or {}), value_kzt_ha=dict(value or {}))


def uniform_curtailment(base, supply_share):
    """Опорное правило для сравнения (не фактическая практика): все площади × доля воды."""
    return {c: v * supply_share for c, v in base.items()}


def run_emergency(coef, base, preset, food, shares, yields=None, value=None, objective="max_area",
                  base_water_m3=None):
    """Сводка режима дефицита: строки по долям воды и по культурам. Невыполнимые доли — с диагнозом."""
    w0 = base_water_m3 if base_water_m3 is not None else sum(coef[c] * base[c] for c in base)
    a0 = float(sum(base.values()))
    summary, crops_rows = [], []
    for sid, share in shares:
        p = emergency_problem(coef, base, preset, food, share, yields, value, w0)
        s = solve(p, objective)
        uni = uniform_curtailment(base, share)
        uni_ok = (share >= preset["min_retained_share"]
                  and sum(uni[c] for c in food) >= p.food_min_ha * (1 - 1e-12))
        row = {"scarcity": sid, "supply_share": share, "budget_m3": p.water_budget_m3, "base_water_m3": w0,
               "baseline_feasible": w0 <= p.water_budget_m3 * (1 + 1e-12), "status": s.status,
               "objective": objective, "base_area_ha": a0,
               "uniform_area_ha": a0 * share, "uniform_respects_constraints": uni_ok}
        if s.status == "optimal":
            wb = next(c for c in s.constraints if c["kind"] == "water")
            row.update({"opt_area_ha": s.area_ha, "opt_area_pct": 100 * s.area_ha / a0,
                        "fallow_ha": a0 - s.area_ha, "water_m3": s.water_m3,
                        "water_unused_m3": wb["slack"], "food_ha": s.food_ha,
                        "area_gain_vs_uniform_ha": s.area_ha - a0 * share,
                        "water_shadow_ha_per_mln_m3": wb["shadow"] * 1e6 if objective == "max_area" else None,
                        "binding": "; ".join([c["name"] for c in s.constraints if c["binding"]]
                                             + [f"{b['crop']} {b['side']}" for b in s.bounds]),
                        "diagnosis": ""})
            for c in base:
                y = (yields or {}).get(c)
                crops_rows.append({"scarcity": sid, "supply_share": share, "crop": c, "base_ha": base[c],
                                   "opt_ha": s.areas[c], "uniform_ha": uni[c],
                                   "change_pct": 100 * (s.areas[c] / base[c] - 1) if base[c] else None,
                                   "base_prod_t": base[c] * y if y else None,
                                   "opt_prod_t": s.areas[c] * y if y else None})
        else:
            row.update({"diagnosis": " | ".join(s.diagnosis), "binding": ""})
        summary.append(row)
    return pd.DataFrame(summary), pd.DataFrame(crops_rows)


def load_planner_presets(df):
    """({preset: {min_retained_share, area_change_max, food_area_min_share}}, [(scarcity_id, share)] по убыванию)."""
    presets = {}
    for r in df[df["entity"] == "emergency"].itertuples():
        presets.setdefault(r.measure, {})[r.param] = float(r.value)
    for k, d in presets.items():
        miss = {"min_retained_share", "area_change_max", "food_area_min_share"} - set(d)
        if miss:
            raise ValueError(f"Предустановка {k}: нет {sorted(miss)}")
    sc = df[(df["entity"] == "scarcity") & (df["param"] == "water_supply_share")]
    shares = sorted(((r.measure, float(r.value)) for r in sc.itertuples()), key=lambda t: -t[1])
    return presets, shares


# --- Экономика: только из data/, без подстановок ---

# Соответствие групп модели строкам yields.csv / prices.csv. None — данных нет (ничего не подставляется).
YIELD_ENTITY = {"rice": "rice", "potato": "potato", "vegetables_open": "vegetables_open", "melons": "melons",
                "oilseeds": "oilseeds", "wheat": None, "fodder": None, "grain_other": None}
PRICE_ENTITY = {"rice": "rice", "potato": "potato", "melons": "watermelon", "wheat": "wheat",
                "fodder": "fodder_hay", "vegetables_open": None, "oilseeds": None, "grain_other": None}
PRICE_NOTE = {"melons": "proxy: watermelon price used for the whole melons group (assumption)",
              "fodder": "hay price; fodder yield in hay equivalent is not in the data",
              "wheat": "wheat yield is not in the data (regional grain yield includes rice)"}


def economic_coefficients(yields_df, prices_df, crops, year=2025, price_year=2026):
    """По культурам: урожайность и цена со статусами и источниками; пропуски остаются пустыми."""
    rows = []
    for c in crops:
        r = {"crop": c, "yield_t_ha": None, "yield_status": "missing", "yield_source": "",
             "price_kzt_t": None, "price_status": "missing", "price_source": "", "note": PRICE_NOTE.get(c, "")}
        ye = YIELD_ENTITY.get(c)
        if ye:
            s = yields_df[(yields_df["entity"] == ye) & (yields_df["param"] == "yield")
                          & (yields_df["year"] == year)]
            if len(s) == 1:
                r.update(yield_t_ha=float(s["value"].iloc[0]), yield_status=s["status"].iloc[0],
                         yield_source=str(s["source"].iloc[0])[:120])
        pe = PRICE_ENTITY.get(c)
        if pe:
            s = prices_df[(prices_df["entity"] == pe) & (prices_df["param"] == "price")
                          & (prices_df["year"] == price_year)]
            if len(s) == 1:
                r.update(price_kzt_t=float(s["value"].iloc[0]), price_status=s["status"].iloc[0],
                         price_source=str(s["source"].iloc[0])[:120])
        rows.append(r)
    return pd.DataFrame(rows)


# --- Почему экономия модуля 6 ограничена (атрибуция) ---

def module6_problem(coef, base, preset, food):
    """Постановка модуля 6 в терминах Portfolio: Σx = Σx0, коридор ±d, продовольственные ≥ f·Σx0_food."""
    d, f = preset["area_change_max"], preset["food_area_min_share"]
    crops = tuple(base)
    return Portfolio(crops=crops, water_m3_ha=dict(coef), base_ha=dict(base),
                     lower_ha={c: base[c] * (1 - d) for c in crops}, upper_ha={c: base[c] * (1 + d) for c in crops},
                     land_equal_ha=float(sum(base.values())), food=frozenset(food),
                     food_min_ha=f * sum(base[c] for c in crops if c in food))


def savings_attribution(coef, base, preset, food, flooded=("rice",)):
    """Эксперименты «что если ослабить одно ограничение» для предустановки модуля 6 + разложение экономии.

    Это диагностика постановки, а не новые рекомендации: каждая строка меняет ровно одно допущение.
    """
    p = module6_problem(coef, base, preset, food)
    w0 = sum(coef[c] * base[c] for c in base)
    nonflood = [c for c in base if c not in flooded]

    def pct(q):
        s = solve(q, "min_water")
        return (100 * (w0 - s.water_m3) / w0, s) if s.status == "optimal" else (None, s)

    exps = [("reference (module 6 preset)", p)]
    exps.append(("food-crop minimum removed", replace(p, food_min_ha=None)))
    exps.append(("rice lower bound removed (rice may fall to 0 ha)",
                 replace(p, lower_ha={**p.lower_ha, **{c: 0.0 for c in flooded}})))
    exps.append(("upper bounds of all other crops doubled (+100 %)",
                 replace(p, upper_ha={**p.upper_ha, **{c: base[c] * 2.0 for c in nonflood}})))
    exps.append(("fodder fixed at its 2025 area (cannot absorb land)",
                 replace(p, lower_ha={**p.lower_ha, "fodder": base["fodder"]},
                         upper_ha={**p.upper_ha, "fodder": base["fodder"]}) if "fodder" in base else p))
    exps.append(("total area may fall (Σx ≤ Σx0, freed land left fallow)",
                 replace(p, land_equal_ha=None, land_max_ha=float(sum(base.values())))))
    rows = []
    for name, q in exps:
        v, s = pct(q)
        rows.append({"experiment": name, "feasible": s.status == "optimal", "saving_pct": v,
                     "water_m3": s.water_m3 if s.status == "optimal" else None,
                     "binding": "; ".join([c["name"] for c in s.constraints if c["binding"]]
                                          + [f"{b['crop']} {b['side']}" for b in s.bounds]) if s.status == "optimal" else
                     " | ".join(s.diagnosis)})
    ref = solve(p, "min_water")
    dec = []
    for c in base:
        dx = ref.areas[c] - base[c]
        dec.append({"crop": c, "change_ha": dx, "water_m3_ha": coef[c], "water_change_m3": dx * coef[c]})
    return pd.DataFrame(rows), pd.DataFrame(dec)
