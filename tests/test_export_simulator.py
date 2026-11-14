"""Тесты src/export_simulator.py (модуль 10, этап 2): перенос результатов модуля 6 без пересчёта и геоданные."""

import copy
import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from src import export_simulator as ex

ROOT = Path(__file__).resolve().parent.parent


# ---------- ручные примеры геометрии ----------

SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]


def test_point_in_polygon_hand_examples():
    poly = [SQUARE]
    assert ex.point_in_polygon(0.5, 0.5, poly)
    assert not ex.point_in_polygon(1.5, 0.5, poly)
    # дыра: квадрат 0.25–0.75 вычитается
    hole = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75], [0.25, 0.25]]
    assert not ex.point_in_polygon(0.5, 0.5, [SQUARE, hole])
    assert ex.point_in_polygon(0.1, 0.1, [SQUARE, hole])


def test_inside_share_hand_examples():
    big = [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    inner = [[[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]]
    half_out = [[[1, 0], [3, 0], [3, 2], [1, 2], [1, 0]]]          # половина внутри big
    assert ex.inside_share([inner], [big], step=0.1) == pytest.approx(1.0)
    assert ex.inside_share([half_out], [big], step=0.1) == pytest.approx(0.5, abs=0.03)
    far = [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]
    assert ex.inside_share([far], [big], step=0.1) == 0.0


def test_ring_area_one_degree_square_at_equator():
    # точная площадь сферической трапеции: R²·Δλ·(sin φ2 − sin φ1) = 12 364 км²
    expected = ex.EARTH_RADIUS_KM ** 2 * math.radians(1) * math.sin(math.radians(1))
    assert abs(ex.ring_area_km2(SQUARE)) == pytest.approx(expected, rel=1e-9)
    assert expected == pytest.approx(12364, abs=1)


def test_ring_problems_hand_examples():
    assert ex.ring_problems(SQUARE) == []
    assert "not closed" in ex.ring_problems(SQUARE[:-1] + [[0, 0.5]])
    bowtie = [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]
    assert any("self-intersection" in p for p in ex.ring_problems(bowtie))
    assert any("bad coordinate" in p for p in ex.ring_problems([[0, 0], [float("nan"), 0], [1, 1], [0, 0]]))


def test_clip_lines_to_box_hand_example():
    line = [[-2, 0], [-1, 0], [0.5, 0], [1.5, 0], [3, 0], [4, 0]]
    parts = ex.clip_lines_to_box([line], (0, -1, 2, 1))
    # одна часть: точка снаружи слева, две внутри, точка снаружи справа
    assert parts == [[[-1, 0], [0.5, 0], [1.5, 0], [3, 0]]]
    assert ex.clip_lines_to_box([[[5, 5], [6, 6]]], (0, 0, 1, 1)) == []


def test_round_polygons_keeps_rings_closed_and_dedupes():
    ring = [[0.00001, 0], [0.00002, 0], [1, 0], [1, 1], [0, 1], [0.00001, 0]]
    out = ex.round_polygons([[ring]], nd=4)[0][0]
    assert out[0] == out[-1]
    assert all(p != q for p, q in zip(out[:-1], out[1:]))


# ---------- экспорт оптимизатора ----------

def _csv(name):
    with open(ROOT / "outputs" / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def inputs():
    if not (ROOT / "outputs" / "optimizer_structures.csv").exists():
        pytest.skip("Нет outputs/ — сначала python -m src.run_all")
    return ex.load_inputs()


@pytest.fixture(scope="module")
def sim(inputs):
    return ex.build_simulator(*inputs)


def test_all_three_presets_present(sim):
    assert sim["optimized"]["presets_order"] == ["tight", "moderate", "flexible"]
    assert set(sim["optimized"]["presets"]) == {"tight", "moderate", "flexible"}


@pytest.mark.parametrize("pid", ["tight", "moderate", "flexible"])
def test_areas_equal_csv_exactly(sim, pid):
    rows = [r for r in _csv("optimizer_structures.csv") if r["preset"] == pid]
    p = sim["optimized"]["presets"][pid]
    assert set(p["areas_ha"]) == {r["crop"] for r in rows}
    for r in rows:
        assert p["areas_ha"][r["crop"]] == float(r["opt_ha"])          # точное равенство, без допуска
        assert p["base_areas_ha"][r["crop"]] == float(r["base_ha"])
    # JSON-круг тоже без потерь
    back = json.loads(ex._dump(p["areas_ha"]))
    assert back == p["areas_ha"]


@pytest.mark.parametrize("pid", ["tight", "moderate", "flexible"])
def test_total_area_preserved_and_non_negative(sim, pid):
    p = sim["optimized"]["presets"][pid]
    assert all(v >= 0 for v in p["areas_ha"].values())
    assert sum(p["areas_ha"].values()) == pytest.approx(sum(p["base_areas_ha"].values()), rel=1e-9)
    assert sum(p["base_areas_ha"].values()) == pytest.approx(sim["baseline"]["total_ha"], rel=1e-12)
    assert p["base_areas_ha"] == sim["baseline"]["areas_ha"]


def test_no_nan_or_infinity(sim, inputs):
    text = ex._dump(sim)                      # allow_nan=False — иначе ValueError
    assert "NaN" not in text and "Infinity" not in text
    with pytest.raises(ValueError):
        ex._dump({"x": float("nan")})


@pytest.mark.parametrize("pid", ["tight", "moderate", "flexible"])
def test_csv_coefficients_match_model_json(sim, inputs, pid):
    # коэффициенты модуля 6 = model.json coef_m3_ha[E_base][mean][crop][river]; W(opt) = оптимум из CSV
    model = inputs[0]
    k = {c: v[2] for c, v in model["coef_m3_ha"][ex.BASE_SCENARIO][ex.MEAN_KEY].items()}
    p = sim["optimized"]["presets"][pid]
    for c, v in p["river_m3_ha_used"].items():
        assert v == pytest.approx(k[c], rel=1e-12)
    assert sum(p["areas_ha"][c] * k[c] for c in k) == pytest.approx(p["optimized_river_m3"], rel=1e-9)
    assert sum(p["base_areas_ha"][c] * k[c] for c in k) == pytest.approx(p["base_river_m3"], rel=1e-9)
    assert p["evaluated_under"] == {"climate": "mean", "efficiency": "base|base|base"}
    assert "river withdrawal" in p["objective"]


def test_experiments_separate_and_flagged(sim):
    e = sim["experiments"]
    assert e["experimental"] is True and all(c["experimental"] for c in e["cases"])
    assert "experiment" not in json.dumps(sim["optimized"]).lower()
    rows = _csv("optimizer_area_experiments.csv")
    assert len(e["cases"]) == len(rows)
    for c, r in zip(e["cases"], rows):
        assert c["feasible"] == (r["feasible"] == "True")
        if c["feasible"]:
            assert c["river_m3"] == float(r["water_m3"]) and c["total_ha"] == float(r["total_ha"])
        else:
            assert c["river_m3"] is None and c["infeasible_reason"]


def test_scenario_lists_match_model_json(sim, inputs):
    model = inputs[0]
    eff = [s["key"] for s in sim["scenarios"]["efficiency"]]
    assert len(eff) == 36 and set(eff) == set(model["coef_m3_ha"])
    clim = [c["key"] for c in sim["scenarios"]["climate"]]
    assert clim == ["mean"] + model["years"]
    for key in eff:
        assert set(model["coef_m3_ha"][key]) == set(clim)


def test_build_does_not_mutate_inputs(inputs):
    before = copy.deepcopy(inputs)
    ex.build_simulator(*inputs)
    assert inputs == before


def test_write_does_not_touch_model_json(sim, tmp_path):
    src = ROOT / "web" / "data" / "model.json"
    (tmp_path / "model.json").write_bytes(src.read_bytes())
    h = hashlib.sha256(src.read_bytes()).hexdigest()
    written = ex.write_simulator(sim, {"meta": {}}, tmp_path)
    assert {p.name for p in written} == {"simulator.json", "simulator.js", "geo.json", "geo.js"}
    assert hashlib.sha256((tmp_path / "model.json").read_bytes()).hexdigest() == h
    js = (tmp_path / "simulator.js").read_text(encoding="utf-8")
    assert js.split("= ", 1)[1].rstrip().rstrip(";") == (tmp_path / "simulator.json").read_text(encoding="utf-8")


def test_published_simulator_json_is_current(sim):
    path = ROOT / "web" / "data" / "simulator.json"
    if not path.exists():
        pytest.skip("simulator.json ещё не экспортирован")
    pub = json.loads(path.read_text(encoding="utf-8"))
    assert pub["optimized"] == sim["optimized"] and pub["experiments"] == sim["experiments"]
    assert pub["baseline"] == sim["baseline"] and pub["scenarios"] == sim["scenarios"]


def test_english_only_labels(sim):
    text = json.dumps({k: v for k, v in sim.items() if k != "meta"}, ensure_ascii=False)
    assert not any("Ѐ" <= ch <= "ӿ" for ch in text)    # нет кириллицы в данных для интерфейса


# ---------- геоданные ----------

@pytest.fixture(scope="module")
def geo():
    return ex.build_geo()


def test_exactly_eight_kyzylorda_territories(geo):
    feats = geo["districts"]["features"]
    assert len(feats) == 8
    assert {f["properties"]["source_name"] for f in feats} == set(ex.DISTRICT_NAMES)
    assert {f["properties"]["name"] for f in feats} == {v[1] for v in ex.DISTRICT_NAMES.values()}
    assert sum(f["properties"]["kind"] == "city" for f in feats) == 1
    for f in feats:
        assert f["properties"]["inside_oblast_share"] >= 0.9     # фактически 0.905–1.000


def test_districts_lie_inside_oblast_and_area_consistent(geo):
    obl = geo["oblast"]
    x0, y0, x1, y1 = geo["bbox"]
    for f in geo["districts"]["features"]:
        bx0, by0, bx1, by1 = ex.bbox(f["geometry"]["coordinates"])
        assert bx0 >= x0 - 0.5 and by0 >= y0 - 0.5 and bx1 <= x1 + 0.5 and by1 <= y1 + 0.5
    total = sum(f["properties"]["area_km2_approx"] for f in geo["districts"]["features"])
    # упрощённые ADM1 и ADM2 не совпадают полностью: сумма районов в пределах ±10 % площади области
    assert total == pytest.approx(obl["properties"]["area_km2_approx"], rel=0.10)


def test_geometry_valid(geo):
    assert ex.geo_problems(geo) == []
    assert geo["oblast"]["properties"]["iso"] == "KZ-KZY"
    assert geo["river"]["geometry"]["coordinates"]


def test_river_clipped_to_region(geo):
    x0, y0, x1, y1 = geo["bbox"]
    m = ex.RIVER_MARGIN_DEG
    for line in geo["river"]["geometry"]["coordinates"]:
        inner = line[1:-1]                    # концы могут быть первой точкой за рамкой
        assert all(x0 - m <= x <= x1 + m and y0 - m <= y <= y1 + m for x, y in inner)


def test_geo_meta_attribution_and_year(geo):
    a = geo["meta"]["attribution"]
    assert "OpenStreetMap contributors" in a["boundaries"] and "ODbL" in a["boundaries"]
    assert "Natural Earth" in a["river"] and "public domain" in a["river"]
    assert geo["meta"]["boundary_year"] == 2017
    for f in [geo["oblast"]] + geo["districts"]["features"]:
        assert f["properties"]["boundary_year"] == 2017 and f["properties"]["source_name"]
    # никаких данных о посевах в геоданных
    text = json.dumps(geo).lower()
    assert "areas_ha" not in text and "crop" not in text.replace("no crop", "")
