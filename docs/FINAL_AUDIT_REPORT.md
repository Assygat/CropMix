# CropMix Twin — final release audit (2026-11-17)

Scope: an independent re-check of the whole repository after the Decision Lab work. Nothing was committed, pushed or
published, and the pre-change backup (`CropMix_backup_20261117_2211`, a sibling folder of the project, outside the repository) is untouched.

**Release status: READY WITH LIMITATIONS.** Model and code are internally consistent and every claimed number was
reproduced. The model is not validated against observed withdrawals, and that limitation is stated on the site.

## 1. What was inspected

- `git status` / `git diff`: 13 tracked files modified, 39 untracked, 0 deleted. Every modification is accounted for:
  the five-page site from 2026-11-16 (still uncommitted), the Decision Lab, and the documentation. No source module,
  dataset or test of modules 1–9 was overwritten. `src/` changed only by 6 registry lines in `data_loader.py` and the
  Decision Lab call in `run_all.py`.
- All six public pages plus `calculator-legacy.html`: duplicate IDs, unclosed or stray tags, heading jumps, number of
  h1s, internal links, assets and `#fragment` targets (static script). All JavaScript files: `node --check`. All CSS
  files: brace balance and empty rules. Searches for TODO/FIXME, overclaiming words and outdated statements.
- Code of `src/portfolio.py`, `climate_stress.py`, `uncertainty.py`, `validation.py`, `decision_support.py` and
  `web/lp_solver.js`, `planner_core.js`, `planner.js`.

## 2. What was verified (independent recomputation)

| Check | Result |
|---|---|
| Baseline preserved | All 15 baseline CSVs in `outputs/` byte-identical to the pre-change backup; `simulator.json`, `geo.json` identical. `model.json` differs only in the data-status summary (3 new assumption files, +33 assumed values) and the generation date. |
| Browser LP vs HiGHS | 111 regenerated cases (3 same-land presets, 48 emergency, 60 random incl. land equality, food minimum, value objective): 87 optimal + 24 infeasible, 0 status mismatches, max relative objective difference 5.0e-16, max relative water difference 1.0e-9, max constraint violation of browser solutions 2.7e-16. |
| Boundary case | Protective rules need ≥ 4.718331 km³ (64.591 %). At that budget both solvers say optimal; 1 ppm below, both say infeasible. |
| Exhaustive planner sweep | 21 300 settings (20 climate cells × 5 rule sets × 71 water shares × 3 objectives): 11 322 optimal, 9 978 infeasible, 0 solver errors, max budget excess of a feasible plan = 0. |
| Degenerate LP | Beale's cycling example terminates at the HiGHS optimum (−1.25); new JS test. |
| Unbounded / infeasible | Reported as such (JS tests). Planner problems are always bounded (finite upper bounds). |
| Units | Water m³ (km³ = 1e9 m³), area ha, coefficients m³/ha from layer 1 (1 mm·ha = 10 m³); shadow price of water reported in ha per million m³ (= 10⁶ / marginal crop m³/ha, 10⁶/39 201 = 25.51). |
| Emergency outputs | Every feasible row satisfies water ≤ budget and area ≤ 2025 area; every infeasible row carries a numeric diagnosis. The page shows "No plan meets all the rules" and never displays areas for an infeasible case. |
| Stress tests | Scenario parameters in outputs equal `data/stress_scenarios.csv`; Tmax/Tmin shifted by exactly ΔT, RH unchanged; ET₀ normal 1 387.0 mm → +2 °C 1 463.3 mm (+5.50 %). Labels on the page: "observed climate", "observed year 2021", "experiment". |
| Latin hypercube | 2 000 samples: exactly one sample per 1/2 000 stratum in every one of 10 dimensions; all within bounds; identical on re-run with the same seed; max pairwise input correlation 0.055; P5/P50/P95 recomputed = outputs (6.175 / 7.333 / 8.750 km³). At base values the sampler reproduces the model to 1e-11 m³/ha. |
| Station data | GSOD in degC, no 9999.9 sentinels (1 raw sentinel day was already excluded), no Tmin > Tmax days; NASA 2010-01-01…2025-12-31, GSOD …2025-08-24; comparisons use common dates only. |
| Consistency of site and outputs | `tests/test_site.py` and `tests/test_decision_site.py` check the static numbers (see §5); the Decision Lab tables are rendered from `planner.json`, written from the same DataFrames as the CSVs. |
| Accessibility | Text contrast on the page background: ice-64 7.5:1, sky 9.9:1, status colours ≥ 10:1 (AA met, AAA for text); one h1 per page, no heading jumps; every planner control has a `<label for>`; keyboard tab order share → warming → rainfall → rules → objective → min → max → food → fallow, then the scrollable tables; arrow keys move the water slider; global `:focus-visible` outline. |

