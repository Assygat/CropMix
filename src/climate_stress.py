"""Климатические стресс-тесты (2026-11-17) — эксперименты чувствительности, НЕ климатические проекции.

Второго движка ET0 нет: изменённый климат подаётся в те же функции модулей 2–3
(etc.crop_water_tables → layer1_losses.layer1_tables), исходные таблицы не меняются (копии в памяти).

Изменения климата (delta change):
  Tmax, Tmin + ΔT (°C) каждого дня NASA POWER; относительная влажность rh_mean не меняется,
  поэтому фактическое давление пара растёт вместе с температурой (допущение, указано на сайте);
  радиация и ветер не меняются; осадки × k.
Сценарии — data/stress_scenarios.csv (все assumed). «Засушливый год» — наблюдённый год реанализа
2010–2025 с наибольшей модельной потребностью (исторический аналог), доля воды — допущение.
Доступная вода = доля × W(A2025, Cmean, E_base) — модельная потребность базовой структуры в НОРМАЛЬНОМ
климате, а не фактический лимит.
"""

import pandas as pd

from src import etc, layer1_losses as l1
from src.et0 import et0_from_climate
from src.export_web import crop_areas_wide

NASA = etc.NASA_ENTITY
SEASON_MONTHS = range(4, 11)        # апрель–октябрь: сезон для сводки ET0
STRESS_PARAMS = ("climate_delta_t", "precip_factor", "water_supply_share")
SCENARIO_ORDER = ("normal", "drought_year", "extreme_heat", "reduced_water", "reduced_precip", "combined")
SCENARIO_LABELS = {"normal": "Normal year", "drought_year": "Drought year (historical analogue)",
                   "extreme_heat": "Extreme heat (+ΔT)", "reduced_water": "Reduced water availability",
                   "reduced_precip": "Reduced precipitation", "combined": "Combined climate stress"}
SCENARIO_KIND = {"normal": "observed reanalysis mean 2010–2025",
                 "drought_year": "observed reanalysis year (historical analogue) + assumed supply cut",
                 "extreme_heat": "user-defined sensitivity experiment",
                 "reduced_water": "user-defined sensitivity experiment",
                 "reduced_precip": "user-defined sensitivity experiment",
                 "combined": "combination of user-defined experiments (not probabilistic)"}


def perturb_climate(climate, delta_t=0.0, precip_factor=1.0, entity=NASA):
    """Копия climate_daily с Tmax/Tmin + ΔT и осадками × k для одного источника."""
    if precip_factor < 0:
        raise ValueError("precip_factor должен быть ≥ 0")
    out = climate.copy()
    ent = out["entity"] == entity
    if delta_t:
        m = ent & out["param"].isin(["tmax", "tmin"])
        out.loc[m, "value"] = out.loc[m, "value"] + float(delta_t)
    if precip_factor != 1.0:
        m = ent & (out["param"] == "precip")
        out.loc[m, "value"] = out.loc[m, "value"] * float(precip_factor)
    return out


def season_et0(climate, sites, years=etc.YEARS, entity=NASA):
    """Средняя сумма ET0 за апрель–октябрь, мм (по годам years)."""
    lat, elev = etc.site_coords(sites, entity)
    s = et0_from_climate(climate, entity, lat, elev, method="pm")
    s = s[s.index.month.isin(SEASON_MONTHS) & s.index.year.isin(list(years))]
    return float(s.groupby(s.index.year).sum().mean())


def coefficients(tables, delta_t=0.0, precip_factor=1.0, years=etc.YEARS, e=("base", "base", "base")):
    """Пересчёт м³/га (plant, field, river) и ETc/Pe по культурам и годам при изменённом климате.

    Возвращает (season, et0_season_mm): season — таблица слоя 1 (культура × год).
    """
    clim = perturb_climate(tables["climate_daily"], delta_t, precip_factor)
    _, daily = etc.crop_water_tables(tables["crops_fao56"], clim, tables["climate_sites"], years=years)
    precip = l1.precip_series(clim, NASA)
    season, _ = l1.layer1_tables(daily, precip, tables["efficiency"], tables["rice_water"], *e)
    return season, season_et0(clim, tables["climate_sites"], years)


def per_ha(season, climate="mean"):
    s = season if climate == "mean" else season[season["year"] == int(climate)]
    return s.groupby("crop")[["etc_mm", "pe_mm", "plant_m3_ha", "field_m3_ha", "river_m3_ha"]].mean()


def load_scenarios(df):
    """{scenario: {climate_delta_t, precip_factor, water_supply_share}} из data/stress_scenarios.csv."""
    out = {}
    for r in df.itertuples():
        if r.param in STRESS_PARAMS:
            if r.param in out.get(r.entity, {}):
                raise ValueError(f"Повтор {r.entity}/{r.param}")
            out.setdefault(r.entity, {})[r.param] = float(r.value)
    for k, d in out.items():
        miss = set(STRESS_PARAMS) - set(d)
        if miss:
            raise ValueError(f"Сценарий {k}: нет {sorted(miss)}")
    return out


