"""Decision Lab на сайте: данные web/data/planner.json и числа на страницах совпадают с outputs/."""

import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
OUT, WEB = ROOT / "outputs", ROOT / "web"
NEEDED = ["emergency_summary.csv", "stress_scenarios.csv", "uncertainty_summary.csv", "validation_climate.csv",
          "decision_attribution.csv"]

pytestmark = pytest.mark.skipif(not all((OUT / f).exists() for f in NEEDED) or not (WEB / "data" / "planner.json").exists(),
                                reason="Нет outputs/ Decision Lab: выполните python -m src.run_all")


def planner():
    return json.loads((WEB / "data" / "planner.json").read_text(encoding="utf-8"))


def text(name):
    src = (WEB / name).read_text(encoding="utf-8")
    src = re.sub(r"<script.*?</script>|<style.*?</style>", " ", src, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", src).replace("&#8239;", " ").replace("&nbsp;", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", t)


def test_planner_data_equals_outputs():
    d = planner()
    em = pd.read_csv(OUT / "emergency_summary.csv")
    assert len(d["emergency_summary"]) == len(em)
    for a, b in zip(d["emergency_summary"], em.to_dict("records")):
        assert a["status"] == b["status"]
        if b["status"] == "optimal":
            assert a["opt_area_pct"] == pytest.approx(b["opt_area_pct"], rel=1e-6)
    st = pd.read_csv(OUT / "stress_scenarios.csv")
    assert [r["scenario"] for r in d["stress"]] == st["scenario"].tolist()
    assert d["base_water_m3"] == pytest.approx(7.3049e9, rel=1e-4)       # W(A2025, Cmean, E_base) модуля 6
    # коэффициенты нормального климата в сетке = коэффициенты сценария normal
    normal = {r["crop"]: r["river_m3_ha"] for r in d["stress_coefficients"] if r["scenario"] == "normal"}
    grid0 = {r["crop"]: r["river_m3_ha"] for r in d["climate_grid"]["rows"] if r["delta_t_c"] == 0 and r["precip_factor"] == 1}
    assert grid0 == pytest.approx(normal, rel=1e-9)


def test_planner_page_static_numbers_match_outputs():
    t = text("planner.html")
    assert "188 094 ha" in t and "7.30 km³" in t
    att = pd.read_csv(OUT / "decision_attribution.csv")
    assert f"{att.iloc[0]['saving_pct']:.1f} %" in t                # 3.4 % в разделе 04


def test_evidence_uncertainty_and_input_check_match_outputs():
    t = text("evidence.html")
    u = pd.read_csv(OUT / "uncertainty_summary.csv").set_index("output")
    w = u.loc["river_m3"]
    assert f"{w['p5'] / 1e9:.2f}–{w['p95'] / 1e9:.2f}" in t
    s = u.loc["saving_moderate_pct"]
    assert f"{s['p5']:.1f}–{s['p95']:.1f}" in t and f"minimum {s['min']:.1f} %" in t
    assert f"{int(w['n']):,}".replace(",", " ") + " model runs" in t
    v = pd.read_csv(OUT / "validation_climate.csv").set_index("check")
    assert f"{int(v.loc['T1', 'n']):,}".replace(",", " ") + " days" in t
    assert f"−{abs(v.loc['T1', 'mean_diff']):.2f} °C" in t and f"+{v.loc['T2', 'mean_diff']:.2f} °C" in t
    # проверка с учётом флагов GSOD: строки T1e/T2e на странице = outputs
    assert f"−{abs(v.loc['T1e', 'mean_diff']):.2f} °C" in t and f"−{abs(v.loc['T2e', 'mean_diff']):.2f} °C" in t
    assert f"{int(v.loc['T2e', 'n']):,}".replace(",", " ") + " days" in t
    assert f"{100 * v.loc['T2', 'station_derived_share']:.0f} % of days" in t
    assert f"ratio {v.loc['T4', 'ratio_of_means']:.2f}" in t
    r = pd.read_csv(OUT / "uncertainty_ranking.csv").set_index("parameter")
    assert f"−{abs(r.loc['eff_canal', 'spearman_water']):.2f}" in t
    assert f"field efficiency (rank correlation {r.loc['eff_field', 'spearman_saving']:.2f})" in t


def test_new_scripts_are_loaded_in_dependency_order():
    src = (WEB / "planner.html").read_text(encoding="utf-8")
    order = re.findall(r'<script src="([^"]+)"', src)
    assert order == ["data/planner.js", "lp_solver.js", "planner_core.js", "planner.js", "site.js"]
