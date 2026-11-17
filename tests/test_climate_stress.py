"""Тесты климатических стресс-тестов (src/climate_stress.py): те же функции модулей 2–3, изменённый вход."""

import pandas as pd
import pytest

from src import climate_stress as cs


@pytest.fixture(scope="module")
def tables():
    from src.data_loader import load_all
    return load_all()


def test_perturbation_changes_only_the_target_series_and_not_the_original():
    clim = pd.DataFrame({"entity": [cs.NASA, cs.NASA, cs.NASA, cs.NASA, "station"],
                         "param": ["tmax", "tmin", "precip", "rh_mean", "tmax"],
                         "date": ["2020-07-01"] * 5, "value": [30.0, 15.0, 10.0, 40.0, 31.0]})
    out = cs.perturb_climate(clim, delta_t=2.0, precip_factor=0.5)
    assert out["value"].tolist() == [32.0, 17.0, 5.0, 40.0, 31.0]   # RH и станция не меняются
    assert clim["value"].tolist() == [30.0, 15.0, 10.0, 40.0, 31.0]  # исходная таблица не изменена
    with pytest.raises(ValueError):
        cs.perturb_climate(clim, precip_factor=-1)


def test_unperturbed_run_equals_the_model_coefficients(tables):
    from src.sensitivity import Engine
    season, _ = cs.coefficients(tables, 0.0, 1.0)
    ref = Engine(tables).season().groupby("crop")["river_m3_ha"].mean()
    got = cs.per_ha(season)["river_m3_ha"]
    assert (got - ref[got.index]).abs().max() < 1e-6


def test_heat_raises_et0_and_demand_and_less_rain_raises_demand(tables):
    s0, e0 = cs.coefficients(tables, 0.0, 1.0)
    s2, e2 = cs.coefficients(tables, 2.0, 1.0)
    sp, _ = cs.coefficients(tables, 0.0, 0.5)
    assert e2 > e0
    r0, r2, rp = (cs.per_ha(s)["river_m3_ha"] for s in (s0, s2, sp))
    assert (r2 > r0).all()
    assert (rp >= r0 - 1e-9).all() and (rp > r0).any()


def test_scenario_table_requires_all_parameters():
    df = pd.DataFrame({"entity": ["x", "x"], "param": ["climate_delta_t", "precip_factor"], "value": [1, 1]})
    with pytest.raises(ValueError, match="water_supply_share"):
        cs.load_scenarios(df)


def test_drought_analogue_is_the_year_with_highest_demand():
    season = pd.DataFrame({"crop": ["a", "b", "a", "b"], "year": [2001, 2001, 2002, 2002],
                           "river_m3_ha": [10.0, 1.0, 5.0, 3.0]})
    year, w = cs.drought_analogue_year(season, {"a": 2.0, "b": 10.0})
    assert w == {2001: 30.0, 2002: 40.0} and year == 2002


def test_stress_run_reports_deficit_against_normal_demand(tables):
    df, _, meta = cs.run_stress(tables)
    n = df.set_index("scenario")
    assert n.loc["normal", "river_vs_normal_pct"] == pytest.approx(0.0, abs=1e-9)
    assert n.loc["reduced_water", "deficit_pct_of_demand"] == pytest.approx(30.0)
    assert n.loc["combined", "deficit_m3"] > n.loc["reduced_water", "deficit_m3"]
    assert meta["drought_year"] in range(2010, 2026)
