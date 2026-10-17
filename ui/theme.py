"""
FXsonic Design System Tokens & Global Styling
Directly aligned with the FXsonic v2 HTML exports:

  * FXsonic_v2_Dark_export.html  (Dark slate:  #1A1A1A / #2D2D2D / #242424 / #3D3D3D)
  * FXsonic_v2_Light_export.html (Off-white:   #F8F9FA / #FFFFFF / #F1F2F4 / #E2E4E8)

Every value below was lifted from those exports. Dark is the app default (applied on
``:root``); light overrides are applied on ``body.body--light``, which Quasar toggles
through ``ui.dark_mode()``.

Tokens are consumed either directly by inline ``.style()`` calls in the UI components or
through the helper classes inside ``GLOBAL_CSS`` (``.fx-btn-*``, ``.filter-chip``,
``.badge-*``, ``.fx-cell`` ...).

Quasar is deliberately neutralised here so its default blue brand colour can never leak
through in either theme (see the ``--q-*`` block).
"""

FONT_FAMILY_HEAD = "'Oswald', sans-serif"
FONT_FAMILY_BODY = "'Roboto', sans-serif"
FONT_FAMILY_MONO = "'Roboto Mono', monospace"

# ---------------------------------------------------------------------------
# Logo assets (header brand lockup)
# ---------------------------------------------------------------------------
# FXsonicD.svg -> white/light wordmark + crimson emblem  => shown in DARK mode
# FXsonicL.svg -> charcoal wordmark  + crimson emblem    => shown in LIGHT mode
LOGO_DARK = "assets/FXsonicD.svg"
LOGO_LIGHT = "assets/FXsonicL.svg"
LOGO_VIEWBOX_WIDTH = 866
LOGO_VIEWBOX_HEIGHT = 164
LOGO_HEIGHT = 32  # px, matches the 32px logo box in both HTML exports
# Constant aspect ratio across theme switches => no logo jitter.
LOGO_WIDTH = round(LOGO_HEIGHT * LOGO_VIEWBOX_WIDTH / LOGO_VIEWBOX_HEIGHT, 2)


# Served URLs for the header logo. main.py mounts the assets folder at
# ``/assets`` and the preload hints reference these exact URLs, so the <img> and
# the <link rel="preload"> never diverge (single fetch, no console warnings).
STATIC_ASSETS_PREFIX = "/assets"
LOGO_URL_DARK = f"{STATIC_ASSETS_PREFIX}/{LOGO_DARK.rsplit('/', 1)[-1]}"
LOGO_URL_LIGHT = f"{STATIC_ASSETS_PREFIX}/{LOGO_LIGHT.rsplit('/', 1)[-1]}"


def logo_asset(dark: bool) -> str:
    """Return the local header logo asset path for the given theme."""
    return LOGO_DARK if dark else LOGO_LIGHT


def logo_url(dark: bool) -> str:
    """Return the served URL of the header logo for the given theme."""
    return LOGO_URL_DARK if dark else LOGO_URL_LIGHT



# ---------------------------------------------------------------------------
# Mockup-exact palette tokens
# ---------------------------------------------------------------------------
DARK_TOKENS = """
  /* Surfaces */
  --fx-bg-window: #1A1A1A;
  --fx-bg-card: #2D2D2D;
  --fx-bg-input: #242424;
  --fx-bg-subtle: #2F2F2F;
  --fx-art-bg: #242424;

  /* Lines */
  --fx-border: #3D3D3D;
  --fx-border-subtle: #2F2F2F;
  --fx-border-button: #4A4A4A;

  /* Brand */
  --fx-crimson: #AA182C;
  --fx-crimson-hover: #851221;
  --fx-crimson-active: #6C0E1B;

  /* Type */
  --fx-text-primary: #F2F2F2;
  --fx-text-muted: #8E8E93;
  --fx-text-on-accent: #FFFFFF;

  /* Interaction */
  --fx-progress-bg: #3D3D3D;
  --fx-row-hover-bg: rgba(255, 255, 255, 0.03);
  --fx-row-selected-bg: #2A1418;
  --fx-outline-hover-bg: rgba(255, 255, 255, 0.05);
  --fx-chip-bg-active: #2D2D2D;
  --fx-chip-border: #3D3D3D;

  /* Status tints */
  --fx-status-matched-dot: #1E824C;
  --fx-status-matched-bg: #12301F;
  --fx-status-matched-text: #35B36E;

  --fx-status-ambig-dot: #E67E22;
  --fx-status-ambig-bg: #35240E;
  --fx-status-ambig-text: #E67E22;

  --fx-status-unmatched-dot: #AA182C;
  --fx-status-unmatched-bg: #35151A;
  --fx-status-unmatched-text: #D9455B;

  /* Metadata diff (current/old value accent) */
  --fx-diff-current: #D9455B;
"""

