#!/usr/bin/env python3
"""
Rebuilds the entire site (index.html + briefings/*.html) from the
plain markdown files in source/.

Usage:  python3 scripts/build_site.py

Design choice: this script does NOT try to guess or fix anything —
it rebuilds every page from every source file, every run. That means
there is no "detect what's new" logic to get wrong: add a markdown
file to source/, run this script, and the whole site is consistent
again. Safe to run as many times as you like; it's fully deterministic
(same inputs always produce the same output).
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "source"
BRIEFINGS_DIR = ROOT / "briefings"
INDEX_PATH = ROOT / "index.html"
PRICES_PATH = ROOT / "data" / "prices.json"

WEEKDAY_ABBR = {
    "Monday": "MON", "Tuesday": "TUE", "Wednesday": "WED", "Thursday": "THU",
    "Friday": "FRI", "Saturday": "SAT", "Sunday": "SUN",
}
MONTH_ABBR = {
    "January": "JAN", "February": "FEB", "March": "MAR", "April": "APR",
    "May": "MAY", "June": "JUN", "July": "JUL", "August": "AUG",
    "September": "SEP", "October": "OCT", "November": "NOV", "December": "DEC",
}


def md_inline(text):
    """Convert the small set of inline markdown we use (**bold**) to HTML."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def render_block(text):
    """Turn a chunk of markdown (paragraphs + '- bullet' lines) into HTML."""
    html_parts = []
    para_buf, list_buf = [], []

    def flush_para():
        if para_buf:
            html_parts.append(f"<p>{md_inline(' '.join(para_buf))}</p>")
            para_buf.clear()

    def flush_list():
        if list_buf:
            items = "".join(f"<li>{md_inline(x)}</li>" for x in list_buf)
            html_parts.append(f"<ul>{items}</ul>")
            list_buf.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_para()
            flush_list()
        elif line.startswith("- "):
            flush_para()
            list_buf.append(line[2:].strip())
        else:
            flush_list()
            para_buf.append(line)
    flush_para()
    flush_list()
    return "\n    ".join(html_parts)


TICKER_NAMES = {
    "IAEX": "AEX index ETF",
    "EUEA": "EURO STOXX 50 ETF",
    "IWDA": "MSCI World ETF",
    "VUSA": "S&amp;P 500 ETF",
    "VHYL": "High Dividend Yield ETF",
}


def expand_tickers(text):
    """Replace ETF ticker shorthand with full names, everywhere in the source."""
    for ticker, full_name in TICKER_NAMES.items():
        text = re.sub(rf"\b{ticker}\b", full_name, text)
    return text


