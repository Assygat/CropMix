"""Экспорт данных для симулятора структуры посевов (модуль 10, этап 2).

Что делает (только упаковка, без новой модели):
- web/data/simulator.json (+ simulator.js для file://) — результаты модуля 6 из ГОТОВЫХ CSV
  (outputs/optimizer_structures.csv, optimizer_feasibility.csv, optimizer_area_experiments.csv),
  базовая структура 2025 г., списки сценариев климата и КПД из web/data/model.json, английские подписи,
  правила точности и оговорки. Оптимизация НЕ пересчитывается; числа переносятся как есть.
- web/data/geo.json (+ geo.js) — реальные границы области (geoBoundaries ADM1, S092), 8 территорий
  (ADM2, S093; принадлежность к области — по доле площади внутри границы области) и осевая линия
  Сырдарьи (Natural Earth, S096). Границы 2017 г., упрощённые. Посевов по районам нет и не выдумывается.

Коэффициенты воды браузер берёт из web/data/model.json (модуль 4); этот модуль его не меняет.

Запуск: python -m src.export_simulator   (после python -m src.run_all)
"""

import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
WEB_DATA_DIR = ROOT / "web" / "data"
GEO_RAW_DIR = ROOT / "data" / "raw" / "geo"
PRESETS_CSV = ROOT / "data" / "optimizer_presets.csv"

PRESET_ORDER = ["tight", "moderate", "flexible"]
BASE_AREA_YEAR = "2025"                 # как в src/run_all.py (BASE_AREA_YEAR)
BASE_SCENARIO = "base|base|base"        # E_base: КПД полива | КПД каналов | перколяция риса
MEAN_KEY = "mean"                       # C_mean: среднее 2010–2025

# Английские подписи групп (перевод подписей src/export_web.py CROP_LABELS; то же «приближение»)
CROP_LABELS_EN = {
    "rice": ("Rice", "rice (FAO-56)"),
    "wheat": ("Wheat", "spring wheat (FAO-56)"),
    "potato": ("Potato", "potato (FAO-56)"),
    "fodder": ("Fodder crops", "alfalfa used as proxy for the whole group"),
    "vegetables_open": ("Open-field vegetables", "tomato used as proxy"),
    "melons": ("Melons", "melon used as proxy"),
    "oilseeds": ("Oilseeds", "safflower used as proxy"),
    "grain_other": ("Other grains", "grain maize used as proxy; area = all grains − rice − wheat"),
}

PRESET_LABELS_EN = {"tight": "Tight", "moderate": "Moderate", "flexible": "Flexible"}

# --- Геоданные ---
GEO_FILES = {
    "adm1": "geoBoundaries-KAZ-ADM1_simplified.geojson",
    "adm2": "geoBoundaries-KAZ-ADM2_simplified.geojson",
    "river": "ne_10m_rivers_lake_centerlines_syr_darya.geojson",
}
OBLAST_ISO = "KZ-KZY"
# Исходная метка geoBoundaries 2017 → (id, современное английское название, тип). Источники S094, S095.
DISTRICT_NAMES = {
    "Aral`skiy": ("aral", "Aral District", "district"),
    "Kazalinskiy": ("kazaly", "Kazaly District", "district"),
    "Karmakchinskiy": ("karmakshy", "Karmakshy District", "district"),
    "Zhalagashskiy": ("zhalagash", "Zhalagash District", "district"),
    "Terenozekskiy": ("syrdariya", "Syrdariya District", "district"),
    "Shieliyskiy": ("shieli", "Shieli District", "district"),
    "Zhanakorganskiy": ("zhanakorgan", "Zhanakorgan District", "district"),
    "Qyzylorda": ("kyzylorda_city", "Kyzylorda City", "city"),
}
GRID_STEP_DEG = 0.03        # шаг сетки для доли площади района внутри области
MIN_INSIDE_SHARE = 0.5      # порог принадлежности (фактически: 0.905–1.000 внутри, ≤ 0.018 снаружи)
COORD_DECIMALS = 4          # ≈ 10 м; исходные границы упрощены намного грубее
RIVER_MARGIN_DEG = 0.25     # линию реки обрезаем до рамки области + запас
EARTH_RADIUS_KM = 6371.0088

