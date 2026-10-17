"""
Script to build the production help.html for FXsonic v0.2.0.
Follows humanizer guidelines:
- Direct, natural, human tone without marketing hype or AI boilerplate.
- No em dashes or en dashes.
- No redundant 'Precision Acoustic Workbench' or 'FXsonic' text.
- Header uses assets/FXsonicD.svg on a dark (#1A1A1E) background.
- Favicon links point to the clean FX favicon assets.
- Embedded high-res UI screenshots.
- Collapsible navigation menu system.
"""

import base64
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def get_b64(rel_path: str) -> str:
    p = BASE_DIR / rel_path
    if not p.exists():
        raise FileNotFoundError(f"Asset not found: {p}")
    return base64.b64encode(p.read_bytes()).decode("ascii")

# Load image assets
img_logo = get_b64("assets/FXsonicD.svg")
img_drop_zone = get_b64("assets/screenshots/help_crops/drop_zone_empty.png")
img_navbar = get_b64("assets/screenshots/help_crops/navbar.png")
img_options = get_b64("assets/screenshots/help_crops/options_bar.png")
img_filters = get_b64("assets/screenshots/help_crops/filters_toolbar.png")
img_select_by = get_b64("assets/screenshots/help_crops/select_by_active.png")
img_sorting = get_b64("assets/screenshots/help_crops/column_sorting.png")
img_staging = get_b64("assets/screenshots/help_crops/staging_rows.png")
img_inspector = get_b64("assets/screenshots/help_crops/inspector_panel.png")
img_footer = get_b64("assets/screenshots/help_crops/status_footer.png")
img_favicon_32 = get_b64("icons/favicon-32x32.png")
img_favicon_ico = get_b64("icons/favicon.ico")

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FXsonic v0.2.0: User Guide and Technical Reference</title>

    <!-- Favicon link pointing to local icon assets with embedded base64 fallback -->
    <link rel="icon" type="image/x-icon" href="data:image/x-icon;base64,{img_favicon_ico}">
    <link rel="icon" type="image/png" sizes="32x32" href="data:image/png;base64,{img_favicon_32}">
    <link rel="icon" type="image/x-icon" href="icons/favicon.ico">
    <link rel="shortcut icon" type="image/x-icon" href="icons/favicon.ico">
    <link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32x32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="icons/favicon-16x16.png">

    <!-- Google Fonts with local fallbacks -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Roboto:wght@300;400;500;700&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">

    <style>
        :root {{
            --bg-page: #17181C;
            --bg-surface: #242424;
            --bg-surface-elevated: #2D2D2D;
            --bg-inset: #1E1E22;
            --border-subtle: #3D3D3D;
            --border-interactive: #4A4A4A;
            --brand-crimson: #AA182C;
            --brand-crimson-hover: #C41F36;
            --text-primary: #F2F2F2;
            --text-secondary: #C9C9C9;
            --text-muted: #8E8E93;
            --color-success: #35B36E;
            --bg-success: #12301F;
            --border-success: #1E824C;
            --color-warning: #F59E0B;
            --color-cyan: #38BDF8;
            --radius: 3px;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        html {{
            scroll-behavior: smooth;
        }}

        body {{
            font-family: 'Roboto', -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            background-color: var(--bg-page);
            background-image:
                radial-gradient(circle at 92% 8%, rgba(170, 24, 44, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 8% 90%, rgba(170, 24, 44, 0.05) 0%, transparent 35%),
                linear-gradient(180deg, #1C1D21 0%, #17181C 100%);
            background-attachment: fixed;
            color: var(--text-secondary);
            line-height: 1.65;
            padding: 0 16px 60px;
            font-weight: 400;
            letter-spacing: 0.1px;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 960px;
            margin: 0 auto;
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-top: none;
            border-radius: 0 0 var(--radius) var(--radius);
            box-shadow: 0 20px 48px rgba(0, 0, 0, 0.45);
            position: relative;
        }}

        /* Locked Header: Stays pinned at top as user scrolls through any topic */
        .locked-header {{
            position: sticky;
            top: 0;
            z-index: 1000;
            background: #1A1A1E;
            border-left: 1px solid var(--border-subtle);
            border-right: 1px solid var(--border-subtle);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.55);
        }}

        /* Top Bar Banner with FXsonicD.svg on dark background */
        .top-banner {{
            background-color: #1A1A1E;
            border-bottom: 2px solid var(--brand-crimson);
            padding: 12px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .brand-link {{
            text-decoration: none;
            display: flex;
            align-items: center;
        }}

        .brand-logo {{
            height: 32px;
            width: auto;
            object-fit: contain;
            display: block;
        }}

        .version-badge {{
            background-color: var(--brand-crimson);
            color: #FFFFFF;
            font-family: 'Oswald', sans-serif;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.8px;
            padding: 3px 8px;
            border-radius: 2px;
            white-space: nowrap;
            text-transform: uppercase;
        }}

        /* Navigation Bar Header */
        .nav-bar-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 32px;
            background: #18191D;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .nav-toggle-btn {{
            background: var(--bg-surface-elevated);
            color: var(--text-primary);
            border: 1px solid var(--border-interactive);
            padding: 6px 14px;
            border-radius: 2px;
            font-family: 'Oswald', sans-serif;
            font-size: 12.5px;
            font-weight: 600;
            letter-spacing: 0.8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: all 0.15s ease;
            text-transform: uppercase;
        }}

        .nav-toggle-btn:hover {{
            background: var(--brand-crimson);
            border-color: var(--brand-crimson-hover);
            color: #FFFFFF;
        }}

        .nav-toggle-btn .chevron {{
            font-size: 10px;
            transition: transform 0.25s ease;
        }}

        .nav-toggle-btn.expanded .chevron {{
            transform: rotate(180deg);
        }}

        .current-topic-label {{
            font-size: 12px;
            font-family: 'Roboto Mono', monospace;
            color: var(--text-muted);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .current-topic-label strong {{
            color: var(--brand-crimson);
        }}

        /* Collapsible Navigation Menu Drawer */
        .nav-drawer {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            background: #1B1C20;
            border-bottom: 1px solid var(--brand-crimson);
        }}

        .nav-drawer.open {{
            max-height: 480px;
            overflow-y: auto;
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.7);
        }}

        .nav-drawer-inner {{
            padding: 18px 36px 22px;
        }}

        .nav-search-box {{
            width: 100%;
            background: var(--bg-inset);
            border: 1px solid var(--border-subtle);
            color: var(--text-primary);
            padding: 8px 12px;
            border-radius: 2px;
            font-size: 13px;
            font-family: 'Roboto', sans-serif;
            margin-bottom: 14px;
            outline: none;
        }}

        .nav-search-box:focus {{
            border-color: var(--brand-crimson);
        }}

        .nav-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 10px;
        }}

        .nav-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 2px;
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 12.5px;
            transition: all 0.15s ease;
        }}

        .nav-item:hover, .nav-item.active {{
            background: var(--bg-surface-elevated);
            border-color: var(--brand-crimson);
            color: #FFFFFF;
            transform: translateX(2px);
        }}

        .nav-item-num {{
            font-family: 'Roboto Mono', monospace;
            font-weight: 600;
            color: var(--brand-crimson);
            font-size: 11px;
            flex-shrink: 0;
        }}

        .nav-item-title {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        /* Main Content */
        .content {{
            padding: 36px 44px 44px;
        }}

        .app-intro {{
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border-subtle);
            margin-bottom: 36px;
        }}

        .headline-section {{
            margin-bottom: 8px;
        }}

        .main-title {{
            font-family: 'Oswald', sans-serif;
            font-size: 26px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: 0.8px;
            text-transform: uppercase;
            line-height: 1.2;
            margin: 0;
        }}

        .app-intro h2 {{
            font-family: 'Oswald', sans-serif;
            font-size: 16px;
            font-weight: 600;
            color: var(--brand-crimson);
            letter-spacing: 0.6px;
            text-transform: uppercase;
            margin-top: 6px;
            margin-bottom: 6px;
        }}

        .app-intro p {{
            font-size: 13.5px;
            color: var(--text-muted);
            margin: 0;
        }}

        /* Section Styling */
        section {{
            margin-bottom: 44px;
            scroll-margin-top: 112px;
        }}

        h3 {{
            font-family: 'Oswald', sans-serif;
            font-size: 18px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-primary);
            margin-top: 36px;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 8px;
        }}

        h3::before {{
            content: "";
            display: inline-block;
            width: 4px;
            height: 18px;
            background-color: var(--brand-crimson);
            border-radius: 1px;
            flex-shrink: 0;
        }}

        h4 {{
            font-family: 'Oswald', sans-serif;
            font-size: 14.5px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-primary);
            margin-top: 18px;
            margin-bottom: 8px;
        }}

        p {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 14px;
            font-weight: 400;
            line-height: 1.65;
        }}

        ol, ul {{
            margin-left: 20px;
            margin-bottom: 20px;
            font-size: 14px;
        }}

        li {{
            margin-bottom: 8px;
            color: var(--text-secondary);
            line-height: 1.6;
        }}

        li strong {{
            font-weight: 600;
            color: var(--text-primary);
        }}

        /* UI Figure & Embedded Screenshot Styling */
        .ui-figure {{
            background: #191A1E;
            border: 1px solid var(--border-subtle);
            border-radius: 3px;
            padding: 8px;
            margin: 18px 0 24px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35);
        }}

        .ui-figure img {{
            width: 100%;
            height: auto;
            display: block;
            border-radius: 2px;
            border: 1px solid #28282D;
        }}

        .ui-caption {{
            font-size: 12px;
            font-family: 'Roboto Mono', monospace;
            color: var(--text-muted);
            margin-top: 8px;
            padding: 2px 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .fig-badge {{
            background: var(--bg-inset);
            border: 1px solid var(--brand-crimson);
            color: #FFFFFF;
            font-weight: 600;
            padding: 1px 6px;
            border-radius: 2px;
            font-size: 10.5px;
        }}

        /* Cards & Grids */
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 20px 0 24px;
        }}

        .card {{
            background: var(--bg-surface-elevated);
            border: 1px solid var(--border-subtle);
            border-left: 3px solid var(--brand-crimson);
            border-radius: 2px;
            padding: 16px 18px;
        }}

        .card h4 {{
            margin-top: 0;
            margin-bottom: 6px;
            color: var(--text-primary);
        }}

        .card p {{
            font-size: 13px;
            color: var(--text-secondary);
            margin: 0;
            line-height: 1.55;
        }}

        /* Callout Box */
        .callout {{
            background: var(--bg-inset);
            border-left: 4px solid var(--brand-crimson);
            padding: 14px 18px;
            border-radius: 0 3px 3px 0;
            margin: 18px 0;
            border-top: 1px solid var(--border-subtle);
            border-right: 1px solid var(--border-subtle);
            border-bottom: 1px solid var(--border-subtle);
        }}

        .callout-title {{
            font-family: 'Oswald', sans-serif;
            font-weight: 600;
            font-size: 13.5px;
            letter-spacing: 0.6px;
            text-transform: uppercase;
            color: #FFFFFF;
            margin-bottom: 4px;
        }}

        /* Badges & Monospace Tags */
        .badge {{
            background: var(--bg-inset);
            border: 1px solid var(--border-subtle);
            color: var(--text-primary);
            font-family: 'Roboto Mono', Consolas, monospace;
            padding: 2px 7px;
            border-radius: 2px;
            font-size: 12px;
            font-weight: 500;
            display: inline-block;
        }}

        .badge-new {{
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid var(--color-success);
            color: var(--color-success);
            font-family: 'Roboto Mono', monospace;
            font-size: 11px;
            font-weight: 600;
            padding: 1px 6px;
            border-radius: 2px;
            text-transform: uppercase;
            margin-left: 6px;
        }}

        kbd {{
            background: #1E1F24;
            border: 1px solid #4B4B52;
            color: #F0F0F0;
            font-family: 'Roboto Mono', monospace;
            font-size: 11.5px;
            padding: 2px 6px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.4);
        }}

        /* Tables */
        .table-wrap {{
            overflow-x: auto;
            margin: 18px 0 28px;
            border: 1px solid var(--border-subtle);
            border-radius: 2px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 13.5px;
        }}

        th {{
            background: #1D1D21;
            font-family: 'Oswald', sans-serif;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            color: var(--text-primary);
            padding: 10px 14px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        td {{
            padding: 10px 14px;
            border-bottom: 1px solid var(--border-subtle);
            color: var(--text-secondary);
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        tr:nth-child(even) td {{
            background: rgba(255, 255, 255, 0.02);
        }}

        /* Footer */
        footer {{
            margin-top: 48px;
            padding-top: 20px;
            border-top: 1px solid var(--border-subtle);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12.5px;
            color: var(--text-muted);
            flex-wrap: wrap;
            gap: 10px;
        }}

        footer a {{
            color: var(--text-secondary);
            text-decoration: none;
            transition: color 0.15s ease;
        }}

        footer a:hover {{
            color: var(--brand-crimson);
            text-decoration: underline;
        }}

        /* Floating Top Button */
        .back-to-top {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--bg-surface-elevated);
            color: var(--text-primary);
            border: 1px solid var(--border-interactive);
            padding: 8px 12px;
            border-radius: 2px;
            font-family: 'Oswald', sans-serif;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.8px;
            text-decoration: none;
            text-transform: uppercase;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            opacity: 0;
            pointer-events: none;
            transition: all 0.2s ease;
            z-index: 99;
        }}

        .back-to-top.visible {{
            opacity: 1;
            pointer-events: auto;
        }}

        .back-to-top:hover {{
            background: var(--brand-crimson);
            border-color: var(--brand-crimson);
            color: #FFFFFF;
        }}

        @media (max-width: 768px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
            .content {{
                padding: 24px 20px;
            }}
            .top-banner, .nav-bar-header {{
                padding: 12px 20px;
            }}
            .nav-drawer-inner {{
                padding: 14px 20px;
            }}
        }}
    </style>
</head>
<body>

<a href="#top" id="topBtn" class="back-to-top" title="Return to top">Top</a>

<div class="container" id="top">
    <!-- Locked Header: Pins logo banner and collapsible menu system to viewport top -->
    <header class="locked-header">
        <div class="top-banner">
            <a href="#top" class="brand-link" title="FXsonic Home">
                <img src="assets/FXsonicD.svg" alt="FXsonic Logo" class="brand-logo" onerror="this.onerror=null; this.src='data:image/svg+xml;base64,{img_logo}';">
            </a>
            <span class="version-badge">v0.2.0</span>
        </div>

        <div class="nav-bar-header">
            <button id="navToggle" class="nav-toggle-btn" aria-expanded="false" onclick="toggleNavMenu()">
                <span>Contents (12 Topics)</span>
                <span id="navChevron" class="chevron">&#9660;</span>
            </button>
            <div class="current-topic-label" id="currentTopicDisplay">
                Topic: <strong>1. Overview and What's New</strong>
            </div>
        </div>

        <div id="navDrawer" class="nav-drawer">
            <div class="nav-drawer-inner">
                <input type="text" id="navSearch" class="nav-search-box" placeholder="Search guide topics..." onkeyup="filterNavTopics()">
                <div class="nav-grid" id="navGrid">
                    <a href="#overview" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">01</span><span class="nav-item-title">Overview and Updates</span></a>
                    <a href="#intake" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">02</span><span class="nav-item-title">Intake and Multi-Drop</span></a>
                    <a href="#navbar" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">03</span><span class="nav-item-title">Navbar and Actions</span></a>
                    <a href="#options" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">04</span><span class="nav-item-title">Options and Output</span></a>
                    <a href="#filters" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">05</span><span class="nav-item-title">Select By Filters</span></a>
                    <a href="#sorting" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">06</span><span class="nav-item-title">Column Sorting</span></a>
                    <a href="#staging" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">07</span><span class="nav-item-title">Staging Table Rows</span></a>
                    <a href="#inspector" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">08</span><span class="nav-item-title">Inspector and Artwork</span></a>
                    <a href="#duplicates" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">09</span><span class="nav-item-title">Duplicate Consolidation</span></a>
                    <a href="#cleantracks" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">10</span><span class="nav-item-title">Title Cleaning and Editing</span></a>
                    <a href="#heuristics" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">11</span><span class="nav-item-title">Multi-Disc and Cache</span></a>
                    <a href="#shortcuts" class="nav-item" onclick="closeNavMenu()"><span class="nav-item-num">12</span><span class="nav-item-title">Shortcuts and Formats</span></a>
                </div>
            </div>
        </div>
    </header>

    <div class="content">
        <!-- App Intro Section without redundant title or precision acoustic text -->
        <div class="app-intro">
            <div class="headline-section">
                <h1 class="main-title">User Guide and Technical Reference</h1>
            </div>
            <h2>Version 0.2.0 Manual</h2>
            <p>Reference documentation and workflow guide for version 0.2.0.</p>
        </div>

        <!-- SECTION 1: OVERVIEW -->
        <section id="overview">
            <h3>1. Overview and What's New in v0.2.0</h3>
            <p>
                FXsonic identifies audio tracks, updates tags, and organizes files. It uses Chromaprint (fpcalc) to generate acoustic fingerprints, queries AcoustID and MusicBrainz for release data, writes standard ID3v2.4 tags, and embeds front cover art.
            </p>
            <p>
                Version 0.2.0 adds multi-folder intake, duplicate detection with album consolidation, column sorting, contextual selection filters, and bulk artwork replacement.
            </p>

            <div class="grid">
                <div class="card">
                    <h4>Multi-Folder and Appending Intake <span class="badge-new">New</span></h4>
                    <p>Select and drag several folders at once. Hold <kbd>Ctrl</kbd> while dropping to append tracks to the active list without clearing previous files or creating duplicates.</p>
                </div>
                <div class="card">
                    <h4>Contextual Selection Filters <span class="badge-new">New</span></h4>
                    <p>Filter by artist, album, folder, or status. Clicking any track row selects all matching sibling tracks across the library.</p>
                </div>
                <div class="card">
                    <h4>Clickable Header Sorting <span class="badge-new">New</span></h4>
                    <p>Sort by filename, artist, title, album, year, track number, or status. Click once for ascending order, twice for descending, or three times to reset.</p>
                </div>
                <div class="card">
                    <h4>Duplicate Detection and Consolidation <span class="badge-new">New</span></h4>
                    <p>Find repeated tracks by acoustic fingerprint, metadata, and normalized filename stems. One click consolidates unique tracks into a single album folder without numbered duplicate suffixes.</p>
                </div>
                <div class="card">
                    <h4>Bulk Artwork Replacement <span class="badge-new">New</span></h4>
                    <p>Pick a track with good cover art, then click Replace Art for All Tracks in the inspector to copy that artwork across every staged track.</p>
                </div>
                <div class="card">
                    <h4>Clean Track Titles and Batch Editing <span class="badge-new">New</span></h4>
                    <p>Strip bracketed tags, website URLs, and rip markers from track titles in bulk. Edit album-level tags across selected tracks in one dialog.</p>
                </div>
            </div>
        </section>

        <!-- SECTION 2: INTAKE AND MULTI-DROP -->
        <section id="intake">
            <h3>2. Intake and Multi-Folder Staging</h3>
            <p>
                Add audio tracks by dragging files or folders onto the drop zone, or click Browse in the top navigation bar. The scanner reads all subdirectories automatically.
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_drop_zone}" alt="Empty Intake Drop Zone">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 2.1</span> Workbench drop zone ready for files or directories
                </div>
            </figure>

            <div class="callout">
                <div class="callout-title"><kbd>Ctrl</kbd> + Drop to Append Tracks</div>
                <p style="margin-bottom: 0;">
                    Dropping files normally replaces the current staging list with the new files. Holding <kbd>Ctrl</kbd> while dropping appends new files to the active session and skips tracks that are already loaded.
                </p>
            </div>
        </section>

        <!-- SECTION 3: TOP NAVBAR -->
        <section id="navbar">
            <h3>3. Top Navigation Bar and Processing Actions</h3>
            <p>
                The top bar manages source folder selection, matching, and tag writing:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_navbar}" alt="Top Action Navbar">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 3.1</span> Top navigation bar with active path, Browse, Process Album, Apply Changes, and Cancel controls
                </div>
            </figure>

            <ul>
                <li><strong>Directory path field:</strong> Shows the active source folder. Click <strong>Browse</strong> to choose a folder using the system file picker.</li>
                <li><strong>Process Album:</strong> Computes acoustic fingerprints with fpcalc, then queries AcoustID and MusicBrainz for release data.</li>
                <li><strong>Apply Changes:</strong> Writes resolved ID3v2.4 tags, embeds cover art, and renames or moves files if those options are checked.</li>
                <li><strong>Cancel / Abort:</strong> Stops a running scan or write job, or clears the staging table when idle.</li>
                <li><strong>Theme toggle:</strong> Click the brand logo to switch between dark and light modes.</li>
            </ul>
        </section>

        <!-- SECTION 4: OPTIONS BAR -->
        <section id="options">
            <h3>4. Options Bar and Formatting Controls</h3>
            <p>
                The bar directly below the top navigation controls metadata cleanup and output paths:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_options}" alt="Options Bar Controls">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 4.1</span> Options bar with tag cleanup toggles, output path selector, and documentation trigger
                </div>
            </figure>

            <div class="grid">
                <div class="card">
                    <h4>Fetch Cover Art</h4>
                    <p>Downloads front cover images from the Cover Art Archive (500px to 1200px) and embeds them into track tags as JPEGs.</p>
                </div>
                <div class="card">
                    <h4>Strip Junk Info</h4>
                    <p>Removes advertising comments, promotional URLs, encoder strings, and rip tags from track containers.</p>
                </div>
                <div class="card">
                    <h4>Prefer Romanized Script</h4>
                    <p>Converts non-Latin scripts (such as Kanji, Cyrillic, or Hanzi) to Latin aliases when provided by MusicBrainz.</p>
                </div>
                <div class="card">
                    <h4>Organize Files</h4>
                    <p>Sorts output files into a clean folder hierarchy: Artist / [Year] - Album / [Disc-]Track - Title.ext.</p>
                </div>
                <div class="card">
                    <h4>Rename Files to Song Title</h4>
                    <p>Sets the output filename to the clean song title and removes illegal characters like colons, quotes, and slashes.</p>
                </div>
                <div class="card">
                    <h4>Output Destination and Reset</h4>
                    <p>Click Change to export tagged files to a separate directory. Click Reset (In-Place) to write changes directly to original files.</p>
                </div>
            </div>
        </section>

        <!-- SECTION 5: CONTEXTUAL SELECT BY -->
        <section id="filters">
            <h3>5. Contextual "Select By" and Staging Filters</h3>
            <p>
                The filter bar makes it easy to work with large libraries and multi-artist collections:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_filters}" alt="Staging Filter Bar">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 5.1</span> Filter bar with text search, Select By menu, Status filter, and batch action buttons
                </div>
            </figure>

            <p>
                When a mode in the <strong>Select By</strong> menu is active, clicking any track row automatically isolates and selects all sibling tracks matching that criterion:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_select_by}" alt="Active Select By Album View">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 5.2</span> Contextual filter active on Select By: Album with isolated tracks and the Show All reset button
                </div>
            </figure>

            <ul>
                <li><strong>Select By: Artist:</strong> Click any track to select all tracks by that artist.</li>
                <li><strong>Select By: Album:</strong> Click any track to select its full album.</li>
                <li><strong>Select By: Folder:</strong> Click any track to select all tracks from the same directory.</li>
                <li><strong>Select By: Status:</strong> Click any track to select all tracks sharing that verification state.</li>
                <li><strong>Show All:</strong> Clears the active filter and restores the full list.</li>
                <li><strong>Status dropdown:</strong> Limits the view to all tracks, identified tracks, ambiguous matches, or unmatched files.</li>
                <li><strong>Filter tracks input:</strong> Filters visible rows as you type by filename, title, artist, or album.</li>
            </ul>
        </section>

        <!-- SECTION 6: CLICKABLE COLUMN SORTING -->
        <section id="sorting">
            <h3>6. Clickable Column Header Sorting</h3>
            <p>
                Every column header in the staging table sorts the active list when clicked:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_sorting}" alt="Clickable Column Sort Headers">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 6.1</span> Column headers with active sort indicator (FILE NAME &#9650;)
                </div>
            </figure>

            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Column Header</th>
                            <th>Sort Order</th>
                            <th>Cycle</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><strong>FILE NAME</strong></td>
                            <td>Alphabetical order of source filenames on disk</td>
                            <td>Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                        <tr>
                            <td><strong>ARTIST</strong></td>
                            <td>Resolved track or album artist name</td>
                            <td>Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                        <tr>
                            <td><strong>TITLE</strong></td>
                            <td>Resolved track title</td>
                            <td>Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                        <tr>
                            <td><strong>ALBUM</strong></td>
                            <td>Resolved album name</td>
                            <td>Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                        <tr>
                            <td><strong>YEAR / TRACK</strong></td>
                            <td>Release year, followed by disc and track number</td>
                            <td>Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                        <tr>
                            <td><strong>STATUS</strong></td>
                            <td>Confidence: Verified, Ambiguous, Staged, Error</td>
                            <td>Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <!-- SECTION 7: STAGING ROWS & WAVEFORMS -->
        <section id="staging">
            <h3>7. Staging Workbench Rows and Waveforms</h3>
            <p>
                Each row in the staging table represents an individual audio file:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_staging}" alt="Staging Workbench Rows">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 7.1</span> Staging table rows showing selection checkboxes, status badges, metadata fields, and acoustic waveform icons
                </div>
            </figure>

            <ul>
                <li><strong>Checkbox:</strong> Toggles inclusion in tag writing and file renaming. The header checkbox toggles all visible tracks.</li>
                <li><strong>Status badges:</strong>
                    <ul>
                        <li><span class="badge">STAGED</span>: Track loaded locally, awaiting identification or tag write.</li>
                        <li><span class="badge" style="color:var(--color-success); border-color:var(--color-success);">VERIFIED</span>: Confirmed match from MusicBrainz.</li>
                        <li><span class="badge" style="color:var(--color-warning); border-color:var(--color-warning);">AMBIGUOUS</span>: Multiple potential release matches found. Review proposed tags in the Inspector.</li>
                        <li><span class="badge" style="color:var(--text-muted);">UNMATCHED</span>: No database match found. Original local tags are kept.</li>
                    </ul>
                </li>
                <li><strong>Acoustic Waveform Icon (<code>graphic_eq</code>):</strong> The soundwave icon indicates that an acoustic fingerprint was calculated for this file.</li>
            </ul>
        </section>

        <!-- SECTION 8: INSPECTOR PANEL & COVER ART INJECTION -->
        <section id="inspector">
            <h3>8. Inspector Panel and Universal Artwork Injection</h3>
            <p>
                The right-hand panel displays artwork previews, diagnostics, and proposed tag differences for the selected track:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_inspector}" alt="Inspector Panel">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 8.1</span> Inspector panel with artwork preview, Play Track player, Replace Art (N) injection, and Metadata Diff
                </div>
            </figure>

            <div class="grid">
                <div class="card">
                    <h4>Cover Art Viewer</h4>
                    <p>Shows embedded or downloaded cover art with pixel dimensions (such as 1000 &times; 1000), format (JPEG), and file weight (66 KB).</p>
                </div>
                <div class="card">
                    <h4>PLAY TRACK Audio Player</h4>
                    <p>Click Play Track to preview the audio file before writing changes or unstaging files.</p>
                </div>
                <div class="card">
                    <h4>REPLACE ART FOR ALL TRACKS <span class="badge-new">New</span></h4>
                    <p>Select any track with good artwork, then click Replace Art (N) to inject that image across all staged tracks in the library.</p>
                </div>
                <div class="card">
                    <h4>METADATA DIFF and EDIT TRACK DATA</h4>
                    <p>Review original tags alongside proposed MusicBrainz tags, or switch to Edit Track Data to modify fields manually.</p>
                </div>
            </div>
        </section>

        <!-- SECTION 9: DUPLICATE DETECTION & CONSOLIDATION -->
        <section id="duplicates">
            <h3>9. Duplicate Detection and Smart Album Consolidation</h3>
            <p>
                Music collections frequently accumulate duplicate songs across singles, compilations, and reissues. Clicking <strong>Select Duplicates</strong> on the toolbar runs three checks:
            </p>

            <ol>
                <li><strong>Acoustic Fingerprint Hash:</strong> Matches identical audio waveforms even when track titles or filenames differ.</li>
                <li><strong>Metadata Matching:</strong> Matches normalized title, artist, and duration within a three-second window.</li>
                <li><strong>Filename Stem Normalization:</strong> Strips track numbers, disc prefixes, bitrates, and extensions to find identical tracks stored in different folders.</li>
            </ol>

            <div class="card" style="margin: 18px 0;">
                <h4>Duplicate Action Dialog Options</h4>
                <ul style="margin-top: 8px;">
                    <li><strong>Consolidate to Unique Album:</strong> Evaluates track quality across duplicates, preferring lossless formats (FLAC or WAV) over lossy formats (MP3 or M4A), and higher bitrates. It unstages redundant copies and combines all unique tracks into a single destination folder without version suffixes like (1) or (2).</li>
                    <li><strong>Unstage Duplicates Only:</strong> Keeps the highest quality version of each song and removes duplicate rows from the active table, leaving original files on disk untouched.</li>
                </ul>
            </div>
        </section>

        <!-- SECTION 10: CLEAN TRACK TITLES & BATCH EDIT -->
        <section id="cleantracks">
            <h3>10. Clean Track Titles and Batch Metadata Editing</h3>
            <p>
                Audio tracks downloaded from web sources often carry website URLs, bracketed rip tags, and promotional strings in their title fields:
            </p>

            <div class="grid">
                <div class="card">
                    <h4>CLEAN TRACK TITLES Dialog <span class="badge-new">New</span></h4>
                    <p>Click Clean Track Titles on the toolbar. Enter any search string (such as [Official Video], [320kbps], or a website name) and click Clean to remove that phrase from all selected titles.</p>
                </div>
                <div class="card">
                    <h4>EDIT ALBUM METADATA Dialog</h4>
                    <p>Updates album title, album artist, release year, genre, and total disc count across all tracks in an album simultaneously.</p>
                </div>
            </div>
        </section>

        <!-- SECTION 11: MULTI-DISC HEURISTICS & CACHE -->
        <section id="heuristics">
            <h3>11. Multi-Disc Box Set Heuristics and Local Cache</h3>
            <p>
                FXsonic v0.2.0 includes multi-disc track numbering parsers and local SQLite caching:
            </p>

            <div class="grid">
                <div class="card">
                    <h4>Multi-Disc Numbering Heuristics</h4>
                    <p>
                        Parses 3-digit and 4-digit disc prefixes (such as 101 for Disc 1, Track 01, and 204 for Disc 2, Track 04), hyphenated numbers (1-01, 2-12), and continuous numbering across multi-disc releases (where tracks 13+ on a 2-CD release map to Disc 2).
                    </p>
                </div>
                <div class="card">
                    <h4>Persistent SQLite Cache (cache.db)</h4>
                    <p>
                        Acoustic fingerprints are saved in cache.db, indexed by file path, size, and modification date. Rescanning an existing folder skips fpcalc execution and loads almost instantly.
                    </p>
                </div>
            </div>

            <h4>Status Footer and Theme Controls</h4>
            <p>
                The bottom status bar shows background task progress and theme settings:
            </p>

            <figure class="ui-figure">
                <img src="data:image/png;base64,{img_footer}" alt="Status Footer">
                <div class="ui-caption">
                    <span class="fig-badge">Figure 11.1</span> Status footer with theme toggle button, fingerprinting progress bar, telemetry counters, and status console
                </div>
            </figure>

            <ul>
                <li><strong>Theme toggle:</strong> Located on the bottom left. Click the moon or sun icon to switch themes.</li>
                <li><strong>Progress bar:</strong> Shows scan percentage and processed track counts in real time.</li>
                <li><strong>Telemetry counters:</strong> Green, orange, and gray counters track identified, ambiguous, and unmatched counts.</li>
                <li><strong>Status console:</strong> Displays the latest system event and loaded track count.</li>
            </ul>
        </section>

        <!-- SECTION 12: SHORTCUTS & FORMAT TABLE -->
        <section id="shortcuts">
            <h3>12. Keyboard Shortcuts and Supported Formats</h3>
            <p>
                Reference table for keyboard navigation, mouse interactions, and supported audio containers:
            </p>

            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Shortcut / Mouse Action</th>
                            <th>Function</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><kbd>Ctrl</kbd> + <strong>Folder Drop</strong></td>
                            <td>Append newly dropped tracks to the current workbench without clearing staged files</td>
                        </tr>
                        <tr>
                            <td><strong>Standard Folder Drop</strong></td>
                            <td>Replace staging workbench with newly dropped audio files</td>
                        </tr>
                        <tr>
                            <td><kbd>Spacebar</kbd> or <strong>Checkbox Click</strong></td>
                            <td>Toggle selection checkbox on the highlighted track</td>
                        </tr>
                        <tr>
                            <td><kbd>&uarr;</kbd> / <kbd>&darr;</kbd> <strong>Arrow Keys</strong></td>
                            <td>Move up and down through the staged track list</td>
                        </tr>
                        <tr>
                            <td><kbd>Delete</kbd></td>
                            <td>Unstage the highlighted track from the workbench</td>
                        </tr>
                        <tr>
                            <td><kbd>Enter</kbd></td>
                            <td>Open the metadata editor for the selected track</td>
                        </tr>
                        <tr>
                            <td><kbd>Escape</kbd></td>
                            <td>Cancel a running scan or write operation, or close the active dialog</td>
                        </tr>
                        <tr>
                            <td><strong>Click Column Header</strong></td>
                            <td>Toggle sort: Ascending (&#9650;) &rarr; Descending (&#9660;) &rarr; Default</td>
                        </tr>
                        <tr>
                            <td><strong>Row Click with "Select By" Active</strong></td>
                            <td>Group and select all related tracks by artist, album, folder, or status</td>
                        </tr>
                        <tr>
                            <td><strong>Click Brand Logo</strong></td>
                            <td>Toggle UI between dark mode and light mode</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <h4>Supported Audio Containers and Tag Specifications</h4>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Container Extension</th>
                            <th>Audio Format</th>
                            <th>Metadata Specification</th>
                            <th>Artwork Support</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><span class="badge">.mp3</span></td>
                            <td>MPEG-1 Audio Layer III</td>
                            <td>ID3v2.3 / ID3v2.4 (UTF-8)</td>
                            <td>Embedded APIC frame (JPEG/PNG)</td>
                        </tr>
                        <tr>
                            <td><span class="badge">.flac</span></td>
                            <td>Free Lossless Audio Codec</td>
                            <td>Vorbis Comments</td>
                            <td>Embedded FLAC Picture block</td>
                        </tr>
                        <tr>
                            <td><span class="badge">.m4a</span> / <span class="badge">.mp4</span></td>
                            <td>Advanced Audio Coding (AAC) / ALAC</td>
                            <td>MP4 iTunes Atoms</td>
                            <td>Embedded 'covr' atom</td>
                        </tr>
                        <tr>
                            <td><span class="badge">.ogg</span> / <span class="badge">.opus</span></td>
                            <td>Ogg Vorbis / Ogg Opus</td>
                            <td>Vorbis Comments</td>
                            <td>METADATA_BLOCK_PICTURE</td>
                        </tr>
                        <tr>
                            <td><span class="badge">.wav</span></td>
                            <td>Waveform Audio File Format</td>
                            <td>RIFF INFO chunk / ID3 chunk</td>
                            <td>Standard chunk tagging</td>
                        </tr>
                        <tr>
                            <td><span class="badge">.aiff</span></td>
                            <td>Audio Interchange File Format</td>
                            <td>ID3 chunk</td>
                            <td>Embedded APIC frame</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Footer -->
        <footer>
            <span>FXsonic v0.2.0 &bull; FXcodez</span>
            <a href="https://github.com/FXcodez/FXsonic" target="_blank" rel="noopener noreferrer">github.com/FXcodez/FXsonic</a>
        </footer>
    </div>
</div>

<script>
    let navCloseTimer = null;

    // Navigation Drawer Functions
    function openNavMenu() {{
        if (navCloseTimer) {{
            clearTimeout(navCloseTimer);
            navCloseTimer = null;
        }}
        const drawer = document.getElementById('navDrawer');
        const btn = document.getElementById('navToggle');
        drawer.classList.add('open');
        btn.classList.add('expanded');
        btn.setAttribute('aria-expanded', 'true');
    }}

    function scheduleCloseNavMenu() {{
        if (navCloseTimer) {{
            clearTimeout(navCloseTimer);
        }}
        navCloseTimer = setTimeout(() => {{
            closeNavMenu();
        }}, 280);
    }}

    function toggleNavMenu() {{
        const drawer = document.getElementById('navDrawer');
        if (drawer.classList.contains('open')) {{
            closeNavMenu();
        }} else {{
            openNavMenu();
        }}
    }}

    function closeNavMenu() {{
        if (navCloseTimer) {{
            clearTimeout(navCloseTimer);
            navCloseTimer = null;
        }}
        const drawer = document.getElementById('navDrawer');
        const btn = document.getElementById('navToggle');
        drawer.classList.remove('open');
        btn.classList.remove('expanded');
        btn.setAttribute('aria-expanded', 'false');
    }}

    // Auto-expand on mouseover
    const navBarHeader = document.querySelector('.nav-bar-header');
    const navDrawerElem = document.getElementById('navDrawer');

    if (navBarHeader) {{
        navBarHeader.addEventListener('mouseenter', () => {{
            openNavMenu();
        }});
        navBarHeader.addEventListener('mouseleave', () => {{
            scheduleCloseNavMenu();
        }});
    }}

    if (navDrawerElem) {{
        navDrawerElem.addEventListener('mouseenter', () => {{
            if (navCloseTimer) {{
                clearTimeout(navCloseTimer);
                navCloseTimer = null;
            }}
        }});
        navDrawerElem.addEventListener('mouseleave', () => {{
            scheduleCloseNavMenu();
        }});
    }}

    // Filter Topics within Navigation Menu
    function filterNavTopics() {{
        const input = document.getElementById('navSearch');
        const filter = input.value.toLowerCase();
        const items = document.querySelectorAll('#navGrid .nav-item');

        items.forEach(item => {{
            const text = item.textContent.toLowerCase();
            if (text.includes(filter)) {{
                item.style.display = 'flex';
            }} else {{
                item.style.display = 'none';
            }}
        }});
    }}

    // Active Topic Tracking and Scroll-to-Top Button
    window.addEventListener('scroll', () => {{
        const sections = document.querySelectorAll('section');
        const navItems = document.querySelectorAll('.nav-item');
        const topicDisplay = document.getElementById('currentTopicDisplay');
        const topBtn = document.getElementById('topBtn');

        let currentSectionId = '';
        let currentSectionTitle = '';

        sections.forEach(sec => {{
            const rect = sec.getBoundingClientRect();
            if (rect.top <= 140) {{
                currentSectionId = sec.getAttribute('id');
                const h3 = sec.querySelector('h3');
                if (h3) {{
                    currentSectionTitle = h3.textContent.trim();
                }}
            }}
        }});

        if (currentSectionTitle) {{
            topicDisplay.innerHTML = 'Topic: <strong>' + currentSectionTitle + '</strong>';
        }}

        navItems.forEach(item => {{
            item.classList.remove('active');
            if (item.getAttribute('href') === '#' + currentSectionId) {{
                item.classList.add('active');
            }}
        }});

        if (window.pageYOffset > 300) {{
            topBtn.classList.add('visible');
        }} else {{
            topBtn.classList.remove('visible');
        }}
    }});

    // Close menu when clicking outside header
    document.addEventListener('click', (e) => {{
        const header = document.querySelector('.locked-header');
        const drawer = document.getElementById('navDrawer');
        if (drawer && drawer.classList.contains('open') && header && !header.contains(e.target)) {{
            closeNavMenu();
        }}
    }});
</script>

</body>
</html>
"""

# Write to both v03/help.html and v03/Features/help.html
target_1 = BASE_DIR / "help.html"
target_2 = BASE_DIR / "Features" / "help.html"

target_1.write_text(html_content, encoding="utf-8")
print(f"Generated {target_1} ({len(html_content)} bytes)")

target_2.write_text(html_content, encoding="utf-8")
print(f"Generated {target_2} ({len(html_content)} bytes)")
