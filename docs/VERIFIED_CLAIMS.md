# CropMix Twin — verified claims (final audit, 2026-11-17)

Each claim was re-checked during the final audit against generated files, the code or an independent recomputation.
Classification: **verified** (reproduced exactly), **partially verified** (true with a stated restriction),
**unsupported** (must not be used). "Safe wording" is the wording recommended for the submission.

| # | Claim | Evidence (exact) | Status | Safe wording |
|---|---|---|---|---|
| 1 | The 2025 crop mix needs 7.30 km³ of river withdrawal in an average year | `outputs/sensitivity_results.csv` river_base_m3 = 7.3049e9; `web/data/planner.json` base_water_m3; recomputed independently | verified (model output) | "The model estimates 7.30 km³ (base efficiencies, 2010–2025 mean climate). This is a model estimate, higher than the official limits and reports (see Data & Evidence)." |
| 2 | Same-land optimisation saves 3.4 % (moderate) | `outputs/optimizer_feasibility.csv` saving_pct_max = 3.3826; reproduced by `src/portfolio.py` to 1e-8 (test) | verified (model output) | "Under assumed limits, restructuring alone reduces modelled withdrawal by 3.4 % (2.1–5.9 % across 2 000 Monte Carlo runs)." |
| 3 | 77 % of the water freed by cutting rice is used again by the crops that replace it | `outputs/decision_attribution_crops.csv`: −1.074 km³ rice, +0.827 km³ others | verified | As stated, adding "in the model". |
| 4 | The binding limit is the upper bound of the small low-water crops (doubling it gives 7.66 %) | `outputs/decision_attribution.csv` | verified | "Relaxing the growth limit of low-water crops matters more than relaxing the food-crop minimum, which is not binding." |
| 5 | At 70 % of normal water, protective rules keep 74.0 % of the sown area, against 70 % for a uniform cut | `outputs/emergency_summary.csv` opt_area_pct = 73.97; the browser shows 74.0 % (headless Edge) | verified (scenario) | "In a user-defined 70 % water scenario with assumed rules, the optimised plan keeps 74 % of the area. A uniform cut keeps 70 % and breaks the food-crop rule." |
| 6 | Below 64.6 % of normal water the protective rules are infeasible | Minimum water 4.718331 km³ = 64.591 % of 7.3049; Python and the browser agree at the boundary and 1 ppm below it | verified | As stated. |
| 7 | Each additional million m³ keeps 25.5 ha (shadow price) | `emergency_summary.csv` water_shadow_ha_per_mln_m3 = 25.51 = 10⁶ / 39 201 | verified (local, scenario-specific) | Add "at the margin, in this scenario". |
| 8 | Rice output falls from 422 to 268 thousand t in the 70 % plan | `outputs/emergency_crops.csv`; the yield of 5.17 t/ha is **assumed** (sources diverge) | partially verified | "With an assumed yield of 5.17 t/ha, about 268 instead of 422 thousand t." |
| 9 | +2 °C raises seasonal ET₀ by 5.5 % and withdrawal by 5.6 % | `outputs/stress_scenarios.csv`; perturbation checked: Tmax shifted by exactly +2.0, RH unchanged | verified (sensitivity experiment) | "In a +2 °C sensitivity experiment (constant RH)…". Never call it a projection. |
| 10 | The drought analogue year 2021 needs 7.4 % more than average | `stress_scenarios.csv`; 2021 is the observed year with the highest modelled demand | verified | "The observed 2021 season, the most demanding of 2010–2025, …" |
| 11 | Monte Carlo: withdrawal 6.17–8.75 km³ (P5–P95), saving 2.1–5.9 % | `outputs/uncertainty_summary.csv`; recomputed independently with identical results; LHS stratified in all 10 dimensions and reproducible from the seed | verified | "Spread under assumed input ranges (not a confidence interval)." |
| 12 | The saving stays positive in all runs | min = 1.906 % in `uncertainty_summary.csv` | verified | As stated, adding "within the sampled ranges". |
| 13 | NASA POWER Tmax is 1.6 °C below the Kyzylorda station | T1 −1.59 °C (n = 5 699); T1e −1.60 °C on explicitly reported days (n = 4 984) | verified | As stated. |
| 14 | NASA POWER Tmin is 0.8 °C above the station / NASA has a narrower daily temperature range | T2 +0.81 °C, but 82 % of station minima are flagged as derived; T2e = −1.43 °C (n = 1 041, mostly winter) | **unsupported** (corrected on the site) | "The minimum-temperature comparison is inconclusive because most station minima are derived values." |
| 15 | The browser LP solver agrees with SciPy/HiGHS | 111 cases (87 optimal, 24 infeasible): 0 status mismatches, maximum relative objective difference 5e-16, maximum constraint violation 3e-16; sweep of 21 300 settings: no solver errors, no budget excess | verified | "The in-browser solver reproduces the reference solver on 111 test problems." |
| 16 | The results of modules 1–9 were preserved | All 15 baseline CSVs are byte-identical to the pre-change backup; `simulator.json` and `geo.json` are identical | verified | As stated. |
| 17 | 320 automated tests pass | `pytest`: 241 passed (one of them re-runs the Node suite); `node --test "tests/js/*.test.js"`: 79 passed, 0 skipped | verified (2026-11-17) | "320 automated tests (241 Python, 79 JavaScript)." |
| 18 | The model is validated | Backtest n ≤ 1 per check; no independent withdrawal series | **unsupported** | "Not validated. Compared with four single observations; the climate input was partly checked against a station." |
| 19 | The tool saves water in practice / is deployed | No field data, no deployment | **unsupported** | Do not claim this. Use "a planning prototype". |
| 20 | Economic benefits | No production costs; yields missing for 3 groups; prices partly national | **unsupported** | "The economic objective is available only with user-entered coefficients." |
| 21 | "Digital twin" | A regional planning model, not synchronised with live data | partially verified | "A reproducible regional decision-support prototype (a planning digital twin)." |
| 22 | No AI or machine learning | Linear programming, FAO-56 formulas, sampling | verified | "No machine learning is used." |
| 23 | Sown area 2025 about 188 000 ha, rice 43 % | `data/crop_areas.csv`: total_sown 188 100 ha (S016), rice 81 696.6 ha (S051), status real | verified (official statistics) | "about 188 000 ha sown in 2025 (official statistics), 43 % rice". Sown area is not irrigated area (122 000 ha irrigated reported for 2026, S062). |
| 24 | Official growing-season irrigation limits 3.7 km³ (2024) and 3.2 km³ (2026) | `data/water_withdrawal.csv`: limit_vegetation 2024 = 3.7e9 m³ (S059), 2026 = 3.2e9 m³ (S061), status real | verified (official figures reported in regional sources) | As stated, citing the sources. |

Numbers that appear on the website are checked against `outputs/` by `tests/test_site.py` and `tests/test_decision_site.py`.
The Decision Lab tables are rendered from `web/data/planner.json`, which `src/decision_support.py` writes from the same
DataFrames as the CSVs.
