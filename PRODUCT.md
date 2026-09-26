# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop-linux

## Stack

Python 3 with PySide6, psutil, and standard Linux/Raspberry Pi OS command-line tools, as specified by the user.

## Users

People preparing a Raspberry Pi 4 Model B for a robotics project, including users who may not be highly technical. They need a trustworthy, understandable indication of what has been checked, what needs attention, and what requires a physical/manual check.

## Product Purpose

Raspberry Pi 4B Hardware Tester performs safe, non-destructive diagnostics on a Raspberry Pi 4 Model B before it is used in a robotics project. Success means a user can run quick, full, individual, and manual diagnostic workflows without confusing absence of an error for verified hardware health.

## Positioning

This is a Pi 4B-specific, evidence-oriented desktop diagnostic tool: every result retains the command evidence and distinguishes PASS, WARNING, FAIL, MANUAL TEST REQUIRED, NOT AVAILABLE, and NOT TESTED.

## Operating Context

The application runs locally in a Raspberry Pi OS or Debian desktop on the target Pi. It gathers only safe diagnostic information using standard OS interfaces and reports results and logs that can be saved for later review.

## Capabilities and Constraints

- Target hardware is Raspberry Pi 4 Model B only; unsupported devices receive a visible warning and are never represented as fully supported.
- No destructive hardware tests, stress tests, configuration changes, privileged writes, or fabricated results.
- Long-running diagnostics must not block the UI.
- Hardware validation can only be confirmed on the physical target after deployment; the project must clearly preserve that distinction.

## Brand Commitments

The product name is Raspberry Pi 4B Hardware Tester. Its voice is calm, plain-language, evidence-first, and suitable for less-technical users.

## Evidence on Hand

The only supplied evidence is the product brief. There are no confirmed target-device readings, visual assets, or hardware test results. Values shown by the application come from live device checks or are marked not tested.

## Product Principles

- State the verification level plainly.
- Keep checks safe and reversible.
- Make the next action obvious when a result needs attention.
- Preserve diagnostic evidence for support and comparison.
- Remain lightweight enough for the target Pi 4B desktop.

## Accessibility & Inclusion

Use high-contrast status indicators paired with text, keyboard-accessible controls, and plain-language outcomes.
