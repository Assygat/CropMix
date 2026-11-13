"""Тесты src/layer3_optimizer.py: ручные задачи, невыполнимость, единицы, реальные данные."""

import pytest

from src import layer3_optimizer as opt


def P(d, f=0.0, a=1.0):
    return {"area_change_max": d, "food_area_min_share": f, "total_area_min_share": a}


def test_two_crops_hand_solution():
    # A 10 000 м³/га, B 4 000 м³/га, по 100 га, коридор ±50 %, общая площадь сохраняется.
    # Ручное решение: A на нижней границе 50 га, B на верхней 150 га.
    # Вода: 50·10 000 + 150·4 000 = 1 100 000 м³ против базы 1 400 000 м³ (−21.43 %).
    r = opt.optimize({"A": 10000, "B": 4000}, {"A": 100, "B": 100}, P(0.5), food=set())
    assert r.status == "optimal"
    assert r.areas["A"] == pytest.approx(50) and r.areas["B"] == pytest.approx(150)
    assert r.water_m3 == pytest.approx(1.1e6)
    assert r.base_water_m3 == pytest.approx(1.4e6)
    assert r.saving_pct == pytest.approx(300000 / 1.4e6 * 100)
    assert "A at lower bound" in r.active and "B at upper bound" in r.active


def test_food_minimum_binding():
    # A — продовольственная и водоёмкая; минимум продовольственных 90 % -> A ≥ 90, B = 110.
    # Вода: 90·10 000 + 110·4 000 = 1 340 000 м³
    r = opt.optimize({"A": 10000, "B": 4000}, {"A": 100, "B": 100}, P(0.5, f=0.9), food={"A"})
    assert r.areas["A"] == pytest.approx(90) and r.areas["B"] == pytest.approx(110)
    assert r.water_m3 == pytest.approx(1.34e6)
    assert "food crops ≥ share of current" in r.active


def test_limit_feasible_and_infeasible():
    coef, base = {"A": 10000, "B": 4000}, {"A": 100, "B": 100}
    # минимум при ±50 % — 1.1 млн м³: лимит 1.2 млн выполним, структура та же
    ok = opt.optimize(coef, base, P(0.5), set(), limit_m3=1.2e6)
    assert ok.status == "optimal" and ok.water_m3 == pytest.approx(1.1e6)
    # лимит 1.0 млн недостижим: понятное сообщение и минимально достижимый объём
    bad = opt.optimize(coef, base, P(0.5), set(), limit_m3=1.0e6)
    assert bad.status == "infeasible"
    assert bad.min_achievable_m3 == pytest.approx(1.1e6)
    assert "недостижим" in bad.message and not bad.areas
    # лимит ровно на минимуме — выполним и отмечен как активный
    edge = opt.optimize(coef, base, P(0.5), set(), limit_m3=1.1e6)
    assert edge.status == "optimal" and "water limit" in edge.active


def test_contradictory_preset_is_reported():
    # Минимум продовольственных 160 % при коридоре ±50 % невыполним даже без лимита воды
    r = opt.optimize({"A": 10000, "B": 4000}, {"A": 100, "B": 100}, P(0.5, f=1.6), food={"A"})
    assert r.status == "infeasible" and "противоречат" in r.message


def test_units_and_total_area_preserved():
    coef = {"A": 13000.0, "B": 9000.0, "C": 25000.0}
    base = {"A": 1000.0, "B": 2000.0, "C": 500.0}
    r = opt.optimize(coef, base, P(0.3), set())
    # вода, м³ = Σ га × м³/га; общая площадь сохраняется (a = 1)
    assert r.water_m3 == pytest.approx(sum(r.areas[k] * coef[k] for k in coef))
    assert sum(r.areas.values()) == pytest.approx(sum(base.values()))
    for k in base:
        assert base[k] * 0.7 - 1e-6 <= r.areas[k] <= base[k] * 1.3 + 1e-6


def test_wider_corridor_never_saves_less():
    coef, base = {"A": 13000.0, "B": 9000.0, "C": 25000.0}, {"A": 1000.0, "B": 2000.0, "C": 500.0}
    savings = [opt.optimize(coef, base, P(d), set()).saving_pct for d in (0.0, 0.15, 0.3, 0.5)]
    assert savings[0] == pytest.approx(0.0, abs=1e-9)  # коридор 0 -> структура не меняется
    assert all(b >= a - 1e-9 for a, b in zip(savings, savings[1:]))


def test_missing_coefficient_raises():
    with pytest.raises(ValueError, match="Нет коэффициентов"):
        opt.optimize({"A": 1.0}, {"A": 1.0, "B": 1.0}, P(0.3), set())


# --- Реальные данные: предустановки из data/, коэффициенты слоя 1 ---

@pytest.fixture(scope="module")
def real():
    from src import etc, layer1_losses as l1
    from src.data_loader import load_all
    from src.export_web import crop_areas_wide
    t = load_all()
    crops = list(t["crops_fao56"]["entity"].drop_duplicates())
    _, daily = etc.crop_water_tables(t["crops_fao56"], t["climate_daily"], t["climate_sites"])
    season, _ = l1.layer1_tables(daily, l1.precip_series(t["climate_daily"], etc.NASA_ENTITY),
                                 t["efficiency"], t["rice_water"])
    coef = season.groupby("crop")["river_m3_ha"].mean().to_dict()
    base = crop_areas_wide(t["crop_areas"], crops).loc[2025].to_dict()
    p = t["optimizer_presets"]
    return coef, base, opt.load_presets(p), opt.food_crops(p, crops), opt.load_targets(p)


def test_real_presets_feasible_and_consistent(real):
    coef, base, presets, food, targets = real
    assert set(presets) == {"tight", "moderate", "flexible"}
    assert food == {"rice", "wheat", "potato", "vegetables_open", "melons"}
    assert targets == {"r10": 0.10, "r20": 0.20, "r30": 0.30}
    savings = {}
    for pid, pr in presets.items():
        r = opt.optimize(coef, base, pr, food)
        assert r.status == "optimal"
        assert sum(r.areas.values()) == pytest.approx(sum(base.values()), rel=1e-9)
        food_now = sum(r.areas[k] for k in food)
        assert food_now >= pr["food_area_min_share"] * sum(base[k] for k in food) * (1 - 1e-9)
        assert r.water_m3 <= r.base_water_m3 + 1e-6
        savings[pid] = r.saving_pct
    assert savings["tight"] <= savings["moderate"] <= savings["flexible"]
