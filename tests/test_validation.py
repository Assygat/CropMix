"""Тесты движка валидации (src/validation.py)."""

import numpy as np
import pandas as pd
import pytest

from src import validation as v


def test_metrics_on_a_hand_example():
    m = v.metrics([1.0, 2.0, 3.0], [1.0, 1.0, 1.0], "q", "q")
    assert m["n"] == 3 and m["mae"] == pytest.approx(1.0)
    assert m["rmse"] == pytest.approx(np.sqrt(5 / 3))
    assert m["bias_pct"] == pytest.approx(100.0)        # (6 − 3) / 3
    assert "r2" not in m                                # n < 10 — R² не выдаётся


def test_different_quantities_are_refused_or_context_only():
    with pytest.raises(ValueError, match="Разные величины"):
        v.metrics([1, 2, 3], [1, 2, 3], "river withdrawal", "evapotranspiration")
    m = v.metrics([2, 4], [1, 2], "river withdrawal", "evapotranspiration", contextual=True)
    assert m["ratio_of_means"] == pytest.approx(2.0) and "mae" not in m and "rmse" not in m


def test_missing_values_are_skipped_not_zero_and_small_n_has_no_statistics():
    m = v.metrics(pd.Series([1.0, np.nan, 3.0]), pd.Series([1.0, 5.0, np.nan]), "q", "q")
    assert m["n"] == 1 and m["mean_diff"] == 0.0 and "mae" not in m


def test_interval_scale_has_no_percentage_metrics_and_r2_needs_ten_points():
    x = np.arange(12, dtype=float)
    m = v.metrics(x + 1.0, x, "t", "t", ratio_scale=False)
    assert m["bias_pct"] is None and m["mape_pct"] is None
    assert m["mae"] == pytest.approx(1.0) and m["pearson_r"] == pytest.approx(1.0)
    assert m["r2"] == pytest.approx(1 - 12 / ((x - x.mean()) ** 2).sum())


def test_block_bootstrap_interval_contains_a_constant_shift():
    rng = np.random.default_rng(0)
    obs = rng.normal(20, 5, 600)
    lo, hi = v.bootstrap_bias_ci(obs + 1.5 + rng.normal(0, 0.5, 600), obs)
    assert lo < 1.5 < hi and hi - lo < 0.3


def test_climate_inputs_against_station():
    from src.data_loader import load_all
    res, monthly = v.climate_input_validation(load_all())
    r = res.set_index("check")
    assert r.loc["T1", "n"] > 5000 and r.loc["T1", "independent"]
    assert r.loc["T1", "r2"] > 0.9 and pd.isna(r.loc["T1", "bias_pct"])
    assert r.loc["T4", "contextual"] and pd.isna(r.loc["T4", "mae"])
    assert set(monthly["month"]) == set(range(1, 13))
    assert len(v.dataset_inventory()) >= 6
    # флаги GSOD: явные дни — подмножество, их доля согласована с долей флагов
    assert r.loc["T2e", "n"] < r.loc["T2", "n"] and r.loc["T1e", "n"] < r.loc["T1", "n"]
    assert r.loc["T2e", "n"] == pytest.approx(r.loc["T2", "n"] * (1 - r.loc["T2", "station_derived_share"]), abs=2)


def test_gsod_flags_are_read_from_raw_attributes(tmp_path):
    raw = ('"STATION","DATE","MAX","MAX_ATTRIBUTES","MIN","MIN_ATTRIBUTES"\n'
           '"38062099999","2020-01-01","  36.1","*","  19.4"," "\n'
           '"38062099999","2020-01-02","  40.0"," ","  20.0","*"\n')
    (tmp_path / "gsod_38062099999_2020.csv").write_text(raw, encoding="utf-8")
    f = v.gsod_derived_flags(tmp_path)
    assert f["max_derived"].tolist() == [True, False] and f["min_derived"].tolist() == [False, True]
    assert v.gsod_derived_flags(tmp_path / "none") is None
