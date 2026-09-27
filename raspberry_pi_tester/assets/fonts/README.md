# Bundled typefaces

Loaded from bytes by `theme.apply_theme` so paths containing non-ASCII characters
work with Qt's font backend. The PyInstaller spec includes this entire directory.
The application does not download fonts at runtime.

- Barlow Semi Condensed Regular / SemiBold: https://github.com/google/fonts/tree/main/ofl/barlowsemicondensed
  - License: `Barlow-OFL.txt` (SIL Open Font License 1.1).
- Source Code Pro Regular / Semibold: https://github.com/adobe-fonts/source-code-pro/tree/release/TTF
  - License: `SourceCodePro-OFL.md` (SIL Open Font License 1.1).

Barlow is used for the application title, headings, labels and buttons.
Source Code Pro is used for diagnostic tables, device values, status text,
progress percentages, evidence and report readouts.
