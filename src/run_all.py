"""Полный пересчёт с нуля: data/ -> outputs/ и web/data/.

Запуск: python -m src.run_all
"""

import sys

from src.data_loader import load_all
from src.data_report import summarize
from src.export_web import build_model, write_outputs


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