def parse_source(path):
    text = path.read_text(encoding="utf-8")
    text = expand_tickers(text)
    lines = text.splitlines()
    title_line = lines[0].lstrip("#").strip()

    if title_line.startswith("Daily Brief"):
        kind = "daily"
    elif title_line.startswith("Weekly Markets Report"):
        kind = "weekly"
    else:
        raise ValueError(f"{path.name}: first line must start with "
                          f"'# Daily Brief' or '# Weekly Markets Report', got: {title_line!r}")

    date_label = title_line.split("—", 1)[1].strip()
    body = "\n".join(lines[1:])

    # Pull out the italic "*Compiled from ...*" sources line, if present.
    sources_line = None
    m = re.search(r"^\*Compiled from.*\*\s*$", body, re.MULTILINE)
    if m:
        sources_line = m.group(0).strip().strip("*").strip()
        body = body[: m.start()] + body[m.end():]

    # Drop the old "Full report delivered as a .docx" boilerplate line — not relevant to the website.
    body = re.sub(r"^Full report \(with sources\).*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"^---\s*$", "", body, flags=re.MULTILINE)

    # Split on '## ' section headers.
    chunks = re.split(r"^##\s+", body, flags=re.MULTILINE)[1:]
    sections = []
    for chunk in chunks:
        header, _, rest = chunk.partition("\n")
        sections.append((header.strip(), rest.strip()))

    return kind, date_label, sections, sources_line


def build_body_html(kind, sections):
    """Returns (headline, body_html). The first section becomes the intro
    paragraph(s) directly under the headline; later sections become <h3> blocks."""
    parts = []
    first_header, first_body = sections[0]

    if kind == "daily" and ":" in first_header:
        headline = first_header.split(":", 1)[1].strip()
        headline = headline[0].upper() + headline[1:]  # source headers start lowercase after the colon
    else:
        headline = None  # weekly headline is set by the caller from the date range

    parts.append(render_block(first_body))

    for header, content in sections[1:]:
        lower = header.lower()
        if lower.startswith("key levels"):
            lines_ = [l.strip()[2:].strip() for l in content.split("\n") if l.strip().startswith("- ")]
            block = "<br>\n    ".join(md_inline(l) for l in lines_)
            parts.append(f"<h3>{header}</h3>")
            parts.append(f'<div class="levels">\n    {block}\n    </div>')
        elif lower.startswith("off the beaten path"):
            subtitle = header.split(":", 1)[1].strip() if ":" in header else header
            parts.append(f"<h3>Off the beaten path &mdash; {subtitle}</h3>")
            parts.append(f'<div class="callout">\n    {render_block(content)}\n    </div>')
        else:
            clean_header = header.split("(")[0].strip() if "(" in header else header
            parts.append(f"<h3>{clean_header}</h3>")
            parts.append(render_block(content))

    return headline, "\n    ".join(parts)


def short_date_label(date_label, kind):
    """'Tuesday, 8 September 2026' -> 'TUE 8 SEP'
       '31 August – 6 September 2026' -> '31 AUG-6 SEP'"""
    if kind == "daily":
        weekday, _, rest = date_label.partition(",")
        rest = rest.strip()
        m = re.match(r"(\d+)\s+([A-Za-z]+)", rest)
        day, month = m.group(1), m.group(2)
        return f"{WEEKDAY_ABBR.get(weekday.strip(), weekday.strip()[:3].upper())} {day} {MONTH_ABBR.get(month, month[:3].upper())}"
    else:
        # Two possible source formats:
        #   "31 August – 6 September 2026"  (both months spelled out)
        #   "24–30 August 2026"              (single shared month)
        two_month = re.match(r"(\d+)\s+([A-Za-z]+)\s*[–\-]\s*(\d+)\s+([A-Za-z]+)", date_label)
        if two_month:
            d1, m1, d2, m2 = two_month.groups()
            return f"{d1} {MONTH_ABBR.get(m1, m1[:3].upper())}-{d2} {MONTH_ABBR.get(m2, m2[:3].upper())}"
        one_month = re.match(r"(\d+)[–\-](\d+)\s+([A-Za-z]+)", date_label)
        if one_month:
            d1, d2, m1 = one_month.groups()
            abbr = MONTH_ABBR.get(m1, m1[:3].upper())
            return f"{d1}-{d2} {abbr}"
        return date_label.upper()


PAGE_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title} — Ruben's Markets Log</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="topbar">
  <a class="site-title" href="../index.html">Ruben's Markets Log</a>
  <a class="back-link" href="../index.html">&larr; all briefings</a>
</div>
<div class="page">
  <article class="entry">
    <div class="entry-kicker">
      <span class="tag {tag_class}">{tag_label}</span>
      <span>{date_label}</span>
    </div>
    <h2>{headline}</h2>

    {body_html}
{sources_html}
  </article>
  <div class="page-nav">
    {prev_html}
    {next_html}
  </div>
