# CropMix Twin — technical summary

Xylem Global Student Innovation Challenge 2026 · Water Quantity track · Kyzylorda Region, Kazakhstan.
All figures are model outputs from `outputs/` unless marked otherwise; see `docs/VERIFIED_CLAIMS.md` for the evidence
behind each one.

## Problem

Kyzylorda Region irrigates about 188 000 ha (official 2025 sown area) from the lower Syr Darya, a shared
transboundary river in the Aral Sea basin. Rice takes 43 % of the area and the most water per hectare. In
low-water years the region has to decide what to sow with less water. Existing tools serve that decision poorly.
Regional reports give totals, not crop-level trade-offs. Irrigation calculators such as CROPWAT compute demand for a field
or a given cropping pattern but do not search for the crop mix that best fits a regional water budget. Allocation decisions are rarely accompanied by an
explicit statement of which rule constrains the outcome.

## What CropMix Twin does

1. **Water demand.** FAO-56 Penman–Monteith ET₀ from daily NASA POWER data (2010–2025) × stage-based crop coefficients
   (FAO-56 Table 12, with the climate adjustment) gives ETc. USDA-SCS effective rainfall gives the net irrigation
   need; rice adds saturation, a standing water layer and percolation. Field and canal efficiencies give river withdrawal
   (1 mm·ha = 10 m³). For the 2025 mix the result is 7.30 km³ in an average year.
2. **Allocation.** Linear programming chooses the area of 8 crop groups. Constraints: a water budget, available land,
   per-crop minimum and maximum, a food-crop minimum, and optionally production and value minimums. Objectives: keep the most
   area, keep the most food-crop area, use the least water, or (with user-entered economics) maximise gross value.
   Ties are broken by using less water.
3. **Explanation.** Each plan reports its binding constraints, slack, shadow prices and a Pareto curve of water against area.
   When no plan is feasible, the exact relaxation needed is stated. No constraint is ever relaxed silently.
4. **Stress and uncertainty.** Climate perturbations are run through the same FAO-56 code. A Latin hypercube with
   2 000 runs over 10 uncertain inputs is propagated through the water balance and the optimiser.
5. **Evidence.** Every input carries a status: real (official statistics, reanalysis), assumed (literature values
   applied to the region, policy rules, scenario parameters) or modelled. A validation engine refuses to compare
   different quantities, for example withdrawal with evapotranspiration.

## Implementation

Python (pandas, numpy, SciPy/HiGHS) computes everything reproducibly: `python -m src.run_all`. A static six-page site
(HTML, CSS and JavaScript, no build step, works from `file://`) shows the results. The Decision Lab solves the LP live in the
browser with a two-phase simplex (Bland's rule). It reproduces SciPy/HiGHS on 111 reference problems, and every plan it
shows is re-checked against all constraints before display. 241 Python and 79 JavaScript automated tests, including
hand-calculated LP cases, a degenerate cycling example and page-versus-output consistency checks.

## Results (model outputs under stated assumptions)

| Question | Result |
|---|---|
| How much can changing the mix alone save, keeping the same land (±30 % per crop)? | 3.4 %; 2.1–5.9 % across 2 000 Monte Carlo runs |
| Why so little? | 77 % of the water freed from rice is used again by the crops that take its land; fodder needs 39 201 m³/ha against 43 822 m³/ha for rice. The binding rule is the growth limit of the small low-water crops; the food minimum does not bind. |
| With 70 % of normal water (assumed protective rules)? | 74.0 % of the area stays in production, against 70 % for a uniform cut (which also breaks the food rule); 25.5 ha per extra million m³ |
| When does planning under these rules become impossible? | Below 64.6 % of normal water; the shortfall is reported in km³ |
| Climate sensitivity | +2 °C (experiment): ET₀ +5.5 %, withdrawal +5.6 %; observed 2021 season: +7.4 % |
| Uncertainty of the water estimate | 6.17–8.75 km³ (5th–95th percentile); dominated by canal efficiency |
| Climate input check | NASA POWER Tmax 1.6 °C below the Kyzylorda station (n = 5 699 days, robust to quality flags); the Tmin comparison is inconclusive |

## What is genuinely new

An FAO-56 water balance coupled to a transparent, explainable allocation model for a water-short irrigated region.
The planner shows why a plan looks the way it does and what the next unit of water is worth, and it refuses to show an
infeasible plan as feasible. The same LP runs in Python and in the browser, verified to agree. A provenance status
on every number and an honest validation record (with n) are part of the product, not an appendix.

## Limitations

- Not validated: the output has been compared with only one observation per check, and no multi-year withdrawal
  series exists. The model estimate is higher than the official limits and reports.
- Efficiencies, rice percolation and all planning rules are assumptions. Water shares and climate changes are user
  scenarios, not forecasts or projections.
- Water is applied at full crop demand or not at all: there is no deficit irrigation and no yield response. The region
  is one unit; canals, districts and the timing of deliveries are not modelled.
- Economic data are incomplete: no production costs, and yields are missing for three groups. No economic benefit is claimed.
- The climate input is reanalysis data; only temperature has been checked against a station.

## Future work

A multi-year observed withdrawal series for validation; satellite actual ET (MOD16/GLEAM) for irrigated land, compared
with consumptive use and not with withdrawal; district-level areas and canal efficiencies; regional cost data;
deficit irrigation with FAO-33 yield response (Ky).

## Reproduce

```
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m src.run_all
.venv\Scripts\python -m pytest
node --test "tests/js/*.test.js"
```
Open `web/index.html` (Decision Lab: `web/planner.html`).
