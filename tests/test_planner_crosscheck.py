"""Сверка браузерного решателя (web/planner_core.js + web/lp_solver.js) с эталоном SciPy/HiGHS (src/portfolio.py).

Одни и те же задачи решаются в Python и в Node; совпадать должны статус, значение цели, вода после доводки
и двойственная оценка водного бюджета. Без Node тест пропускается (с причиной), а не считается пройденным.
"""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src import portfolio as pf

ROOT = Path(__file__).resolve().parent.parent
RUNNER = """
const P = require(process.argv[1]);
let data = ''; process.stdin.on('data', d => data += d); process.stdin.on('end', () => {
  const cases = JSON.parse(data);
  const out = cases.map(c => {
    const s = P.solve(c.problem, c.objective);
    const w = (s.constraints || []).find(r => r.kind === 'water');
    return {status: s.status, objective: s.objectiveValue, water: s.water, area: s.area,
            waterShadow: w ? w.shadow : null, waterBinding: w ? w.binding : null};
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def to_js(p):
    return {"crops": list(p.crops), "water": p.water_m3_ha, "base": p.base_ha, "lower": p.lower_ha,
            "upper": p.upper_ha, "budget": p.water_budget_m3, "landMax": p.land_max_ha, "landEqual": p.land_equal_ha,
            "food": sorted(p.food), "foodMin": p.food_min_ha,
            "value": p.value_kzt_ha or None, "valueMin": p.value_min_kzt}


def cases():
    from src import layer3_optimizer as opt
    from src.data_loader import load_all
    from src.sensitivity import Engine
    t = load_all()
    e = Engine(t)
    coef = e.season().groupby("crop")["river_m3_ha"].mean().to_dict()
    base = e.areas.loc[2025].to_dict()
    food = opt.food_crops(t["optimizer_presets"], list(base))
    out = []
    for pr in opt.load_presets(t["optimizer_presets"]).values():
        out.append((pf.module6_problem(coef, base, pr, food), "min_water"))
    em, shares = pf.load_planner_presets(t["planner_presets"])
    for pr in em.values():
        for share in [0.45, 0.5, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0]:
            p = pf.emergency_problem(coef, base, pr, food, share)
            for obj in ("max_area", "max_food_area", "min_water"):
                out.append((p, obj))
    rng = np.random.default_rng(11)
    for _ in range(60):
        crops = tuple(f"c{i}" for i in range(int(rng.integers(2, 9))))
        b = {c: float(rng.uniform(100, 80000)) for c in crops}
        w = {c: float(rng.uniform(15000, 50000)) for c in crops}
        lo = {c: b[c] * float(rng.choice([0, rng.uniform(0, 0.9)])) for c in crops}
        hi = {c: b[c] * float(rng.uniform(1.0, 2.5)) for c in crops}
        f = frozenset(c for c in crops if rng.random() < 0.5)
        land_eq = rng.random() < 0.3
        p = pf.Portfolio(crops, w, b, lo, hi,
                         water_budget_m3=float(rng.uniform(0.4, 1.3)) * sum(b[c] * w[c] for c in crops),
                         land_max_ha=None if land_eq else sum(b.values()),
                         land_equal_ha=sum(b.values()) if land_eq else None,
                         food=f, food_min_ha=float(rng.uniform(0.3, 1.0)) * sum(b[c] for c in f) if f else None,
                         value_kzt_ha={c: float(rng.uniform(1e5, 2e6)) for c in crops})
        out.append((p, str(rng.choice(["max_area", "min_water", "max_value", "max_food_area"]))))
    return out


def test_browser_solver_matches_highs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js не найден: сверка браузерного решателя не выполнена")
    cs = cases()
    payload = json.dumps([{"problem": to_js(p), "objective": o} for p, o in cs])
    r = subprocess.run([node, "-e", RUNNER, str(ROOT / "web" / "planner_core.js")], input=payload,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    n_opt = n_inf = 0
    for (p, obj), j in zip(cs, js):
        ref = pf.solve(p, obj)
        assert j["status"] == ref.status, (obj, ref.status, j["status"], ref.diagnosis)
        if ref.status != "optimal":
            n_inf += 1
            continue
        n_opt += 1
        scale = max(1.0, abs(ref.objective_value))
        assert abs(j["objective"] - ref.objective_value) <= 1e-6 * scale
        assert j["water"] == pytest.approx(ref.water_m3, rel=1e-6)
        wref = next((c for c in ref.constraints if c["kind"] == "water"), None)
        if wref is not None and wref["binding"] and j["waterBinding"]:
            assert j["waterShadow"] == pytest.approx(wref["shadow"], rel=1e-3, abs=1e-12)
    assert n_opt >= 60 and n_inf >= 3          # проверены и решения, и невыполнимые случаи