ATTRIBUTION = {
    "boundaries": "Boundaries: © OpenStreetMap contributors, via geoBoundaries (gbOpen KAZ ADM1/ADM2, "
                  "boundary year 2017), licensed under ODbL 1.0",
    "boundaries_license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
    "osm_copyright_url": "https://www.openstreetmap.org/copyright",
    "river": "River: Natural Earth 1:10m rivers and lake centerlines v5.1.2 (public domain)",
    "river_terms_url": "https://www.naturalearthdata.com/about/terms-of-use/",
}

DISCLAIMERS = [
    "Planning model, not a field measurement, and not validated. The closest backtest check (V1: one "
    "partial-season observation, n = 1, with partly different coverage) gave modelled river withdrawal about "
    "1.7 times the observed value. One observation is not enough to conclude a systematic overestimate, and "
    "the other checks are not directly comparable (docs/backtest.md).",
    "The whole Kyzylorda Region is one modelling unit. District boundaries are shown for orientation only; "
    "the project has no crop data by district.",
    "Optimized structures minimise modelled river withdrawal under mean climate (Cmean, 2010–2025) and baseline "
    "efficiencies (E_base). They are not an economic optimum: income is not modelled.",
    "Preset bounds (crop corridor, food-crop minimum, fixed total area) are author assumptions, not policy.",
    "Area-reduction cases are experimental and are kept separate from the optimizer presets.",
    "Boundaries date from 2017 and are simplified; the Syr Darya line is a generalised 1:10m centreline.",
]

PRECISION = {
    "volume_km3_decimals": 2,
    "area_ha_round_to": 10,
    "percent_decimals": 1,
    "coef_m3_per_ha_round_to": 100,
    "note": "Stored values keep full precision; rounding applies to display only.",
}


# ============================================================================================
# Чтение готовых результатов модуля 6 (без пересчёта)
# ============================================================================================

def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _num(text):
    """Строка CSV → float без потери точности (float(repr) — точный обратный перевод)."""
    if text is None or text == "":
        return None
    v = float(text)
    if not math.isfinite(v):
        raise ValueError(f"Нечисловое значение в CSV: {text!r}")
    return v


def _bool(text):
    if text not in ("True", "False"):
        raise ValueError(f"Ожидалось True/False, получено {text!r}")
    return text == "True"


def load_preset_params(path=PRESETS_CSV):
    """Параметры предустановок, цели и метки продовольственных культур — как в data/optimizer_presets.csv."""
    rows = _read_csv(path)
    presets, targets, food, experiments = {}, {}, {}, {}
    for r in rows:
        if r["entity"] == "preset":
            presets.setdefault(r["measure"], {})[r["param"]] = {"value": float(r["value"]), "status": r["status"]}
        elif r["entity"] == "target":
            targets[r["measure"]] = float(r["value"])
        elif r["entity"] == "experiment":
            experiments[r["measure"]] = float(r["value"])
        elif r["param"] == "food_crop":
            food[r["entity"]] = r["value"] in ("1", "1.0")
    return presets, targets, food, experiments


def build_presets(structures_rows, feasibility_rows, preset_params):
    """Предустановки из CSV модуля 6: площади культур — ровно opt_ha / base_ha из optimizer_structures.csv."""
    out = {}
    for pid in PRESET_ORDER:
        rows = [r for r in structures_rows if r["preset"] == pid]
        feas = [r for r in feasibility_rows if r["preset"] == pid]
        if not rows or not feas:
            raise ValueError(f"В выходах модуля 6 нет предустановки {pid}")
        base_m3 = {_num(r["base_m3"]) for r in feas}
        min_m3 = {_num(r["min_achievable_m3"]) for r in feas}
        saving = {_num(r["saving_pct_max"]) for r in feas}
        if len(base_m3) != 1 or len(min_m3) != 1 or len(saving) != 1:
            raise ValueError(f"Противоречивые итоги предустановки {pid} в optimizer_feasibility.csv")
        params = preset_params[pid]
        out[pid] = {
            "label": PRESET_LABELS_EN[pid],
            "kind": "optimizer_preset",
            "objective": "minimum modelled river withdrawal",
            "evaluated_under": {"climate": MEAN_KEY, "efficiency": BASE_SCENARIO},
            "params": {k: v["value"] for k, v in params.items()},
            "params_status": sorted({v["status"] for v in params.values()}),
            "areas_ha": {r["crop"]: _num(r["opt_ha"]) for r in rows},
            "base_areas_ha": {r["crop"]: _num(r["base_ha"]) for r in rows},
            "river_m3_ha_used": {r["crop"]: _num(r["river_m3_ha"]) for r in rows},
            "base_river_m3": base_m3.pop(),
            "optimized_river_m3": min_m3.pop(),
            "saving_pct": saving.pop(),
            "targets": [{"kind": r["limit_kind"], "id": r["limit_id"], "limit_m3": _num(r["limit_m3"]),
                         "feasible": _bool(r["feasible"])} for r in feas],
        }
    return out


