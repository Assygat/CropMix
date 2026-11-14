"""Отчёт по данным: сколько чисел real / assumed / simulated и список всех assumed.

Запуск: python -m src.data_report
"""

import sys

import pandas as pd

from src.data_loader import DATA_DIR, DataValidationError, load_all

STATUS_ORDER = ["real", "assumed", "simulated"]
STATUS_LEGEND = (
    "(real = число получено из внешнего источника с записью и цитатой в data/SOURCES.md: официальная статистика,\n"
    " публикации или внешние наборы данных. Это не обязательно прямое измерение: климат climate_daily и\n"
    " climate_daily_2026 — сеточный продукт NASA POWER (реанализ MERRA-2 и спутник CERES, ячейка 0.5°×0.625°),\n"
    " а не наблюдения местной метеостанции. assumed = допущение; simulated = результат моделирования.)"
)


def summarize(tables: dict) -> pd.DataFrame:
    """Таблица: файл -> количество чисел каждого статуса, всего и доля real (%)."""
    rows = []
    for name, df in sorted(tables.items()):
        counts = df["status"].value_counts()
        row = {"table": name, **{s: int(counts.get(s, 0)) for s in STATUS_ORDER}}
        row["total"] = len(df)
        rows.append(row)
    summary = pd.DataFrame(rows, columns=["table", *STATUS_ORDER, "total"])
    if not summary.empty:
        total = summary[STATUS_ORDER + ["total"]].sum()
        summary.loc[len(summary)] = {"table": "ИТОГО", **total.to_dict()}
    summary["real_pct"] = (100 * summary["real"] / summary["total"]).round(1) if len(summary) else []
    return summary


def assumed_rows(tables: dict) -> pd.DataFrame:
    """Все числа со status=assumed — их нужно явно показать автору."""
    cols = ["table", "entity", "param", "year", "value", "unit", "source"]
    parts = []
    for name, df in sorted(tables.items()):
        part = df[df["status"] == "assumed"].copy()
        part.insert(0, "table", name)
        parts.append(part[cols])
    if not parts:
        return pd.DataFrame(columns=cols)
    return pd.concat(parts, ignore_index=True)


def main(data_dir=DATA_DIR) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    try:
        tables = load_all(data_dir)
    except DataValidationError as exc:
        print(exc)
        return 1

    if not tables:
        print(f"В {data_dir} пока нет CSV-файлов с данными.")
        return 0

    print("Статусы чисел по файлам:")
    print(STATUS_LEGEND)
    print(summarize(tables).to_string(index=False))

    assumed = assumed_rows(tables)
    print(f"\nДопущения (assumed): {len(assumed)}")
    if not assumed.empty:
        print(assumed.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
