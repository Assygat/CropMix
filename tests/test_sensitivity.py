"""Тесты src/sensitivity.py (модуль 9): база, КПД без двойного учёта, проценты, эластичность, ранжирование."""

import copy

import pandas as pd
import pytest

from src import sensitivity as sv
from src.data_loader import load_all


@pytest.fixture(scope="module")
def run():
    tables = load_all()
    before = copy.deepcopy(tables)
    res, rk, sc = sv.run_sensitivity(tables)
    return tables, before, res.set_index("parameter"), rk, sc


def test_baseline_reproduced(run):
    # W(A2025, Cmean, E_base) = 7.30 км³ — планировочная база (docs/limitations.md, обозначения)
    from src import etc, layer1_losses as l1
    from src.export_web import crop_areas_wide
    t, _, res, _, sc = run
    crops = list(t["crops_fao56"]["entity"].drop_duplicates())
    _, daily = etc.crop_water_tables(t["crops_fao56"], t["climate_daily"], t["climate_sites"])
    s, _ = l1.layer1_tables(daily, l1.precip_series(t["climate_daily"], etc.NASA_ENTITY), t["efficiency"], t["rice_water"])
    coef = s.groupby("crop")["river_m3_ha"].mean()
    a = crop_areas_wide(t["crop_areas"], crops).loc[2025]
    expected = sum(a[c] * coef[c] for c in crops)
    assert res["river_base_m3"].iloc[0] == pytest.approx(expected, rel=1e-12)
    assert expected / 1e9 == pytest.approx(7.30, abs=0.005)
    assert sc.set_index("scenario").loc["baseline", "river_m3"] == pytest.approx(expected, rel=1e-12)


def test_pessimistic_once_and_not_ranked(run):
    res, rk = run[2], run[3]
    assert list(res.index).count("eff_canal_pessimistic") == 1
    assert res.loc["eff_canal_pessimistic", "kind"] == "scenario_level"
    assert "eff_canal_pessimistic" not in set(rk["parameter"])
    assert list(res.index).count("eff_canal") == 1


def test_canal_efficiency_affects_river_only(run):
    r = run[2].loc["eff_canal"]
    # из реки = на поле / КПД каналов -> W ∝ 1/КПД; «у растения» и «на поле» не меняются
    assert r.river_low_m3 / r.river_base_m3 == pytest.approx(0.575 / 0.50, rel=1e-12)
    assert r.river_high_m3 / r.river_base_m3 == pytest.approx(0.575 / 0.65, rel=1e-12)
    for lv in ("plant", "field"):
        assert getattr(r, f"{lv}_low_m3") == pytest.approx(getattr(r, f"{lv}_base_m3"), rel=1e-12)
        assert getattr(r, f"{lv}_high_m3") == pytest.approx(getattr(r, f"{lv}_base_m3"), rel=1e-12)


def test_no_double_counting_of_efficiencies(run):
    res = run[2]
    # КПД полива и перколяция не меняют «у растения»
    for p in ("eff_field", "rice_percolation"):
        r = res.loc[p]
        assert r.plant_low_m3 == pytest.approx(r.plant_base_m3, rel=1e-12)
        assert r.plant_high_m3 == pytest.approx(r.plant_base_m3, rel=1e-12)
    # во всех строках с базовым КПД каналов «из реки» / «на поле» = 1 / 0.575 — потери каналов учтены один раз
    for p in ("eff_field", "rice_percolation", "kc_fao56_table_range", "nasa_wind_factor", "climate_year",
              "crop_structure_year", "etc_scale_10pct", "precip_scale_20pct", "pe_zero_bound"):
        r = res.loc[p]
        for side in ("low", "base", "high"):
            assert getattr(r, f"river_{side}_m3") / getattr(r, f"field_{side}_m3") == pytest.approx(1 / 0.575, rel=1e-12)


def test_wind_changes_climate_not_result_directly(run):
    # ветер ×0.84 пересчитывает ET0 и Kc: «у растения» тоже уменьшается, и не ровно на 16 %
    r = run[2].loc["nasa_wind_factor"]
    ratio = r.plant_low_m3 / r.plant_base_m3
    assert 0.84 < ratio < 1.0
    assert r.river_low_m3 < r.river_base_m3


