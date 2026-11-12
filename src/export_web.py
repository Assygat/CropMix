"""Экспорт результатов модели для веб-интерфейса (модуль 4).

Истину считает только Python (модули 1–3). Браузер лишь умножает площадь на
готовые коэффициенты м³/га: модель линейна по площади, поэтому
вода_всего = Σ площадь_культуры × коэффициент_культуры — это точный пересчёт.

Что пишется:
- outputs/etc_season.csv        — ET0 и ETc за сезон, культура × год;
- outputs/layer1_scenarios.csv  — слой 1 для всех сценариев КПД и перколяции риса;
- outputs/regional_check.csv    — модельный водозабор области против официальных величин;
- web/data/model.json           — всё для веба (коэффициенты, площади, статусы, сравнение);
- web/data/model.js             — то же, обёрнутое в window.CROPMIX_MODEL (страница открывается
                                  через file://, где браузер не даёт читать JSON через fetch).

Ничего не калибруется: официальные величины только показываются рядом для сравнения.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from src import etc
from src import layer1_losses as l1
from src.data_report import summarize

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
WEB_DATA_DIR = ROOT / "web" / "data"
MEAN_KEY = "mean"

# Подписи групп для интерфейса (чем описана группа — см. docs/limitations.md, раздел Kc).
CROP_LABELS = {
    "rice": ("Рис", "рис (FAO-56)"),
    "wheat": ("Пшеница", "яровая пшеница (FAO-56)"),
    "potato": ("Картофель", "картофель (FAO-56)"),
    "fodder": ("Кормовые", "люцерна как приближение для всей группы"),
    "vegetables_open": ("Овощи открытого грунта", "томат как приближение"),
    "melons": ("Бахчевые", "дыня как приближение"),
    "oilseeds": ("Масличные", "сафлор как приближение"),
    "grain_other": ("Прочие зерновые", "кукуруза на зерно как приближение; площадь = зерновые − рис − пшеница"),
}

# Какие официальные величины сравнимы с годовой моделью того же года (measure в water_withdrawal.csv).
# Частичный факт на дату внутри сезона (actual_to_..., supplied_to_...) не сравнивается с сезонной суммой.
COMPARABLE_OFFICIAL = {"limit_vegetation": "лимит на вегетацию", "plan_vegetation": "план на вегетацию"}

WARNING_POINTS = [
    "Это расчётная потребность в воде по модели, а не измеренный фактический водозабор.",
    "Расчёт охватывает все посевные площади культур, хотя не все они обязательно орошаются.",
    "ETc и КПД полива и каналов содержат допущения (статус assumed) и неопределённость.",
    "Абсолютные значения по области нельзя считать подтверждёнными до бэктеста (модуль 8).",
]

LIMITATIONS = [
    "Модель для планирования, а не измерение на поле.",
    "Климат — сеточная модель NASA POWER (реанализ MERRA-2 и спутник CERES), а не метеостанция.",
    "Kc — литературные значения FAO-56 с климатической поправкой; для 5 групп культура-приближение.",
    "ETc риса выше литературного ET риса (10–11 тыс. м³/га) в 1.22–1.34 раза — это верхняя оценка.",
    "КПД каналов и полива — допущения; измерений по области нет.",
    "Календари сева фиксированы; сброс воды с рисовых чеков и промывка засолённых земель не учтены.",
    "Эффективные осадки по USDA SCS (вторичный источник S090); их вклад 2–5 % ETc.",
    "Доход пока не рассчитывается: нет затрат на гектар, а урожайность и цены есть не для всех групп.",
]


def scenario_key(field_measure, canal_measure, perc_measure):
    return f"{field_measure}|{canal_measure}|{perc_measure}"


def _measures(table, entity, param):
    sub = table[(table["entity"] == entity) & (table["param"] == param)]
    return [{"id": m, "value": float(v), "status": s}
            for m, v, s in sorted(zip(sub["measure"], sub["value"], sub["status"]), key=lambda x: x[1])]


def crop_areas_wide(crop_areas, crops):
    """Площади (га) 8 групп по годам. grain_other = grain_total − rice − wheat (вычисляется)."""
    a = crop_areas.pivot_table(index="year", columns="entity", values="value", aggfunc="first")
    a["grain_other"] = a["grain_total"] - a["rice"] - a["wheat"]
    if (a["grain_other"] < 0).any():
        raise ValueError("grain_other < 0: зерновые меньше суммы риса и пшеницы")
    missing = [c for c in crops if c not in a.columns]
    if missing:
        raise ValueError(f"Нет площадей для групп: {missing}")
    return a[crops].astype(float)


def area_status(crop_areas, crops):
    """Статус площадей по группам: real из данных; grain_other — вычислено из real."""
    out = {}
    for c in crops:
        if c == "grain_other":
            out[c] = {"status": "derived", "note": "вычислено: зерновые − рис − пшеница (все три — real)"}
            continue
        sub = crop_areas[crop_areas["entity"] == c]
        out[c] = {"status": ",".join(sorted(set(sub["status"]))),
                  "source": ",".join(sorted(set(map(str, sub["source"]))))}
    return out


def regional_totals(coef_year, areas):
    """Σ площадь × коэффициент для трёх величин (м³). coef_year: {crop: [plant, field, river]}."""
    totals = [0.0, 0.0, 0.0]
    for crop, area in areas.items():
        for i in range(3):
            totals[i] += float(area) * coef_year[crop][i]
    return {"plant_m3": totals[0], "field_m3": totals[1], "river_m3": totals[2]}


def build_model(tables, years=etc.YEARS):
    """Считает модули 1–3 для всех сценариев и собирает словарь для веба и таблицы для outputs/."""
    crops_df, climate, sites = tables["crops_fao56"], tables["climate_daily"], tables["climate_sites"]
    efficiency, rice_water = tables["efficiency"], tables["rice_water"]
    crops = list(crops_df["entity"].drop_duplicates())
    years = list(years)

    etc_season, daily = etc.crop_water_tables(crops_df, climate, sites, years=years)
    precip = l1.precip_series(climate, etc.NASA_ENTITY)

    field_m = _measures(efficiency, l1.FIELD_ENTITY, "eff_field")
    canal_m = _measures(efficiency, l1.CANAL_ENTITY, "eff_canal")
    perc_m = _measures(rice_water, "rice", "rice_percolation")

    parts, coef = [], {}
    for f in field_m:
        for c in canal_m:
            for p in perc_m:
                season, _ = l1.layer1_tables(daily, precip, efficiency, rice_water,
                                             f["id"], c["id"], p["id"])
                key = scenario_key(f["id"], c["id"], p["id"])
                parts.append(season.assign(eff_field_measure=f["id"], eff_canal_measure=c["id"],
                                           perc_measure=p["id"]))
                by_year = {}
                for year, g in season.groupby("year"):
                    by_year[str(year)] = {r.crop: [r.plant_m3_ha, r.field_m3_ha, r.river_m3_ha]
                                          for r in g.itertuples()}
                mean = season.groupby("crop")[["plant_m3_ha", "field_m3_ha", "river_m3_ha"]].mean()
                by_year[MEAN_KEY] = {crop: list(map(float, row)) for crop, row in mean.iterrows()}
                coef[key] = by_year
    scenarios_df = pd.concat(parts, ignore_index=True)

    areas = crop_areas_wide(tables["crop_areas"], crops)
    official = tables["water_withdrawal"]
    official_rows = [{"entity": r.entity, "param": r.param, "year": None if pd.isna(r.year) else int(r.year),
                      "measure": r.measure, "value": float(r.value), "unit": r.unit,
                      "source": r.source, "status": r.status} for r in official.itertuples()]

    # Сравнение: модель (площади и климат того же года) против лимита/плана того же года.
    check_rows = []
    comparable = official[(official["param"] == "water_withdrawal") &
                          official["measure"].isin(COMPARABLE_OFFICIAL)]
    for r in comparable.itertuples():
        y = int(r.year)
        if y not in areas.index or str(y) not in coef[scenario_key("base", "base", "base")]:
            continue
        for key, by_year in coef.items():
            tot = regional_totals(by_year[str(y)], areas.loc[y].to_dict())
            check_rows.append({"year": y, "official_measure": r.measure,
                               "official_label": COMPARABLE_OFFICIAL[r.measure],
                               "official_m3": float(r.value), "official_source": r.source,
                               "scenario": key, "model_river_m3": tot["river_m3"],
                               "ratio": tot["river_m3"] / float(r.value)})
    check = pd.DataFrame(check_rows)
    if check.empty:
        raise ValueError("Нет официальных величин, сравнимых с моделью по году")
    base_check = check[check["scenario"] == scenario_key("base", "base", "base")]
    comparison = {
        "rows": base_check.to_dict("records"),
        "ratio_all_scenarios": [float(check["ratio"].min()), float(check["ratio"].max())],
        "ratio_base": [float(base_check["ratio"].min()), float(base_check["ratio"].max())],
        "note": "Модель: площади и климат того же года; официально: лимит или план на вегетацию того же года. "
                "Частичный факт на дату внутри сезона не сравнивается.",
    }

    status_summary = summarize(tables)
    model = {
        "meta": {"generated": date.today().isoformat(), "units": "площадь — га; вода — м³ (1 мм на 1 га = 10 м³)",
                 "climate": "NASA POWER, точка 44.8° с. ш., 65.5° в. д. (S063, S088)",
                 "what": "Модельная потребность в воде по культурам: ETc (FAO-56) → осадки и КПД (слой 1)"},
        "crops": [{"id": c, "name": CROP_LABELS[c][0], "proxy": CROP_LABELS[c][1],
                   "flooded": c in set(rice_water["entity"])} for c in crops],
        "years": [str(y) for y in years],
        "mean_key": MEAN_KEY,
        "scenarios": {"eff_field": field_m, "eff_canal": canal_m, "rice_percolation": perc_m},
        "coef_m3_ha": coef,
        "areas_ha": {str(y): {c: float(v) for c, v in row.items()} for y, row in areas.iterrows()},
        "area_status": area_status(tables["crop_areas"], crops),
        "official_withdrawal": official_rows,
        "comparison": comparison,
        "data_status": status_summary.to_dict("records"),
        "warning_points": WARNING_POINTS,
        "limitations": LIMITATIONS,
        "income": {"available": False,
                   "reason": "Нет data/costs.csv; урожайности нет у пшеницы, прочих зерновых и кормовых, "
                             "цен нет у овощей и масличных (решение автора 2026-11-12: в модуле 4 только вода)."},
    }
    frames = {"etc_season": etc_season, "layer1_scenarios": scenarios_df, "regional_check": check}
    return model, frames


def write_outputs(model, frames, outputs_dir=OUTPUTS_DIR, web_data_dir=WEB_DATA_DIR):
    outputs_dir, web_data_dir = Path(outputs_dir), Path(web_data_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    web_data_dir.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(outputs_dir / f"{name}.csv", index=False, encoding="utf-8")
    text = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    (web_data_dir / "model.json").write_text(text, encoding="utf-8")
    (web_data_dir / "model.js").write_text(
        "// Сгенерировано src/export_web.py — не редактировать вручную.\n"
        f"window.CROPMIX_MODEL = {text};\n", encoding="utf-8")
    return web_data_dir / "model.json"
