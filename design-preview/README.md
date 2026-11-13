# CropMix Twin — Homepage Hero Prototype

An isolated visual experiment for the CropMix Twin homepage. It does not touch the working application in `web/`, the Python model or `model.json`.

## Open it

Double-click `design-preview/index.html`, or serve the folder locally:

```
python -m http.server 8000 --directory design-preview
```

then open <http://localhost:8000>.

## Files

| File | Purpose |
|---|---|
| `index.html` | Hero, glass navigation, "From river to root" card, short research section |
| `styles.css` | Design tokens, glass material, typography, responsive and reduced-motion rules |
| `landscape.js` | Procedural aerial landscape drawn on `<canvas>`: noise-shaded steppe and desert, meandering river with variable width, point bars, side channel and oxbow lake, riparian woodland, canals branching from the river, irregular field strips laid out along each canal, rice basins with bunds and sky reflections, windbreaks, saline fallow; flowing water and glints |
| `main.js` | Mobile menu, cursor-following button light, scroll reveals |

## Design tokens

| Token | Hex | Use |
|---|---|---|
| Electric blue | `#001AA4` | Deepest brand blue: end of the primary gradient, droplet depth, distant haze |
| Ocean blue | `#063BCE` | Middle of the brand gradient |
| Bright blue | `#007DFF` | Primary accent: glows, borders on hover, eyebrow, river node |
| Sky (tint of bright blue) | `#8EC2FF` | Small accent text on dark backgrounds (contrast) |
| Deep navy | `#061522` | Page background |
| Navy | `#0A1F3D` | Research section, opaque glass fallback |
| Cyan | `#36B9D6` | Secondary accent (field stage, pathway line) |
| Mint | `#75E0D0` | Secondary accent (crop stage) |
| White | `#F2F8FA` | Text, light button |

Brand gradient: `#007DFF → #063BCE → #001AA4` (primary button starts at `#0A5CF0` to keep white text above 4.5:1).

Typography: **DM Serif Display** (headline, section titles, italic accents), **Manrope** (navigation, body, buttons), **Space Grotesk** (small uppercase labels). Fallbacks: Georgia / system-ui.

## Honesty rules applied

- The landscape is illustrative and labelled as such on the page; it is not a map, satellite image or model output.
- The hero shows no model results. The floating card describes the real structure of the model (river intake, field, crop; ETc = ET0 × Kc, FAO-56).
- Facts in the footer strip are true of the current model: FAO-56 Penman–Monteith, NASA POWER 2010–2025, 8 crop groups, 36 efficiency combinations.
- "Explore the Model" and "Model" open the existing application at `../web/index.html`.

## Accessibility and performance

- Glass is used only for navigation, the pathway card and buttons; opaque fallback when `backdrop-filter` is unsupported or `prefers-reduced-transparency` is set.
- `prefers-reduced-motion`: one static frame of the landscape, no grain, no reveals.
- The animation pauses when the hero is off-screen or the tab is hidden; canvas resolution is capped.
- Headline is a single accessible `<h1>` ("Every drop matters."); decorative parts are `aria-hidden`.

## External dependencies

- Google Fonts (Instrument Serif, Manrope, Space Grotesk). Without internet the page falls back to system fonts.
- No images, videos, frameworks or JavaScript libraries.