</div>
</body>
</html>
"""


def load_prices():
    """Price history for the portfolio panel. Optional: if data/prices.json is
    missing the panel simply renders empty rather than failing the build."""
    if not PRICES_PATH.exists():
        print(f"note: {PRICES_PATH} not found — portfolio panel will be empty")
        return {"tickers": [], "series": {}}
    return json.loads(PRICES_PATH.read_text(encoding="utf-8"))


def main():
    if not SOURCE_DIR.exists():
        sys.exit(f"No source/ folder found at {SOURCE_DIR}")

    files = sorted(SOURCE_DIR.glob("*.md"))
    if not files:
        print("No source files found — nothing to build.")
        return

    entries = []
    for f in files:
        kind, date_label, sections, sources_line = parse_source(f)
        headline, body_html = build_body_html(kind, sections)
        if kind == "weekly":
            headline = f"Weekly Markets Report — {date_label}"
        out_name = f.stem + ".html"  # e.g. 2026-09-08-daily.html
        iso_date = f.stem[:10]       # weeklies are named for the Sunday they close on
        entries.append({
            "path": out_name,
            "iso_date": iso_date,
            "kind": kind,
            "date_label": date_label,
            "short_date": short_date_label(date_label, kind),
            "headline": headline,
            "body_html": body_html,
            "sources_line": sources_line,
        })

    # entries are already in chronological order because filenames sort that way
    BRIEFINGS_DIR.mkdir(exist_ok=True)

    for i, e in enumerate(entries):
        prev_html = '<span class="disabled">&larr; previous</span>'
        next_html = '<span class="disabled">next &rarr;</span>'
        if i > 0:
            prev_html = f'<a href="../briefings/{entries[i-1]["path"]}">&larr; previous</a>'
        if i < len(entries) - 1:
            next_html = f'<a href="../briefings/{entries[i+1]["path"]}">next &rarr;</a>'

        sources_html = f'    <p class="sources">{e["sources_line"]}</p>' if e["sources_line"] else ""

        page = PAGE_SHELL.format(
            page_title=e["headline"],
            tag_class=e["kind"],
            tag_label="Weekly report" if e["kind"] == "weekly" else "Daily brief",
            date_label=e["date_label"],
            headline=e["headline"],
            body_html=e["body_html"],
            sources_html=sources_html,
            prev_html=prev_html,
            next_html=next_html,
        )
        (BRIEFINGS_DIR / e["path"]).write_text(page, encoding="utf-8")

    # ---- index.html ----
    # The landing page is a calendar + portfolio dashboard rendered client-side
    # by assets/app.js. Everything it needs is inlined here as one JSON blob, so
    # the page still works when opened straight off disk (no fetch, no server).
    site_data = {
        "today": dt.date.today().isoformat(),
        "briefings": [
            {
                "date": e["iso_date"],
                "kind": e["kind"],
                "href": f'briefings/{e["path"]}',
                "headline": e["headline"],
                "long": e["date_label"],
                "short": e["short_date"],
            }
            for e in entries
        ],
        "prices": load_prices(),
    }
    data_json = json.dumps(site_data, ensure_ascii=False, separators=(",", ":"))
    # Guard the inline <script> against a stray "</script>" inside any headline.
    data_json = data_json.replace("<", "\\u003c")

    archive_items = "\n".join(
        f'      <li><a href="briefings/{e["path"]}"><span class="idx-teaser">{e["headline"]}</span>'
        f'<span class="idx-date">{e["short_date"]}</span></a></li>'
        for e in reversed(entries)
    )
    latest_items = "\n".join(
        f'      <li><a href="briefings/{e["path"]}"><span class="l-date">{e["short_date"]}'
        f' &middot; {"Weekly" if e["kind"] == "weekly" else "Daily"}</span>{e["headline"]}</a></li>'
        for e in list(reversed(entries))[:4]
    )

    newest = entries[-1]
    counts = f'{sum(1 for e in entries if e["kind"] == "daily")} daily &middot; ' \
             f'{sum(1 for e in entries if e["kind"] == "weekly")} weekly'

    prices = site_data["prices"]
    perf_warn = ""
    if prices.get("placeholder"):
        perf_warn = ('    <p class="perf-warn">Placeholder prices &mdash; replace '
                     'data/prices.json with real closes.</p>\n')

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ruben's Markets Log</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<div class="topbar">
  <a class="site-title" href="index.html">Ruben's Markets Log</a>
</div>
<div class="page-wide">

  <header class="masthead">
    <h1>Ruben's Markets Log</h1>
    <p>Daily briefs and weekly wrap-ups tracking the Fed/ECB path, the Iran conflict, and Russia&ndash;Ukraine talks against the AEX index, EURO STOXX 50, MSCI World, S&amp;P 500 and FTSE All-World High Dividend Yield ETFs.</p>
  </header>
  <div class="masthead-meta">
    <span>{counts}</span>
    <span>Latest &mdash; {newest["short_date"]}</span>
  </div>

  <div class="dash">
    <section>
      <p class="panel-label">Briefing calendar</p>
      <div class="cal-head">
        <span class="cal-month" id="calMonth"></span>
        <span class="cal-nav">
          <button id="calPrev" type="button" aria-label="Previous month">&larr;</button>
          <button id="calNext" type="button" aria-label="Next month">&rarr;</button>
        </span>
      </div>
      <div class="cal-grid" id="calGrid"></div>
      <div class="cal-legend">
        <span><i class="swatch daily"></i> Daily brief</span>
        <span><i class="swatch weekly"></i> Weekly report (row end)</span>
      </div>
      <div class="cal-preview is-empty" id="calPreview"></div>
    </section>

    <aside>
      <p class="panel-label">Portfolio
        <span class="perf-switch" id="perfSwitch">
          <button type="button" data-range="ytd" aria-pressed="true">YTD</button>
          <button type="button" data-range="1m" aria-pressed="false">1M</button>
          <button type="button" data-range="1w" aria-pressed="false">1W</button>
        </span>
      </p>
      <div class="perf">
{perf_warn}        <p class="perf-window" id="perfWindow"></p>
        <div id="perfRows"></div>
        <p class="perf-foot">Price return in each fund's own currency &mdash; no FX,
        dividends or position sizes. Source: data/prices.json.</p>
      </div>

      <section class="latest">
        <p class="panel-label">Latest</p>
        <ol>
{latest_items}
        </ol>
      </section>
    </aside>
  </div>

  <details class="archive">
    <summary>Full archive &mdash; all {len(entries)} briefings</summary>
    <ul class="index-list">
{archive_items}
    </ul>
  </details>

</div>
<script id="site-data" type="application/json">{data_json}</script>
<script>window.SITE_DATA = JSON.parse(document.getElementById('site-data').textContent);</script>
<script src="assets/app.js"></script>
</body>
</html>
"""
    INDEX_PATH.write_text(index_html, encoding="utf-8")

    print(f"Built {len(entries)} pages + index.html")


if __name__ == "__main__":
    main()
