"""Полный пересчёт с нуля: data/ -> outputs/ и web/data/.

Запуск: python -m src.run_all
"""

import sys

from src.data_loader import load_all
from src.data_report import summarize
from src.export_web import OUTPUTS_DIR, build_model, regional_totals, write_outputs
from src.layer2_scenarios import build_scenarios


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