def drought_analogue_year(season, areas):
    """Наблюдённый год с наибольшей модельной потребностью «из реки» при структуре areas."""
    w = {int(y): sum(areas[c] * v for c, v in g.set_index("crop")["river_m3_ha"].items())
         for y, g in season.groupby("year")}
    return max(w, key=w.get), w


def run_stress(tables, base_year=2025, cache=None):
    """Таблица сценариев: ET0, ETc, Pe, вода трёх уровней, доступная вода, дефицит. Плюс коэффициенты по культурам.

    cache — словарь {(ΔT, k): (season, et0)} для повторного использования пересчётов.
    """
    cache = {} if cache is None else cache
    crops = list(tables["crops_fao56"]["entity"].drop_duplicates())
    areas = crop_areas_wide(tables["crop_areas"], crops).loc[base_year]

    def run(dt, pf):
        k = (float(dt), float(pf))
        if k not in cache:
            cache[k] = coefficients(tables, dt, pf)
        return cache[k]

    sc = load_scenarios(tables["stress_scenarios"])
    normal_season, normal_et0 = run(0.0, 1.0)
    normal_ph = per_ha(normal_season)
    w_normal = float(sum(areas[c] * normal_ph.loc[c, "river_m3_ha"] for c in crops))
    dyear, _ = drought_analogue_year(normal_season, areas)

    rows, coef_rows = [], []
    for name in [s for s in SCENARIO_ORDER if s in sc] + [s for s in sc if s not in SCENARIO_ORDER]:
        d = sc[name]
        season, et0_mean = run(d["climate_delta_t"], d["precip_factor"])
        climate = dyear if name == "drought_year" else "mean"
        ph = per_ha(season, climate)
        if climate != "mean":
            clim = perturb_climate(tables["climate_daily"], d["climate_delta_t"], d["precip_factor"])
            et0_mean = season_et0(clim, tables["climate_sites"], years=[dyear])
        tot = {lv: float(sum(areas[c] * ph.loc[c, f"{lv}_m3_ha"] for c in crops)) for lv in ("plant", "field", "river")}
        avail = d["water_supply_share"] * w_normal
        rows.append({"scenario": name, "label": SCENARIO_LABELS.get(name, name), "kind": SCENARIO_KIND.get(name, ""),
                     "climate": f"C{dyear}" if climate != "mean" else "Cmean 2010–2025",
                     "delta_t_c": d["climate_delta_t"], "precip_factor": d["precip_factor"],
                     "water_supply_share": d["water_supply_share"],
                     "et0_season_mm": et0_mean,
                     "etc_weighted_mm": float(sum(areas[c] * ph.loc[c, "etc_mm"] for c in crops) / areas.sum()),
                     "pe_weighted_mm": float(sum(areas[c] * ph.loc[c, "pe_mm"] for c in crops) / areas.sum()),
                     "plant_m3": tot["plant"], "field_m3": tot["field"], "river_m3": tot["river"],
                     "river_vs_normal_pct": 100 * (tot["river"] / w_normal - 1),
                     "available_m3": avail, "deficit_m3": max(tot["river"] - avail, 0.0),
                     "deficit_pct_of_demand": 100 * max(tot["river"] - avail, 0.0) / tot["river"]})
        for c in crops:
            coef_rows.append({"scenario": name, "crop": c, **{k: float(ph.loc[c, k]) for k in ph.columns}})
    return pd.DataFrame(rows), pd.DataFrame(coef_rows), {"w_normal_m3": w_normal, "drought_year": dyear,
                                                         "et0_normal_mm": normal_et0}


def climate_grid(tables, delta_ts=(0, 1, 2, 3, 4), precip_factors=(1.0, 0.85, 0.7, 0.5), cache=None):
    """Сетка ΔT × k для интерактивного планировщика: средние м³/га «из реки» по культурам и ET0 сезона."""
    cache = {} if cache is None else cache
    rows = []
    for dt in delta_ts:
        for pf in precip_factors:
            k = (float(dt), float(pf))
            if k not in cache:
                cache[k] = coefficients(tables, dt, pf)
            season, et0_mean = cache[k]
            ph = per_ha(season)
            for c in ph.index:
                rows.append({"delta_t_c": float(dt), "precip_factor": float(pf), "crop": c,
                             "river_m3_ha": float(ph.loc[c, "river_m3_ha"]), "etc_mm": float(ph.loc[c, "etc_mm"]),
                             "pe_mm": float(ph.loc[c, "pe_mm"]), "et0_season_mm": et0_mean})
    return pd.DataFrame(rows)
