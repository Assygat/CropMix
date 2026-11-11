import pandas as pd
import pytest

from src.data_loader import (
    DataValidationError,
    load_all,
    load_table,
    parse_sources,
    validate,
)

SOURCES_MD = """# Источники

Шаблон, который не должен считаться записью:
## SNNN
- url: https://example.org

## Записи

## S001
- url: https://www.fao.org/3/x0490e/x0490e00.htm
- document: FAO-56, Allen et al. 1998
- location: Table 12, строка Rice
- quote: Rice 1.05 1.20 0.90-0.60
- accessed: 2026-11-12

## S002
- url: https://stat.gov.kz/
- document: Посевные площади
- location: табл. 1
- quote:
- accessed: 2026-11-12
"""


def row(**overrides):
    base = {
        "entity": "rice",
        "param": "kc_mid",
        "year": "",
        "value": 1.2,
        "unit": "-",
        "source": "FAO-56 табл. 12, без проверки цитаты",
        "status": "assumed",
    }
    base.update(overrides)
    return base


@pytest.fixture
def sources(tmp_path):
    path = tmp_path / "SOURCES.md"
    path.write_text(SOURCES_MD, encoding="utf-8")
    return parse_sources(path)


def errors_for(rows, sources):
    return validate(pd.DataFrame(rows), sources, table="t.csv")


def assert_one_error(errors, fragment):
    assert len(errors) == 1, errors
    assert fragment in errors[0], errors


# --- правильные данные проходят ---


def test_valid_rows_pass(sources):
    rows = [
        row(),
        row(param="kc_ini", value=1.05, source="S001", status="real"),
        row(entity="kyzylorda", param="area", year=2023, value=150_000, unit="ha"),
    ]
    assert errors_for(rows, sources) == []


def test_extra_key_column_allows_same_param_on_different_dates(sources):
    rows = [
        row(entity="kyzylorda", param="tmax", year=2023, value=31.0, unit="degC", date="2023-07-01"),
        row(entity="kyzylorda", param="tmax", year=2023, value=33.5, unit="degC", date="2023-07-02"),
    ]
    assert errors_for(rows, sources) == []


def test_parse_sources_reads_entries_and_skips_template(sources):
    assert set(sources) == {"S001", "S002"}
    assert sources["S001"]["location"] == "Table 12, строка Rice"
    assert sources["S002"]["quote"] == ""


# --- source и status ---


def test_missing_source_column(sources):
    df = pd.DataFrame([row()]).drop(columns=["source"])
    assert_one_error(validate(df, sources), "нет обязательных колонок")


def test_empty_source(sources):
    assert_one_error(errors_for([row(source="")], sources), "пустой source")


def test_bad_status(sources):
    assert_one_error(errors_for([row(status="measured")], sources), "status 'measured'")


# --- единицы ---


def test_unknown_unit(sources):
    errors = errors_for([row(param="water_withdrawal", value=4.5, unit="km3")], sources)
    assert any("неизвестная единица 'km3'" in e for e in errors), errors


def test_unit_does_not_match_param(sources):
    # площадь записали в м³ — перепутаны единицы
    errors = errors_for([row(param="area", value=1000, unit="m3")], sources)
    assert_one_error(errors, "ожидалась 'ha'")


# --- диапазоны и типы ---


def test_kc_out_of_range(sources):
    assert_one_error(errors_for([row(value=1.8)], sources), "вне диапазона")


def test_negative_area(sources):
    errors = errors_for([row(param="area", value=-5, unit="ha")], sources)
    assert_one_error(errors, "вне диапазона")


def test_value_not_a_number(sources):
    assert_one_error(errors_for([row(value="около 1.2")], sources), "value не число")


def test_unknown_param(sources):
    assert_one_error(errors_for([row(param="kc_magic")], sources), "нет в реестре PARAMS")


def test_duplicate_rows(sources):
    errors = errors_for([row(), row(value=1.1)], sources)
    assert len(errors) == 2 and all("повтор ключа" in e for e in errors), errors


# --- status=real требует запись в SOURCES.md ---


def test_real_without_sources_entry(sources):
    errors = errors_for([row(source="S009", status="real")], sources)
    assert_one_error(errors, "записи S009 нет")


def test_real_with_empty_quote(sources):
    errors = errors_for([row(source="S002", status="real")], sources)
    assert_one_error(errors, "не заполнены поля ['quote']")


def test_real_with_free_text_source(sources):
    errors = errors_for([row(source="FAO-56", status="real")], sources)
    assert_one_error(errors, "не id вида S001")


# --- загрузка файлов ---


def write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")


def test_load_table_returns_numeric_values(tmp_path):
    (tmp_path / "SOURCES.md").write_text(SOURCES_MD, encoding="utf-8")
    write_csv(tmp_path / "crops.csv", [row(value="1.2")])
    df = load_table(tmp_path / "crops.csv")
    assert df["value"].dtype.kind == "f"
    assert df["value"].iloc[0] == pytest.approx(1.2)


def test_load_all_collects_errors_from_all_files(tmp_path):
    (tmp_path / "SOURCES.md").write_text(SOURCES_MD, encoding="utf-8")
    write_csv(tmp_path / "a.csv", [row(value=1.8)])
    write_csv(tmp_path / "b.csv", [row(status="guess")])
    with pytest.raises(DataValidationError) as exc:
        load_all(tmp_path)
    text = "\n".join(exc.value.errors)
    assert "a.csv" in text and "b.csv" in text


def test_load_all_on_empty_dir(tmp_path):
    assert load_all(tmp_path) == {}
