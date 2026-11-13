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
    print("Модель «из реки» / официальный лимит или план того же года (НЕ калибровка): "
          f"база {c['ratio_base'][0]:.2f}–{c['ratio_base'][1]:.2f}, "
          f"все сценарии {c['ratio_all_scenarios'][0]:.2f}–{c['ratio_all_scenarios'][1]:.2f}")

    # Слой 2: классы водности и лимиты (модуль 5)
    years, scenarios = build_scenarios(tables["river_flow"], tables["water_withdrawal"])
    years.to_csv(OUTPUTS_DIR / "water_years.csv", index=False, encoding="utf-8")
    scenarios.to_csv(OUTPUTS_DIR / "layer2_scenarios.csv", index=False, encoding="utf-8")
    print("\nСлой 2 — классы водности (сток бассейна Сырдарьи, перцентили; грубо при коротком ряде):")
    print(years[["year", "runoff_m3", "water_class"]].to_string(index=False))
    print(scenarios[["water_class", "years", "limit_m3", "limit_year", "limit_status", "climate_key"]]
          .to_string(index=False))
    # Справка, не калибровка: модельная потребность «из реки» при среднем климате, базовых КПД
    # и площадях года лимита против самого лимита.
    for r in scenarios.dropna(subset=["limit_m3"]).itertuples():
        y = str(int(r.limit_year))
        tot = regional_totals(model["coef_m3_ha"]["base|base|base"][r.climate_key], model["areas_ha"][y])
        print(f"  {r.water_class}: потребность (климат {r.climate_key}, площади {y}) "
              f"{tot['river_m3'] / 1e9:.2f} км³ против лимита {r.limit_m3 / 1e9:.2f} км³ "
              f"(×{tot['river_m3'] / r.limit_m3:.2f})")

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
    print(f"\nСлой 3 — минимум воды «из реки» (площади {BASE_AREA_YEAR}, базовые КПД, средний климат; модель, не факт):")
    best = feasibility.drop_duplicates("preset")[["preset", "base_m3", "min_achievable_m3", "saving_pct_max"]]
    for r in best.itertuples():
        print(f"  {r.preset:9s} база {r.base_m3 / 1e9:.2f} км³ -> минимум {r.min_achievable_m3 / 1e9:.2f} км³ "
              f"(−{r.saving_pct_max:.1f} %)")
    print(feasibility[["preset", "limit_kind", "limit_id", "feasible"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
