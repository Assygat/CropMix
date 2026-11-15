"""Модуль 9: анализ чувствительности W(A, C, E) — НЕ валидация и НЕ оценка точности модели.

Что делается (методика согласована с автором 2026-11-14, docs/sensitivity.md):
- OAT (one-at-a-time) по ДОКУМЕНТИРОВАННЫМ диапазонам: уровни E из data/ (КПД каналов, КПД полива,
  перколяция риса), границы Kc из табл. 12 FAO-56 (data/sensitivity_ranges.csv), ветер NASA × 0.84
  (диагностика модуля 2), климат года и структура посевов 2010–2025 (реальные данные). По ним — ранжирование.
- Нормированная чувствительность ±10 / ±20 % (план, модуль 9) для ETc (= ET0 × Kc; масштабирование ET0
  и Kc неразличимо) и осадков (→ Pe); граница Pe = 0. Это эластичности, а не диапазоны неопределённости.
- Сценарии: база; огибающие по E, климату; экспериментальные сочетания крайних значений (не вероятностные).

Всё считается существующими функциями модулей 2–3 (etc.crop_water_tables, layer1_losses.layer1_tables);
КПД меняются только через уровни E из data/, второго механизма изменения КПД нет. Исходные таблицы
не изменяются (модификации — на копиях в памяти). Уровни: plant = (ETc − Pe)⁺, field = на поле, river = из реки.
"""

import pandas as pd

from src import etc, layer1_losses as l1
from src.export_web import crop_areas_wide

LEVELS = ("plant", "field", "river")
BASE_E = ("base", "base", "base")
BASE_AREA_YEAR = 2025
WIND_FACTOR = 0.84          # ветер NASA ≈ на 16 % выше станционной оценки (docs/limitations.md, модуль 2)
NORMALIZED_STEPS = (0.10, 0.20)


class Engine:
    """Кэширующий расчёт W(A, C, E) с модификациями входов, только через функции модулей 2–3."""

    def __init__(self, tables, years=etc.YEARS):
        self.t = tables
        self.years = list(years)
        self.crops = list(tables["crops_fao56"]["entity"].drop_duplicates())
        self.areas = crop_areas_wide(tables["crop_areas"], self.crops)
        self.precip = l1.precip_series(tables["climate_daily"], etc.NASA_ENTITY)
        self._daily = {}
        self._season = {}

    def daily(self, key="base", crops=None, wind_factor=1.0):
        if key not in self._daily:
            _, d = etc.crop_water_tables(crops if crops is not None else self.t["crops_fao56"],
                                         self.t["climate_daily"], self.t["climate_sites"],
                                         years=self.years, wind_factor=wind_factor)
            self._daily[key] = d
        return self._daily[key]

    def season(self, e=BASE_E, daily_key="base", etc_scale=1.0, precip_scale=1.0):
        k = (e, daily_key, etc_scale, precip_scale)
        if k not in self._season:
            d = self.daily(daily_key)
            if etc_scale != 1.0:
                d = d.assign(etc_mm=d["etc_mm"] * etc_scale)
            p = self.precip * precip_scale
            s, _ = l1.layer1_tables(d, p, self.t["efficiency"], self.t["rice_water"], *e)
            self._season[k] = s
        return self._season[k]

    def w(self, season, areas=None, climate="mean"):
        """{plant, field, river} в м³: Σ площадь × м³/га (средний климат 2010–2025 или год)."""
        a = self.areas.loc[BASE_AREA_YEAR] if areas is None else areas
        s = season if climate == "mean" else season[season["year"] == int(climate)]
        per_ha = s.groupby("crop")[[f"{lv}_m3_ha" for lv in LEVELS]].mean()
        return {lv: float(sum(a[c] * per_ha.loc[c, f"{lv}_m3_ha"] for c in self.crops)) for lv in LEVELS}


def _e_levels(tables):
    eff, rw = tables["efficiency"], tables["rice_water"]

    def get(df, param):
        sub = df[df["param"] == param]
        return dict(zip(sub["measure"], sub["value"].astype(float)))
    return get(eff, "eff_field"), get(eff, "eff_canal"), get(rw, "rice_percolation")


