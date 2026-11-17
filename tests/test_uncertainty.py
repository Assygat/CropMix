"""Тесты анализа неопределённости (src/uncertainty.py)."""

import numpy as np
import pytest

from src import uncertainty as unc


@pytest.fixture(scope="module")
def tables():
    from src.data_loader import load_all
    return load_all()


@pytest.fixture(scope="module")
def sampler(tables):
    return unc.Sampler(tables)


def one(sampler, **over):
    v = sampler.base_values()
    v.update(over)
    return sampler.river_coefficients({k: np.array([x]) for k, x in v.items()})[0]


def test_base_values_reproduce_the_model_exactly(tables, sampler):
    from src.sensitivity import Engine
    ref = Engine(tables).season().groupby("crop")["river_m3_ha"].mean()
    assert np.abs(one(sampler) - ref[sampler.crops].to_numpy()).max() < 1e-6


def test_kc_endpoint_equals_a_full_rerun_and_canal_efficiency_is_a_divisor(tables, sampler):
    from src.sensitivity import Engine
    lows = {f"{e}_{p}": lo for e, p, lo, b, hi in sampler.kc_params}
    got = one(sampler, **lows)
    eng = Engine(tables)
    eng.daily("kc_low", crops=unc._with_kc(tables, "low"))
    ref = eng.season(daily_key="kc_low").groupby("crop")["river_m3_ha"].mean()
    assert np.abs(got - ref[sampler.crops].to_numpy()).max() < 1e-6
    # ручной пример: КПД каналов 0.575 → 0.5 умножает забор на 0.575 / 0.5 = 1.15
    assert one(sampler, eff_canal=0.5) == pytest.approx(one(sampler) * 1.15)


def test_monotone_responses(sampler):
    base = one(sampler)
    assert (one(sampler, et0_factor=1.1) > base).all()
    assert (one(sampler, eff_field=0.7) <= base + 1e-9).all()
    rice = sampler.crops.index("rice")
    high = one(sampler, rice_percolation=8.0)
    assert high[rice] > base[rice]
    assert np.delete(high, rice) == pytest.approx(np.delete(base, rice))


def test_latin_hypercube_is_stratified_and_within_ranges(sampler):
    n = 40
    v = sampler.lhs(n, seed=1)
    for name, lo, _, hi in sampler.params:
        x = v[name]
        assert (x >= lo).all() and (x <= hi).all()
        bins = np.floor((x - lo) / (hi - lo) * n).clip(0, n - 1)
        assert len(set(bins)) == n            # ровно по одному значению в каждой из n полос


def test_small_run_reports_sample_size_and_ranking(tables):
    _, summary, ranking = unc.run_uncertainty(tables, n=60, seed=5)
    s = summary.set_index("output")
    assert int(s.loc["river_m3", "n"]) == 60
    assert s.loc["river_m3", "p5"] <= s.loc["river_m3", "p50"] <= s.loc["river_m3", "p95"]
    assert s.loc["river_m3_at_base_values", "mean"] == pytest.approx(7.3049e9, rel=1e-4)
    assert set(ranking["distribution"]) == {"uniform"}
    assert ranking.iloc[0]["parameter"] in {"eff_canal", "eff_field", "et0_factor"}
