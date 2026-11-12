"""Коэффициент культуры Kc по FAO-56 (Allen et al., 1998), глава 6.

- Кривая Kc по 4 стадиям (начальная, развитие, середина, поздняя) — ур. 66:
  Kc постоянен на начальной и средней стадиях и меняется линейно на стадиях
  развития и поздней.
- Климатическая поправка Kc_mid (ур. 62) и Kc_end (ур. 65) по ветру u2 и RHmin:
  Kc = Kc(Tab) + [0.04 (u2 − 2) − 0.004 (RHmin − 45)] (h / 3)^0.3.
  Kc_end поправляется только при Kc_end(Tab) ≥ 0.45 (FAO-56, текст к ур. 65).
  Пределы применимости: 1 ≤ u2 ≤ 6 м/с, 20 ≤ RHmin ≤ 80 %, 0.1 < h ≤ 10 м;
  u2 и RHmin вне пределов обрезаются до границ.
- RHmin = ea / e°(Tmax) × 100 (решение автора 2 в docs/plan.md, модуль 2);
  ea — по ур. 19 из средней RH (как в src/et0.py).
- Сезон культуры: по дате сева plant_doy (номер дня невисокосного года, в любой год —
  та же календарная дата) и сумме длин стадий. Если plant_doy в данных нет
  (кормовые = люцерна), сезон считается по заморозкам −4 °C (решение автора 3):
  от дня после последнего весеннего до дня перед первым осенним заморозком;
  l_mid = длина сезона − l_ini − l_dev − l_late.
- u2 и RHmin для поправки берутся средними за среднюю (для Kc_mid) и позднюю
  (для Kc_end) стадии каждого года (FAO-56: «averages for these periods»).

Все значения Kc и длины стадий берутся из data/crops_fao56.csv, здесь не зашиты.
"""

import numpy as np
import pandas as pd

from src.et0 import actual_vapour_pressure_rh_mean, sat_vapour_pressure

STAGE_PARAMS = ["l_ini", "l_dev", "l_mid", "l_late"]
KC_PARAMS = ["kc_ini", "kc_mid", "kc_end"]
FROST_THRESHOLD_C = -4.0  # FAO-56, табл. 11, сноска 4 (люцерна)
KC_END_ADJUST_MIN = 0.45  # ур. 65 применяется только при Kc_end(Tab) ≥ 0.45
FROST_SPLIT_MONTH = 7  # весенние заморозки — до июля, осенние — с июля
# plant_doy в data/crops_fao56.csv записан как номер дня невисокосного года
# (135 = 15 мая, 74 = 15 марта). Чтобы сев был в ту же календарную дату и в
# високосные годы, номер дня переводится в месяц и день по этому опорному году.
SOWING_REFERENCE_YEAR = 2001


def _whole_days(value, name):
    """Длина в днях: целое число ≥ 0; дробное значение — ошибка, а не тихое усечение."""
    v = float(value)
    if not v.is_integer():
        raise ValueError(f"{name} должно быть целым числом дней, получено {value}")
    return int(v)


def sowing_date(plant_doy, year):
    """Дата сева в году year: та же календарная дата (месяц, день), что plant_doy
    в невисокосном году. Пример: plant_doy = 135 -> 15 мая и в 2020, и в 2021 г."""
    doy = _whole_days(plant_doy, "plant_doy")
    if not 1 <= doy <= 365:
        raise ValueError(f"plant_doy должен быть от 1 до 365 (невисокосный год), получено {plant_doy}")
    ref = pd.Timestamp(SOWING_REFERENCE_YEAR, 1, 1) + pd.Timedelta(days=doy - 1)
    return pd.Timestamp(year, ref.month, ref.day)


# --- Кривая Kc (ур. 66) ---

