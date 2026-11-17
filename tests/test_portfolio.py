"""Тесты расширенного оптимизатора (src/portfolio.py) — ручные примеры с известным решением."""

import pytest

from src import portfolio as pf

# Две культуры: A (10 м³/га), B (4 м³/га)
CROPS = ("A", "B")
W = {"A": 10.0, "B": 4.0}
BASE = {"A": 50.0, "B": 50.0}


def problem(**kw):
    d = dict(crops=CROPS, water_m3_ha=W, base_ha=BASE, lower_ha={"A": 0.0, "B": 0.0},
             upper_ha={"A": 100.0, "B": 100.0})
    d.update(kw)
    return pf.Portfolio(**d)


def test_min_water_same_land_moves_everything_to_the_cheaper_crop():
    s = pf.solve(problem(land_equal_ha=100.0), "min_water")
    assert s.status == "optimal"
    assert s.areas["A"] == pytest.approx(0.0, abs=1e-9) and s.areas["B"] == pytest.approx(100.0)
    assert s.water_m3 == pytest.approx(400.0)        # 100 га × 4 м³/га


def test_food_minimum_is_binding_and_its_shadow_price_is_the_water_difference():
    # A — продовольственная, минимум 30 га: x = (30, 70), вода = 300 + 280 = 580 м³
    p = problem(land_equal_ha=100.0, food=frozenset({"A"}), food_min_ha=30.0)
    s = pf.solve(p, "min_water")
    assert s.water_m3 == pytest.approx(580.0)
    food = next(c for c in s.constraints if c["kind"] == "food")
    assert food["binding"]
    # ослабить минимум на 1 га = перевести 1 га из A в B = экономия 10 − 4 = 6 м³
    assert food["shadow"] == pytest.approx(6.0)
    assert pf.resolve_marginal(p, "min_water", "food_min_ha", -1.0) == pytest.approx(6.0)


def test_max_area_under_water_budget_fills_cheap_crop_first():
    # B до верхней границы 50 га (200 м³), затем A на остаток 400 м³ → 40 га; площадь 90 га
    p = problem(upper_ha={"A": 100.0, "B": 50.0}, land_max_ha=200.0, water_budget_m3=600.0)
    s = pf.solve(p, "max_area")
    assert s.area_ha == pytest.approx(90.0)
    assert s.areas == pytest.approx({"A": 40.0, "B": 50.0})
    assert s.water_m3 <= 600.0 * (1 + 1e-12)
    water = next(c for c in s.constraints if c["kind"] == "water")
    assert water["binding"] and water["shadow"] == pytest.approx(0.1)   # 1 м³ даёт 1/10 га культуры A
    assert any(b["crop"] == "B" and b["side"] == "upper" for b in s.bounds)
    assert pf.resolve_marginal(p, "max_area", "water_budget_m3", 1.0) == pytest.approx(0.1)


def test_infeasible_budget_is_reported_with_the_missing_volume_not_relaxed():
    # минимум B = 50 га × 4 = 200 м³ > бюджета 100 м³
    p = problem(lower_ha={"A": 0.0, "B": 50.0}, land_max_ha=200.0, water_budget_m3=100.0)
    s = pf.solve(p, "max_area")
    assert s.status == "infeasible" and not s.areas
    text = " ".join(s.diagnosis)
    assert "raise the budget by" in text
    assert "lower the minimum retained share" in text


def test_value_objective_is_unavailable_without_complete_coefficients():
    s = pf.solve(problem(land_max_ha=100.0, value_kzt_ha={"A": 5.0}), "max_value")
    assert s.status == "unavailable" and "B" in s.message
    # стоимость на м³: A 0.5, B 0.25 → вода в A: 50 га, стоимость 250
    s2 = pf.solve(problem(land_max_ha=100.0, water_budget_m3=500.0, value_kzt_ha={"A": 5.0, "B": 1.0}), "max_value")
    assert s2.status == "optimal" and s2.value_kzt == pytest.approx(250.0)


def test_pareto_objective_is_monotone_in_the_water_budget():
    p = problem(upper_ha={"A": 100.0, "B": 50.0}, land_max_ha=200.0)
    par = pf.pareto(p, "max_area", [100, 200, 400, 800, 1200, 2000])
    vals = par["objective"].tolist()
    assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))
    assert vals[0] == pytest.approx(25.0)             # 100 м³ / 4 м³/га
    assert vals[-1] == pytest.approx(150.0)           # все верхние границы
    assert (par["water_m3"] <= par["budget_m3"] * (1 + 1e-12)).all()


