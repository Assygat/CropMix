"""Тесты src/climate_import.py: перенос NASA POWER без изменений, пропуски не заполняются."""

import pandas as pd
import pytest

from src.climate_import import POWER_COLUMNS, missing_counts, read_power_csv, to_long

RAW_2010_2025 = "data/raw/nasa_power_daily_44.8N_65.5E_2010-2025.csv"
RAW_2026 = "data/raw/nasa_power_daily_44.8N_65.5E_2026-01-01_2026-09-30.csv"


def test_reproduces_existing_climate_rows_exactly():
    # Импорт сырого файла S063 воспроизводит все строки NASA в data/climate_daily.csv
    _, df = read_power_csv(RAW_2010_2025)
    new = to_long(df, "nasa_power_44.8N_65.5E", "S063")
    old = pd.read_csv("data/climate_daily.csv")
    old = old[old.entity == "nasa_power_44.8N_65.5E"]
    m = old.merge(new, on=["param", "date"], suffixes=("_o", "_n"))
    assert len(m) == len(old) == len(new)
    assert (m.value_o - m.value_n).abs().max() == 0
    assert (m.unit_o == m.unit_n).all() and (m.year_o == m.year_n).all()


def test_2026_table_matches_raw_file():
    header, df = read_power_csv(RAW_2026)
    assert any("01/01/2026 through 09/30/2026" in h for h in header)
    assert len(df) == 273 and missing_counts(df) == {c: 0 for c in POWER_COLUMNS}
    table = pd.read_csv("data/climate_daily_2026.csv")
    assert len(table) == 273 * 6
    assert set(table.source) == {"S091"} and set(table.status) == {"real"}
    assert table.date.min() == "2026-01-01" and table.date.max() == "2026-09-30"
    # значения перенесены без пересчёта
    first = table[(table.date == "2026-01-01") & (table.param == "tmax")].value.iloc[0]
    assert first == df.loc[0, "T2M_MAX"]


def test_missing_values_are_dropped_not_filled(tmp_path):
    p = tmp_path / "power.csv"
    p.write_text("-BEGIN HEADER-\nsynthetic\n-END HEADER-\n"
                 "YEAR,DOY,T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR\n"
                 "2026,1,1.0,-2.0,80,3.0,-999,0.5\n2026,2,2.0,-1.0,70,2.0,5.0,0.0\n", encoding="utf-8")
    _, df = read_power_csv(p)
    out = to_long(df, "x", "Sxxx")
    rs = out[out.param == "rs"]
    assert list(rs.date) == ["2026-01-02"]           # день с -999 отсутствует, а не равен нулю
    assert len(out) == 11
    assert out[out.date == "2026-01-01"].shape[0] == 5


def test_missing_header_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("YEAR,DOY\n2026,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="заголовка"):
        read_power_csv(p)