def kc_curve(kc_ini, kc_mid, kc_end, l_ini, l_dev, l_mid, l_late):
    """Kc на каждый день сезона i = 1..L (массив длины L = сумма стадий), ур. 66.

    Стадия нулевой длины пропускается без деления на ноль: при l_dev = 0 Kc сразу
    переходит от Kc_ini к Kc_mid, при l_late = 0 сезон кончается на Kc_mid.
    """
    lengths = [_whole_days(v, n) for v, n in zip((l_ini, l_dev, l_mid, l_late), STAGE_PARAMS)]
    if any(n < 0 for n in lengths):
        raise ValueError(f"Длина стадии не может быть отрицательной: {lengths}")
    total = sum(lengths)
    if total == 0:
        raise ValueError("Длина сезона равна нулю")
    i = np.arange(1, total + 1, dtype=float)
    end_ini = lengths[0]
    end_dev = end_ini + lengths[1]
    end_mid = end_dev + lengths[2]
    kc = np.empty(total)
    kc[i <= end_ini] = kc_ini
    dev = (i > end_ini) & (i <= end_dev)
    kc[dev] = kc_ini + (i[dev] - end_ini) / lengths[1] * (kc_mid - kc_ini)
    kc[(i > end_dev) & (i <= end_mid)] = kc_mid
    late = i > end_mid
    kc[late] = kc_mid + (i[late] - end_mid) / lengths[3] * (kc_end - kc_mid)
    return kc


# --- Климатическая поправка (ур. 62, 65) ---

def rh_min_from_ea(ea, tmax):
    """RHmin, %, = ea / e°(Tmax) × 100 (решение автора 2)."""
    return np.asarray(ea, dtype=float) / sat_vapour_pressure(tmax) * 100.0


def climate_adjustment(u2, rh_min, height_m):
    """Добавка к Kc по ур. 62/65. При u2 = 2 м/с и RHmin = 45 % равна нулю."""
    if not 0.1 < height_m <= 10:
        raise ValueError(f"Ур. 62 применимо при 0.1 < h ≤ 10 м, получено h = {height_m}")
    u2 = np.clip(u2, 1.0, 6.0)
    rh_min = np.clip(rh_min, 20.0, 80.0)
    return (0.04 * (u2 - 2.0) - 0.004 * (rh_min - 45.0)) * (height_m / 3.0) ** 0.3


def adjust_kc_mid(kc_mid_tab, u2, rh_min, height_m):
    """Kc_mid с поправкой на климат (ур. 62)."""
    return kc_mid_tab + climate_adjustment(u2, rh_min, height_m)


def adjust_kc_end(kc_end_tab, u2, rh_min, height_m):
    """Kc_end с поправкой на климат (ур. 65); при Kc_end(Tab) < 0.45 без поправки."""
    if kc_end_tab < KC_END_ADJUST_MIN:
        return float(kc_end_tab)
    return kc_end_tab + climate_adjustment(u2, rh_min, height_m)


# --- Параметры культур из data/crops_fao56.csv ---

def crop_params(crops, entity):
    """Словарь param -> value для одной культуры из «длинной» таблицы crops_fao56."""
    sub = crops[crops["entity"] == entity]
    if sub.empty:
        raise ValueError(f"В данных культур нет {entity!r}")
    return dict(zip(sub["param"], sub["value"].astype(float)))


# --- Сезон ---

def frost_season(tmin, year, threshold=FROST_THRESHOLD_C):
    """Сезон по заморозкам: (первый день, последний день) года year.

    tmin — Series минимальной температуры (°C) с индексом-датой.
    Начало — день после последнего дня с Tmin ≤ threshold до июля;
    конец — день перед первым днём с Tmin ≤ threshold с июля.
    Нет весеннего заморозка — начало 1 января; нет осеннего — конец 31 декабря.
    """
    t = tmin[tmin.index.year == year]
    if t.empty:
        raise ValueError(f"Нет Tmin за {year} год")
    frost = t[t <= threshold]
    spring = frost[frost.index.month < FROST_SPLIT_MONTH]
    autumn = frost[frost.index.month >= FROST_SPLIT_MONTH]
    start = spring.index.max() + pd.Timedelta(days=1) if len(spring) else pd.Timestamp(year, 1, 1)
    end = autumn.index.min() - pd.Timedelta(days=1) if len(autumn) else pd.Timestamp(year, 12, 31)
    return start, end