def test_no_negative_areas_and_bounds_respected_in_random_problems():
    import numpy as np
    rng = np.random.default_rng(3)
    for _ in range(40):
        crops = tuple(f"c{i}" for i in range(5))
        base = {c: float(rng.uniform(10, 100)) for c in crops}
        w = {c: float(rng.uniform(1, 50)) for c in crops}
        lo = {c: base[c] * float(rng.uniform(0, 0.8)) for c in crops}
        hi = {c: base[c] * float(rng.uniform(1, 2)) for c in crops}
        bud = float(rng.uniform(0.3, 1.2)) * sum(base[c] * w[c] for c in crops)
        p = pf.Portfolio(crops, w, base, lo, hi, water_budget_m3=bud, land_max_ha=sum(base.values()))
        s = pf.solve(p, "max_area")
        if s.status == "optimal":
            for c in crops:
                assert lo[c] - 1e-9 <= s.areas[c] <= hi[c] + 1e-9 and s.areas[c] >= 0
            assert s.water_m3 <= bud * (1 + 1e-9)
            assert s.area_ha <= sum(base.values()) * (1 + 1e-12)
        else:   # невыполнимо только если одни минимумы уже не помещаются в бюджет
            assert sum(lo[c] * w[c] for c in crops) > bud * (1 - 1e-9)


@pytest.fixture(scope="module")
def regional():
    from src import layer3_optimizer as opt
    from src.data_loader import load_all
    from src.sensitivity import Engine
    t = load_all()
    e = Engine(t)
    coef = e.season().groupby("crop")["river_m3_ha"].mean().to_dict()
    base = e.areas.loc[2025].to_dict()
    food = opt.food_crops(t["optimizer_presets"], list(base))
    return t, coef, base, food, opt.load_presets(t["optimizer_presets"])


def test_module6_presets_are_reproduced_exactly(regional):
    from src import layer3_optimizer as opt
    _, coef, base, food, presets = regional
    for pr in presets.values():
        s = pf.solve(pf.module6_problem(coef, base, pr, food), "min_water")
        assert s.water_m3 == pytest.approx(opt.optimize(coef, base, pr, food).water_m3, rel=1e-8)


def test_attribution_reference_and_decomposition_add_up(regional):
    _, coef, base, food, presets = regional
    att, dec = pf.savings_attribution(coef, base, presets["moderate"], food)
    w0 = sum(coef[c] * base[c] for c in base)
    ref = att.iloc[0]
    assert ref["saving_pct"] == pytest.approx(3.3825562, rel=1e-6)
    assert -dec["water_change_m3"].sum() / w0 * 100 == pytest.approx(ref["saving_pct"], rel=1e-9)
    assert dec["change_ha"].sum() == pytest.approx(0.0, abs=1e-6)     # земля сохранена
    removed = att.set_index("experiment").loc["food-crop minimum removed", "saving_pct"]
    assert removed == pytest.approx(ref["saving_pct"])                # минимум продовольственных не активен


def test_emergency_constraints_hold_and_beat_uniform_curtailment(regional):
    t, coef, base, food, _ = regional
    presets, shares = pf.load_planner_presets(t["planner_presets"])
    summ, crops = pf.run_emergency(coef, base, presets["protective"], food, shares)
    w0 = sum(coef[c] * base[c] for c in base)
    for r in summ.itertuples():
        if r.status == "optimal":
            assert r.water_m3 <= r.supply_share * w0 * (1 + 1e-9)
            assert r.opt_area_ha <= sum(base.values()) * (1 + 1e-12)
            assert r.opt_area_ha >= r.uniform_area_ha - 1e-6            # не хуже равномерного сокращения
            assert r.food_ha >= presets["protective"]["food_area_min_share"] * sum(base[c] for c in food) * (1 - 1e-9)
        else:
            assert "raise the budget" in r.diagnosis
    assert (crops["opt_ha"] >= 0).all()
    st = dict(zip(summ["scarcity"], summ["status"]))
    assert st["s70"] == "optimal" and st["s50"] == "infeasible"


def test_economic_coefficients_never_fill_missing_values(regional):
    t, _, base, _, _ = regional
    econ = pf.economic_coefficients(t["yields"], t["prices"], list(base)).set_index("crop")
    assert econ.loc["rice", "price_status"] == "real"
    assert econ.loc["wheat", "yield_status"] == "missing"
    assert econ.loc["grain_other", "price_status"] == "missing"
    assert econ.loc["vegetables_open", "yield_t_ha"] == pytest.approx(18.52)
