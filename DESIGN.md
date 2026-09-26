# Design

## Visual World

This native Linux tool is a field-service inspection ledger: calm light surfaces, compact evidence rows, and a single teal action color make the board easy to scan at a workbench without turning diagnostic uncertainty into visual drama.

## Operating Surface

- The first screen answers three questions immediately: which device is being inspected, the current overall health, and which safe workflow to run.
- Results use an ordered ledger with explicit text labels and a details pane. Color reinforces status but never carries the meaning alone.
- The primary actions are Quick Test and Full Hardware Test. Individual and manual routes remain one click away but do not compete with the normal workflow.
- During a run, progress names the current check and fills one determinate bar. The interface is intentionally free of implied live-success animation.
- The details pane keeps raw evidence and a practical next step close to the selected row.

## System

- Background: cool off-white; information surfaces: white with a restrained 1px neutral border and medium rounded corners.
- Text: system sans with a robust Raspberry Pi OS fallback; tabular evidence lives in a plain read-only field.
- Status colors: green for PASS, amber for WARNING, red for FAIL, indigo for manual confirmation, neutral gray for unavailable or untested. Every color appears beside a full text label.
- Controls: clear verb-first labels, keyboard focus ring, disabled state during diagnostics, and no hidden destructive action.

## Constraints

The application must remain lightweight on Raspberry Pi 4B, have no image assets or network requirement, and never imply that untested, unavailable, or user-observed hardware passed automatically.