def season_stages(params, year, tmin=None):
    """Дата сева и длины 4 стадий культуры в году year.

    Если в params есть plant_doy — календарь фиксирован (длины из данных).
    Иначе — сезон по заморозкам (нужен tmin), l_mid = остаток сезона.
    Возвращает (start: Timestamp, [l_ini, l_dev, l_mid, l_late]).
    """
    if "plant_doy" in params:
        missing = [p for p in STAGE_PARAMS if p not in params]
        if missing:
            raise ValueError(f"Нет длин стадий {missing}")
        start = sowing_date(params["plant_doy"], year)
        return start, [_whole_days(params[p], p) for p in STAGE_PARAMS]

    missing = [p for p in ["l_ini", "l_dev", "l_late"] if p not in params]
    if missing:
        raise ValueError(f"Нет ни plant_doy, ни длин стадий для сезона по заморозкам: {missing}")
    if tmin is None:
        raise ValueError("Для сезона по заморозкам нужна Tmin")
    start, end = frost_season(tmin, year)
    total = (end - start).days + 1
    l_ini, l_dev, l_late = (_whole_days(params[p], p) for p in ("l_ini", "l_dev", "l_late"))
    l_mid = total - l_ini - l_dev - l_late
    if l_mid < 0:
        raise ValueError(f"{year}: сезон {total} дн. короче суммы стадий {l_ini + l_dev + l_late} дн.")
    return start, [l_ini, l_dev, l_mid, l_late]


# --- Kc сезона с поправкой на климат ---

def daily_kc(params, year, climate_wide):
    """Kc по дням сезона культуры в году year с климатической поправкой.

    climate_wide — DataFrame с индексом-датой и колонками tmax, tmin, rh_mean, u2
    (суточные данные NASA POWER). Возвращает (Series Kc по датам, dict с деталями:
    даты, длины стадий, табличные и поправленные Kc_mid/Kc_end, средние u2 и RHmin).
    """
    start, stages = season_stages(params, year, climate_wide["tmin"])
    dates = pd.date_range(start, periods=sum(stages), freq="D")
    missing_days = dates.difference(climate_wide.index)
    if len(missing_days):
        raise ValueError(f"{year}: нет климата за {len(missing_days)} дн. сезона")
    clim = climate_wide.loc[dates]
    ea = actual_vapour_pressure_rh_mean(clim["tmax"], clim["tmin"], clim["rh_mean"])
    rh_min = pd.Series(rh_min_from_ea(ea, clim["tmax"]), index=dates)
    u2 = clim["u2"]

    l_ini, l_dev, l_mid, l_late = stages
    mid = dates[l_ini + l_dev: l_ini + l_dev + l_mid]
    late = dates[l_ini + l_dev + l_mid:]
    h = params["max_height"]
    info = {"start": dates[0], "end": dates[-1], "stages": stages,
            "kc_ini": params["kc_ini"], "kc_mid_tab": params["kc_mid"], "kc_end_tab": params["kc_end"]}

    if l_mid > 0:
        info["u2_mid"], info["rh_min_mid"] = float(u2[mid].mean()), float(rh_min[mid].mean())
        kc_mid = float(adjust_kc_mid(params["kc_mid"], info["u2_mid"], info["rh_min_mid"], h))
    else:
        kc_mid = float(params["kc_mid"])
    if l_late > 0:
        info["u2_late"], info["rh_min_late"] = float(u2[late].mean()), float(rh_min[late].mean())
        kc_end = adjust_kc_end(params["kc_end"], info["u2_late"], info["rh_min_late"], h)
    else:
        kc_end = float(params["kc_end"])
    info["kc_mid"], info["kc_end"] = kc_mid, float(kc_end)

    kc = kc_curve(params["kc_ini"], kc_mid, kc_end, *stages)
    return pd.Series(kc, index=dates, name="kc"), info
