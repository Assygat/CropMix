"""Полный пересчёт с нуля: data/ -> outputs/ и web/data/.

Запуск: python -m src.run_all
"""

import sys

from src.data_loader import load_all
from src.data_report import summarize
from src.export_web import OUTPUTS_DIR, build_model, regional_totals, write_outputs
from src.layer2_scenarios import build_scenarios
from src import layer3_optimizer as opt
from src.export_web import crop_areas_wide

import pandas as pd

from src.backtest import run_backtest
from src.sensitivity import run_sensitivity

BASE_AREA_YEAR = 2025  # текущая структура посевов для оптимизатора (последний год данных)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    tables = load_all()
    print("Статусы чисел в data/:")
    print(summarize(tables).to_string(index=False))
    model, frames = build_model(tables)
    path = write_outputs(model, frames)
    c = model["comparison"]
    print(f"\nЗаписано: {path} и outputs/ ({', '.join(f + '.csv' for f in frames)})")
    print(f"Культур: {len(model['crops'])}, лет: {len(model['years'])}, сценариев: {len(model['coef_m3_ha'])}")
    print("Обозначения: W(A<год площадей>, C<год климата | mean>, E<сценарий КПД>) — модельный забор «из реки».")
    print("W(A_y, C_y, E_base) / официальный лимит или план года y (НЕ калибровка): "
          f"база {c['ratio_base'][0]:.2f}–{c['ratio_base'][1]:.2f}, "
          f"все сценарии E {c['ratio_all_scenarios'][0]:.2f}–{c['ratio_all_scenarios'][1]:.2f}")

    # Слой 2: классы водности и лимиты (модуль 5)
    years, scenarios = build_scenarios(tables["river_flow"], tables["water_withdrawal"])
    years.to_csv(OUTPUTS_DIR / "water_years.csv", index=False, encoding="utf-8")
    scenarios.to_csv(OUTPUTS_DIR / "layer2_scenarios.csv", index=False, encoding="utf-8")
    print("\nСлой 2 — классы водности (сток бассейна Сырдарьи, перцентили; грубо при коротком ряде):")
    print(years[["year", "runoff_m3", "water_class"]].to_string(index=False))
    print(scenarios[["water_class", "years", "limit_m3", "limit_year", "limit_status", "climate_key"]]
          .to_string(index=False))
    # Справка, не калибровка. Правило: историческое сравнение — площади и климат того же года, W(A_y, C_y, E_base).
    for r in scenarios.dropna(subset=["limit_m3"]).itertuples():
        y = str(int(r.limit_year))
        tot = regional_totals(model["coef_m3_ha"]["base|base|base"][y], model["areas_ha"][y])
        print(f"  {r.water_class}: W(A{y}, C{y}, E_base) = {tot['river_m3'] / 1e9:.2f} км³ "
              f"против лимита {y} г. {r.limit_m3 / 1e9:.2f} км³ (×{tot['river_m3'] / r.limit_m3:.2f})")

    # Слой 3: оптимизатор, цель — минимум воды «из реки» (модуль 6)
    crops = [c["id"] for c in model["crops"]]
    presets_df = tables["optimizer_presets"]
    coef = opt.river_coefficients(frames["layer1_scenarios"])          # база КПД, средний климат
    base = crop_areas_wide(tables["crop_areas"], crops).loc[BASE_AREA_YEAR].to_dict()
    high = scenarios.dropna(subset=["limit_m3"])
    abs_limit = float(high["limit_m3"].iloc[0]) if len(high) else None
    structures, feasibility = opt.run_presets(coef, base, opt.load_presets(presets_df),
                                              opt.food_crops(presets_df, crops), opt.load_targets(presets_df), abs_limit)
    structures.to_csv(OUTPUTS_DIR / "optimizer_structures.csv", index=False, encoding="utf-8")
    feasibility.to_csv(OUTPUTS_DIR / "optimizer_feasibility.csv", index=False, encoding="utf-8")
    print(f"\nСлой 3 — минимум воды «из реки»; планировочная база W(A{BASE_AREA_YEAR}, Cmean, E_base); "
          "общая площадь = площади базового года (модель, не факт):")
    best = feasibility.drop_duplicates("preset")[["preset", "base_m3", "min_achievable_m3", "saving_pct_max"]]
    for r in best.itertuples():
        print(f"  {r.preset:9s} база {r.base_m3 / 1e9:.2f} км³ -> минимум {r.min_achievable_m3 / 1e9:.2f} км³ "
              f"(−{r.saving_pct_max:.1f} %)")
    print(feasibility[["preset", "limit_kind", "limit_id", "feasible"]].to_string(index=False))

    # Экспериментальные сценарии сокращения общей площади — отдельно от основных предустановок
    exps = opt.run_area_experiments(coef, base, opt.load_presets(presets_df), opt.food_crops(presets_df, crops),
                                    opt.load_area_experiments(presets_df))
    exps.to_csv(OUTPUTS_DIR / "optimizer_area_experiments.csv", index=False, encoding="utf-8")
    print("\nЭКСПЕРИМЕНТАЛЬНЫЕ сценарии (не предустановки): общая площадь сокращена; экономия = структура + площадь")
    for r in exps.itertuples():
        if r.feasible:
            print(f"  {r.preset:9s} −{r.area_reduction:.0%} площади: −{r.saving_total_pct:.1f} % "
                  f"(структура {r.saving_structure_pct:.1f} + площадь {r.saving_area_pct:.1f})")
        else:
            print(f"  {r.preset:9s} −{r.area_reduction:.0%} площади: решения нет — {r.message}")

    # Модуль 8: бэктест V1–V4 (без калибровки; статус доказательности и n указаны в каждой строке)
    bt_results, bt_v1, bt_v2, bt_v3 = run_backtest(tables, frames)
    bt_results.to_csv(OUTPUTS_DIR / "backtest_results.csv", index=False, encoding="utf-8")
    bt_v1.to_csv(OUTPUTS_DIR / "backtest_v1_scenarios.csv", index=False, encoding="utf-8")
    bt_v2.to_csv(OUTPUTS_DIR / "backtest_v2_scenarios.csv", index=False, encoding="utf-8")
    bt_v3.to_csv(OUTPUTS_DIR / "backtest_v3_years.csv", index=False, encoding="utf-8")
    print("\nБэктест V1–V4 — НЕ валидация; модель не калибровалась (подробно: docs/backtest.md):")
    for r in bt_results.itertuples():
        scale, unit = (1e9, "км³") if r.unit in ("m3", "m3/year") else (1.0, "м³/га")
        obs = (f"{r.observed / scale:,.2f}" if pd.notna(r.observed) else
               f"{r.observed_low / scale:,.2f}–{r.observed_high / scale:,.2f}" if pd.notna(r.observed_low) else "нет наблюдения")
        print(f"  {r.check} n={r.n_observations}: наблюдение {obs} {unit}; модель {r.model_base / scale:,.2f} "
              f"({r.model_min / scale:,.2f}–{r.model_max / scale:,.2f}) {unit} — {r.quantity}")

    # Модуль 9: чувствительность W(A, C, E) — НЕ валидация (подробно: docs/sensitivity.md)
    sens, ranking, sens_sc = run_sensitivity(tables)
    sens.to_csv(OUTPUTS_DIR / "sensitivity_results.csv", index=False, encoding="utf-8")
    ranking.to_csv(OUTPUTS_DIR / "sensitivity_ranking.csv", index=False, encoding="utf-8")
    sens_sc.to_csv(OUTPUTS_DIR / "sensitivity_scenarios.csv", index=False, encoding="utf-8")
    print("\nЧувствительность — ранжирование по документированным диапазонам (размах W «из реки», база "
          f"W(A{BASE_AREA_YEAR}, Cmean, E_base) = {sens['river_base_m3'].iloc[0] / 1e9:.2f} км³):")
    for r in ranking.itertuples():
        print(f"  {r.rank}. {r.parameter:22s} {r.p_low} … {r.p_high}: {r.river_low_m3 / 1e9:.2f}–{r.river_high_m3 / 1e9:.2f} км³ "
              f"(размах {r.river_swing_km3:.2f} км³, {r.river_swing_pct_of_base:.1f} %)")

    # Decision Lab (2026-11-17): расширенный оптимизатор, режим дефицита, стресс-тесты, неопределённость,
    # проверка входов. Отдельные файлы outputs/ и web/data/planner.js; результаты выше не меняются.
    from src import decision_support
    decision_support.run(tables)
    return 0


if __name__ == "__main__":
    sys.exit(main())
