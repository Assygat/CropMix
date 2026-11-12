"""Тесты src/layer2_scenarios.py: классы водности, лимиты, флаги, пропуски, связь с модулем 4."""

import numpy as np
import pandas as pd
import pytest

from src import layer2_scenarios as l2
from src.data_loader import load_all


def _runoff(values, years=None):
    years = years or list(range(2001, 2001 + len(values)))
    return pd.DataFrame({"entity": l2.RUNOFF_ENTITY, "param": "river_flow", "year": years,
                         "measure": l2.RUNOFF_MEASURE, "value": values, "unit": "m3"})


def _limits(rows):
    return pd.DataFrame([{"entity": l2.LIMIT_ENTITY, "param": "water_withdrawal", "year": y,
                          "measure": l2.LIMIT_MEASURE, "value": v, "source": "Sxxx", "status": "real"}
                         for y, v in rows])


# --- Классификация ---

def test_hand_series_classification():
    # Ряд 10, 20, ..., 80 (8 лет): P25 = 27.5, P75 = 62.5 (numpy linear)
    years = l2.classify_years(l2.runoff_series(_runoff([10, 20, 30, 40, 50, 60, 70, 80])))
    assert years["p25_m3"].iloc[0] == pytest.approx(27.5)
    assert years["p75_m3"].iloc[0] == pytest.approx(62.5)
    assert list(years["water_class"]) == ["low", "low", "average", "average", "average", "average", "high", "high"]


def test_boundary_values_are_average():
    # Ряд из 5 лет: P25 и P75 совпадают со 2-м и 4-м значениями -> они «средние», а не крайние
    years = l2.classify_years(l2.runoff_series(_runoff([1, 2, 3, 4, 5])))
    assert list(years["water_class"]) == ["low", "average", "average", "average", "high"]


def test_missing_and_too_short_series():
    # Пропуск года не превращается в ноль и не классифицируется
    s = l2.runoff_series(_runoff([10, np.nan, 30, 40, 50]))
    assert list(s.index) == [2001, 2003, 2004, 2005]
    with pytest.raises(ValueError, match="не меньше"):
        l2.classify_years(l2.runoff_series(_runoff([10, 20])))
    with pytest.raises(ValueError, match="Повтор"):
        l2.runoff_series(_runoff([10, 20, 30], years=[2001, 2001, 2002]))
    with pytest.raises(ValueError, match="больше нуля"):
        l2.runoff_series(_runoff([10, 0, 30]))


# --- Лимиты ---

def test_limit_only_for_class_with_real_limit():
    river = _runoff([1, 2, 3, 4, 5])  # 2001 low, 2005 high
    _, sc = l2.build_scenarios(river, _limits([(2005, 3.7e9), (2026, 3.2e9)]))  # 2026 — стока нет
    sc = sc.set_index("water_class")
    assert sc.loc["high", "limit_m3"] == 3.7e9 and sc.loc["high", "limit_status"] == "real"
    assert pd.isna(sc.loc["low", "limit_m3"]) and sc.loc["low", "limit_status"] == "no_data"
    assert pd.isna(sc.loc["average", "limit_m3"]) and sc.loc["average", "limit_status"] == "no_data"
    assert set(sc["climate_key"]) == {"mean"}


def test_limit_order_low_le_average_le_high():
    river = _runoff([1, 2, 3, 4, 5])
    ok = l2.build_scenarios(river, _limits([(2001, 3.0e9), (2003, 3.3e9), (2005, 3.7e9)]))[1]
    assert l2.check_limit_order(ok)
    with pytest.raises(ValueError, match="больше лимита"):
        l2.build_scenarios(river, _limits([(2001, 4.0e9), (2005, 3.7e9)]))


def test_two_limits_in_one_class_needs_decision():
    with pytest.raises(ValueError, match="несколько лимитов"):
        l2.build_scenarios(_runoff([1, 2, 3, 4, 5]), _limits([(2002, 3.3e9), (2003, 3.4e9)]))


# --- Реальные данные и согласованность с модулями 1–4 ---

def test_real_data_classes_and_limit():
    t = load_all()
    years, sc = l2.build_scenarios(t["river_flow"], t["water_withdrawal"])
    cls = dict(zip(years["year"], years["water_class"]))
    assert cls == {2020: "average", 2021: "low", 2022: "average", 2023: "average", 2024: "high"}
    sc = sc.set_index("water_class")
    # лимит многоводного класса = лимит 2024 из data/water_withdrawal.csv (S059), без изменений
    w = t["water_withdrawal"]
    lim2024 = float(w[(w.year == 2024) & (w.measure == "limit_vegetation")].value.iloc[0])
    assert sc.loc["high", "limit_m3"] == lim2024 == 3.7e9
    assert sc.loc["high", "limit_source"] == "S059"
    assert list(sc.loc[["low", "average"], "limit_status"]) == ["no_data", "no_data"]
    # сток в таблице лет = данные river_flow (м³), без пересчёта
    r = t["river_flow"]
    r = r[r.measure == l2.RUNOFF_MEASURE].set_index("year").value
    for row in years.itertuples():
        assert row.runoff_m3 == r[float(row.year)]


def test_climate_key_exists_in_module4_export():
    from src.export_web import MEAN_KEY
    assert l2.CLIMATE_KEY == MEAN_KEY
