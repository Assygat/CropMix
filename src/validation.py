"""Движок валидации (2026-11-17): сравнение «модель/вход ↔ независимое наблюдение» с явной типизацией величин.

Правила:
- Сравнивать можно только одинаковые величины (quantity). Разные величины (забор из реки ↔ испарение,
  лимит ↔ фактическая подача) — только как «контекст» (contextual=True), метрики точности не выдаются.
- Пропуски не превращаются в ноль: берутся только общие отсчёты (метрики модуля 8, src/backtest.py).
- R² выдаётся только при n ≥ 10; при n < 3 — только разность (никаких «статистических» выводов).
- Наборы данных, производные от одного источника, независимой проверкой не считаются (флаг independent).

Сейчас реально посчитано (данные уже в data/):
  T1, T2  — суточные Tmax, Tmin NASA POWER (вход модели) против станции GSOD 38062 Кызылорда (независимое
            наблюдение, n ≈ 5 700 дней) — проверка входа модели, не выхода;
  T3      — ET0 Hargreaves по температурам NASA против Hargreaves по станции: та же формула, разные данные —
            изолирует вклад температурного входа;
  T4      — ET0 Penman–Monteith (NASA, как в модели) против Hargreaves (станция): РАЗНЫЕ методы → контекст.
Выход модели (забор «из реки») независимым рядом не проверен: есть только n = 1 (модуль 8, docs/backtest.md).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src import etc
from src.backtest import bias_pct, mae, mape, rmse
from src.et0 import et0_from_climate, pivot_daily

NASA = etc.NASA_ENTITY
GSOD = "gsod_38062_kyzylorda"
SEASON_MONTHS = range(4, 11)
R2_MIN_N = 10


def metrics(sim, obs, quantity_sim, quantity_obs, contextual=False, ratio_scale=True):
    """Метрики сравнения двух рядов (индексы совпадают по смыслу: даты, годы...).

    ratio_scale=False (например, температура в °C): относительные метрики (bias %, MAPE) не выдаются —
    у шкалы нет абсолютного нуля, и проценты от неё бессмысленны.
    """
    if quantity_sim != quantity_obs and not contextual:
        raise ValueError(f"Разные величины: {quantity_sim!r} и {quantity_obs!r}. "
                         "Сравнение допустимо только как контекст (contextual=True), без метрик точности.")
    s, o = pd.Series(sim, dtype=float), pd.Series(obs, dtype=float)
    both = pd.concat([s, o], axis=1, keys=["s", "o"]).dropna()
    n = int(len(both))
    out = {"quantity_sim": quantity_sim, "quantity_obs": quantity_obs, "n": n, "contextual": bool(contextual)}
    if n == 0:
        raise ValueError("Нет общих отсчётов")
    resid = both["s"] - both["o"]
    out.update({"mean_sim": float(both["s"].mean()), "mean_obs": float(both["o"].mean()),
                "mean_diff": float(resid.mean())})
    if contextual:
        out["ratio_of_means"] = float(both["s"].mean() / both["o"].mean()) if both["o"].mean() else None
        return out
    if n < 3:
        return out
    out.update({"mae": mae(both["s"], both["o"]), "rmse": rmse(both["s"], both["o"]),
                "bias_pct": bias_pct(both["s"], both["o"]) if ratio_scale and both["o"].sum() else None,
                "mape_pct": mape(both["s"], both["o"]) if ratio_scale and (both["o"] > 0).all() else None,
                "resid_sd": float(resid.std()), "resid_p05": float(resid.quantile(0.05)),
                "resid_p95": float(resid.quantile(0.95))})
    if n >= R2_MIN_N:
        ss_res = float(((both["o"] - both["s"]) ** 2).sum())
        ss_tot = float(((both["o"] - both["o"].mean()) ** 2).sum())
        out["r2"] = 1 - ss_res / ss_tot if ss_tot else None   # коэффициент детерминации относительно 1:1
        out["pearson_r"] = float(np.corrcoef(both["s"], both["o"])[0, 1])
    return out


def bootstrap_bias_ci(sim, obs, n_boot=2000, block=30, seed=1):
    """95 % интервал средней разности блочным бутстрепом (блоки по block отсчётов — учёт автокорреляции)."""
    both = pd.concat([pd.Series(sim, dtype=float), pd.Series(obs, dtype=float)], axis=1).dropna()
    d = (both.iloc[:, 0] - both.iloc[:, 1]).to_numpy()
    if len(d) < 2 * block:
        return None, None
    rng = np.random.default_rng(seed)
    nb = len(d) // block
    blocks = d[: nb * block].reshape(nb, block)
    means = blocks[rng.integers(0, nb, size=(n_boot, nb))].mean(axis=(1, 2))
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def gsod_derived_flags(raw_dir=RAW_DIR, station="38062099999"):
    """Флаги GSOD: MAX/MIN_ATTRIBUTES = '*' — экстремум выведен из срочных наблюдений, а не из отчёта о max/min
    (документация NOAA GSOD). Такой Tmax обычно ниже истинного, Tmin — выше. Возвращает DataFrame по датам
    (max_derived, min_derived: bool) или None, если сырых файлов нет."""
    files = sorted(Path(raw_dir).glob(f"gsod_{station}_*.csv"))
    if not files:
        return None
    raw = pd.concat([pd.read_csv(f, dtype=str) for f in files], ignore_index=True)
    out = pd.DataFrame({"max_derived": raw["MAX_ATTRIBUTES"].str.strip() == "*",
                        "min_derived": raw["MIN_ATTRIBUTES"].str.strip() == "*"})
    out.index = pd.to_datetime(raw["DATE"])
    return out[~out.index.duplicated()]


def climate_input_validation(tables, raw_dir=RAW_DIR):
    """T1–T4: таблица метрик (одна строка — одно сравнение) и помесячная таблица остатков.

    T1e/T2e — то же, но только по дням, где станция сообщила max/min явно (без флага '*').
    Границы суток не совпадают: дни GSOD — по UTC, суточные файлы NASA POWER скачаны в местном солнечном
    времени (заголовок файла: «in LST», для 65.5° в. д. ≈ UTC+4.4 ч). Сдвиг около 4 ч влияет на суточные
    экстремумы, на месячные суммы T3 — мало.
    """
    clim, sites = tables["climate_daily"], tables["climate_sites"]
    nasa = pivot_daily(clim[clim["entity"] == NASA])
    st = pivot_daily(clim[clim["entity"] == GSOD])
    flags = gsod_derived_flags(raw_dir)
    rows, monthly = [], []
    for param in ("tmax", "tmin"):
        m = metrics(nasa[param], st[param], f"daily {param} (degC)", f"daily {param} (degC)", ratio_scale=False)
        lo, hi = bootstrap_bias_ci(nasa[param], st[param])
        check = "T1" if param == "tmax" else "T2"
        share = None
        if flags is not None:
            fl = flags["max_derived" if param == "tmax" else "min_derived"].reindex(st[param].dropna().index)
            share = float(fl.mean())
        rows.append({"check": check,
                     "description": f"NASA POWER daily {param} (model input) vs GSOD 38062 station {param}",
                     "independent": True, "unit": "degC", "bias_ci95_low": lo, "bias_ci95_high": hi,
                     "station_derived_share": share, **m})
        if flags is not None:
            fl = flags["max_derived" if param == "tmax" else "min_derived"]
            explicit = st[param][fl.reindex(st.index).eq(False)]
            me = metrics(nasa[param], explicit, f"daily {param} (degC)", f"daily {param} (degC)", ratio_scale=False)
            lo, hi = bootstrap_bias_ci(nasa[param], explicit)
            rows.append({"check": check + "e", "description": f"as {check}, station days with an explicitly reported "
                         f"{param} only (GSOD flag '*' excluded)", "independent": True, "unit": "degC",
                         "bias_ci95_low": lo, "bias_ci95_high": hi, "station_derived_share": 0.0, **me})
        d = (nasa[param] - st[param]).dropna()
        for mo, g in d.groupby(d.index.month):
            monthly.append({"variable": param, "month": int(mo), "n": int(len(g)), "mean_diff": float(g.mean()),
                            "sd_diff": float(g.std())})
    lat_n, el_n = etc.site_coords(sites, NASA)
    lat_g, el_g = etc.site_coords(sites, GSOD) if (sites["entity"] == GSOD).any() else (lat_n, el_n)
    pm = et0_from_climate(clim, NASA, lat_n, el_n, method="pm")
    hg_n = et0_from_climate(clim, NASA, lat_n, el_n, method="hargreaves")
    hg_s = et0_from_climate(clim, GSOD, lat_g, el_g, method="hargreaves")

    def season_month_sums(s):
        s = s[s.index.month.isin(SEASON_MONTHS)]
        g = s.groupby([s.index.year, s.index.month])
        sums, counts = g.sum(), g.size()
        full = counts == pd.Series([pd.Period(f"{y}-{m:02d}").days_in_month for y, m in counts.index],
                                   index=counts.index)
        return sums[full]   # только полные месяцы: неполный месяц занизил бы сумму

    hn, hs, pmm = season_month_sums(hg_n), season_month_sums(hg_s), season_month_sums(pm)
    m3 = metrics(hn, hs, "monthly ET0 Hargreaves (mm)", "monthly ET0 Hargreaves (mm)")
    rows.append({"check": "T3", "description": "Hargreaves ET0 from NASA temperatures vs from station temperatures "
                 "(same formula, different input data; complete Apr–Oct months)", "independent": True, "unit": "mm/month",
                 **m3})
    m4 = metrics(pmm, hs, "monthly ET0 Penman-Monteith (mm)", "monthly ET0 Hargreaves (mm)", contextual=True)
    rows.append({"check": "T4", "description": "Model ET0 (Penman–Monteith, NASA) vs Hargreaves ET0 (station): "
                 "different methods — context only, no accuracy metrics", "independent": True, "unit": "mm/month", **m4})
    return pd.DataFrame(rows), pd.DataFrame(monthly)


# Инвентаризация внешних наборов данных (что можно и что нельзя проверить). Не результаты — план и статус.
DATASETS = [
    {"dataset": "NOAA GSOD station 38062 Kyzylorda", "coverage": "point station, 3 km from the model grid point",
     "period": "2010–2025 (2025 incomplete)", "resolution": "daily", "variables": "Tmax, Tmin (precipitation mostly unreported)",
     "independent_of_model_inputs": "yes", "can_validate": "climate input (temperature) — T1–T3", "status": "integrated"},
    {"dataset": "CAWater-Info / BWO Syr Darya yearbooks", "coverage": "Syr Darya basin, Kyzylorda section",
     "period": "2020–2024 (+ 2025 partial)", "resolution": "annual / seasonal", "variables": "limits, withdrawals, river flow",
     "independent_of_model_inputs": "yes (not used to calibrate)", "can_validate": "river withdrawal — n = 1 per quantity "
     "(module 8, V1–V3)", "status": "integrated (backtest)"},
    {"dataset": "stat.gov.kz / taldau regional statistics", "coverage": "Kyzylorda Region", "period": "2010–2025",
     "resolution": "annual", "variables": "sown area, yield, production, prices, water use",
     "independent_of_model_inputs": "areas are model inputs (not independent); water-use tables would be independent",
     "can_validate": "annual regional water withdrawal if a consistent series is extracted", "status": "partly integrated"},
    {"dataset": "FAO WaPOR v3", "coverage": "Africa and the Near East (Level 1, 300 m)",
     "period": "2018–present", "resolution": "dekadal", "variables": "actual ET and interception (AETI)",
     "independent_of_model_inputs": "yes", "can_validate": "crop ET (not withdrawal)",
     "status": "not usable: Kyzylorda appears to be outside the WaPOR mapped extent (to be re-checked)"},
    {"dataset": "MODIS MOD16A2 / GLEAM", "coverage": "global, 500 m (MOD16) / 0.1° (GLEAM)",
     "period": "2000–present", "resolution": "8-day / daily", "variables": "actual evapotranspiration",
     "independent_of_model_inputs": "yes", "can_validate": "seasonal actual ET of irrigated land (consumptive use, not withdrawal)",
     "status": "framework ready (metrics()); data needs an Earthdata/registration download and an irrigated-area mask"},
    {"dataset": "ERA5-Land (Copernicus CDS)", "coverage": "global, 0.1°", "period": "1950–present", "resolution": "hourly",
     "variables": "temperature, humidity, wind, radiation, precipitation, potential evaporation",
     "independent_of_model_inputs": "partly (different reanalysis from NASA POWER, but not an observation)",
     "can_validate": "cross-check of NASA POWER inputs (reanalysis vs reanalysis — consistency, not validation)",
     "status": "not integrated: requires a CDS account and API key"},
    {"dataset": "FAO AQUASTAT / FAOSTAT", "coverage": "Kazakhstan (national)", "period": "multi-year", "resolution": "annual / 5-year",
     "variables": "agricultural water withdrawal, irrigated area, production", "independent_of_model_inputs": "yes",
     "can_validate": "national context only — not regional", "status": "context only"},
]


def dataset_inventory():
    return pd.DataFrame(DATASETS)
