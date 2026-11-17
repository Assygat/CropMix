# CropMix Twin — competition submission text (English)

Prepared for the Xylem Global Student Innovation Challenge 2026, Water Quantity track. Every figure below is taken
from `outputs/` or `data/` and listed with its evidence in `docs/VERIFIED_CLAIMS.md`. The platform's character
limits have **not** been verified. Where the length may matter, two versions are given; trim to the limit shown in
the form.

Labels used in this text: *official data* (published statistics or limits), *reanalysis* (gridded climate data),
*assumption* (a value we chose and documented), *model estimate* (a result of our calculation), *scenario* (a
"what if" chosen by the user).

---

## A. Project title

**CropMix Twin: planning crop mixes for water-short years in Kazakhstan's Aral Sea basin**

Shorter alternative: **CropMix Twin — crop water planning for Kyzylorda, Kazakhstan**

## B. Short description, challenge, country

- **Country:** Kazakhstan (Kyzylorda Region)
- **Challenge / track:** Xylem Global Student Innovation Challenge 2026 — Water Quantity (High School)

**Short description, about 150 characters:**
> An open, explainable model that shows how changing the crop mix changes irrigation water use and finds what to sow when river water is short.

**Short description, about 300 characters:**
> CropMix Twin is an open planning model for Kyzylorda Region, Kazakhstan. It turns a crop mix and a climate year into river water demand using FAO-56 methods. It then uses linear programming to find which crops to sow when water is short, and explains every trade-off and uncertainty behind the answer.

## C. The Issue

Kyzylorda Region lies on the lower Syr Darya, the river that once filled the northern Aral Sea. Farming here depends on
irrigation from a river shared by several countries. In 2025 the region sowed about **188 000 ha**
(*official data*), and **43 %** of that was rice, the crop that needs the most water per hectare.

Water is getting tighter. The official irrigation limit for the growing season was **3.7 km³ in 2024 and 3.2 km³ in
2026** (*official data*, regional reports). In a low-water year, planners, district water offices and farm
cooperatives must decide how much of each crop to sow before they know how the season will go.

The tools available to them do not answer that question well:

- Regional statistics report totals, not what a different crop mix would change.
- Irrigation calculators such as CROPWAT compute the water need of a field or a given cropping pattern. They do not
  search for the mix that best fits a water budget.
- When water is cut, every crop is often expected to take the same share of the cut. Nobody shows which rule limits
  the result, or what the next cubic metre of water would be worth.

The result is that decisions about the scarcest resource in the region are made without a transparent way to compare
options.

## D. Our Magic Solution

**CropMix Twin** is an open, transparent "planning twin" of the region's irrigated agriculture. It is not a sensor
network or a forecast. It is a calculator that answers one practical question honestly: *if we have this much water,
what should we sow, and what does that choice cost us?*

1. **It measures demand the way agronomists do.** Daily FAO-56 Penman–Monteith reference evapotranspiration and crop
   coefficients give the water each of eight crop groups needs. Effective rainfall, rice flooding and field and canal
   losses then convert that need into the water taken from the river.
2. **It finds the best crop mix under real rules.** Linear programming chooses crop areas within a water budget,
   minimum and maximum areas for each crop, and a minimum area of food crops. It then tells you which rule decided the
   answer and how many extra hectares one more million cubic metres of water would keep in production.
3. **It never hides a "no".** If no plan can satisfy the rules, it says so and states exactly how much water is
   missing, instead of quietly breaking a rule.
4. **It stress-tests itself.** Warmer and drier seasons are run through the same equations, and 2 000 Monte Carlo runs
   show how far the answer moves when uncertain inputs change.
5. **It is honest about evidence.** Every input on the website is labelled as official data, reanalysis,
   literature, assumption or model estimate. The limitations are published alongside the results.

What makes it different is the combination: an agronomic water balance, an explainable optimiser and an open record
of uncertainty in one tool that runs in any web browser with no installation.

## E. How It Works

1. **Climate in.** 16 years (2010–2025) of daily weather for the region from NASA POWER (*reanalysis*). Temperature
   was compared with the Kyzylorda weather station over 5 699 days.
2. **Crop water need.** For each crop and day: reference evapotranspiration × crop coefficient (FAO-56) = crop water
   use. Effective rainfall is subtracted (USDA-SCS method). Rice also needs water to saturate and flood its fields.
3. **From field to river.** Field and canal efficiencies (*assumptions* from FAO guidance, varied in the uncertainty
   analysis) convert the field need into river withdrawal: 1 mm on 1 ha = 10 m³. For the 2025 crop mix in an average
   year the *model estimate* is 7.30 km³. This is higher than the official limits, which is one reason results are
   compared as shares and changes, not as absolute volumes.
4. **Optimisation.** A linear programme over the eight crop areas. The user sets the water available (a *scenario*),
   the rules (minimum and maximum area per crop, minimum food-crop area, whether land may stay unsown) and the goal:
   keep the most land, keep the most food-crop land, or use the least water. When all economic inputs are entered, the
   goal can also be gross value.
5. **Explanation.** Each answer lists the binding rules, unused water, shadow prices (the value of one more unit of
   water or land) and a Pareto curve of water against land kept.
6. **Stress and uncertainty.** Climate experiments (+1 to +4 °C, −15 to −50 % rain, the observed drought-like 2021
   season) and 2 000 Latin hypercube runs over ten uncertain inputs.
7. **Open and checkable.** Python computes the reference results. The website solves the same linear programme live
   in the browser and was checked against the reference solver on 111 test problems. 241 Python and 79 JavaScript
   automated tests check equations, constraints and every number shown on the site.

