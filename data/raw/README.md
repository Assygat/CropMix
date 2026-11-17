# data/raw — original downloaded files

Byte-for-byte copies of source files, kept so that the processed tables in `data/` can be checked. Checksums of
**all** files used, including the ones that are not redistributed, are in `SHA256SUMS`.

## Included in the repository

| Files | Source | Used by |
|---|---|---|
| `nasa_power_daily_44.8N_65.5E_2010-2025.csv`, `..._2026-01-01_2026-09-30.csv`, `..._2026_download.json` | NASA POWER daily API (S063, S091) | `tests/test_climate_import.py` |
| `gsod_38062099999_2010.csv` … `_2025.csv` | NOAA NCEI GSOD (S064) | `src/validation.py` (quality flags for the station check) |
| `geo/` (geoBoundaries KAZ ADM1/ADM2 + metadata, Natural Earth rivers) | geoBoundaries (ODbL 1.0), Natural Earth (public domain) | `src/export_simulator.py` (maps) |

## Not redistributed (unclear redistribution terms)

These documents were downloaded and checked while the data were built, but they are not part of the public
repository. No code or test reads them. To verify a value, download the document from the URL, compare its
checksum with `SHA256SUMS`, and find the quotation given in `data/SOURCES.md`. Web pages may have changed since
the access date; in that case the checksum will differ and only the quotation can be compared.

| File | Source id(s) in `data/SOURCES.md` | URL |
|---|---|---|
| `fao56_chapter3_x0490e07.htm` | S084 | https://www.fao.org/4/x0490e/x0490e07.htm |
| `fao56_chapter4_x0490e08.htm` | S085 | https://www.fao.org/4/x0490e/x0490e08.htm |
| `fao56_chapter6_x0490e0b.htm` | S065–S072, S087 | https://www.fao.org/4/x0490e/x0490e0b.htm |
| `fao56_annex2_x0490e0j.htm` | S086 | https://www.fao.org/4/x0490e/x0490e0j.htm |
| `fao_s2022e08_irrigation_water_needs_ch4.htm` | S082 | https://www.fao.org/4/s2022e/s2022e08.htm |
| `fao_t7202e08_annex1_irrigation_efficiencies.htm` | S073 | https://www.fao.org/3/t7202e/t7202e08.htm |
| `cawater_syrdarya_water_kb.htm` | S075 | https://www.cawater-info.net/syrdarya-knowledge-base/water.htm |
| `cawater_yearbook2020_02_ru.htm` | S076 | https://www.cawater-info.net/yearbook/2020/02_yearbook2020_ru.htm |
| `cawater_yearbook2021_02_ru.htm` | S077 | https://www.cawater-info.net/yearbook/2021/02_yearbook2021_ru.htm |
| `cawater_yearbook2022_02_ru.htm` | S078 | https://www.cawater-info.net/yearbook/2022/02_yearbook2022_ru.htm |
| `cawater_yearbook2023_02_ru.htm` | S079 | https://www.cawater-info.net/yearbook/2023/02_yearbook2023_ru.htm |
| `cawater_yearbook2024_02_ru.htm` | S080 | https://www.cawater-info.net/yearbook/2024/02_yearbook2024_ru.htm |
| `cawater_saniiri80_8_nabiev_rice.pdf` | S083 | https://www.cawater-info.net/library/rus/saniiri80_8.pdf |
| `siar_mapa_precipitacion_efectiva.pdf` | S090 | https://servicio.mapa.gob.es/siarweb/documentos/masInfo/Precipitación-Efectiva.pdf |

Checksum on Windows: `certutil -hashfile <file> SHA256`; on Linux/macOS: `sha256sum <file>`.