def _row(param, group, kind, origin, status, p_base, p_low, p_high, w0, wl, wh, continuous, affects):
    r = {"parameter": param, "group": group, "kind": kind, "range_origin": origin, "data_status": status,
         "p_base": p_base, "p_low": p_low, "p_high": p_high, "levels_affected": affects}
    for lv in LEVELS:
        r[f"{lv}_base_m3"], r[f"{lv}_low_m3"], r[f"{lv}_high_m3"] = w0[lv], wl[lv], wh[lv]
    for side, w in (("low", wl), ("high", wh)):
        r[f"river_delta_{side}_km3"] = (w["river"] - w0["river"]) / 1e9
        r[f"river_delta_{side}_pct"] = 100 * (w["river"] - w0["river"]) / w0["river"]
        p = p_low if side == "low" else p_high
        ok = continuous and isinstance(p, (int, float)) and p != p_base and p_base
        r[f"elasticity_{side}"] = ((w["river"] - w0["river"]) / w0["river"]) / ((p - p_base) / p_base) if ok else None
    vals = [wl["river"], w0["river"], wh["river"]]
    r["river_swing_km3"] = (max(vals) - min(vals)) / 1e9
    r["river_swing_pct_of_base"] = 100 * (max(vals) - min(vals)) / w0["river"]
    return r