## F. Freestyle — Impact at Scale

**What CropMix Twin can do today (verified model results):**

- **Why reshuffling crops alone saves little.** Keeping the same land and allowing each crop to change by ±30 %, the
  best mix uses 3.4 % less water (2.1–5.9 % across 2 000 uncertainty runs). The model shows why: 77 % of the water freed by
  cutting rice is used again by the crops that take its land. Planners learn where the real lever is.
- **Planning for a short year.** With 70 % of normal water and protective rules (each crop keeps at least half its
  area; food crops keep at least 80 %), the optimised plan keeps **74 %** of the farmland in production. An equal cut
  for every crop keeps 70 % and breaks the food rule. The cost is visible too: rice output falls from about 422 to 268
  thousand tonnes (with an assumed yield).
- **Knowing the breaking point.** Below about 65 % of normal water, no plan meets those rules. The tool says so and
  states the shortfall, which is information a water office needs before the season starts.
- **Climate pressure.** A +2 °C season raises crop water demand by about 5.6 % in the model, and the observed 2021
  season needed 7.4 % more than average.

**How it can scale.** The method uses open global data (NASA POWER, FAO-56 parameters, OpenStreetMap boundaries) and
open-source code (MIT licence). Any irrigated district with sown-area statistics and a water budget could be added:
for example other Syr Darya and Amu Darya provinces, or other dry irrigated regions. The next steps that would turn
the prototype into a planning instrument are: a multi-year record of measured water withdrawal for validation,
district-level areas and canal efficiencies, and regional cost data. With those, the same interface could support
seasonal allocation meetings between water offices and farmers.

**What it is not.** It is not validated against a series of measured withdrawals. It is not deployed on farms. It does
not guarantee savings. Efficiencies, planning rules and climate changes are assumptions or scenarios, and they are
labelled that way. We see that honesty as part of the solution: a planning tool is only useful if it shows how much it
can be trusted.

## G. Key verified results

| Result | Value | Type |
|---|---|---|
| Sown area, Kyzylorda Region, 2025 | about 188 000 ha (rice 43 %) | official data |
| Official growing-season irrigation limit | 3.7 km³ (2024), 3.2 km³ (2026) | official data |
| River withdrawal of the 2025 crop mix, average year | 7.30 km³ (5th–95th percentile 6.17–8.75) | model estimate |
| Saving from changing the mix on the same land (±30 % per crop) | 3.4 % (2.1–5.9 %) | model estimate under assumed rules |
| Land kept at 70 % of normal water (protective rules) | 74.0 % vs 70 % for an equal cut | scenario result |
| Marginal value of water in that scenario | 25.5 ha per extra million m³ | model estimate, local |
| Water level below which the protective rules cannot be met | 64.6 % of normal | model estimate |
| +2 °C season | ET₀ +5.5 %, withdrawal +5.6 % | sensitivity experiment |
| Browser solver vs reference solver | 111 test problems, identical status, objective difference ≤ 5·10⁻¹⁶ | verification |
| Automated tests | 241 Python + 79 JavaScript, all passing | verification |
| NASA POWER vs Kyzylorda station, daily maximum temperature | −1.6 °C (n = 5 699 days) | input check |

## H. Links

- **Source code and data:** https://github.com/Assygat/CropMix
- **Website:** https://assygat.github.io/CropMix/ (Decision Lab: https://assygat.github.io/CropMix/planner.html).
  Published from `web/` by the GitHub Actions workflow `.github/workflows/pages.yml`.
- **Technical summary:** `docs/COMPETITION_TECHNICAL_SUMMARY.md`
- **Evidence behind each claim:** `docs/VERIFIED_CLAIMS.md`
- **Limitations:** `docs/limitations.md` (Russian) and the Limitations section of the Data & Evidence page (English)
- **Licences:** `LICENSE` (MIT), `NOTICE.md` (CC BY 4.0, third-party terms)

## I. Where to put supporting material on the platform

- **Main text fields:** sections C–F above.
- **Research documentation / attachments (if the form accepts files):** a PDF export of
  `docs/COMPETITION_TECHNICAL_SUMMARY.md` as the main research document, and `docs/VERIFIED_CLAIMS.md` as the evidence
  table. Do not attach third-party documents (FAO, CAWater, SANIIRI, SIAR); cite them through `data/SOURCES.md`.
- **Links field:** the GitHub repository and the website https://assygat.github.io/CropMix/ (Decision Lab page:
  https://assygat.github.io/CropMix/planner.html).
- **Presentation and video:** see section J; the demonstration script is in `docs/competition_package.md`, section 7.

## J. Presentation outline (8 slides)

1. **The river and the region.** Kyzylorda, the Syr Darya and the Aral Sea; 188 000 ha sown in 2025, 43 % of it rice.
2. **The decision.** Limits of 3.7 km³ (2024) and 3.2 km³ (2026): what do we sow when the water is short?
3. **How water demand is calculated.** Climate → crop water need (FAO-56) → rainfall and losses → river withdrawal.
4. **Finding 1.** Changing the mix on the same land saves 3.4 % (2.1–5.9 %), and 77 % of the freed water is used again.
5. **Finding 2.** At 70 % water the plan keeps 74 % of the land; the rice trade-off; the breaking point at about 65 %.
6. **Live demo.** Decision Lab: water slider, binding rules, shadow price, the "no feasible plan" message, Pareto curve.
7. **Trust.** Data labels, the station check, 2 000 uncertainty runs, the browser solver matching the reference,
   320 automated tests.
8. **Limits and next steps.** Not validated yet; what data would change that; scaling to other irrigated districts.
