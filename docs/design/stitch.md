# Google Stitch design record

## Correction to D-012

The project id recorded in D-012 (`12444680124780591192`) and its design-system asset
(`602809031577218080`) are **not accessible from the Stitch account this session is
connected to**. `get_project` returns `The caller does not have permission`, and
`list_projects` returns four projects, none of them that one:

`AIAKILOV CRM`, `Michaela Hotels CRM`, `Matika Learning Hub`, `FinSight Pro`.

Either it was created under a different account or it was never created. Do not cite it
as evidence that a design exists.

## What actually exists (2026-09-16)

| Item | Value |
|------|-------|
| Project | `projects/318546168212711602` — "Herbal Evidence — ראיות צמחים", private |
| Design system asset | `assets/16b8291a31b74b9d8b5d37ec7bafa0b1` — "Clinical Evidence Review", v1 |
| Screens generated | **1 of 10** |

### Screens

| Screen | Stitch screen id | State |
|--------|------------------|-------|
| תשובה מאושרת (approved response) | `672ca258ca924b0299d0a035350c4901` | ✅ generated, HTML saved at `docs/design/screens/approved-response.html` |
| בקשה חדשה (request form) | — | ❌ generation timed out twice |
| עורך הסקירה (review editor) | — | ❌ generation timed out (also with GEMINI_3_8_FLASH) |
| landing, auth, dashboard, waiting status, researcher queue, review repository, staff management | — | ⬜ not attempted |

`generate_screen_from_text` returned `The operation timed out` on three of four calls.
`list_screens` returns `{}` even for the screen that demonstrably exists, so a timed-out
generation cannot be recovered by polling — the screen id only arrives in the successful
response. Shorter prompts did not help; the one success had a mid-length prompt.

## Design tokens the design system settled on

These are the values to implement against. `frontend/styles.css` already matches most of them.

| Token | Value |
|-------|-------|
| Page canvas | `#F7F7F4` |
| Card surface | `#FFFFFF`, border `1px solid #E2E4DE`, radius 8px, padding 20px |
| Interactive border | `#D5D8D0` |
| Primary | `#3F6B5A`, hover `#34594A`, on-primary `#FFFFFF` |
| Body ink | `#1C2421`; secondary `#525E59`; tertiary `#78847F` |
| Caveat (animal / in-vitro / risk-of-bias) | text `#8A6D3B` on `#F9F6F0` |
| Hebrew face | Noto Sans (Hebrew) |
| Latin / identifiers face | Work Sans, tabular numerals |
| Radius | uniform 8px; nested elements 4px or square; **no pills, no circles** |
| Elevation | outlines and tonal tiers only — **no drop shadows, no gradients** |

Bidi rule from the design system: every inline Latin term, PMID, DOI, CI and date is
wrapped in `<bdi dir="ltr">`. Numbers use `font-variant-numeric: tabular-nums`.

## Four things the generated screen got wrong

The draft is a mockup, not an approved pattern. These must **not** carry into implementation:

1. **"GRADE Low"** — spec §5 forbids labelling a rating as formal GRADE unless the
   methodology is actually implemented. Use a plain Hebrew word plus the written
   explanation.
2. **"פרוטוקול סקירה שיטתי מבוסס PRISMA"** — a compliance claim nothing implements.
   Remove it.
3. **"4 מקורות מתוך 147 פריטים שנסרקו ב-PubMed ו-Cochrane Central"** — invented counts,
   and Cochrane Central is not an agreed source (D-009 is PubMed + Europe PMC).
4. **"שיתוף עם רופא מטפל"** — a sharing feature that is not in the MVP.

All study titles, PMIDs and DOIs in the mockup are **placeholder data**. They are not real
citations and must never be shown outside a design file.
