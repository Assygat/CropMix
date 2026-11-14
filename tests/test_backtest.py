"""Тесты src/backtest.py: метрики на ручных рядах, частичный сезон = методика модулей 2–3, статус результатов."""

import numpy as np
import pandas as pd
import pytest

from src import backtest as bt


# --- Метрики (план: идеальная модель -> 0; пропущенный год пропускается) ---

def test_metrics_hand_series():
    obs = pd.Series({2020: 10.0, 2021: 20.0, 2022: 30.0})
    assert bt.mae(obs, obs) == 0 and bt.rmse(obs, obs) == 0 and bt.mape(obs, obs) == 0 and bt.bias_pct(obs, obs) == 0
    model = pd.Series({2020: 12.0, 2021: 18.0, 2022: 33.0})
    assert bt.mae(model, obs) == pytest.approx((2 + 2 + 3) / 3)
    assert bt.rmse(model, obs) == pytest.approx(np.sqrt((4 + 4 + 9) / 3))
    assert bt.mape(model, obs) == pytest.approx((20 + 10 + 10) / 3)
    assert bt.bias_pct(model, obs) == pytest.approx(100 * (63 - 60) / 60)


def test_missing_year_is_skipped_not_zero():
    obs = pd.Series({2020: 10.0, 2021: np.nan, 2022: 30.0})
    model = pd.Series({2020: 11.0, 2021: 999.0, 2022: 29.0})
    assert bt.mae(model, obs) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="Нет общих"):
        bt.mae(pd.Series({2019: 1.0}), obs)
    with pytest.raises(ValueError, match="MAPE"):
        bt.mape(pd.Series({1: 1.0}), pd.Series({1: 0.0}))


def test_measure_date():
    assert bt.measure_date("actual_to_2025-08-04") == pd.Timestamp("2025-08-04")
    with pytest.raises(ValueError):
        bt.measure_date("limit_vegetation")


# --- Реальные данные ---

@pytest.fixture(scope="module")
def ctx():
    from src.data_loader import load_all
    from src.export_web import build_model
    tables = load_all()
    model, frames = build_model(tables)
    return tables, model, frames, bt.run_backtest(tables, frames)


def test_kc_to_cutoff_equals_module2_with_full_climate(ctx):
    # При полном климате и отсечке после конца сезона — ровно kc.daily_kc (методика модуля 2 не меняется)
    from src import etc, kc
    tables = ctx[0]
    wide = etc.climate_wide(tables["climate_daily"])
    for crop in tables["crops_fao56"]["entity"].drop_duplicates():
        p = kc.crop_params(tables["crops_fao56"], crop)
        full, _ = kc.daily_kc(p, 2025, wide)
        part, _ = bt.kc_to_cutoff(p, 2025, wide, "2025-12-31")
        assert part.index.equals(full.index)
        assert np.allclose(part.to_numpy(), full.to_numpy(), rtol=0, atol=1e-12)
        # отсечка внутри сезона — та же кривая, обрезанная по дате
        cut = full.index[len(full) // 2]
        part2, _ = bt.kc_to_cutoff(p, 2025, wide, cut)
        assert part2.index.max() == cut and np.allclose(part2.to_numpy(), full[full.index <= cut].to_numpy())


def test_full_season_cutoff_reproduces_module3_total(ctx):
    # Накопленный забор до 31.12 = полная сезонная сумма W(A2025, C2025, E_base) из модуля 4 (regional_check)
    from src import etc, layer1_losses as l1
    from src.export_web import crop_areas_wide
    tables, model, frames, _ = ctx
    crops = list(tables["crops_fao56"]["entity"].drop_duplicates())
    _, daily = etc.crop_water_tables(tables["crops_fao56"], tables["climate_daily"], tables["climate_sites"], years=[2025])
    areas = crop_areas_wide(tables["crop_areas"], crops).loc[2025].to_dict()
    df = bt.withdrawal_by_scenario(daily, l1.precip_series(tables["climate_daily"], etc.NASA_ENTITY),
                                   tables["efficiency"], tables["rice_water"], areas, [bt.BASE_KEY])
    expected = sum(areas[k] * model["coef_m3_ha"]["base|base|base"]["2025"][k][2] for k in crops)
    assert df["river_m3"].iloc[0] == pytest.approx(expected, rel=1e-12)


def test_v1_partial_season_and_status(ctx):
    res, v1, _, _ = ctx[3]
    r = res[res.check == "V1"].iloc[0]
    assert r.observed == 3.03e9 and r.observed_source == "S060"
    assert r.n_observations == 1 and "partial-season benchmark" in r.evidence_status and "not an annual validation" in r.evidence_status
    assert len(v1) == 36 and set(v1.cutoff) == {"2025-08-04"}
    assert r.model_min <= r.model_base <= r.model_max
    assert r.ratio_base == pytest.approx(r.model_base / r.observed)
    # частичный сезон меньше полного сезона того же года
    assert r.model_base < 7.684e9


def test_v2_states_different_denominators(ctx):
    res, _, v2, _ = ctx[3]
    r = res[res.check == "V2"].iloc[0]
    assert r.observed == pytest.approx(3.3e9 / 122000)
    assert "SOWN" in r.quantity and "IRRIGATED" in r.quantity
    assert "cannot conclude" in r.limitations
    assert set(v2.bracket) == {"fodder_end_earliest", "fodder_end_latest"} and len(v2) == 72


def test_v3_and_v4_are_not_validation(ctx):
    res = ctx[3][0]
    v3 = res[res.check == "V3"]
    assert len(v3) == 3 and v3.observed.isna().all()
    assert all("not a quantitative validation" in s for s in v3.evidence_status)
    v4 = res[res.check == "V4"]
    assert len(v4) == 3
    river = v4[v4.quantity.str.contains("river withdrawal")].iloc[0]
    assert river.n_observations == 0 and river.evidence_status.startswith("not possible")
    # ни одна проверка не объявляет модель валидированной
    assert not any(s.startswith("valid") for s in res.evidence_status.astype(str))
