"""Загрузка и проверка данных из data/.

Формат каждого файла data/*.csv — «длинный»: одна строка = одно число.
Обязательные колонки: entity, param, year, value, unit, source, status.
Можно добавлять ключевые колонки (например, date или month для суточного климата).

Проверки (все ошибки собираются в один список):
- есть все обязательные колонки, value — число;
- source не пустой; status — real, assumed или simulated;
- param есть в реестре PARAMS, unit совпадает с единицей параметра и есть в src.units;
- value в правдоподобном диапазоне параметра;
- нет повторов одного и того же числа;
- для status=real: source — id вида S001, и в data/SOURCES.md у него есть
  url, location (страница/таблица), quote (точная цитата) и accessed (дата обращения).
"""

import re
from pathlib import Path

import pandas as pd

from src.units import KNOWN_UNITS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCES_FILE = "SOURCES.md"

REQUIRED_COLUMNS = ["entity", "param", "year", "value", "unit", "source", "status"]
STATUSES = {"real", "assumed", "simulated"}
SOURCE_ID_RE = re.compile(r"^S\d{3,}$")
REQUIRED_SOURCE_FIELDS = ["url", "location", "quote", "accessed"]

# Реестр параметров: имя -> (единица, минимум, максимум).
# Диапазоны — грубая защита от опечаток и перепутанных единиц, а не научные границы.
# Новый параметр сначала добавляется сюда, иначе загрузчик его не пропустит.
PARAMS = {
    # Климат (суточные значения)
    "tmin": ("degC", -45, 50),
    "tmax": ("degC", -40, 55),
    "rh_mean": ("%", 0, 100),
    "rh_min": ("%", 0, 100),
    "rh_max": ("%", 0, 100),
    "u2": ("m/s", 0, 40),
    "rs": ("MJ/m2/day", 0, 40),
    "sunshine": ("h", 0, 24),
    "precip": ("mm", 0, 300),
    # Культуры (FAO-56)
    "kc_ini": ("-", 0.1, 1.5),
    "kc_mid": ("-", 0.1, 1.5),
    "kc_end": ("-", 0.1, 1.5),
    "l_ini": ("day", 1, 200),
    "l_dev": ("day", 1, 200),
    "l_mid": ("day", 1, 200),
    "l_late": ("day", 1, 200),
    "plant_doy": ("doy", 1, 366),
    "max_height": ("m", 0, 10),
    # Площади, урожай, экономика
    "area": ("ha", 0, 2_000_000),
    "harvested_area": ("ha", 0, 2_000_000),
    "production": ("t", 0, 50_000_000),
    "yield": ("t/ha", 0, 150),
    "price": ("KZT/t", 0, 10_000_000),
    "cost": ("KZT/ha", 0, 10_000_000),
    # Вода
    "eff_field": ("fraction", 0.1, 1.0),
    "eff_canal": ("fraction", 0.1, 1.0),
    "water_withdrawal": ("m3", 0, 50_000_000_000),
    "irrigated_area": ("ha", 0, 2_000_000),
    "river_flow": ("m3", 0, 100_000_000_000),
}


class DataValidationError(Exception):
    """Данные не прошли проверку. В .errors — список всех найденных ошибок."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("Ошибки в данных:\n" + "\n".join(f"- {e}" for e in self.errors))


def parse_sources(path) -> dict:
    """Читает SOURCES.md и возвращает {id: {поле: значение}}.

    Формат записи:
        ## S001
        - url: https://...
        - document: название документа
        - location: стр. 12, табл. 3, строка «Рис»
        - quote: точная цитата из источника, с единицами
        - accessed: 2026-11-12
    """
    path = Path(path)
    if not path.exists():
        return {}
    sources = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(S\d{3,})\s*$", line.strip())
        if heading:
            current = heading.group(1)
            sources[current] = {}
            continue
        field = re.match(r"^\s*-\s*([a-z_]+)\s*:\s*(.*)$", line)
        if current and field:
            sources[current][field.group(1)] = field.group(2).strip()
    return sources


def validate(df: pd.DataFrame, sources: dict, table: str = "table") -> list:
    """Возвращает список ошибок (пустой, если всё в порядке)."""
    errors = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return [f"{table}: нет обязательных колонок {missing}"]

    for i, row in df.iterrows():
        where = f"{table}, строка {i + 2} ({row['entity']}/{row['param']}/{row['year']})"

        value = pd.to_numeric(row["value"], errors="coerce")
        if pd.isna(value):
            errors.append(f"{where}: value не число: {row['value']!r}")

        source = "" if pd.isna(row["source"]) else str(row["source"]).strip()
        if not source:
            errors.append(f"{where}: пустой source")

        status = "" if pd.isna(row["status"]) else str(row["status"]).strip()
        if status not in STATUSES:
            errors.append(f"{where}: status {status!r} не из {sorted(STATUSES)}")

        unit = "" if pd.isna(row["unit"]) else str(row["unit"]).strip()
        if unit not in KNOWN_UNITS:
            errors.append(f"{where}: неизвестная единица {unit!r}")

        param = row["param"]
        if param not in PARAMS:
            errors.append(f"{where}: параметра {param!r} нет в реестре PARAMS")
        else:
            expected_unit, low, high = PARAMS[param]
            if unit != expected_unit:
                errors.append(f"{where}: единица {unit!r}, ожидалась {expected_unit!r}")
            if not pd.isna(value) and not (low <= value <= high):
                errors.append(f"{where}: значение {value} вне диапазона [{low}, {high}]")

        if status == "real" and source:
            errors.extend(_check_real_source(where, source, sources))

    key_cols = [c for c in df.columns if c not in ("value", "unit", "source", "status")]
    dup = df.duplicated(subset=key_cols, keep=False)
    for i in df.index[dup]:
        errors.append(f"{table}, строка {i + 2}: повтор ключа {df.loc[i, key_cols].to_dict()}")

    return errors


def _check_real_source(where: str, source: str, sources: dict) -> list:
    if not SOURCE_ID_RE.match(source):
        return [f"{where}: status=real, но source {source!r} не id вида S001"]
    if source not in sources:
        return [f"{where}: status=real, но записи {source} нет в {SOURCES_FILE}"]
    entry = sources[source]
    empty = [f for f in REQUIRED_SOURCE_FIELDS if not entry.get(f)]
    if empty:
        return [f"{where}: в {SOURCES_FILE} у {source} не заполнены поля {empty}"]
    return []


def load_table(path, sources_path=None) -> pd.DataFrame:
    """Читает один CSV и проверяет его. При ошибках бросает DataValidationError."""
    path = Path(path)
    if sources_path is None:
        sources_path = path.parent / SOURCES_FILE
    df = pd.read_csv(path, encoding="utf-8", dtype={"source": str, "status": str, "unit": str})
    errors = validate(df, parse_sources(sources_path), table=path.name)
    if errors:
        raise DataValidationError(errors)
    df["value"] = pd.to_numeric(df["value"])
    return df


def load_all(data_dir=DATA_DIR) -> dict:
    """Читает и проверяет все data/*.csv. Возвращает {имя файла без .csv: DataFrame}.

    Ошибки всех файлов собираются вместе, чтобы сразу увидеть полный список.
    """
    data_dir = Path(data_dir)
    sources_path = data_dir / SOURCES_FILE
    tables, errors = {}, []
    for path in sorted(data_dir.glob("*.csv")):
        try:
            tables[path.stem] = load_table(path, sources_path)
        except DataValidationError as exc:
            errors.extend(exc.errors)
    if errors:
        raise DataValidationError(errors)
    return tables