def test_percent_and_elasticity_formulas(run):
    for _, r in run[2].iterrows():
        for side in ("low", "high"):
            w, w0 = getattr(r, f"river_{side}_m3"), r.river_base_m3
            assert getattr(r, f"river_delta_{side}_pct") == pytest.approx(100 * (w - w0) / w0)
            assert getattr(r, f"river_delta_{side}_km3") == pytest.approx((w - w0) / 1e9)
            el = getattr(r, f"elasticity_{side}")
            if pd.notna(el):
                pv = getattr(r, f"p_{side}")
                assert el == pytest.approx(((w - w0) / w0) / ((float(pv) - float(r.p_base)) / float(r.p_base)))
    res = run[2]
    assert res.loc["eff_canal", "elasticity_low"] < 0 and res.loc["eff_canal", "elasticity_high"] < 0
    # ETc линейна: эластичность одинакова для ±10 и ±20 %, положительна и не больше 1
    assert res.loc["etc_scale_10pct", "elasticity_high"] == pytest.approx(res.loc["etc_scale_20pct", "elasticity_high"], rel=1e-3)
    assert 0 < res.loc["etc_scale_10pct", "elasticity_high"] <= 1
    # категориальные параметры — без эластичности
    assert res[["elasticity_low", "elasticity_high"]].loc[["climate_year", "crop_structure_year", "kc_fao56_table_range"]].isna().all().all()


def test_structure_keeps_2025_total_area(run):
    from src.export_web import crop_areas_wide
    t, res = run[0], run[2]
    crops = list(t["crops_fao56"]["entity"].drop_duplicates())
    a = crop_areas_wide(t["crop_areas"], crops)
    y = int(str(res.loc["crop_structure_year", "p_high"]).lstrip("A"))
    scaled = a.loc[y] * (a.loc[2025].sum() / a.loc[y].sum())
    assert scaled.sum() == pytest.approx(a.loc[2025].sum())
    eng = sv.Engine(t)
    assert eng.w(eng.season(), areas=scaled)["river"] == pytest.approx(res.loc["crop_structure_year", "river_high_m3"], rel=1e-12)


def test_boundary_pe_zero_and_identity(run):
    r = run[2].loc["pe_zero_bound"]
    for lv in ("plant", "field", "river"):
        assert getattr(r, f"{lv}_low_m3") >= getattr(r, f"{lv}_base_m3")
    eng = sv.Engine(run[0])
    assert eng.w(eng.season(etc_scale=1.0, precip_scale=1.0))["river"] == pytest.approx(r.river_base_m3, rel=1e-12)


def test_ranking_only_documented_ranges_sorted(run):
    res, rk = run[2], run[3]
    assert list(rk["rank"]) == list(range(1, len(rk) + 1))
    assert rk["river_swing_km3"].is_monotonic_decreasing
    assert set(rk["parameter"]) == set(res.index[res["kind"] == "documented_range"])


def test_scenarios_flag_experimental(run):
    sc = run[4].set_index("scenario")
    exp = sc[sc["experimental"]]
    assert set(exp.index) == {"combined_low_demand_experimental", "combined_high_demand_experimental"}
    assert all("not a probability" in n for n in exp["note"])
    assert sc.loc["combined_low_demand_experimental", "river_m3"] <= sc.loc["efficiency_low_demand", "river_m3"]
    assert sc.loc["combined_high_demand_experimental", "river_m3"] >= sc.loc["efficiency_high_demand", "river_m3"]


def test_source_tables_unchanged(run):
    tables, before = run[0], run[1]
    assert set(tables) == set(before)
    for k in tables:
        pd.testing.assert_frame_equal(tables[k], before[k])


def test_kc_ranges_match_crops_and_stage(run):
    t = run[0]
    rng = t["sensitivity_ranges"]
    assert set(zip(rng.entity, rng.param)) == {("rice", "kc_end"), ("wheat", "kc_end"), ("vegetables_open", "kc_end"),
                                              ("grain_other", "kc_end"), ("oilseeds", "kc_mid")}
    crops = t["crops_fao56"]
    for (e, p), g in rng.groupby(["entity", "param"]):
        lo, hi = g[g.measure == "low"].value.iloc[0], g[g.measure == "high"].value.iloc[0]
        mid = crops[(crops.entity == e) & (crops.param == p)].value.iloc[0]
        assert lo < hi and lo <= mid <= hi   # базовое значение лежит внутри своего диапазона FAO-56


def test_run_all_integration():
    from src import run_all
    assert run_all.run_sensitivity is sv.run_sensitivity
