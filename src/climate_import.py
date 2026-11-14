"""Импорт суточного CSV NASA POWER (Daily API, community AG) в «длинный» формат data/climate_daily*.csv.

Только перенос значений: единицы не пересчитываются, пропуски (-999) не заполняются и не записываются.
Используется для data/climate_daily_2026.csv; на сыром файле 2010–2025 воспроизводит
существующие строки data/climate_daily.csv (тест).
"""

from io import StringIO

import pandas as pd

# столбец NASA POWER -> (param, unit) проекта
POWER_COLUMNS = {
    "T2M_MAX": ("tmax", "degC"),
    "T2M_MIN": ("tmin", "degC"),
    "RH2M": ("rh_mean", "%"),
    "WS2M": ("u2", "m/s"),
    "ALLSKY_SFC_SW_DWN": ("rs", "MJ/m2/day"),
    "PRECTOTCORR": ("precip", "mm"),
}
MISSING = -999


def read_power_csv(path):
    """(header_lines, DataFrame с колонками YEAR, DOY и параметрами) из сырого файла NASA POWER."""
    lines = open(path, encoding="utf-8").read().splitlines()
    if not lines or lines[0].strip() != "-BEGIN HEADER-":
        raise ValueError("Нет заголовка NASA POWER (-BEGIN HEADER-)")
    end = lines.index("-END HEADER-")
    header = [line.rstrip() for line in lines[1:end]]
    df = pd.read_csv(StringIO("\n".join(lines[end + 1:])))
    missing = [c for c in ["YEAR", "DOY", *POWER_COLUMNS] if c not in df.columns]
    if missing:
        raise ValueError(f"В файле нет столбцов {missing}")
    return header, df


def to_long(df, entity, source, status="real"):
    """«Длинная» таблица: entity, param, year, date, value, unit, source, status. Значения -999 пропускаются."""
    dates = pd.to_datetime(df["YEAR"].astype(str), format="%Y") + pd.to_timedelta(df["DOY"] - 1, unit="D")
    parts = []
    for col, (param, unit) in POWER_COLUMNS.items():
        ok = df[col] != MISSING
        parts.append(pd.DataFrame({
            "entity": entity, "param": param, "year": df.loc[ok, "YEAR"].astype(int),
            "date": dates[ok].dt.strftime("%Y-%m-%d"), "value": df.loc[ok, col].astype(float),
            "unit": unit, "source": source, "status": status,
        }))
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["date", "param"], kind="stable").reset_index(drop=True)


def missing_counts(df):
    """Число значений -999 по столбцам (для метаданных загрузки)."""
    return {c: int((df[c] == MISSING).sum()) for c in POWER_COLUMNS}