## 3. Defects found and fixed

| # | Severity | Defect | Fix |
|---|---|---|---|
| 1 | **High (scientific)** | The station check presented NASA Tmin as "+0.81 °C above the station" and inferred a "narrower diurnal range". 82 % of the GSOD minima (and 13 % of maxima) carry the flag "*" (derived from synoptic observations, typically too warm for minima). On explicitly reported days the Tmin sign reverses (−1.43 °C, n = 1 041, mostly winter). | `src/validation.py` reads the raw GSOD attributes (`gsod_derived_flags`) and adds the checks T1e/T2e; Evidence §09, `docs/decision_lab.md`, `docs/competition_package.md` and `docs/limitations.md` now state that Tmax is robust and Tmin is inconclusive, and note the unaligned day boundaries (GSOD days are UTC). Tests added. |
| 2 | Medium (reliability) | The browser planner trusted the simplex output without re-checking it. | `planner_core.js` re-checks every constraint and bound (1 ppm) and returns `numerical_error` instead of a plan; `planner.js` shows "No plan shown" for any non-optimal, non-infeasible status. The 21 300-setting sweep produced no such case. |
| 3 | Medium (consistency) | Methodology described the original optimiser as the only one. | One paragraph added that points to the Decision Lab formulation and states that it does not change the results. |
| 4 | Low (docs) | Outdated statements: "Monte Carlo is not done" (`plan.md`, `sensitivity.md`, `limitations.md`), "5 pages" (`limitations.md`, `website.md`). | Dated notes added; the historical text is kept. |
| 5 | Low (docs) | Test counts in the docs (317) were out of date after the new tests. | Updated to 320 (241 + 79). |

No duplicate IDs, broken links, unclosed tags, JS syntax errors, unbalanced CSS, TODOs or overclaiming words were found.

## 4. Exact test results (final run, 2026-11-17)

- `python -m src.run_all`: exit code 0 (about 1.5 min).
- `python -m pytest`: **241 passed**, 0 failed, 0 skipped (156 s). This includes `test_planner_crosscheck.py` and `test_sim_core.py::test_js_unit_tests_pass`, which runs the Node suite once more (Node present).
- `node --test "tests/js/*.test.js"`: **79 passed**, 0 failed, 0 skipped.
- Browser (headless Microsoft Edge 1440×900 and 390×844, CDP scripts outside the repository): all six pages load from
  `file://` with 0 console errors or exceptions, and no horizontal overflow at either width. On the Decision Lab, 70 %
  water gives 74.0 % of the area (= Python); 55 % protective gives the infeasibility message with the 0.701 km³ shortfall;
  flexible gives 62.0 %; +2 °C / −30 % rain gives 69.6 % (= Python); the value objective lists exactly the 5 crops without
  coefficients. The simulator renders 7.30 / 4.20 / 2.36 km³ (= outputs). Evidence §08–09 render, including T1e/T2e.
- Not done: Google Chrome is not installed (the DevTools MCP could not start), so Edge (Chromium) was used. No W3C
  validator was available; the HTML check used a parser script. Firefox and Safari were not tested. Simulator preset
  buttons were not clicked in this audit; their logic is covered by the 70 simulator JS tests.

