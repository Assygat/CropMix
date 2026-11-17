"""Анализ неопределённости методом латинского гиперкуба (2026-11-17) — НЕ валидация.

Выборка входов по документированным или явно допущенным диапазонам (все распределения — равномерные,
потому что у диапазонов нет информации о форме; это допущение):
  ET0 × f_ET0, осадки × f_P               — data/uncertainty_ranges.csv (assumed);
  КПД полива, КПД каналов                 — уровни low/high из data/efficiency.csv (assumed; уровень
                                             pessimistic — сценарий, не граница, как в модуле 9);
  перколяция риса                         — low/high из data/rice_water.csv (assumed);
  Kc_end риса, пшеницы, овощей, прочих зерновых и Kc_mid масличных — границы табл. 12 FAO-56
                                             (data/sensitivity_ranges.csv), независимо по культурам.
Площади (реальные, 2025 г.) не варьируются.

Как считается (без второго движка): месячный баланс слоя 1 (layer1_losses.monthly_balance) берётся для
трёх прогонов ETc — Kc на нижней границе, база, верхняя граница (etc.crop_water_tables). ETc линейна
по табличному Kc, поэтому значение между прогонами — кусочно-линейная интерполяция (точна, кроме
порога Kc_end = 0.45 климатической поправки FAO-56 у прочих зерновых; ошибка оценивается тестом).
Далее те же формулы слоя 1: Pe (USDA SCS) по месячным осадкам × f_P, NIR = max(ETc·f_ET0 − Pe, 0)
по месяцам, рис: max(ETc + SAT + WL + PERC·дни − Pe, 0), «на поле» = NIR / КПД полива (не для риса),
«из реки» = / КПД каналов. Результат при базовых значениях совпадает с моделью (тест).
"""

import numpy as np
import pandas as pd
from scipy.stats import qmc, spearmanr

from src import etc, layer1_losses as l1
from src import layer3_optimizer as opt
from src.export_web import crop_areas_wide

BASE_AREA_YEAR = 2025


def _levels(df, entity_param):
    sub = df[df["param"] == entity_param]
    return dict(zip(sub["measure"], sub["value"].astype(float)))


def _months(tables, crops_df):
    _, daily = etc.crop_water_tables(crops_df, tables["climate_daily"], tables["climate_sites"])
    precip = l1.precip_series(tables["climate_daily"], etc.NASA_ENTITY)
    _, months = l1.layer1_tables(daily, precip, tables["efficiency"], tables["rice_water"])
    return months.sort_values(["crop", "year", "month"]).reset_index(drop=True)


def _with_kc(tables, side):
    crops = tables["crops_fao56"].copy()
    rng = tables["sensitivity_ranges"]
    for r in rng[rng["measure"] == side].itertuples():
        m = (crops["entity"] == r.entity) & (crops["param"] == r.param)
        if m.sum() != 1:
            raise ValueError(f"Нет параметра {r.entity}/{r.param} в crops_fao56")
        crops.loc[m, "value"] = float(r.value)
    return crops


