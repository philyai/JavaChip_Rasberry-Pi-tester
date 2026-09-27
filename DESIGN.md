---
name: JavaChip Raspberry pi Tester
description: Graphite / Copper Bench native diagnostic instrument
colors:
  background: "#141917"
  panel: "#1D2521"
  readout: "#101512"
  border: "#465249"
  text: "#EDF0E9"
  secondary: "#ADB8AE"
  accent: "#D7A15D"
  pass: "#DEE8DC"
  warning: "#F0BE69"
  fault: "#ED859C"
  unavailable: "#A6ADA7"
  manual: "#B8ABD8"
  selection: "#394A3D"
  selection_text: "#FFFFFF"
  table_header: "#29352D"
  alternate_row: "#202923"
  row_hover: "#303C33"
  progress_fill: "#D7A15D"
typography:
  display:
    fontFamily: Barlow Semi Condensed
    fontSize: 32px
    fontWeight: 600
  heading:
    fontFamily: Barlow Semi Condensed
    fontSize: 20px
    fontWeight: 600
  body:
    fontFamily: Barlow Semi Condensed
    fontSize: 14px
    fontWeight: 400
  readout:
    fontFamily: Source Code Pro
    fontSize: 12px
    fontWeight: 400
rounded:
  panel: 0px
  button: 2px
spacing:
  root: 16px
  panel-horizontal: 18px
  evidence: 10px
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.readout}"
    rounded: "{rounded.button}"
    padding: 4px 10px
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.button}"
    padding: 4px 10px
  evidence:
    backgroundColor: "{colors.readout}"
    textColor: "{colors.text}"
    typography: "{typography.readout}"
    padding: 10px
  progress:
    backgroundColor: "{colors.readout}"
    textColor: "{colors.text}"
    typography: "{typography.readout}"
  status:
    typography: "{typography.readout}"
---

# Design System: JavaChip Raspberry pi Tester

## Overview

**Creative North Star: "Graphite / Copper Bench"**

A native diagnostic instrument with PCB graphite surfaces, copper actions and crisp inspection-sheet framing. The system uses tonal separation and geometric status markers rather than dashboard cards or decorative effects.

**Key Characteristics:**
- Instrument-panel framing.
- Monospaced machine data.
- Shape and text status redundancy.

Source of truth: `raspberry_pi_tester/theme.py`; native PySide6 Qt Widgets,
Fusion, QPalette, QSS and QPainter. No web frontend.

## Colors

The frontmatter records the exact shipping token values. Copper identifies the
existing primary actions, focus/selection accents and progress fill. Silver marks
PASS, amber WARNING, magenta FAIL, lavender manual checks, and muted silver
unavailable/untested states. A selection uses green graphite with white text.

## Typography

Barlow Semi Condensed Regular and SemiBold serve headings, labels and buttons.
The title is 32px/600; section and dialog headings 20px/600; body and buttons
14px; subtitle and selected summary 15px. The existing health caption remains
14px regular without added letter spacing; its uppercase copy is retained, not
an invitation to add eyebrow labels elsewhere.

Source Code Pro Regular and Semibold serve 12px tables, device values, evidence,
reports and progress, 13px selected status and 18px overall health. Status table
text uses semibold. Fonts and OFL licenses are bundled under `assets/fonts` and
loaded from bytes to handle non-ASCII paths. No runtime download is required.

## Layout

The existing header, overview grid, test row, results/detail splitter, progress
row and footer retain their positions and control order. Root margins are
28px horizontal/24px vertical with 16px spacing. Overview padding is 18px/14px;
detail padding 18px/16px; evidence padding 10px. Overview column gaps are 20px.
The default window remains 1180x780, minimum 920x620; splitter initial sizes stay
760/360. There are no web breakpoints. Native resize, scrolling and splitters
retain their roles. Long progress copy wraps within its existing region.

## Elevation & Depth

No shadows. Background, panel and darker readout tones provide depth; 1px borders
and technical dividers frame information without raised cards.

## Shapes

Panels, tables, evidence and progress are square. Buttons have a 2px radius.
Status markers are painted geometry: filled circle PASS, outlined triangle
WARNING, slashed square NOT AVAILABLE, crossed diamond FAIL, outlined diamond
MANUAL TEST REQUIRED, and hollow circle NOT TESTED. Overall GOOD/UNKNOWN/PROBLEM
DETECTED reuse the corresponding pass/untested/fail markers without changing text.

## Components

- **Buttons:** 28px minimum content height, 4px/10px padding, 1px border.
  Existing primary actions use copper/dark text. Hover, pressed, disabled and
  2px focus states are explicit; focus padding compensates for border thickness.
- **Results:** identical Check/Status/Summary columns, 12px mono text, alternating
  green-graphite rows, 36px minimum row height, 7px/8px cell padding, crisp grid,
  condensed 14px headers. Selection has a copper leading edge; the complete
  selected summary remains in the adjacent existing panel at narrow widths.
- **Readouts:** dark, square, read-only fields retain existing text, wrapping and
  selection. Evidence placeholder text uses the secondary text token.
- **Progress:** existing QProgressBar subclass paints 7px copper segments at a
  9px pitch, with a dark-backed percentage for stable contrast. Indeterminate
  progress delegates to Qt's native busy animation. No synthetic success motion.
- **Dialogs:** the same global palette and font roles apply to existing report,
  system, individual, manual and distance dialogs. Manual rows stripe and wrap.
- **Status indicators:** icons/painting decorate existing cells and labels;
  they add no focusable control or replacement status text.

## Do's and Don'ts

- Do preserve existing labels, controls, actions and layout regions.
- Do pair every status with its unchanged text and a distinct geometric marker.
- Do use bundled fonts for consistent offline typography.

- Don’t add shadows, gradients, glass, pills or decorative circuitry.
- Don’t treat unavailable or untested hardware as a pass.
- Don’t introduce web screens or replace the native Qt stack.

Validation covers native Qt offscreen Windows renders at both window sizes,
existing dialog/status states, tests and packaged startup. Physical Pi rendering
and hardware operation are outside this visual verification.