def run_sensitivity(tables):
    """Возвращает (results, ranking, scenarios) — три DataFrame."""
    eng = Engine(tables)
    f_lv, c_lv, p_lv = _e_levels(tables)
    w0 = eng.w(eng.season())
    rows = []

    # --- A. OAT по документированным диапазонам ---
    # Уровни E: каждый компонент отдельно, остальные — base
    for comp, levels, idx, affects in (
            ("eff_canal", c_lv, 1, "river only"),
            ("eff_field", f_lv, 0, "field and river (not rice; not plant)"),
            ("rice_percolation", p_lv, 2, "rice field and river (not plant)")):
        def e_with(m, idx=idx):
            e = list(BASE_E)
            e[idx] = m
            return tuple(e)
        rows.append(_row(comp, "E (efficiency scenario)", "documented_range",
                         "data/efficiency.csv or rice_water.csv levels low/high", "assumed",
                         levels["base"], levels["low"], levels["high"], w0,
                         eng.w(eng.season(e_with("low"))), eng.w(eng.season(e_with("high"))), True, affects))
        if "pessimistic" in levels:
            # Сценарный уровень (не граница согласованного диапазона): показывается, но не ранжируется,
            # чтобы один и тот же параметр не попадал в tornado дважды.
            rows.append(_row(comp + "_pessimistic", "E (efficiency scenario)", "scenario_level",
                             "data/efficiency.csv level pessimistic (scenario, not measured)", "assumed",
                             levels["base"], levels["pessimistic"], levels["base"], w0,
                             eng.w(eng.season(e_with("pessimistic"))), w0, True, affects))

    # Kc: все группы с диапазоном табл. 12 одновременно на нижней / верхней границе
    rng = tables["sensitivity_ranges"]
    kc_w = {}
    for side in ("low", "high"):
        crops_mod = tables["crops_fao56"].copy()
        for r in rng[rng["measure"] == side].itertuples():
            mask = (crops_mod["entity"] == r.entity) & (crops_mod["param"] == r.param)
            if mask.sum() != 1:
                raise ValueError(f"Нет параметра {r.entity}/{r.param} в crops_fao56")
            crops_mod.loc[mask, "value"] = float(r.value)
        eng.daily(f"kc_{side}", crops=crops_mod)
        kc_w[side] = eng.w(eng.season(daily_key=f"kc_{side}"))
    rows.append(_row("kc_fao56_table_range", "Kc", "documented_range",
                     "data/sensitivity_ranges.csv: FAO-56 Table 12 ranges (S065, S066, S069, S071, S072); "
                     "Kc_end of rice, wheat, vegetables, grain_other and Kc_mid of oilseeds together", "assumed",
                     "midpoint", "all low", "all high", w0, kc_w["low"], kc_w["high"], False, "all levels"))

    # Ветер NASA × 0.84 (ET0 и климатическая поправка Kc вместе), односторонне
    eng.daily("wind", wind_factor=WIND_FACTOR)
    rows.append(_row("nasa_wind_factor", "ET0 and Kc (wind)", "documented_range",
                     "docs/limitations.md: NASA wind ≈ 16 % above station estimate (module 2 diagnostic)", "assumed",
                     1.0, WIND_FACTOR, 1.0, w0, eng.w(eng.season(daily_key="wind")), w0, True, "all levels"))

    # Климат года (ET0, Kc-поправка, Pe меняются вместе), структура 2025, E_base
    base_season = eng.season()
    by_year = {y: eng.w(base_season, climate=y) for y in eng.years}
    ylo = min(by_year, key=lambda y: by_year[y]["river"])
    yhi = max(by_year, key=lambda y: by_year[y]["river"])
    rows.append(_row("climate_year", "C (climate)", "documented_range", "NASA POWER years 2010–2025 (S063)", "real",
                     "mean 2010–2025", f"C{ylo}", f"C{yhi}", w0, by_year[ylo], by_year[yhi], False, "all levels"))

    # Структура посевов лет 2010–2025, приведённая к общей площади 2025 г. (изолирует структуру)
    total25 = float(eng.areas.loc[BASE_AREA_YEAR].sum())
    by_struct = {}
    for y in eng.areas.index:
        a = eng.areas.loc[y] * (total25 / float(eng.areas.loc[y].sum()))
        by_struct[int(y)] = eng.w(base_season, areas=a)
    slo = min(by_struct, key=lambda y: by_struct[y]["river"])
    shi = max(by_struct, key=lambda y: by_struct[y]["river"])
    rows.append(_row("crop_structure_year", "A (crop structure)", "documented_range",
                     "crop_areas 2010–2025 (stat.gov.kz), each scaled to the 2025 total area", "real",
                     f"A{BASE_AREA_YEAR}", f"A{slo}", f"A{shi}", w0, by_struct[slo], by_struct[shi], False, "all levels"))

    # --- B. Нормированная чувствительность (не диапазоны неопределённости) ---
    for step in NORMALIZED_STEPS:
        rows.append(_row(f"etc_scale_{int(step * 100)}pct", "ETc = ET0 × Kc", "normalized",
                         f"plan.md module 9: ±{int(step * 100)} %; scaling ET0 or Kc is equivalent", "n/a",
                         1.0, 1 - step, 1 + step, w0, eng.w(eng.season(etc_scale=1 - step)),
                         eng.w(eng.season(etc_scale=1 + step)), True, "all levels"))
        rows.append(_row(f"precip_scale_{int(step * 100)}pct", "Precipitation -> Pe", "normalized",
                         f"plan.md module 9: ±{int(step * 100)} % of daily precipitation (Pe responds non-linearly)", "n/a",
                         1.0, 1 - step, 1 + step, w0, eng.w(eng.season(precip_scale=1 - step)),
                         eng.w(eng.season(precip_scale=1 + step)), True, "all levels"))
    rows.append(_row("pe_zero_bound", "Precipitation -> Pe", "bound", "bound: effective rainfall ignored (Pe = 0)", "n/a",
                     1.0, 0.0, 1.0, w0, eng.w(eng.season(precip_scale=0.0)), w0, False, "all levels"))
    results = pd.DataFrame(rows)

    # --- D. Ранжирование: только документированные диапазоны (нормированные — отдельно, не смешиваются) ---
    rk = results[results["kind"] == "documented_range"].copy()
    rk = rk.sort_values("river_swing_km3", ascending=False).reset_index(drop=True)
    rk.insert(0, "rank", range(1, len(rk) + 1))
    ranking = rk[["rank", "parameter", "group", "data_status", "p_low", "p_base", "p_high",
                  "river_low_m3", "river_base_m3", "river_high_m3", "river_swing_km3", "river_swing_pct_of_base"]]

    # --- C. Сценарии ---
    e_all = [(a, b, c) for a in f_lv for b in c_lv for c in p_lv]
    by_e = {e: eng.w(eng.season(e)) for e in e_all}
    elo = min(by_e, key=lambda e: by_e[e]["river"])
    ehi = max(by_e, key=lambda e: by_e[e]["river"])
    sc = [("baseline", "W(A2025, Cmean, E_base)", False, w0),
          ("efficiency_low_demand", f"W(A2025, Cmean, E={'/'.join(elo)}) — lowest of 36 E", False, by_e[elo]),
          ("efficiency_high_demand", f"W(A2025, Cmean, E={'/'.join(ehi)}) — highest of 36 E", False, by_e[ehi]),
          ("climate_low_demand", f"W(A2025, C{ylo}, E_base)", False, by_year[ylo]),
          ("climate_high_demand", f"W(A2025, C{yhi}, E_base)", False, by_year[yhi]),
          ("combined_low_demand_experimental", f"W(A2025, C{ylo}, E={'/'.join(elo)})", True,
           eng.w(eng.season(elo), climate=ylo)),
          ("combined_high_demand_experimental", f"W(A2025, C{yhi}, E={'/'.join(ehi)})", True,
           eng.w(eng.season(ehi), climate=yhi))]
    scenarios = pd.DataFrame([{"scenario": n, "definition": d, "experimental": x,
                               **{f"{lv}_m3": w[lv] for lv in LEVELS},
                               "river_vs_base_pct": 100 * (w["river"] - w0["river"]) / w0["river"],
                               "note": ("combination of independent extreme assumptions; not a probability statement"
                                        if x else "")} for n, d, x, w in sc])
    return results, ranking, scenarios
