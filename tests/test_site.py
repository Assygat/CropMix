"""Публичный сайт web/ (5 страниц): структура HTML, общая навигация, ссылки, язык, и числа на страницах = outputs/.

Числа на Home / Methodology / Evidence / About написаны в HTML статично (outputs/ не хранится в Git и не публикуется),
поэтому этот тест пересчитывает их из outputs/ и проверяет, что на страницах стоят именно эти значения. Без outputs/
числовые тесты пропускаются с подсказкой (как в tests/test_sim_core.py). Браузерные проверки (вёрстка, интерактив)
выполняются отдельно в headless-браузере; здесь — только то, что проверяется без браузера.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PAGES = ["index.html", "simulator.html", "planner.html", "methodology.html", "evidence.html", "about.html"]
NAV = [("index.html", "Home"), ("simulator.html", "Simulator"), ("planner.html", "Decision Lab"), ("methodology.html", "Methodology"),
       ("evidence.html", "Data & Evidence"), ("about.html", "About")]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
OLD_CALC_IDS = {"climate-year", "area-year", "eff-field", "eff-canal", "rice-perc", "t-plant", "t-field", "t-river",
                "sliders", "chart", "chart-fallback", "income", "limitations", "data-banner"}


class Page(HTMLParser):
    """Минимальный разбор: счётчики тегов, баланс вложенности, id, ссылки, навигация, видимый текст."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.counts, self.ids = [], [], {}, []
        self.decls, self.hrefs, self.srcs, self.sheets, self.text = [], [], [], [], []
        self.nav, self.lang, self.meta = [], None, {}
        self._in_nav_links = False
        self._a = None

    def handle_decl(self, d):
        self.decls.append(d)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content", "")
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])
            if self._in_nav_links:
                self._a = [a["href"], "", a.get("aria-current")]
        if tag == "script" and a.get("src"):
            self.srcs.append(a["src"])
        if tag == "link" and a.get("rel") == "stylesheet":
            self.sheets.append(a["href"])
        if tag == "ul" and a.get("id") == "nav-links":
            self._in_nav_links = True
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag == "a" and self._a is not None:
            self.nav.append(tuple(self._a))
            self._a = None
        if tag == "ul" and self._in_nav_links:
            self._in_nav_links = False
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"line {self.getpos()[0]}: </{tag}>, open <{self.stack[-1] if self.stack else None}>")
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.stack.pop()

    def handle_data(self, data):
        if self._a is not None:
            self._a[1] += data
        if "script" not in self.stack and "style" not in self.stack:
            self.text.append(data)


def parse(name):
    src = (WEB / name).read_text(encoding="utf-8")
    p = Page()
    p.feed(src)
    p.close()
    return src, p


def visible_text(name):
    """Видимый текст страницы с нормализованными пробелами (NBSP и узкий NBSP -> пробел)."""
    _, p = parse(name)
    return re.sub(r"[\s  ]+", " ", " ".join(p.text))


def require_outputs(*names):
    paths = [ROOT / "outputs" / n for n in names]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        pytest.skip(f"Нет outputs/{', outputs/'.join(missing)}: outputs/ не хранится в Git — "
                    "сначала выполните python -m src.run_all")
    return paths[0] if len(paths) == 1 else paths


# ------------------------------------------------------------------ структура


@pytest.mark.parametrize("name", PAGES)
def test_document_structure(name):
    src, p = parse(name)
    assert src.lstrip().lower().startswith("<!doctype html>") and len(p.decls) == 1
    for tag in ("html", "head", "body", "main", "title", "h1"):
        assert p.counts.get(tag) == 1, (tag, p.counts.get(tag))
    assert p.lang == "en"
    assert not p.errors and not p.stack, (p.errors[:5], p.stack)
    dup = sorted({i for i in p.ids if p.ids.count(i) > 1})
    assert not dup, dup
    assert len(p.meta.get("description", "")) > 60
    assert "CropMix Twin" in re.search(r"<title>(.*?)</title>", src, re.S).group(1)


@pytest.mark.parametrize("name", PAGES)
def test_shared_navigation_and_footer(name):
    src, p = parse(name)
    assert [(h, t.strip()) for h, t, _ in p.nav] == NAV
    assert [h for h, _, cur in p.nav if cur == "page"] == [name]
    assert 'class="site-footer"' in src and "site.js" in p.srcs and p.sheets[1] == "site.css"


