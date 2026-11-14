"""Модуль 8: бэктест V1–V4 (протокол согласован автором 2026-11-13/14).

Модель НЕ калибруется: все наблюдения используются только для независимого сравнения.
Ряда фактического водозабора по годам нет, поэтому это не валидация, а набор проверок
с явно указанным статусом доказательности и числом независимых наблюдений (n):

- V1 partial-season benchmark: накопленный забор «из реки» W(A2025, C2025, E) с начала сезона
  до даты наблюдения (S060, 04.08.2025) против факта 3.03 км³; 36 сценариев E; n = 1.
- V2 intensity: модельный забор на гектар посевов (A2025 как структура-заместитель, климат 2026,
  до даты наблюдения S062) против «подано / орошаемая площадь» (S062). Знаменатели разные
  (посевная площадь модели против орошаемой площади наблюдения) — вывод о завышении не делается; n = 1.
- V3 order of magnitude: W(A_y, C_y, E) и модельные аналоги «потребления» против 3.5–4 км³/год
  (S058, «water consumption», годы не указаны); только ориентир; n = 1.
- V4 rice components: ETc риса, подача на поле и забор из реки на гектар — по отдельности против
  литературных диапазонов S083 (вторичный источник); для забора из реки наблюдения нет.

Методика модулей 1–6 не меняется: частичный сезон считается теми же функциями слоя 1
на суточных строках до даты отсечки. Для 2026 г. (климат до 30.09) Kc считается теми же
формулами, что kc.daily_kc, со средними по дням, на которые есть климат; неизвестный конец
сезона кормовых (первый осенний заморозок) берётся в «вилку» 2010–2025 гг.
"""

import numpy as np
import pandas as pd

from src import etc, kc as kcm, layer1_losses as l1
from src.et0 import actual_vapour_pressure_rh_mean, et0_from_climate
from src.export_web import crop_areas_wide

BASE_KEY = ("base", "base", "base")
EVIDENCE = {
    "V1": "partial-season benchmark (n = 1); not an annual validation",
    "V2": "per-hectare intensity comparison with different denominators (n = 1); not a validation of 2026 withdrawal",
    "V3": "order-of-magnitude reference (n = 1; years unspecified; consumption vs withdrawal unclear); not a quantitative validation",
    "V4": "component plausibility against a secondary literature range; not a validation",
}


# --- Метрики (для будущих рядов; при n = 1–2 в выводы не идут) ---

def _aligned(model, obs):
    m, o = pd.Series(model, dtype=float), pd.Series(obs, dtype=float)
    both = pd.concat([m, o], axis=1, keys=["m", "o"]).dropna()  # пропущенный год пропускается, а не становится нулём
    if both.empty:
        raise ValueError("Нет общих наблюдений")
    return both["m"], both["o"]


def bias_pct(model, obs):
    m, o = _aligned(model, obs)
    return 100.0 * (m.sum() - o.sum()) / o.sum()


def mae(model, obs):
    m, o = _aligned(model, obs)
    return float((m - o).abs().mean())


def rmse(model, obs):
    m, o = _aligned(model, obs)
    return float(np.sqrt(((m - o) ** 2).mean()))


def mape(model, obs):
    m, o = _aligned(model, obs)
    if (o == 0).any():
        raise ValueError("MAPE не определён при нулевых наблюдениях")
    return float(100.0 * ((m - o) / o).abs().mean())


# --- Наблюдения из data/ ---

def measure_date(measure):
    """'actual_to_2025-08-04' -> Timestamp('2025-08-04')."""
    if "_to_" not in measure:
        raise ValueError(f"В measure нет даты: {measure}")
    return pd.Timestamp(measure.split("_to_")[-1])


def _one(df, **eq):
    sub = df
    for k, v in eq.items():
        sub = sub[sub[k] == v]
    if len(sub) != 1:
        raise ValueError(f"Ожидалась одна строка {eq}, найдено {len(sub)}")
    return sub.iloc[0]


def _withdrawal_obs(w, prefix, param="water_withdrawal"):
    sub = w[(w["param"] == param) & w["measure"].astype(str).str.startswith(prefix)]
    if len(sub) != 1:
        raise ValueError(f"Ожидалось одно наблюдение {prefix}, найдено {len(sub)}")
    return sub.iloc[0]


# --- Расчёт забора на часть сезона ---