def build_experiments(experiment_rows):
    """Экспериментальные сокращения общей площади — только итоги из CSV (по культурам площади там не сохранены)."""
    out = []
    for r in experiment_rows:
        if r["scenario_type"] != "experimental":
            raise ValueError("В optimizer_area_experiments.csv ожидаются только экспериментальные строки")
        ok = _bool(r["feasible"])
        out.append({
            "experimental": True, "preset": r["preset"], "id": r["experiment"],
            "area_reduction": _num(r["area_reduction"]), "feasible": ok,
            "total_ha": _num(r["total_ha"]), "base_ha": _num(r["base_ha"]),
            "river_m3": _num(r["water_m3"]), "base_river_m3": _num(r["base_m3"]),
            "saving_total_pct": _num(r["saving_total_pct"]),
            "saving_structure_pct": _num(r["saving_structure_pct"]),
            "saving_area_pct": _num(r["saving_area_pct"]),
            "infeasible_reason": None if ok else "no solution: crop corridor and food-crop minimum "
                                                 "cannot fit the reduced total area",
        })
    return out


def scenario_options(model):
    """Сценарии климата и КПД, для которых в model.json есть коэффициенты."""
    sc = model["scenarios"]
    eff = [{"key": f"{f['id']}|{c['id']}|{p['id']}",
            "eff_field": f["value"], "eff_canal": c["value"], "rice_percolation_mm_day": p["value"],
            "status": sorted({f["status"], c["status"], p["status"]})}
           for f in sc["eff_field"] for c in sc["eff_canal"] for p in sc["rice_percolation"]]
    climate = [{"key": MEAN_KEY, "label": "Mean 2010–2025"}] + \
              [{"key": y, "label": f"Climate of {y}"} for y in model["years"]]
    return {
        "climate": climate,
        "efficiency": eff,
        "efficiency_levels": {
            "eff_field": [{"id": f["id"], "value": f["value"]} for f in sc["eff_field"]],
            "eff_canal": [{"id": c["id"], "value": c["value"]} for c in sc["eff_canal"]],
            "rice_percolation_mm_day": [{"id": p["id"], "value": p["value"]} for p in sc["rice_percolation"]],
        },
        "default": {"climate": MEAN_KEY, "efficiency": BASE_SCENARIO},
        "not_available": ["Climate 2026 (NASA POWER Jan–Sep 2026, S091) is used only in the backtest; "
                          "model.json has no 2026 coefficients."],
    }


def build_simulator(model, structures_rows, feasibility_rows, experiment_rows, preset_params_tuple):
    presets_params, _targets, food, exp_params = preset_params_tuple
    crops = [c["id"] for c in model["crops"]]
    baseline = {c: float(model["areas_ha"][BASE_AREA_YEAR][c]) for c in crops}
    presets = build_presets(structures_rows, feasibility_rows, presets_params)
    experiments = build_experiments(experiment_rows)
    return {
        "meta": {
            "generated": date.today().isoformat(),
            "generator": "src/export_simulator.py",
            "units": {"area": "ha", "water": "m3 (1 mm on 1 ha = 10 m3)", "display_volume": "km3"},
            "notation": "W(A, C, E) = sum over crops of A_c x k(c, C, E); k from model.json coef_m3_ha "
                        "[E][C][crop] = [plant, field, river] m3/ha",
            "inputs": ["outputs/optimizer_structures.csv", "outputs/optimizer_feasibility.csv",
                       "outputs/optimizer_area_experiments.csv", "data/optimizer_presets.csv",
                       "web/data/model.json"],
            "coefficients_file": "model.json",
            "modelling_unit": "Kyzylorda Region (whole oblast)",
        },
        "crops": [{"id": c, "name": CROP_LABELS_EN[c][0], "proxy": CROP_LABELS_EN[c][1],
                   "food_crop": food[c], "flooded": next(x["flooded"] for x in model["crops"] if x["id"] == c),
                   "area_status": model["area_status"][c]["status"]} for c in crops],
        "baseline": {"label": "Baseline", "area_year": int(BASE_AREA_YEAR), "areas_ha": baseline,
                     "total_ha": sum(baseline.values()), "status": "real (stat.gov.kz; other grains derived)"},
        "optimized": {
            "note": "Optimized = minimum modelled river withdrawal under Cmean and E_base with fixed total area. "
                    "Not an economic optimum. When the user changes climate or efficiency, the optimized areas "
                    "stay the same and are re-evaluated; they are not re-optimized in the browser.",
            "presets_order": PRESET_ORDER,
            "presets": presets,
        },
        "experiments": {
            "experimental": True,
            "note": "Experimental: total sown area reduced by 5/10/15 %. Saving = structure + area. Not optimizer "
                    "presets. Per-crop areas are not stored by module 6, so only totals are exported.",
            "parameters": exp_params,
            "cases": experiments,
        },
        "scenarios": scenario_options(model),
        "precision": PRECISION,
        "disclaimers": DISCLAIMERS,
    }