## 5. Consistency report (number → source → where it appears)

| Number | Source | Appears in |
|---|---|---|
| 7.30 km³ (2025 mix, Cmean, E_base) | `sensitivity_results.csv`, `planner.json` | Methodology, Evidence, Decision Lab, Simulator (rendered from `model.js`), docs |
| 3.4 % moderate saving (1.5 / 5.6 % tight / flexible) | `optimizer_feasibility.csv` | Home, Methodology, Evidence, Decision Lab §04, docs (test_site) |
| 2.1–5.9 %, min 1.9 %; 6.17–8.75 km³ | `uncertainty_summary.csv` | Evidence §08, docs (test_decision_site) |
| 74.0 % / 70 %, +7 469 ha, 25.5 ha per million m³ | `emergency_summary.csv` | Decision Lab (rendered from JSON), docs |
| 64.6 % / 4.718 km³ infeasibility threshold | recomputed; `emergency_summary.csv` diagnosis | Decision Lab message, docs |
| ET₀ 1 387 → 1 463 mm, +5.6 %, 2021 +7.4 %, combined 69.6 % | `stress_scenarios.csv`, `stress_emergency.csv` | Decision Lab §02, docs |
| 1.074 / 0.827 / 0.534 km³, 7.66 %, 26.3 % | `decision_attribution*.csv` | Decision Lab §04 (rendered), docs |
| T1 −1.59, T1e −1.60, T2 +0.81, T2e −1.43 °C, n 5 699 / 4 984 / 1 041 | `validation_climate.csv` | Evidence §09 (test_decision_site), docs |
| 111 cross-check cases | `tests/test_planner_crosscheck.py` | docs |

Units are consistent: km³ for regional volumes, m³/ha per hectare, ha for areas, mm for ET₀, °C for temperature. No page
claims measured savings, economic benefit or deployment; every page that shows results says the model is not validated.

## 6. Remaining limitations (not fixable by an audit)

Not validated (one observation per check). Model withdrawal is above the official limits and reports. Efficiencies,
percolation, planning rules and stress parameters are assumptions. No deficit irrigation or yield response. The
region is modelled as one unit. Economic data are incomplete. Only temperature in the climate input has been checked,
and the Tmin check is inconclusive. The uncertainty ranges are assumed, not empirical confidence intervals; they omit
mid-season Kc of rice and fodder, sowing dates and model structure. Full list: `docs/limitations.md`.

## 7. Git status summary

Branch `main`, last commit `76210c6`. Modified (13): `CLAUDE.md`, `README.md`, `docs/limitations.md`, `docs/plan.md`,
`docs/sensitivity.md`, `docs/simulator.md`, `src/data_loader.py`, `src/run_all.py`, `web/data/model.js`,
`web/data/model.json`, `web/index.html`, `web/simulator.css`, `web/simulator.html`. Untracked (39): the site pages and
assets from 2026-11-16, the Decision Lab sources, data, tests and docs, and this audit's three documents. `outputs/` is
git-ignored and regenerated by `run_all`. Nothing was committed.

Files changed in this audit: `src/validation.py`, `web/evidence.html`, `web/methodology.html`, `web/planner_core.js`,
`web/planner.js`, `tests/test_validation.py`, `tests/test_decision_site.py`, `tests/js/lp_solver.test.js`,
`docs/limitations.md`, `docs/plan.md`, `docs/sensitivity.md`, `docs/website.md`, `docs/decision_lab.md`,
`docs/competition_package.md`; new: `docs/FINAL_AUDIT_REPORT.md`, `docs/COMPETITION_TECHNICAL_SUMMARY.md`,
`docs/VERIFIED_CLAIMS.md`. Regenerated: `outputs/*.csv`, `web/data/planner.js(.json)`, `web/data/model.js(.json)`.

## 8. Reproduce everything

```
cd CropMix
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m src.run_all
.venv\Scripts\python -m pytest
node --test "tests/js/*.test.js"
start web\index.html
```