def scenario_list(efficiency, rice_water):
    f = sorted(set(efficiency[efficiency["param"] == "eff_field"]["measure"]))
    c = sorted(set(efficiency[efficiency["param"] == "eff_canal"]["measure"]))
    p = sorted(set(rice_water[rice_water["param"] == "rice_percolation"]["measure"]))
    return [(a, b, d) for a in f for b in c for d in p]


def withdrawal_by_scenario(daily, precip, efficiency, rice_water, areas, scenarios):
    """Забор «из реки», «на поле» и «у растения» (м³) по области для каждого сценария E на суточных строках daily."""
    rows = []
    for fm, cm, pm in scenarios:
        season, _ = l1.layer1_tables(daily, precip, efficiency, rice_water, fm, cm, pm)
        s = season.set_index("crop")
        rows.append({"eff_field": fm, "eff_canal": cm, "perc": pm,
                     "river_m3": float(sum(areas[k] * s.loc[k, "river_m3_ha"] for k in areas)),
                     "field_m3": float(sum(areas[k] * s.loc[k, "field_m3_ha"] for k in areas)),
                     "plant_m3": float(sum(areas[k] * s.loc[k, "plant_m3_ha"] for k in areas))})
    return pd.DataFrame(rows)


def _summary(df, col="river_m3"):
    base = df[(df.eff_field == BASE_KEY[0]) & (df.eff_canal == BASE_KEY[1]) & (df.perc == BASE_KEY[2])][col]
    return float(base.iloc[0]), float(df[col].min()), float(df[col].max())


def kc_to_cutoff(params, year, wide, cutoff, season_end=None):
    """Kc по дням сезона до даты cutoff: формулы kc.daily_kc, средние u2/RHmin — по дням, где есть климат.

    season_end — конец сезона для культур с сезоном по заморозкам, если осенний заморозок
    лежит за пределами данных. При полном климате и cutoff ≥ конца сезона результат равен kc.daily_kc.
    """
    if "plant_doy" in params:
        start, stages = kcm.season_stages(params, year)
    else:
        start, end = kcm.frost_season(wide["tmin"], year)
        if season_end is not None:
            end = pd.Timestamp(season_end)
        total = (end - start).days + 1
        l_ini, l_dev, l_late = (int(params[p]) for p in ("l_ini", "l_dev", "l_late"))
        l_mid = total - l_ini - l_dev - l_late
        if l_mid < 0:
            raise ValueError(f"{year}: сезон {total} дн. короче суммы стадий")
        stages = [l_ini, l_dev, l_mid, l_late]
    dates = pd.date_range(start, periods=sum(stages), freq="D")
    have = dates[dates.isin(wide.index)]
    clim = wide.loc[have]
    ea = actual_vapour_pressure_rh_mean(clim["tmax"], clim["tmin"], clim["rh_mean"])
    rh_min = pd.Series(kcm.rh_min_from_ea(ea, clim["tmax"]), index=have)
    u2 = clim["u2"]
    l_ini, l_dev, l_mid, l_late = stages
    mid = dates[l_ini + l_dev: l_ini + l_dev + l_mid].intersection(have)
    late = dates[l_ini + l_dev + l_mid:].intersection(have)
    h = params["max_height"]
    kc_mid = float(kcm.adjust_kc_mid(params["kc_mid"], u2[mid].mean(), rh_min[mid].mean(), h)) if l_mid > 0 and len(mid) else float(params["kc_mid"])
    kc_end = float(kcm.adjust_kc_end(params["kc_end"], u2[late].mean(), rh_min[late].mean(), h)) if l_late > 0 and len(late) else float(params["kc_end"])
    curve = pd.Series(kcm.kc_curve(params["kc_ini"], kc_mid, kc_end, *stages), index=dates, name="kc")
    info = {"start": dates[0], "end": dates[-1], "stages": stages,
            "mid_days_with_climate": f"{len(mid)}/{l_mid}", "late_days_with_climate": f"{len(late)}/{l_late}"}
    return curve[curve.index <= pd.Timestamp(cutoff)], info


