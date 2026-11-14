"""Паритет web/sim_core.js с Python (модуль 10, этап 3).

Эталон считается в Python НЕ из model.json, а из outputs/layer1_scenarios.csv (слой 1, модули 1–3):
W_l(A, C, E) = Σ A_c · k_l(c, C, E); для C = mean — среднее по годам, как в src/export_web.py.
Сравниваются Baseline 2025 и три оптимизированных пресета для всех 36 сценариев E и 17 вариантов C,
на трёх уровнях. Допуск — 1e-12 км³ (= 1e-3 м³). Также запускаются JS-тесты (node --test).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
KM3_TOL = 1e-12
LEVELS = {"plant": "plant_m3_ha", "field": "field_m3_ha", "river": "river_m3_ha"}

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")

NODE_EVAL = r"""
const path = require("path"), fs = require("fs");
const root = process.argv[1];
const SimCore = require(path.join(root, "web", "sim_core.js"));
const read = (n) => JSON.parse(fs.readFileSync(path.join(root, "web", "data", n), "utf8"));
const sim = read("simulator.json");
const core = SimCore.createSimCore(read("model.json"), sim);
const sets = { baseline: sim.baseline.areas_ha };
for (const p of sim.optimized.presets_order) sets[p] = sim.optimized.presets[p].areas_ha;
const out = [];
for (const e of sim.scenarios.efficiency) for (const c of sim.scenarios.climate)
  for (const [name, areas] of Object.entries(sets)) {
    const r = core.evaluate(areas, c.key, e.key);
    out.push({ set: name, climate: c.key, efficiency: e.key, plant: r.km3.plant, field: r.km3.field, river: r.km3.river });
  }
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_results():
    out = subprocess.run(["node", "-e", NODE_EVAL, str(ROOT)], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return pd.DataFrame(json.loads(out.stdout))


@pytest.fixture(scope="module")
def python_results():
    sim = json.loads((ROOT / "web" / "data" / "simulator.json").read_text(encoding="utf-8"))
    l1 = pd.read_csv(ROOT / "outputs" / "layer1_scenarios.csv")
    l1["E"] = l1["eff_field_measure"] + "|" + l1["eff_canal_measure"] + "|" + l1["perc_measure"]
    by_year = l1.assign(C=l1["year"].astype(str))[["E", "C", "crop", *LEVELS.values()]]
    mean = l1.groupby(["E", "crop"], sort=False)[list(LEVELS.values())].mean().reset_index().assign(C="mean")
    coef = pd.concat([by_year, mean], ignore_index=True)
    sets = {"baseline": sim["baseline"]["areas_ha"],
            **{p: sim["optimized"]["presets"][p]["areas_ha"] for p in sim["optimized"]["presets_order"]}}
    rows = []
    for (e, c), g in coef.groupby(["E", "C"], sort=False):
        g = g.set_index("crop")
        for name, areas in sets.items():
            rows.append({"set": name, "climate": c, "efficiency": e,
                         **{lv: sum(areas[k] * g.loc[k, col] for k in areas) / 1e9 for lv, col in LEVELS.items()}})
    return pd.DataFrame(rows), sim


def test_js_unit_tests_pass():
    # все JS-тесты (sim_core — этап 3, sim_map — этап 4); файлы перечисляются явно: node --test <папка> в Node 24 не работает
    files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
    assert len(files) >= 2
    out = subprocess.run(["node", "--test", *files], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-2000:]
    assert "# fail 0" in out.stdout or "ℹ fail 0" in out.stdout


def test_parity_all_scenarios_all_levels(js_results, python_results):
    py, _ = python_results
    m = js_results.merge(py, on=["set", "climate", "efficiency"], suffixes=("_js", "_py"), validate="1:1")
    assert len(m) == 4 * 36 * 17 == len(js_results) == len(py)
    for lv in LEVELS:
        diff = (m[f"{lv}_js"] - m[f"{lv}_py"]).abs()
        assert diff.max() <= KM3_TOL, m.loc[diff.idxmax(), ["set", "climate", "efficiency"]].to_dict()


NODE_RANGE = r"""
const path = require("path"), fs = require("fs");
const root = process.argv[1];
const read = (n) => JSON.parse(fs.readFileSync(path.join(root, "web", "data", n), "utf8"));
const sim = read("simulator.json");
const core = require(path.join(root, "web", "sim_core.js")).createSimCore(read("model.json"), sim);
const C = require(path.join(root, "web", "sim_conditions.js"));
const X = require(path.join(root, "web", "sim_compare.js"));
const combos = C.allCombinations(C.createOptions(sim));
const out = {};
for (const p of sim.optimized.presets_order) {
  const r = X.savingRange(core, combos, sim.baseline.areas_ha, p);
  out[p] = { n: r.n, min: r.optimized.min, max: r.optimized.max, minAt: r.optimized.minAt, maxAt: r.optimized.maxAt };
}
process.stdout.write(JSON.stringify(out));
"""


def test_saving_range_matches_python(python_results):
    """Этап 6: диапазон экономии Optimized по 17 × 36 условиям = расчёт pandas из outputs/layer1_scenarios.csv.

    Экономия = (Baseline − Optimized) / Baseline × 100 % (забор из реки), при одних и тех же C и E.
    """
    py, _ = python_results
    out = subprocess.run(["node", "-e", NODE_RANGE, str(ROOT)], capture_output=True, text=True, encoding="utf-8", check=True)
    js = json.loads(out.stdout)
    wide = py.pivot_table(index=["climate", "efficiency"], columns="set", values="river")
    for p in ("tight", "moderate", "flexible"):
        saving = 100 * (wide["baseline"] - wide[p]) / wide["baseline"]
        assert js[p]["n"] == len(saving) == 612
        assert abs(js[p]["min"] - saving.min()) <= 1e-9
        assert abs(js[p]["max"] - saving.max()) <= 1e-9
        # КПД каналов делит забор всех культур одинаково и сокращается в экономии (%), поэтому экстремум
        # достигается сразу при нескольких уровнях КПД каналов (ничья в пределах ошибок округления).
        # Проверяем значение в названной точке, а не то, какой из равных вариантов выбран.
        for at, ref in ((js[p]["minAt"], saving.min()), (js[p]["maxAt"], saving.max())):
            assert abs(saving.loc[(at["climate"], at["efficiency"])] - ref) <= 1e-9
        df = saving.rename("s").reset_index()
        parts = df["efficiency"].str.split("|", expand=True)
        df["field"], df["perc"] = parts[0], parts[2]
        canal_spread = df.groupby(["climate", "field", "perc"])["s"].agg(lambda s: s.max() - s.min())
        assert len(canal_spread) == 17 * 3 * 3 and canal_spread.max() <= 1e-9


def test_parity_with_python_optimizer_outputs(js_results):
    # Python LP (модуль 6): базовый и оптимальный забор при Cmean / E_base из optimizer_feasibility.csv
    feas = pd.read_csv(ROOT / "outputs" / "optimizer_feasibility.csv").drop_duplicates("preset").set_index("preset")
    j = js_results[(js_results.climate == "mean") & (js_results.efficiency == "base|base|base")].set_index("set")
    for p in ("tight", "moderate", "flexible"):
        assert abs(j.loc[p, "river"] - feas.loc[p, "min_achievable_m3"] / 1e9) <= KM3_TOL
        assert abs(j.loc["baseline", "river"] - feas.loc[p, "base_m3"] / 1e9) <= KM3_TOL