class Sampler:
    """Готовит месячные таблицы один раз и быстро считает коэффициенты «из реки» для любой выборки."""

    def __init__(self, tables):
        self.t = tables
        self.crops = list(tables["crops_fao56"]["entity"].drop_duplicates())
        base = _months(tables, tables["crops_fao56"])
        low = _months(tables, _with_kc(tables, "low"))
        high = _months(tables, _with_kc(tables, "high"))
        for other in (low, high):
            if not (other[["crop", "year", "month"]].values == base[["crop", "year", "month"]].values).all():
                raise RuntimeError("Месячные таблицы прогонов Kc не совпадают по строкам")
        self.m = base
        self.etc_base, self.etc_low, self.etc_high = (base["etc_mm"].to_numpy(), low["etc_mm"].to_numpy(),
                                                      high["etc_mm"].to_numpy())
        per = pd.PeriodIndex(base["month"], freq="M")
        self.day_frac = base["days"].to_numpy() / per.days_in_month.to_numpy()
        self.p_month = base["p_month_mm"].to_numpy()
        self.days = base["days"].to_numpy()
        self.sat_wl = (base["sat_mm"] + base["wl_mm"]).to_numpy()
        self.is_rice = base["crop"].isin(set(tables["rice_water"]["entity"])).to_numpy()
        self.crop_idx = base["crop"].map({c: i for i, c in enumerate(self.crops)}).to_numpy()
        self.n_years = base.groupby("crop")["year"].nunique().to_dict()
        rng = tables["sensitivity_ranges"]
        self.kc_params = []   # (crop, param, low, base, high)
        crops_df = tables["crops_fao56"]
        for (ent, par), g in rng.groupby(["entity", "param"]):
            lv = dict(zip(g["measure"], g["value"].astype(float)))
            b = float(crops_df[(crops_df["entity"] == ent) & (crops_df["param"] == par)]["value"].iloc[0])
            self.kc_params.append((ent, par, lv["low"], b, lv["high"]))
        eff, rw, ur = tables["efficiency"], tables["rice_water"], tables["uncertainty_ranges"]
        f, c, pr = _levels(eff, "eff_field"), _levels(eff, "eff_canal"), _levels(rw, "rice_percolation")
        et0f, pf = _levels(ur, "et0_factor"), _levels(ur, "precip_factor")
        self.params = [("et0_factor", et0f["low"], 1.0, et0f["high"]),
                       ("precip_factor", pf["low"], 1.0, pf["high"]),
                       ("eff_field", f["low"], f["base"], f["high"]),
                       ("eff_canal", c["low"], c["base"], c["high"]),
                       ("rice_percolation", pr["low"], pr["base"], pr["high"])]
        self.params += [(f"{e}_{p}", lo, b, hi) for e, p, lo, b, hi in self.kc_params]

    def base_values(self):
        return {name: b for name, _, b, _ in self.params}

    def river_coefficients(self, values):
        """values: {параметр: массив длины N} → массив N × культуры (м³/га «из реки», среднее по годам)."""
        n = len(next(iter(values.values())))
        etc_mm = np.repeat(self.etc_base[:, None], n, axis=1)
        for e, p, lo, b, hi in self.kc_params:
            v = np.asarray(values[f"{e}_{p}"], dtype=float)
            rows = (self.m["crop"] == e).to_numpy()
            up = np.clip((v - b) / (hi - b), 0, None) if hi != b else np.zeros(n)
            dn = np.clip((b - v) / (b - lo), 0, None) if lo != b else np.zeros(n)
            etc_mm[rows] += (self.etc_high[rows, None] - self.etc_base[rows, None]) * up \
                + (self.etc_low[rows, None] - self.etc_base[rows, None]) * dn
        etc_mm = etc_mm * np.asarray(values["et0_factor"])[None, :]
        pe = l1.pe_usda_scs(self.p_month[:, None] * np.asarray(values["precip_factor"])[None, :]) \
            * self.day_frac[:, None]
        perc = np.asarray(values["rice_percolation"])[None, :] * self.days[:, None]
        need_rice = np.maximum(etc_mm + self.sat_wl[:, None] + perc - pe, 0.0)
        nir = np.maximum(etc_mm - pe, 0.0)
        field = np.where(self.is_rice[:, None], need_rice, nir / np.asarray(values["eff_field"])[None, :])
        river_mm = field / np.asarray(values["eff_canal"])[None, :]
        out = np.zeros((n, len(self.crops)))
        for i, c in enumerate(self.crops):
            rows = self.crop_idx == i
            out[:, i] = river_mm[rows].sum(axis=0) / self.n_years[c] * 10.0   # мм → м³/га (1 мм·га = 10 м³)
        return out

    def lhs(self, n, seed=20261117):
        s = qmc.LatinHypercube(d=len(self.params), seed=seed).random(n)
        return {name: lo + s[:, i] * (hi - lo) for i, (name, lo, _, hi) in enumerate(self.params)}


def run_uncertainty(tables, n=2000, seed=20261117, preset_name="moderate"):
    """Возвращает (samples, summary, ranking) — DataFrame выборки, квантилей и рангов Спирмена."""
    smp = Sampler(tables)
    vals = smp.lhs(n, seed)
    coefs = smp.river_coefficients(vals)
    areas = crop_areas_wide(tables["crop_areas"], smp.crops).loc[BASE_AREA_YEAR]
    a = areas[smp.crops].to_numpy(dtype=float)
    w = coefs @ a
    presets_df = tables["optimizer_presets"]
    preset = opt.load_presets(presets_df)[preset_name]
    food = opt.food_crops(presets_df, smp.crops)
    base = areas[smp.crops].to_dict()
    saving = np.empty(n)
    for i in range(n):
        r = opt.optimize(dict(zip(smp.crops, coefs[i])), base, preset, food)
        saving[i] = r.saving_pct if r.status == "optimal" else np.nan
    samples = pd.DataFrame(vals)
    samples["river_m3"] = w
    samples[f"saving_{preset_name}_pct"] = saving
    for i, c in enumerate(smp.crops):
        samples[f"river_m3_ha_{c}"] = coefs[:, i]
    qs = [0.05, 0.25, 0.5, 0.75, 0.95]
    summary = []
    for col, unit in (("river_m3", "m3"), (f"saving_{preset_name}_pct", "%")):
        v = samples[col].dropna()
        summary.append({"output": col, "unit": unit, "n": int(len(v)), "mean": float(v.mean()),
                        "std": float(v.std()), "min": float(v.min()), "max": float(v.max()),
                        **{f"p{int(q * 100)}": float(v.quantile(q)) for q in qs}})
    base_vals = smp.base_values()
    base_coef = smp.river_coefficients({k: np.array([v]) for k, v in base_vals.items()})[0]
    summary.append({"output": "river_m3_at_base_values", "unit": "m3", "n": 1, "mean": float(base_coef @ a)})
    ranking = []
    for name, lo, b, hi in smp.params:
        rw = spearmanr(samples[name], samples["river_m3"]).statistic
        rs = spearmanr(samples[name], samples[f"saving_{preset_name}_pct"], nan_policy="omit").statistic
        ranking.append({"parameter": name, "low": lo, "base": b, "high": hi, "distribution": "uniform",
                        "spearman_water": float(rw), "spearman_saving": float(rs)})
    ranking = pd.DataFrame(ranking)
    ranking["rank_water"] = ranking["spearman_water"].abs().rank(ascending=False, method="min").astype(int)
    ranking = ranking.sort_values("rank_water").reset_index(drop=True)
    return samples, pd.DataFrame(summary), ranking