def daily_to_cutoff(crops_df, climate, sites, year, cutoff, season_end=None, entity=etc.NASA_ENTITY):
    """Суточная таблица (crop, year, date, et0_mm, kc, etc_mm) до cutoff для года, где климат может быть неполным."""
    wide = etc.climate_wide(climate, entity)
    lat, elev = etc.site_coords(sites, entity)
    et0 = et0_from_climate(climate, entity, lat, elev, method="pm")
    parts, infos = [], {}
    for crop in crops_df["entity"].drop_duplicates():
        params = kcm.crop_params(crops_df, crop)
        k, info = kc_to_cutoff(params, year, wide, cutoff, season_end)
        infos[crop] = info
        day = etc.daily_etc(et0, k).reset_index(names="date")
        day.insert(0, "year", year); day.insert(0, "crop", crop)
        parts.append(day)
    return pd.concat(parts, ignore_index=True)[etc.DAILY_COLUMNS], infos


def frost_end_bracket(climate, years):
    """Самый ранний и самый поздний конец сезона по заморозкам (месяц-день) за годы years."""
    wide = etc.climate_wide(climate)
    ends = [kcm.frost_season(wide["tmin"], y)[1] for y in years]
    md = sorted((e.month, e.day) for e in ends)
    return md[0], md[-1]


# --- Проверки V1–V4 ---