@pytest.mark.parametrize("name", PAGES)
def test_public_pages_are_english(name):
    # кириллицы нет ни в видимом тексте, ни в разметке, ни в атрибутах страницы (данные в data/*.js не входят)
    src, _ = parse(name)
    cyr = [ln for ln in src.splitlines() if re.search("[Ѐ-ӿ]", ln)]
    assert not cyr, cyr[:3]


@pytest.mark.parametrize("name", PAGES)
def test_links_and_assets_resolve(name):
    _, p = parse(name)
    for ref in p.hrefs + p.srcs + p.sheets:
        if re.match(r"^(https?:|mailto:)", ref):
            continue
        file, _, frag = ref.partition("#")
        target = WEB / file if file else WEB / name
        assert target.is_file(), ref
        if frag:
            assert f'id="{frag}"' in target.read_text(encoding="utf-8"), ref
    # внешние ресурсы страницы (не ссылки для перехода) — только шрифты Google
    external = [r for r in p.srcs + p.sheets if r.startswith("http")]
    assert all(r.startswith("https://fonts.googleapis.com/") for r in external), external


def test_home_has_no_calculator_and_legacy_page_is_unlinked():
    _, p = parse("index.html")
    assert not OLD_CALC_IDS & set(p.ids)
    assert not any(t in p.counts for t in ("input", "select", "textarea", "table"))
    assert p.srcs == ["landscape.js", "site.js"]
    for name in PAGES:
        assert "calculator-legacy" not in (WEB / name).read_text(encoding="utf-8"), name
    # старая страница сохранена и по-прежнему ссылается на свои скрипты
    legacy = (WEB / "calculator-legacy.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex"' in legacy and "app.js" in legacy and "model_calc.js" in legacy


def test_simulator_keeps_its_scripts_in_order():
    # интеграция в общий дизайн не меняет набор и порядок скриптов симулятора
    _, p = parse("simulator.html")
    assert p.srcs == ["data/geo.js", "data/model.js", "data/simulator.js", "model_calc.js", "sim_core.js", "sim_state.js",
                      "sim_conditions.js", "sim_compare.js", "sim_structure.js", "sim_editor.js", "sim_map.js",
                      "sim_mosaic.js", "sim_mosaic_view.js", "simulator.js", "site.js"]
    assert p.sheets[1:] == ["site.css", "simulator.css"]


def test_data_views_use_existing_calculation_only():
    # data_views.js не содержит формул модели: только CropMixCalc (Σ площадь × коэффициент) и CropMixMap
    js = (WEB / "data_views.js").read_text(encoding="utf-8")
    assert "Calc.compute(" in js and "Calc.cropRows(" in js
    for formula_hint in ("0.408", "900", "penman", "linprog", "et0"):
        assert formula_hint not in js.lower(), formula_hint


# ------------------------------------------------------------------ числа на страницах = outputs/


def pct(x):
    return f"{x:.1f}".replace("-", "−")


def km3(m3):
    return f"{m3 / 1e9:.2f}"


def test_optimizer_numbers_match_outputs():
    feas = pd.read_csv(require_outputs("optimizer_feasibility.csv")).drop_duplicates("preset").set_index("preset")
    assert km3(feas["base_m3"].iloc[0]) == "7.30"
    for page in ("methodology.html", "evidence.html"):
        text = visible_text(page)
        for p in ("tight", "moderate", "flexible"):
            assert km3(feas.loc[p, "min_achievable_m3"]) in text, (page, p)
            assert pct(100 * (1 - feas.loc[p, "min_achievable_m3"] / feas.loc[p, "base_m3"])) + " %" in text, (page, p)
    home = visible_text("index.html")
    for p in ("tight", "moderate", "flexible"):
        assert pct(feas.loc[p, "saving_pct_max"]) + " %" in home, p


def test_saving_ranges_over_612_conditions_match_outputs():
    l1 = pd.read_csv(require_outputs("layer1_scenarios.csv"))
    sim = json.loads((WEB / "data" / "simulator.json").read_text(encoding="utf-8"))
    l1["E"] = l1["eff_field_measure"] + "|" + l1["eff_canal_measure"] + "|" + l1["perc_measure"]
    coef = pd.concat([l1.assign(C=l1["year"].astype(str))[["E", "C", "crop", "river_m3_ha"]],
                      l1.groupby(["E", "crop"])["river_m3_ha"].mean().reset_index().assign(C="mean")])
    sets = {"baseline": sim["baseline"]["areas_ha"],
            **{p: sim["optimized"]["presets"][p]["areas_ha"] for p in sim["optimized"]["presets_order"]}}
    rows = []
    for _, g in coef.groupby(["E", "C"]):
        k = g.set_index("crop")["river_m3_ha"]
        rows.append({n: sum(a[c] * k[c] for c in a) for n, a in sets.items()})
    w = pd.DataFrame(rows)
    assert len(w) == 612
    pages = {p: visible_text(p) for p in ("index.html", "methodology.html", "evidence.html")}
    for p in ("tight", "moderate", "flexible"):
        s = 100 * (w["baseline"] - w[p]) / w["baseline"]
        label = f"{pct(s.min())} to {pct(s.max())} %"
        for name, text in pages.items():
            assert label in text, (name, p, label)


def test_official_comparison_matches_outputs():
    rc = pd.read_csv(require_outputs("regional_check.csv"))
    base = rc[rc["scenario"] == "base|base|base"].set_index("year")
    ev = visible_text("evidence.html")
    for y in (2024, 2025):
        assert km3(base.loc[y, "model_river_m3"]) in ev and f"×{base.loc[y, 'ratio']:.2f}" in ev, y
    assert f"{rc['ratio'].min():.2f} to {rc['ratio'].max():.2f}" in ev
    home = visible_text("index.html")
    assert km3(base.loc[2024, "model_river_m3"]) in home and f"×{base.loc[2024, 'ratio']:.2f}" in home


def test_sensitivity_numbers_match_outputs():
    rk = pd.read_csv(require_outputs("sensitivity_ranking.csv")).sort_values("rank")
    src = (WEB / "evidence.html").read_text(encoding="utf-8")
    swings = re.findall(r'<span class="hbar-val">([\d.]+)</span>', src)
    assert swings == [f"{v:.2f}" for v in rk["river_swing_km3"]]
    ends = re.findall(r'<span class="hbar-ends"><span>([\d.]+)</span><span>([\d.]+)</span>', src)
    expect = [tuple(sorted((km3(r.river_low_m3), km3(r.river_high_m3)), key=float)) for r in rk.itertuples()]
    assert ends == expect
    # положение полос на оси 6.2–8.6 км³ соответствует значениям
    bars = re.findall(r'class="hbar" style="--a:([\d.]+)%;--b:([\d.]+)%', src)
    assert len(bars) == len(ends)
    for (lo, hi), (a, b) in zip(ends, bars):
        assert abs(float(a) - (float(lo) - 6.2) / 2.4 * 100) < 0.6
        assert abs(float(b) - (float(hi) - 6.2) / 2.4 * 100) < 0.6


def test_etc_and_water_year_tables_match_outputs():
    etc = pd.read_csv(require_outputs("etc_season.csv")).groupby("crop").mean(numeric_only=True)
    names = {c["id"]: c["name"] for c in json.loads((WEB / "data" / "simulator.json").read_text(encoding="utf-8"))["crops"]}
    text = visible_text("methodology.html")
    for crop, r in etc.iterrows():
        # вся строка таблицы: культура, дни сезона, ETc мм, ETc м³/га (число встречается и в тексте, поэтому строкой)
        row = f"{names[crop]} {r['days']:.0f} {r['etc_mm']:,.0f} {r['etc_m3_ha']:,.0f}".replace(",", " ")
        assert row in text, row
    wy = pd.read_csv(require_outputs("water_years.csv"))
    for r in wy.itertuples():
        assert f"{r.year} {r.runoff_m3 / 1e9:.2f} {r.water_class}" in text, r.year


def test_area_experiments_match_outputs():
    ex = pd.read_csv(require_outputs("optimizer_area_experiments.csv"))
    text = visible_text("evidence.html")
    for p in ("tight", "moderate", "flexible"):
        cells = [pct(r.saving_total_pct) + " %" if r.feasible else "no solution"
                 for r in ex[ex["preset"] == p].sort_values("area_reduction").itertuples()]
        assert f"{p.capitalize()} " + " ".join(cells) in text, (p, cells)


def test_optimised_areas_match_simulator_export():
    sim = json.loads((WEB / "data" / "simulator.json").read_text(encoding="utf-8"))
    text = visible_text("evidence.html")
    for c in sim["crops"]:
        cid = c["id"]
        vals = [sim["baseline"]["areas_ha"][cid]] + [sim["optimized"]["presets"][p]["areas_ha"][cid]
                                                      for p in ("tight", "moderate", "flexible")]
        row = c["name"] + " " + " ".join(f"{v:,.0f}".replace(",", " ") for v in vals)
        assert row in text, row
