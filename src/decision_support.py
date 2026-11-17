"""Decision Lab (2026-11-17): сборка новых модулей в outputs/ и web/data/planner.js.

Запускается из src/run_all.py ПОСЛЕ модулей 1–9 и не меняет их результаты. Новые файлы outputs/:
  decision_attribution.csv, decision_attribution_crops.csv — почему экономия модуля 6 ограничена;
  emergency_summary.csv, emergency_crops.csv              — режим дефицита (нормальный климат);
  pareto_area.csv                                         — компромисс «вода ↔ засеянная площадь»;
  stress_scenarios.csv, stress_coefficients.csv, stress_emergency.csv — стресс-тесты;
  uncertainty_summary.csv, uncertainty_ranking.csv, uncertainty_hist.csv — латинский гиперкуб;
  validation_climate.csv, validation_monthly.csv, validation_datasets.csv — проверка входов;
  economic_coefficients.csv                               — урожайность и цены (со статусами, без подстановок).
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src import climate_stress as cs
from src import layer3_optimizer as opt
from src import portfolio as pf
from src import uncertainty as unc
from src import validation as val
from src.export_web import OUTPUTS_DIR, WEB_DATA_DIR, crop_areas_wide

BASE_AREA_YEAR = 2025
N_SAMPLES = 2000
SEED = 20261117
GRID_DT = (0, 1, 2, 3, 4)
GRID_P = (1.0, 0.85, 0.7, 0.5)
PARETO_SHARES = tuple(np.round(np.arange(0.40, 1.0001, 0.025), 3))


def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else round(float(v), 6)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _records(df):
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def run(tables, verbose=True, n_samples=N_SAMPLES):
    out = {}
    crops = list(tables["crops_fao56"]["entity"].drop_duplicates())
    areas = crop_areas_wide(tables["crop_areas"], crops)
    base = areas.loc[BASE_AREA_YEAR][crops].to_dict()
    presets_df = tables["optimizer_presets"]
    food = opt.food_crops(presets_df, crops)
    m6 = opt.load_presets(presets_df)
    em_presets, shares = pf.load_planner_presets(tables["planner_presets"])

    # Климат: нормальный (Cmean) и стресс-сценарии — одни и те же функции модулей 2–3
    cache = {}
    stress, stress_coef, meta = cs.run_stress(tables, BASE_AREA_YEAR, cache)
    coef = stress_coef[stress_coef["scenario"] == "normal"].set_index("crop")["river_m3_ha"].to_dict()
    w0 = sum(coef[c] * base[c] for c in crops)

    # Экономика (только данные; пропуски не заполняются)
    econ = pf.economic_coefficients(tables["yields"], tables["prices"], crops)
    yields = {r.crop: r.yield_t_ha for r in econ.itertuples() if pd.notna(r.yield_t_ha)}
    out["economic_coefficients"] = econ

    # 1. Почему экономия модуля 6 ограничена
    att, dec = pf.savings_attribution(coef, base, m6["moderate"], food)
    out["decision_attribution"], out["decision_attribution_crops"] = att, dec

    # 2. Режим дефицита (нормальный климат), обе предустановки
    sums, crs = [], []
    for pid, pr in em_presets.items():
        s, c = pf.run_emergency(coef, base, pr, food, shares, yields=yields, base_water_m3=w0)
        s.insert(0, "preset", pid); c.insert(0, "preset", pid)
        sums.append(s); crs.append(c)
    out["emergency_summary"], out["emergency_crops"] = pd.concat(sums), pd.concat(crs)

    # 3. Парето «вода ↔ площадь» (предустановка protective, нормальный климат)
    p_prot = pf.emergency_problem(coef, base, em_presets["protective"], food, 1.0, yields, base_water_m3=w0)
    par = pf.pareto(p_prot, "max_area", [s * w0 for s in PARETO_SHARES])
    par.insert(0, "supply_share", PARETO_SHARES)
    out["pareto_area"] = par

    # 4. Стресс-тесты + режим дефицита в каждом сценарии
    se = []
    for r in stress.itertuples():
        c_s = stress_coef[stress_coef["scenario"] == r.scenario].set_index("crop")["river_m3_ha"].to_dict()
        p = pf.emergency_problem(c_s, base, em_presets["protective"], food, 1.0, yields, base_water_m3=w0)
        p = pf.replace(p, water_budget_m3=r.available_m3)
        sol = pf.solve(p, "max_area")
        row = {"scenario": r.scenario, "available_m3": r.available_m3, "demand_m3": r.river_m3,
               "baseline_feasible": r.river_m3 <= r.available_m3 * (1 + 1e-12), "status": sol.status}
        if sol.status == "optimal":
            row.update({"opt_area_ha": sol.area_ha, "opt_area_pct": 100 * sol.area_ha / sum(base.values()),
                        "water_m3": sol.water_m3, "food_ha": sol.food_ha,
                        "rice_ha": sol.areas["rice"], "rice_prod_t": sol.production_t.get("rice"),
                        **{f"area_{c}": sol.areas[c] for c in crops}})
        else:
            row["diagnosis"] = " | ".join(sol.diagnosis)
        se.append(row)
    out["stress_scenarios"], out["stress_coefficients"], out["stress_emergency"] = stress, stress_coef, pd.DataFrame(se)
    grid = cs.climate_grid(tables, GRID_DT, GRID_P, cache)

    # 5. Неопределённость (латинский гиперкуб)
    samples, usum, urank = unc.run_uncertainty(tables, n=n_samples, seed=SEED)
    out["uncertainty_summary"], out["uncertainty_ranking"] = usum, urank
    hist = []
    for col, edges in (("river_m3", np.linspace(4.5e9, 10.5e9, 25)), ("saving_moderate_pct", np.linspace(0, 9, 19))):
        cnt, e = np.histogram(samples[col].dropna(), bins=edges)
        hist += [{"output": col, "bin_low": float(a), "bin_high": float(b), "count": int(k)}
                 for a, b, k in zip(e[:-1], e[1:], cnt)]
    out["uncertainty_hist"] = pd.DataFrame(hist)

    # 6. Валидация входов
    vc, vm = val.climate_input_validation(tables)
    out["validation_climate"], out["validation_monthly"] = vc, vm
    out["validation_datasets"] = val.dataset_inventory()

    for name, df in out.items():
        df.to_csv(OUTPUTS_DIR / f"{name}.csv", index=False, encoding="utf-8")

    web = {
        "generated_by": "src/decision_support.py",
        "base_year": BASE_AREA_YEAR, "crops": crops, "base_ha": {c: float(base[c]) for c in crops},
        "food": sorted(food), "base_water_m3": w0, "drought_year": meta["drought_year"],
        "module6_presets": {k: {kk: float(vv) for kk, vv in v.items()} for k, v in m6.items()},
        "emergency_presets": em_presets, "scarcity_levels": [{"id": a, "share": b} for a, b in shares],
        "climate_grid": {"delta_t": list(map(float, GRID_DT)), "precip": list(map(float, GRID_P)),
                         "rows": _records(grid)},
        "economics": _records(econ),
        "stress": _records(stress), "stress_coefficients": _records(stress_coef),
        "stress_emergency": _records(out["stress_emergency"]),
        "emergency_summary": _records(out["emergency_summary"]),
        "emergency_crops": _records(out["emergency_crops"]),
        "pareto_area": _records(par[["supply_share", "budget_m3", "status", "objective", "water_m3", "area_ha",
                                     "food_ha", "water_shadow"]]),
        "attribution": _records(att), "attribution_crops": _records(dec),
        "uncertainty": {"n": n_samples, "seed": SEED, "summary": _records(usum), "ranking": _records(urank),
                        "hist": _records(out["uncertainty_hist"])},
        "validation": {"climate": _records(vc), "monthly": _records(vm), "datasets": _records(out["validation_datasets"])},
    }
    text = json.dumps(web, ensure_ascii=False, separators=(",", ":"))
    (WEB_DATA_DIR / "planner.json").write_text(text, encoding="utf-8")
    (WEB_DATA_DIR / "planner.js").write_text("window.CROPMIX_PLANNER = " + text + ";\n", encoding="utf-8")

    if verbose:
        _print(out, w0, meta)
    return out, web


def _print(out, w0, meta):
    print("\nDecision Lab (2026-11-17) — новые модули, результаты модулей 1–9 не меняются:")
    print("  Почему экономия moderate ограничена (по одному ослабленному допущению):")
    for r in out["decision_attribution"].itertuples():
        print(f"    {r.experiment:58s} {r.saving_pct:6.2f} %")
    print(f"  Режим дефицита (max площади; доступно = доля × {w0 / 1e9:.2f} км³; пользовательские сценарии):")
    for r in out["emergency_summary"].itertuples():
        if r.status == "optimal":
            print(f"    {r.preset:10s} {r.supply_share:.0%}: засеяно {r.opt_area_pct:.1f} % площади "
                  f"(равномерное сокращение: {100 * r.supply_share:.0f} %)")
        else:
            print(f"    {r.preset:10s} {r.supply_share:.0%}: решения нет — {r.diagnosis[:150]}")
    print(f"  Стресс-тесты (эксперименты чувствительности; засушливый год-аналог C{meta['drought_year']}):")
    for r in out["stress_scenarios"].itertuples():
        print(f"    {r.scenario:15s} ET0 {r.et0_season_mm:6.0f} мм, W {r.river_m3 / 1e9:.2f} км³ "
              f"({r.river_vs_normal_pct:+.1f} %), доступно {r.available_m3 / 1e9:.2f}, дефицит {r.deficit_pct_of_demand:.1f} %")
    u = out["uncertainty_summary"].set_index("output")
    print(f"  Латинский гиперкуб, n = {int(u.loc['river_m3', 'n'])}: W P5–P95 = {u.loc['river_m3', 'p5'] / 1e9:.2f}–"
          f"{u.loc['river_m3', 'p95'] / 1e9:.2f} км³; экономия moderate P5–P95 = "
          f"{u.loc['saving_moderate_pct', 'p5']:.1f}–{u.loc['saving_moderate_pct', 'p95']:.1f} %")
    for r in out["validation_climate"].itertuples():
        print(f"    {r.check}: n = {r.n}, средняя разность {r.mean_diff:+.2f} {r.unit}")