LIGHT_TOKENS = """
  /* Surfaces */
  --fx-bg-window: #F8F9FA;
  --fx-bg-card: #FFFFFF;
  --fx-bg-input: #F1F2F4;
  --fx-bg-subtle: #E9EAEE;
  --fx-art-bg: #F1F2F4;

  /* Lines */
  --fx-border: #E2E4E8;
  --fx-border-subtle: #E9EAEE;
  --fx-border-button: #1A1A1A;

  /* Brand */
  --fx-crimson: #AA182C;
  --fx-crimson-hover: #851221;
  --fx-crimson-active: #6C0E1B;

  /* Type */
  --fx-text-primary: #1A1A1A;
  --fx-text-muted: #555555;
  --fx-text-on-accent: #FFFFFF;

  /* Interaction */
  --fx-progress-bg: #E2E4E8;
  --fx-row-hover-bg: rgba(0, 0, 0, 0.025);
  --fx-row-selected-bg: #FAEAEC;
  --fx-outline-hover-bg: rgba(0, 0, 0, 0.04);
  --fx-chip-bg-active: #FFFFFF;
  --fx-chip-border: #E2E4E8;

  /* Status tints */
  --fx-status-matched-dot: #1E824C;
  --fx-status-matched-bg: #E8F5EE;
  --fx-status-matched-text: #1E824C;

  --fx-status-ambig-dot: #E67E22;
  --fx-status-ambig-bg: #FDF2E4;
  --fx-status-ambig-text: #E67E22;

  --fx-status-unmatched-dot: #AA182C;
  --fx-status-unmatched-bg: #FAEAEC;
  --fx-status-unmatched-text: #AA182C;

  /* Metadata diff (current/old value accent) */
  --fx-diff-current: #AA182C;
"""