# ============================================================================================
# Геометрия (чистый Python, без новых зависимостей)
# ============================================================================================

def polygons_of(geometry):
    """GeoJSON Polygon/MultiPolygon → список полигонов (каждый — список колец [[lon, lat], ...])."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"Ожидался полигон, получено {geometry['type']}")


def point_in_polygon(x, y, polygon):
    """Чётно-нечётное правило по всем кольцам полигона (внешнее + дыры)."""
    inside = False
    for ring in polygon:
        for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def bbox(polygons):
    xs = [p[0] for poly in polygons for ring in poly for p in ring]
    ys = [p[1] for poly in polygons for ring in poly for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _grid_cells(polygons, step):
    x0, y0, x1, y1 = bbox(polygons)
    cells = set()
    for i in range(math.floor(x0 / step), math.floor(x1 / step) + 1):
        for j in range(math.floor(y0 / step), math.floor(y1 / step) + 1):
            cx, cy = (i + 0.5) * step, (j + 0.5) * step
            if any(point_in_polygon(cx, cy, p) for p in polygons):
                cells.add((i, j))
    return cells


def inside_share(polygons, container, step=GRID_STEP_DEG):
    """Доля площади polygons внутри container (по центрам ячеек сетки, градусы). 0, если ячеек нет."""
    own = _grid_cells(polygons, step)
    if not own:
        return 0.0
    ref = _grid_cells(container, step)
    return len(own & ref) / len(own)


def ring_area_km2(ring):
    """Площадь кольца на сфере (Chamberlain & Duquette 2007), км²; знак зависит от обхода."""
    total = 0.0
    for (l1, p1), (l2, p2) in zip(ring[:-1], ring[1:]):
        total += math.radians(l2 - l1) * (2 + math.sin(math.radians(p1)) + math.sin(math.radians(p2)))
    return total * EARTH_RADIUS_KM ** 2 / 2


def polygons_area_km2(polygons):
    """Внешнее кольцо минус дыры, км²."""
    return sum(abs(ring_area_km2(poly[0])) - sum(abs(ring_area_km2(h)) for h in poly[1:]) for poly in polygons)


def _round_ring(ring, nd):
    out = []
    for x, y in ring:
        p = [round(x, nd), round(y, nd)]
        if not out or out[-1] != p:
            out.append(p)
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def round_polygons(polygons, nd=COORD_DECIMALS):
    return [[_round_ring(ring, nd) for ring in poly] for poly in polygons]


def _segments_cross(a, b, c, d):
    """Собственное пересечение отрезков ab и cd (касание концами не считается)."""
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 0) - (v < 0)
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def ring_problems(ring):
    """Список проблем кольца: незамкнутость, мало точек, нечисла, дубли подряд, самопересечения, нулевая площадь."""
    probs = []
    if len(ring) < 4:
        probs.append("fewer than 4 points")
    if ring[0] != ring[-1]:
        probs.append("not closed")
    for x, y in ring:
        if not (math.isfinite(x) and math.isfinite(y)) or not (-180 <= x <= 180 and -90 <= y <= 90):
            probs.append(f"bad coordinate {x},{y}")
            break
    if any(p == q for p, q in zip(ring[:-1], ring[1:])):
        probs.append("repeated consecutive point")
    segs = list(zip(ring[:-1], ring[1:]))
    n = len(segs)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(*segs[i], *segs[j]):
                probs.append(f"self-intersection between segments {i} and {j}")
                return probs
    if abs(ring_area_km2(ring)) <= 0:
        probs.append("zero area")
    return probs


def line_problems(line):
    probs = []
    if len(line) < 2:
        probs.append("fewer than 2 points")
    for x, y in line:
        if not (math.isfinite(x) and math.isfinite(y)) or not (-180 <= x <= 180 and -90 <= y <= 90):
            probs.append(f"bad coordinate {x},{y}")
            break
    return probs


def clip_lines_to_box(lines, box):
    """Оставить части линий внутри рамки (x0, y0, x1, y1); граничные точки снаружи сохраняются для непрерывности."""
    x0, y0, x1, y1 = box
    inside = lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1  # noqa: E731
    out = []
    for line in lines:
        run = []
        for k, p in enumerate(line):
            if inside(p):
                if not run and k > 0:
                    run.append(line[k - 1])
                run.append(p)
            elif run:
                run.append(p)
                out.append(run)
                run = []
        if run:
            out.append(run)
    return [r for r in out if len(r) >= 2]


def _round_line(line, nd):
    out = []
    for x, y in line:
        p = [round(x, nd), round(y, nd)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def _load_geojson(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_geo(raw_dir=GEO_RAW_DIR):
    raw_dir = Path(raw_dir)
    adm1 = _load_geojson(raw_dir / GEO_FILES["adm1"])
    adm2 = _load_geojson(raw_dir / GEO_FILES["adm2"])
    river = _load_geojson(raw_dir / GEO_FILES["river"])

    obl = [f for f in adm1["features"] if f["properties"].get("shapeISO") == OBLAST_ISO]
    if len(obl) != 1:
        raise ValueError(f"В ADM1 ожидался ровно один объект {OBLAST_ISO}, найдено {len(obl)}")
    obl = obl[0]
    obl_polys = polygons_of(obl["geometry"])
    ox0, oy0, ox1, oy1 = bbox(obl_polys)

    districts = []
    for f in adm2["features"]:
        polys = polygons_of(f["geometry"])
        x0, y0, x1, y1 = bbox(polys)
        if x1 < ox0 or x0 > ox1 or y1 < oy0 or y0 > oy1:
            continue
        share = inside_share(polys, obl_polys)
        if share < MIN_INSIDE_SHARE:
            continue
        src = f["properties"]["shapeName"]
        if src not in DISTRICT_NAMES:
            raise ValueError(f"Территория {src!r} внутри области, но нет в DISTRICT_NAMES")
        did, name, kind = DISTRICT_NAMES[src]
        districts.append({"type": "Feature",
                          "properties": {"id": did, "name": name, "kind": kind, "source_name": src,
                                         "source_shape_id": f["properties"]["shapeID"],
                                         "inside_oblast_share": round(share, 3),
                                         "area_km2_approx": round(polygons_area_km2(polys), -1),
                                         "boundary_year": 2017, "source": "S093"},
                          "geometry": {"type": "MultiPolygon", "coordinates": round_polygons(polys)}})
    missing = set(DISTRICT_NAMES) - {d["properties"]["source_name"] for d in districts}
    if missing or len(districts) != len(DISTRICT_NAMES):
        raise ValueError(f"Ожидалось {len(DISTRICT_NAMES)} территорий; не найдены: {sorted(missing)}")
    districts.sort(key=lambda d: d["properties"]["name"])

    lines = []
    for f in river["features"]:
        g = f["geometry"]
        lines.extend(g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]])
    box = (ox0 - RIVER_MARGIN_DEG, oy0 - RIVER_MARGIN_DEG, ox1 + RIVER_MARGIN_DEG, oy1 + RIVER_MARGIN_DEG)
    clipped = [_round_line(l, COORD_DECIMALS) for l in clip_lines_to_box(lines, box)]
    clipped = [l for l in clipped if len(l) >= 2]
    src_name = river["features"][0]["properties"]["name"]

    return {
        "meta": {
            "generated": date.today().isoformat(),
            "generator": "src/export_simulator.py",
            "crs": "EPSG:4326 (lon, lat, degrees)",
            "coordinate_decimals": COORD_DECIMALS,
            "boundary_year": 2017,
            "simplified": True,
            "district_assignment": f"share of district area inside the oblast boundary on a {GRID_STEP_DEG}° grid "
                                   f"≥ {MIN_INSIDE_SHARE}",
            "attribution": ATTRIBUTION,
            "sources": {"oblast": "S092", "districts": "S093", "district_names": "S094, S095", "river": "S096"},
            "notes": ["Boundaries represent 2017 (OpenStreetMap via geoBoundaries) and are simplified; ADM1 and "
                      "ADM2 simplifications do not match exactly.",
                      "District names shown are current English names; original 2017 labels are kept in "
                      "source_name.",
                      "No crop, field or water data exist by district in this project.",
                      "The Syr Darya line is a generalised 1:10m centreline clipped to the region's bounding box, "
                      "not the river channel or the canal network."],
        },
        "oblast": {"type": "Feature",
                   "properties": {"id": "kyzylorda_region", "name": "Kyzylorda Region", "iso": OBLAST_ISO,
                                  "source_name": obl["properties"]["shapeName"],
                                  "source_shape_id": obl["properties"]["shapeID"],
                                  "area_km2_approx": round(polygons_area_km2(obl_polys), -1),
                                  "boundary_year": 2017, "source": "S092"},
                   "geometry": {"type": "MultiPolygon", "coordinates": round_polygons(obl_polys)}},
        "districts": {"type": "FeatureCollection", "features": districts},
        "river": {"type": "Feature",
                  "properties": {"id": "syr_darya", "name": "Syr Darya", "source_name": src_name,
                                 "source": "S096"},
                  "geometry": {"type": "MultiLineString", "coordinates": clipped}},
        "bbox": [round(ox0, COORD_DECIMALS), round(oy0, COORD_DECIMALS),
                 round(ox1, COORD_DECIMALS), round(oy1, COORD_DECIMALS)],
    }


def geo_problems(geo):
    """Все найденные проблемы геометрии (пустой список — всё в порядке)."""
    probs = []
    feats = [geo["oblast"]] + geo["districts"]["features"]
    for f in feats:
        polys = f["geometry"]["coordinates"]
        if not polys:
            probs.append(f"{f['properties']['id']}: empty geometry")
        for poly in polys:
            for ring in poly:
                probs += [f"{f['properties']['id']}: {p}" for p in ring_problems(ring)]
    lines = geo["river"]["geometry"]["coordinates"]
    if not lines:
        probs.append("river: empty geometry")
    for line in lines:
        probs += [f"river: {p}" for p in line_problems(line)]
    return probs


# ============================================================================================
# Запись
# ============================================================================================

def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_simulator(sim, geo, web_data_dir=WEB_DATA_DIR):
    """Пишет simulator.json/.js и geo.json/.js. model.json не трогает."""
    web_data_dir = Path(web_data_dir)
    web_data_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, var, obj in (("simulator", "CROPMIX_SIMULATOR", sim), ("geo", "CROPMIX_GEO", geo)):
        text = _dump(obj)
        (web_data_dir / f"{name}.json").write_text(text, encoding="utf-8")
        (web_data_dir / f"{name}.js").write_text(
            "// Сгенерировано src/export_simulator.py — не редактировать вручную.\n"
            f"window.{var} = {text};\n", encoding="utf-8")
        written += [web_data_dir / f"{name}.json", web_data_dir / f"{name}.js"]
    return written


def load_inputs(outputs_dir=OUTPUTS_DIR, web_data_dir=WEB_DATA_DIR, presets_csv=PRESETS_CSV):
    outputs_dir, web_data_dir = Path(outputs_dir), Path(web_data_dir)
    with open(web_data_dir / "model.json", encoding="utf-8") as fh:
        model = json.load(fh)
    return (model, _read_csv(outputs_dir / "optimizer_structures.csv"),
            _read_csv(outputs_dir / "optimizer_feasibility.csv"),
            _read_csv(outputs_dir / "optimizer_area_experiments.csv"), load_preset_params(presets_csv))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sim = build_simulator(*load_inputs())
    geo = build_geo()
    probs = geo_problems(geo)
    if probs:
        raise ValueError("Геометрия невалидна: " + "; ".join(probs[:10]))
    for p in write_simulator(sim, geo):
        print(f"Записано: {p.relative_to(ROOT)} ({p.stat().st_size / 1024:.0f} КБ)")
    for pid in PRESET_ORDER:
        p = sim["optimized"]["presets"][pid]
        print(f"  {pid:9s} {p['base_river_m3'] / 1e9:.2f} → {p['optimized_river_m3'] / 1e9:.2f} км³ "
              f"(−{p['saving_pct']:.1f} %), Cmean / E_base")
    print(f"  территорий: {len(geo['districts']['features'])}; линий реки: "
          f"{len(geo['river']['geometry']['coordinates'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