def run_backtest(tables, frames, years=etc.YEARS):
    """Возвращает (results, v1_scenarios, v2_scenarios, v3_years)."""
    crops_df, climate, sites = tables["crops_fao56"], tables["climate_daily"], tables["climate_sites"]
    eff, rice_water, w = tables["efficiency"], tables["rice_water"], tables["water_withdrawal"]
    crops = list(crops_df["entity"].drop_duplicates())
    areas_all = crop_areas_wide(tables["crop_areas"], crops)
    scenarios = scenario_list(eff, rice_water)
    precip = l1.precip_series(climate, etc.NASA_ENTITY)
    results = []

    # V1 — partial season 2025
    obs1 = _withdrawal_obs(w, "actual_to_")
    cut1 = measure_date(obs1["measure"]); y1 = cut1.year
    _, daily1 = etc.crop_water_tables(crops_df, climate, sites, years=[y1])
    d1 = daily1[daily1["date"] <= cut1]
    a1 = areas_all.loc[y1].to_dict()
    v1 = withdrawal_by_scenario(d1, precip, eff, rice_water, a1, scenarios)
    d1_apr = d1[d1["date"] >= pd.Timestamp(y1, 4, 1)]
    v1_apr = withdrawal_by_scenario(d1_apr, precip, eff, rice_water, a1, [BASE_KEY])
    base1, lo1, hi1 = _summary(v1)
    o1 = float(obs1["value"])
    results.append({
        "check": "V1", "evidence_status": EVIDENCE["V1"], "n_observations": 1, "unit": "m3",
        "quantity": f"W(A{y1}, C{y1}, E) cumulative from crop season start to {cut1.date()}",
        "observed": o1, "observed_source": obs1["source"], "observed_status": obs1["status"],
        "observed_definition": "«общий водозабор в регионе ... на сельхознужды» на дату (сезон не завершён)",
        "model_base": base1, "model_min": lo1, "model_max": hi1,
        "ratio_base": base1 / o1, "rel_diff_base_pct": 100 * (base1 - o1) / o1,
        "observed_within_model_range": lo1 <= o1 <= hi1,
        "sensitivity": f"from {y1}-04-01 only (E_base): {v1_apr['river_m3'].iloc[0] / 1e9:.3f} km3",
        "coverage_check": ("territory: Kyzylorda Region in both (match); category: observation = all agricultural "
                           "withdrawal, model = irrigation of 8 crop groups incl. canal losses, no leaching/flushing, "
                           "livestock, fish ponds (partial match); interval: observation start date not stated, model starts "
                           "at each crop's season start (partial match); areas: model = all sown area of 8 groups"),
        "limitations": "n = 1; season incomplete; withdrawal measurement point and categories not documented; no calibration",
    })

    # V2 — per-hectare intensity, 2026 climate, structure of the last data year as proxy
    obs2 = _withdrawal_obs(w, "supplied_to_")
    area2 = _withdrawal_obs(w, "irrigated_to_", param="irrigated_area")
    cut2 = measure_date(obs2["measure"]); y2 = cut2.year
    clim26 = tables.get(f"climate_daily_{y2}")
    v2 = pd.DataFrame()
    if clim26 is None:
        results.append({"check": "V2", "evidence_status": "not possible: no climate data for the observation year",
                        "n_observations": 0, "limitations": f"climate_daily_{y2} missing"})
    else:
        proxy_year = int(areas_all.index.max())
        a2 = areas_all.loc[proxy_year].to_dict(); sown = sum(a2.values())
        (m0, d0), (m1, d1_) = frost_end_bracket(climate, years)
        precip26 = l1.precip_series(clim26, etc.NASA_ENTITY)
        parts = []
        for label, (mm, dd) in (("fodder_end_earliest", (m0, d0)), ("fodder_end_latest", (m1, d1_))):
            dd2, info = daily_to_cutoff(crops_df, clim26, sites, y2, cut2, season_end=pd.Timestamp(y2, mm, dd))
            df = withdrawal_by_scenario(dd2, precip26, eff, rice_water, a2, scenarios)
            df["fodder_season_end"] = f"{y2}-{mm:02d}-{dd:02d}"; df["bracket"] = label
            df["kc_coverage_rice"] = info["rice"]["late_days_with_climate"]
            parts.append(df)
        v2 = pd.concat(parts, ignore_index=True)
        v2["river_m3_per_sown_ha"] = v2["river_m3"] / sown
        b = v2[(v2.eff_field == "base") & (v2.eff_canal == "base") & (v2.perc == "base")]["river_m3_per_sown_ha"]
        o2 = float(obs2["value"]) / float(area2["value"])
        results.append({
            "check": "V2", "evidence_status": EVIDENCE["V2"], "n_observations": 1, "unit": "m3/ha",
            "quantity": (f"model: river withdrawal per SOWN ha, areas {proxy_year} (proxy structure, {sown:,.0f} ha), "
                         f"climate {y2} to {cut2.date()}; observation: supplied per IRRIGATED ha ({float(area2['value']):,.0f} ha)"),
            "observed": o2, "observed_source": obs2["source"], "observed_status": obs2["status"],
            "observed_definition": f"{float(obs2['value']) / 1e9:.2f} km3 supplied to {float(area2['value']):,.0f} ha irrigated land, as of the publication date",
            "model_base": float(b.mean()), "model_min": float(v2["river_m3_per_sown_ha"].min()),
            "model_max": float(v2["river_m3_per_sown_ha"].max()),
            "ratio_base": float(b.mean()) / o2, "rel_diff_base_pct": 100 * (float(b.mean()) - o2) / o2,
            "observed_within_model_range": float(v2["river_m3_per_sown_ha"].min()) <= o2 <= float(v2["river_m3_per_sown_ha"].max()),
            "sensitivity": (f"fodder season end bracket {y2}-{m0:02d}-{d0:02d} … {y2}-{m1:02d}-{d1_:02d}: base "
                            f"{b.min():,.0f} … {b.max():,.0f} m3/ha"),
            "coverage_check": ("denominators differ: model divides by all sown area of 8 groups, observation by irrigated land "
                               "(122 thousand ha); no 2026 crop areas; supply measurement point not documented"),
            "limitations": "n = 1; different denominators; 2026 structure unknown; cannot conclude over- or under-estimation",
        })

    # V3 — order of magnitude vs World Bank range
    lo3 = _one(w, measure="average_annual_low"); hi3 = _one(w, measure="average_annual_high")
    l1s = frames["layer1_scenarios"]; etc_s = frames["etc_season"]
    base_s = l1s[(l1s.eff_field_measure == "base") & (l1s.eff_canal_measure == "base") & (l1s.perc_measure == "base")]
    yrows = []
    for y in years:
        if y not in areas_all.index:
            continue
        a = areas_all.loc[y]
        s = base_s[base_s.year == y].set_index("crop"); e = etc_s[etc_s.year == y].set_index("crop")
        yrows.append({"year": y, "river_m3": float(sum(a[k] * s.loc[k, "river_m3_ha"] for k in crops)),
                      "plant_nir_m3": float(sum(a[k] * s.loc[k, "plant_m3_ha"] for k in crops)),
                      "etc_m3": float(sum(a[k] * e.loc[k, "etc_m3_ha"] for k in crops))})
    v3 = pd.DataFrame(yrows)
    pre = v3[v3.year <= 2018]  # документ подготовлен в декабре 2019 г.; годы оценки не указаны
    rng = (float(lo3["value"]), float(hi3["value"]))
    for col, name in (("river_m3", "river withdrawal W(A_y, C_y, E_base)"),
                      ("plant_nir_m3", "net irrigation requirement (ETc − Pe) × area"),
                      ("etc_m3", "crop evapotranspiration ETc × area")):
        results.append({
            "check": "V3", "evidence_status": EVIDENCE["V3"], "n_observations": 1, "unit": "m3/year",
            "quantity": f"{name}, mean of 2010–2018 (years before the source document)",
            "observed": None, "observed_low": rng[0], "observed_high": rng[1],
            "observed_source": lo3["source"], "observed_status": lo3["status"],
            "observed_definition": "«water consumption of agriculture sector ... around 3.5-4 km3 a year» (multi-year average, years not stated)",
            "model_base": float(pre[col].mean()), "model_min": float(pre[col].min()), "model_max": float(pre[col].max()),
            "observed_within_model_range": None,
            "model_mean_within_observed_range": rng[0] <= float(pre[col].mean()) <= rng[1],
            "coverage_check": ("«consumption» may mean water consumed (evaporated) or water withdrawn; both model analogues are "
                               "shown and neither is treated as directly comparable"),
            "limitations": "years unspecified; definition unclear; order-of-magnitude reference only",
        })

    # V4 — rice components per hectare, each against its own literature range
    rw = rice_water
    et_lo, et_hi = (float(_one(rw, param="rice_seasonal_et", measure=m)["value"]) for m in ("low", "high"))
    ex_lo, ex_hi = (float(_one(rw, param="rice_field_supply", measure=m)["value"]) for m in ("existing_low", "existing_high"))
    im_lo, im_hi = (float(_one(rw, param="rice_field_supply", measure=m)["value"]) for m in ("improved_low", "improved_high"))
    rice_etc = etc_s[etc_s.crop == "rice"]["etc_m3_ha"]
    rice_l1 = l1s[(l1s.crop == "rice") & (l1s.eff_field_measure == "base") & (l1s.eff_canal_measure == "base")]
    field_by_perc = rice_l1.groupby("perc_measure")["field_m3_ha"].mean()
    river_all = l1s[l1s.crop == "rice"]["river_m3_ha"]
    src83 = _one(rw, param="rice_seasonal_et", measure="low")["source"]
    common = {"check": "V4", "evidence_status": EVIDENCE["V4"], "unit": "m3/ha", "observed_status": "assumed (literature range)"}
    results.append({**common, "n_observations": 1,
                    "quantity": "rice ETc per ha, E-independent, mean (min–max) 2010–2025",
                    "observed_low": et_lo, "observed_high": et_hi, "observed_source": src83,
                    "observed_definition": "seasonal rice evapotranspiration, Central Asia and lower Volga (secondary citation)",
                    "model_base": float(rice_etc.mean()), "model_min": float(rice_etc.min()), "model_max": float(rice_etc.max()),
                    "ratio_base": float(rice_etc.mean()) / ((et_lo + et_hi) / 2),
                    "model_mean_within_observed_range": et_lo <= float(rice_etc.mean()) <= et_hi,
                    "limitations": "literature range, years and method unknown; model ETc is an upper estimate (see ETc section)"})
    results.append({**common, "n_observations": 1,
                    "quantity": "rice field supply per ha (no field efficiency for rice), mean 2010–2025; min/max over percolation 4/6/8 mm/day",
                    "observed_low": im_lo, "observed_high": ex_hi, "observed_source": src83,
                    "observed_definition": f"existing norm {ex_lo:,.0f}–{ex_hi:,.0f} m3/ha (and more); after improvements {im_lo:,.0f}–{im_hi:,.0f} m3/ha",
                    "model_base": float(field_by_perc["base"]), "model_min": float(field_by_perc.min()), "model_max": float(field_by_perc.max()),
                    "model_vs_existing": "below" if field_by_perc.max() < ex_lo else "overlaps",
                    "model_vs_improved": ("above" if field_by_perc.min() > im_hi else "below" if field_by_perc.max() < im_lo else "overlaps"),
                    "limitations": "model excludes drainage spills and leaching that the existing norm includes; secondary source"})
    results.append({**common, "n_observations": 0, "evidence_status": "not possible: no observation of rice river withdrawal per ha",
                    "quantity": "rice river withdrawal per ha, min–max over 36 scenarios and 2010–2025",
                    "model_base": float(rice_l1[rice_l1.perc_measure == "base"]["river_m3_ha"].mean()),
                    "model_min": float(river_all.min()), "model_max": float(river_all.max()),
                    "limitations": "no observed value exists in data/; not compared"})
    return pd.DataFrame(results), v1.assign(cutoff=str(cut1.date())), v2, v3
