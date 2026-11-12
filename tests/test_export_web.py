"""Тесты модуля 4: экспорт для веба и совпадение расчёта в браузере (JS) с Python.

Модель считается один раз на реальных данных (фикстура уровня модуля), в tmp-папки.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from src import export_web as ew
from src.data_loader import load_all

ROOT = Path(__file__).resolve().parent.parent
CALC_JS = ROOT / "web" / "model_calc.js"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tables = load_all()
    model, frames = ew.build_model(tables)
    out = tmp_path_factory.mktemp("outputs")
    web = tmp_path_factory.mktemp("web_data")
    json_path = ew.write_outputs(model, frames, out, web)
    return tables, model, frames, json_path, out


def test_json_has_all_crops_years_scenarios(built):
    tables, model, frames, json_path, _ = built
    data = json.loads(json_path.read_text(encoding="utf-8"))
    crops = list(tables["crops_fao56"]["entity"].drop_duplicates())
    assert [c["id"] for c in data["crops"]] == crops and len(crops) == 8
    # 3 КПД полива × 4 КПД каналов × 3 перколяции = 36 сценариев, 16 лет + среднее
    assert len(data["coef_m3_ha"]) == 36
    for by_year in data["coef_m3_ha"].values():
        assert set(by_year) == set(data["years"]) | {data["mean_key"]}
        for coef in by_year.values():
            assert set(coef) == set(crops)
    # model.js содержит тот же объект
    js = (json_path.parent / "model.js").read_text(encoding="utf-8")
    assert js.split("window.CROPMIX_MODEL = ", 1)[1].rstrip().rstrip(";") == json_path.read_text(encoding="utf-8")


def test_json_coefficients_equal_python_layer1(built):
    _, model, frames, _, _ = built
    df = frames["layer1_scenarios"]
    for key in ["base|base|base", "low|pessimistic|high", "high|high|low"]:
        f, c, p = key.split("|")
        sub = df[(df.eff_field_measure == f) & (df.eff_canal_measure == c) & (df.perc_measure == p)]
        for r in sub.itertuples():
            assert model["coef_m3_ha"][key][str(r.year)][r.crop] == pytest.approx(
                [r.plant_m3_ha, r.field_m3_ha, r.river_m3_ha])
        mean = sub.groupby("crop").river_m3_ha.mean()
        for crop, v in mean.items():
            assert model["coef_m3_ha"][key]["mean"][crop][2] == pytest.approx(v)


def test_scenarios_and_statuses_from_data(built):
    tables, model, _, _, _ = built
    eff = tables["efficiency"]
    canal = {m["id"]: m["value"] for m in model["scenarios"]["eff_canal"]}
    assert canal == {r.measure: r.value for r in eff[eff.param == "eff_canal"].itertuples()}
    assert all(m["status"] == "assumed" for m in model["scenarios"]["eff_canal"])
    assert model["area_status"]["rice"]["status"] == "real"
    assert model["area_status"]["grain_other"]["status"] == "derived"
    assert model["income"]["available"] is False


def _python_totals(frames, key, year, areas):
    f, c, p = key.split("|")
    df = frames["layer1_scenarios"]
    sub = df[(df.eff_field_measure == f) & (df.eff_canal_measure == c) & (df.perc_measure == p)]
    sub = sub[sub.year == int(year)].set_index("crop") if year != "mean" else \
        sub.groupby("crop")[["plant_m3_ha", "field_m3_ha", "river_m3_ha"]].mean()
    return {q: sum(areas[crop] * sub.loc[crop, f"{q}_m3_ha"] for crop in areas) for q in ("plant", "field", "river")}


HAND_SETS = [
    # (сценарий, климат года, площади, га)
    ("base|base|base", "2025", {"rice": 80000, "wheat": 10000, "potato": 2000, "fodder": 70000,
                                "vegetables_open": 6000, "melons": 8000, "oilseeds": 6000, "grain_other": 3000}),
    ("low|pessimistic|high", "mean", {"rice": 60000, "wheat": 20000, "potato": 0, "fodder": 50000,
                                      "vegetables_open": 10000, "melons": 12000, "oilseeds": 5000, "grain_other": 0}),
    ("high|high|low", "2012", {"rice": 1, "wheat": 0, "potato": 0, "fodder": 0,
                               "vegetables_open": 0, "melons": 0, "oilseeds": 0, "grain_other": 0}),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js для проверки JS-расчёта")
@pytest.mark.parametrize("key,year,areas", HAND_SETS)
def test_browser_calc_equals_python(built, key, year, areas):
    _, _, frames, json_path, _ = built
    script = (
        "const calc = require(process.argv[1]);"
        "const model = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));"
        "const res = calc.compute(model, process.argv[3], process.argv[4], JSON.parse(process.argv[5]));"
        "console.log(JSON.stringify(res.totals));"
    )
    out = subprocess.run(["node", "-e", script, str(CALC_JS), str(json_path), key, year, json.dumps(areas)],
                         capture_output=True, text=True, check=True, encoding="utf-8")
    js = json.loads(out.stdout)
    py = _python_totals(frames, key, year, areas)
    for q in ("plant", "field", "river"):
        assert js[q] == pytest.approx(py[q], rel=1e-12)
    assert js["area"] == pytest.approx(sum(areas.values()))


def test_regional_comparison_not_calibrated_and_year_matched(built):
    _, model, frames, _, out = built
    c = model["comparison"]
    # сравниваются только лимит/план на вегетацию с моделью того же года; частичный факт — нет
    assert {r["official_measure"] for r in c["rows"]} <= set(ew.COMPARABLE_OFFICIAL)
    check = pd.read_csv(out / "regional_check.csv")
    assert set(check["year"]) == {2024, 2025}
    assert c["ratio_all_scenarios"][0] <= c["ratio_base"][0] <= c["ratio_base"][1] <= c["ratio_all_scenarios"][1]
    # пересчёт отношения вручную для 2024 (базовые КПД)
    row = [r for r in c["rows"] if r["year"] == 2024][0]
    areas = model["areas_ha"]["2024"]
    river = sum(areas[k] * model["coef_m3_ha"]["base|base|base"]["2024"][k][2] for k in areas)
    assert row["ratio"] == pytest.approx(river / 3.7e9)


def test_grain_other_area_is_grain_minus_rice_minus_wheat(built):
    tables, model, _, _, _ = built
    a = tables["crop_areas"]
    v = lambda e: float(a[(a.entity == e) & (a.year == 2025)].value.iloc[0])
    assert model["areas_ha"]["2025"]["grain_other"] == pytest.approx(v("grain_total") - v("rice") - v("wheat"))
