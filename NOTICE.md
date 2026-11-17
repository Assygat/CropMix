# NOTICE — licences and third-party material in CropMix Twin

Copyright © 2026 Assygat Iran. CropMix Twin combines original work with third-party data. Each part is covered by
different terms. Where this file and a source's own terms differ, the source's terms prevail for that source's material.

## 1. Original material by the author

| Material | Paths | Licence |
|---|---|---|
| Source code | `src/`, `tests/`, HTML/CSS/JavaScript code in `web/` and `design-preview/`, configuration files (`pytest.ini`, `requirements*.txt`, `.gitignore`, `.gitattributes`) | **MIT** — see `LICENSE` |
| Documentation and written text | `README.md`, `docs/`, `data/SOURCES.md` (the author's own text, excluding quotations), `data/raw/README.md`, the prose on the web pages | **CC BY 4.0** — <https://creativecommons.org/licenses/by/4.0/> |
| Original data created by the author | `data/optimizer_presets.csv`, `data/planner_presets.csv`, `data/stress_scenarios.csv`, `data/uncertainty_ranges.csv`; generated model results `web/data/model.*`, `web/data/planner.*`, `web/data/simulator.*` and the files written to `outputs/` | **CC BY 4.0** |
| Compilations of third-party values | the other `data/*.csv` tables | **CC BY 4.0** for the author's selection, structure, units and annotations (`source`, `status`) only. The individual values belong to their sources (section 2) and are cited per row in `data/SOURCES.md`; no rights are claimed over them. |

Suggested attribution: "CropMix Twin, Assygat Iran (2026), https://github.com/Assygat/CropMix, CC BY 4.0 / MIT".

The CC BY 4.0 licence does **not** extend to quotations from third-party documents in `data/SOURCES.md`, which are
reproduced as short citations for verification.

## 2. Third-party data included in this repository

| Material | Paths | Source | Terms |
|---|---|---|---|
| NASA POWER daily point data, 44.8° N 65.5° E | `data/raw/nasa_power_*`; values in `data/climate_daily.csv`, `data/climate_daily_2026.csv` | NASA Langley Research Center, POWER Project | Freely available NASA data. Acknowledgement requested by the provider: "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the NASA Earth Science/Applied Science Program." |
| NOAA Global Surface Summary of the Day, station 38062 (Kyzylorda) | `data/raw/gsod_38062099999_*.csv`; values in `data/climate_daily.csv` | NOAA National Centers for Environmental Information | Freely available. Data from non-US stations are exchanged under WMO Resolution 40 and may carry restrictions on commercial use; used here for non-commercial research. |
| geoBoundaries KAZ ADM1/ADM2 (2017, simplified) | `data/raw/geo/geoBoundaries-*` | geoBoundaries (gbOpen), from OpenStreetMap / Wambacher | **Open Database License (ODbL) 1.0** — <https://opendatacommons.org/licenses/odbl/1-0/>. © OpenStreetMap contributors. |
| Derived boundary database | `web/data/geo.json`, `web/data/geo.js` (built by `src/export_simulator.py` from the files above and Natural Earth) | derived from geoBoundaries / OpenStreetMap | **ODbL 1.0**, as required for a publicly distributed derived database (share-alike); not covered by MIT or CC BY. The maps drawn on the website are Produced Works and carry the attribution "© OpenStreetMap contributors via geoBoundaries, ODbL 1.0". |
| Natural Earth 10 m rivers (Syr Darya extract) | `data/raw/geo/ne_10m_rivers_*` | Natural Earth | Public domain |
| Official statistics, runoff, limits and reported water figures | values in `data/crop_areas.csv`, `yields.csv`, `prices.csv`, `water_withdrawal.csv`, `river_flow.csv` | Bureau of National Statistics of Kazakhstan; CAWater-Info (SIC ICWC); regional reports | Factual figures with a citation and short quotation per value in `data/SOURCES.md`. Copyright in the original publications remains with their publishers. |
| Literature parameters | values in `data/crops_fao56.csv`, `rice_water.csv`, `efficiency.csv`, `sensitivity_ranges.csv`, `climate_sites.csv` | FAO (Irrigation and Drainage Paper 56, Training Manuals 3 and 4); SANIIRI; Ministry of Agriculture of Spain (SIAR) | Individual parameters cited with short quotations in `data/SOURCES.md`. Copyright in the documents remains with their publishers. |

## 3. Third-party documents not redistributed

Full copies of 14 source documents (FAO web pages, CAWater-Info yearbook and knowledge-base pages, a SANIIRI paper
and a SIAR note) were used while building the data. They are **not included in the current version** of the public
repository because their redistribution terms are unclear. Their URLs, bibliographic details, quotations and
SHA-256 checksums remain in `data/SOURCES.md`, `data/raw/SHA256SUMS` and `data/raw/README.md`. No code or test reads
these files. Copies were part of earlier commits of this repository; the Git history has not been rewritten.

## 4. External resources loaded by the website

Web fonts (DM Serif Display, Manrope, Space Grotesk) are loaded from Google Fonts at run time under the SIL Open
Font License 1.1; they are not stored in this repository.