_CSS_TEMPLATE = """
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@300;400;500;600;700&family=Roboto+Mono:wght@400;500;600&family=Roboto:wght@300;400;500;700&display=swap');

/* ==========================================================================
   1. THEME TOKENS  (Dark = default on :root, Light = body.body--light)
   ========================================================================== */
:root {
  --font-oswald: 'Oswald', sans-serif;
  --font-roboto: 'Roboto', sans-serif;
  --font-mono: 'Roboto Mono', monospace;

  /* NiceGUI pads .nicegui-content with 1rem by default, which would push the
     100vh shell past the viewport. Kill it at the source. */
  --nicegui-default-padding: 0px;
  --nicegui-default-gap: 0px;

__DARK_TOKENS__
}

body.body--light {
__LIGHT_TOKENS__
}

/* ==========================================================================
   2. QUASAR BRAND NEUTRALISATION
   Keeps primary actions #AA182C and stops Quasar's default blue leaking
   into either theme.
   ========================================================================== */
html, body {
  --q-primary: #AA182C !important;
  --q-secondary: #AA182C !important;
  --q-accent: #AA182C !important;
  --q-negative: #AA182C !important;
  --q-positive: #1E824C !important;
  --q-warning: #E67E22 !important;
  --q-info: #8E8E93 !important;
  --q-dark: #1A1A1A !important;
  --q-dark-page: #1A1A1A !important;
}

/* ==========================================================================
   3. PAGE SHELL  (full-viewport, never scrolls)
   ========================================================================== */
*, *::before, *::after {
  box-sizing: border-box;
}

html, body {
  height: 100%;
  margin: 0;
  padding: 0;
  overflow: hidden;
}

body {
  font-family: var(--font-roboto);
  background-color: var(--fx-bg-window) !important;
  color: var(--fx-text-primary) !important;
  user-select: none;
}

.nicegui-content {
  padding: 0 !important;
  gap: 0 !important;
  margin: 0 !important;
  width: 100%;
  height: 100vh;
  overflow: hidden !important;
}

.q-layout, .q-page-container, .q-page {
  background-color: var(--fx-bg-window) !important;
}

/* Scrollbars */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--fx-bg-window); }
::-webkit-scrollbar-thumb { background: var(--fx-border); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--fx-text-muted); }

/* ==========================================================================
   4. TYPOGRAPHY
   ========================================================================== */
.font-oswald {
  font-family: var(--font-oswald) !important;
  text-transform: uppercase;
}
.font-roboto { font-family: var(--font-roboto) !important; }
.font-mono { font-family: var(--font-mono) !important; }

/* ==========================================================================
   5. HEADER BRAND LOCKUP  (dynamic logo swapping)
   The logo box is 32px tall in both exports; the SVG viewBox ratio (866x164)
   is preserved exactly so the mark never shifts when the theme is toggled.
   ========================================================================== */
.fx-logo {
  display: block;
  height: __LOGO_HEIGHT__px;
  width: __LOGO_WIDTH__px;
  object-fit: contain;
  object-position: left center;
  flex-shrink: 0;
}

.fx-theme-toggle {
  background-color: transparent !important;
  color: var(--fx-text-muted) !important;
  border-radius: 2px !important;
  min-height: 26px !important;
  padding: 0 4px !important;
}
.fx-theme-toggle:hover {
  color: var(--fx-crimson) !important;
  background-color: var(--fx-outline-hover-bg) !important;
}

/* ==========================================================================
   6. BUTTONS  (defined treatments for BOTH themes)
   ========================================================================== */
.q-btn {
  box-shadow: none !important;
  text-transform: none !important;
  min-height: 0 !important;
  font-family: var(--font-oswald) !important;
  letter-spacing: normal !important;
}
/* Quasar's hover overlay would tint our bespoke buttons - we own the hover. */
.q-btn .q-focus-helper {
  opacity: 0 !important;
}

.fx-btn-primary {
  background-color: var(--fx-crimson) !important;
  color: var(--fx-text-on-accent) !important;
  border: 1px solid var(--fx-crimson) !important;
  border-radius: 2px !important;
  height: 34px !important;
  font-family: var(--font-oswald) !important;
  font-size: 11px !important;
  font-weight: 700 !important;
  letter-spacing: 0.6px !important;
  box-shadow: none !important;
}
.fx-btn-primary:hover { background-color: var(--fx-crimson-hover) !important; }
.fx-btn-primary:active { background-color: var(--fx-crimson-active) !important; }

.fx-btn-outline {
  background-color: transparent !important;
  color: var(--fx-text-primary) !important;
  border: 1px solid var(--fx-border-button) !important;
  border-radius: 2px !important;
  height: 34px !important;
  font-family: var(--font-oswald) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.6px !important;
  box-shadow: none !important;
}
.fx-btn-outline:hover { background-color: var(--fx-outline-hover-bg) !important; }

.fx-btn-ghost-danger {
  background-color: transparent !important;
  color: var(--fx-crimson) !important;
  border: 1px solid var(--fx-crimson) !important;
  border-radius: 2px !important;
  height: 34px !important;
  font-family: var(--font-oswald) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.6px !important;
  box-shadow: none !important;
}
.fx-btn-ghost-danger:hover { background-color: rgba(170, 24, 44, 0.12) !important; }

.fx-btn-cancel {
  background-color: transparent !important;
  color: var(--fx-text-primary) !important;
  border: 1px solid var(--fx-border-button) !important;
  border-radius: 2px !important;
  height: 34px !important;
  font-family: var(--font-oswald) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.6px !important;
  box-shadow: none !important;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.fx-btn-cancel * {
  color: inherit !important;
}
.fx-btn-cancel:hover {
  background-color: rgba(170, 24, 44, 0.25) !important;
  border-color: var(--fx-crimson) !important;
  color: #FFFFFF !important;
}
.fx-btn-cancel:hover * {
  color: #FFFFFF !important;
}


/* ==========================================================================
   7. INPUTS  (path field, search field - outlined, 2px radius)
   ========================================================================== */
.q-field--outlined .q-field__control {
  border-radius: 2px !important;
  background-color: transparent !important;
}
.q-field--outlined .q-field__control:before,
.q-field--outlined:hover .q-field__control:before,
.q-field--outlined.q-field--highlighted .q-field__control:before {
  border-color: var(--fx-border) !important;
}
.q-field--outlined.q-field--focused .q-field__control:after {
  border-color: var(--fx-crimson) !important;
}
.q-field__native,
.q-field__input,
.q-field__prefix,
.q-field__suffix {
  color: var(--fx-text-primary) !important;
}
.q-field__native::placeholder,
.q-field__input::placeholder {
  color: var(--fx-text-muted) !important;
  opacity: 1 !important;
}
.q-field__marginal { color: var(--fx-text-muted) !important; }
.q-field__bottom, .q-field__messages { color: var(--fx-text-muted) !important; }

/* Compact field boxes (mockup: 34px path input / 30px search input, 0 padding) */
.fx-input .q-field__control {
  height: 34px !important;
  min-height: 34px !important;
  padding: 0px !important;
}
.fx-input .q-field__marginal {
  height: 32px !important;
  min-height: 32px !important;
}
.fx-input .q-field__native,
.fx-input .q-field__input {
  padding: 0px !important;
  font-family: var(--font-mono);
  font-size: 12px;
}
.fx-input-sm .q-field__control {
  height: 30px !important;
  min-height: 30px !important;
  padding: 0px !important;
}
.fx-input-sm .q-field__marginal {
  height: 28px !important;
  min-height: 28px !important;
}
.fx-input-sm .q-field__native,
.fx-input-sm .q-field__input {
  padding: 0px !important;
  font-family: var(--font-roboto);
  font-size: 12.5px;
}
.fx-input-sm .q-field__native::placeholder,
.fx-input-sm .q-field__input::placeholder {
  color: var(--fx-text-muted) !important;
}

/* Dialog form inputs: 34px height, 10px horizontal padding, clean readable font */
.fx-dialog-input .q-field__control {
  height: 34px !important;
  min-height: 34px !important;
  padding: 0 10px !important;
}
.fx-dialog-input .q-field__native,
.fx-dialog-input .q-field__input {
  padding: 0px !important;
  font-family: var(--font-roboto) !important;
  font-size: 13px !important;
  color: var(--fx-text-primary) !important;
}
.fx-dialog-input .q-field__native::placeholder,
.fx-dialog-input .q-field__input::placeholder {
  color: var(--fx-text-muted) !important;
  opacity: 0.6 !important;
  font-size: 12px !important;
}

/* Drag & Drop zone visual cues */
.fx-drop-active {
  outline: 2px dashed var(--fx-crimson) !important;
  outline-offset: -2px !important;
  background-color: rgba(170, 24, 44, 0.08) !important;
  transition: all 0.15s ease-in-out !important;
}
.fx-drop-active * {
  pointer-events: none !important;
}

/* Static "you can drop a folder here" affordance (Inspector empty state) */
.fx-drop-hint {
  border: 1px dashed var(--fx-border-button) !important;
  border-radius: 2px !important;
  background-color: var(--fx-bg-subtle) !important;
}

/* ==========================================================================
   8. CHECKBOXES
   ========================================================================== */
.q-checkbox__bg {
  border-radius: 2px !important;
  border-width: 1px !important;
  border-color: var(--fx-border) !important;
}
.q-checkbox__inner--falsy .q-checkbox__bg {
  background-color: transparent !important;
}
.q-checkbox__inner--truthy .q-checkbox__bg,
.q-checkbox__inner--indet .q-checkbox__bg {
  background-color: var(--fx-crimson) !important;
  border-color: var(--fx-crimson) !important;
}
.q-checkbox__svg { color: #FFFFFF !important; }
.q-checkbox__label {
  color: var(--fx-text-muted) !important;
  font-family: var(--font-roboto) !important;
}

/* ==========================================================================
   9. LINEAR PROGRESS (activity drawer)
   ========================================================================== */
.q-linear-progress {
  border-radius: 0 !important;
}
.q-linear-progress__track {
  background-color: var(--fx-progress-bg) !important;
  opacity: 1 !important;
}
.q-linear-progress__model {
  background-color: var(--fx-crimson) !important;
}

/* ==========================================================================
   10. FILTER CHIPS  (mockup: idle = 1px outline + muted, active = tint fill)
   ========================================================================== */
.filter-chip {
  align-items: center;
  border-radius: 2px;
  box-sizing: border-box;
  display: flex;
  flex-direction: row;
  flex-shrink: 0;
  gap: 0px;
  height: 28px;
  padding: 0px 12px;
  cursor: pointer;
  border: 1px solid var(--fx-chip-border);
  background-color: transparent;
  color: var(--fx-text-muted);
  font-family: var(--font-oswald);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  white-space: nowrap;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.filter-chip:hover {
  color: var(--fx-text-primary);
}
.filter-chip.active {
  background-color: var(--fx-chip-bg-active);
  border-color: var(--fx-chip-bg-active);
  color: var(--fx-text-primary);
  font-weight: 600;
}

/* ==========================================================================
   11. STATUS BADGES  (dot + tinted fill, both themes)
   ========================================================================== */
.badge-matched,
.badge-ambiguous,
.badge-unmatched,
.badge-staged,
.badge-unverified {
  border-radius: 2px;
  font-family: var(--font-oswald);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.4px;
  padding: 3px 7px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.badge-matched { background-color: var(--fx-status-matched-bg); color: var(--fx-status-matched-text); }
.badge-matched .dot { width: 7px; height: 7px; border-radius: 50%; background-color: var(--fx-status-matched-dot); }

.badge-ambiguous { background-color: var(--fx-status-ambig-bg); color: var(--fx-status-ambig-text); }
.badge-ambiguous .dot { width: 7px; height: 7px; border-radius: 50%; background-color: var(--fx-status-ambig-dot); }

.badge-unmatched { background-color: var(--fx-status-unmatched-bg); color: var(--fx-status-unmatched-text); }
.badge-unmatched .dot { width: 7px; height: 7px; border-radius: 50%; background-color: var(--fx-status-unmatched-dot); }

.badge-staged,
.badge-unverified { background-color: var(--fx-bg-input); color: var(--fx-text-muted); border: 1px solid var(--fx-border); }
.badge-staged .dot,
.badge-unverified .dot { width: 7px; height: 7px; border-radius: 50%; background-color: var(--fx-text-muted); }

/* Small tag used for the OLD / NEW path badges */
.fx-tag {
  display: inline-flex;
  align-items: center;
  border-radius: 2px;
  padding: 1px 6px;
  font-family: var(--font-oswald);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  flex-shrink: 0;
}
.fx-tag-old { background-color: var(--fx-row-selected-bg); color: var(--fx-text-muted); }
.fx-tag-new { background-color: var(--fx-status-matched-bg); color: var(--fx-text-primary); }
/* ==========================================================================
   12. STAGING TABLE  (fixed pixel column grid - headers and cells share the
   exact same widths so nothing truncates or bunches up)
   ========================================================================== */
.fx-table-header {
  height: 33.5px;
  min-height: 33.5px;
  background-color: var(--fx-bg-input);
  border-bottom: 1px solid var(--fx-border);
}
.fx-table-row {
  height: 39.5px;
  min-height: 39.5px;
  border-bottom: 1px solid var(--fx-border-subtle);
  transition: background-color 0.12s ease;
  position: relative;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
}
.fx-table-row:hover {
  background-color: var(--fx-row-hover-bg);
}
.fx-table-row.row-selected {
  background-color: var(--fx-row-selected-bg) !important;
}
.fx-table-row.row-selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background-color: var(--fx-crimson);
}

.fx-cell {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0px 8px;
  gap: 0px;
  overflow: hidden;
}
.fx-cell-grow {
  flex: 1 1 0;
  min-width: 0;
}

.fx-th {
  font-family: var(--font-oswald);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--fx-text-muted);
  white-space: nowrap;
}

.fx-td {
  font-family: var(--font-roboto);
  font-size: 13px;
  font-weight: 400;
  color: var(--fx-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 auto;
  min-width: 0;
}
.fx-td-mono { font-family: var(--font-mono); font-size: 12px; }
.fx-td-muted { color: var(--fx-text-muted); }
.fx-td-year {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--fx-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 0 0 auto;
}

/* ==========================================================================
   13. PANEL BUILDING BLOCKS (inspector / options / footer)
   ========================================================================== */
.fx-section-head {
  font-family: var(--font-oswald);
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  color: var(--fx-text-primary);
}
.fx-eyebrow {
  font-family: var(--font-oswald);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--fx-text-muted);
}
.fx-path-box {
  background-color: var(--fx-bg-input);
  border: 1px solid var(--fx-border);
  border-radius: 2px;
  padding: 8px 10px;
  gap: 8px;
  overflow: hidden;
}
.fx-diff-row {
  height: 27.5px;
  min-height: 27.5px;
  border-bottom: 1px solid var(--fx-border-subtle);
  gap: 8px;
  align-items: center;
}
.fx-diff-label {
  width: 92px;
  flex-shrink: 0;
  font-family: var(--font-oswald);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  color: var(--fx-text-muted);
}
.fx-diff-head {
  font-family: var(--font-oswald);
  font-size: 8.5px;
  font-weight: 600;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  color: var(--fx-text-muted);
}
.fx-diff-value {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--fx-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 0;
  min-width: 0;
}
.fx-console {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--fx-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 0;
  min-width: 0;
}
"""

GLOBAL_CSS = (
    _CSS_TEMPLATE
    .replace('__DARK_TOKENS__', DARK_TOKENS.strip())
    .replace('__LIGHT_TOKENS__', LIGHT_TOKENS.strip())
    .replace('__LOGO_HEIGHT__', str(LOGO_HEIGHT))
    .replace('__LOGO_WIDTH__', f'{LOGO_WIDTH:g}')
)
