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


AMP_RE = re.compile(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+);)")


def esc_amp(text):
    """Escape bare ampersands while leaving real entities (&amp;, &ndash;) alone."""
    return AMP_RE.sub("&amp;", text)


def md_inline(text):
    """Convert the small set of inline markdown we use (**bold**) to HTML."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc_amp(text))


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


def slugify(text):
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:48] or "section"


# Instruments we recognise at the start of a "Key levels" item, longest first
# so "Brent crude" wins over "Brent" and "Euro Stoxx 50" over "Stoxx 50".
INSTRUMENTS = sorted([
    "S&amp;P 500", "S&P 500", "Nasdaq", "Dow", "Euro Stoxx 50", "Stoxx 50", "DAX", "AEX",
    "US 10Y", "US 2Y", "Japan 10Y", "Fed funds", "Brent crude", "Brent",
    "Gold", "EUR/USD", "DXY", "ECB deposit rate", "WTI",
], key=len, reverse=True)

# A signed percentage, but only when the sign starts a token — this must not
# match the "-4.92%" inside a range like "4.90-4.92%".
PCT_RE = re.compile(r"(?<![\w.,])([+-]\d+(?:\.\d+)?%)")


def colour_pcts(text):
    def repl(m):
        val = m.group(1)
        cls = "up" if val.startswith("+") else "down"
        return f'<span class="pct {cls}">{val}</span>'
    return PCT_RE.sub(repl, text)


def render_levels(content):
    """The weekly 'Key levels' block. Each '- ' line holds one theme, sometimes
    with several instruments separated by ' | '. Split those into labelled rows
    and pull a trailing ' — ...' commentary out as a note for the group, so the
    numbers stay scannable and the prose doesn't get glued onto the last row."""
    rows = []
    for raw in content.split("\n"):
        line = raw.strip()
        if not line.startswith("- "):
            continue
        items = [x.strip() for x in line[2:].split(" | ")]

        note = None
        if len(items) > 1 and " — " in items[-1]:
            items[-1], _, note = items[-1].partition(" — ")
            items[-1] = items[-1].strip()

        group = []
        for item in items:
            label, value = None, item
            for name in INSTRUMENTS:
                if item.startswith(name + " "):
                    label, value = name, item[len(name):].strip()
                    break
            label_html = f'<span class="lv-label">{esc_amp(label)}</span>' if label else \
                         '<span class="lv-label lv-none"></span>'
            group.append(f'<div class="lv-row">{label_html}'
                         f'<span class="lv-val">{colour_pcts(md_inline(value))}</span></div>')
        if note:
            group.append(f'<p class="lv-note">{colour_pcts(md_inline(note.strip()))}</p>')
        rows.append('<div class="lv-group">' + "".join(group) + "</div>")
    return '<div class="levels">' + "\n    ".join(rows) + "</div>"


def reading_time(sections):
    words = sum(len(body.split()) for _, body in sections)
    return max(1, round(words / 220))


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
    """Returns (headline, body_html, toc). The first section is the lead — it sits
    directly under the headline with no heading of its own; the rest become
    numbered sections. Section order is fixed by the source format (daily: top
    story / markets / also in the news / off the beaten path; weekly: summary /
    key levels / portfolio / watch next week), so numbering them is stable."""
    parts = []
    toc = []
    first_header, first_body = sections[0]

    if kind == "daily" and ":" in first_header:
        headline = first_header.split(":", 1)[1].strip()
        headline = headline[0].upper() + headline[1:]  # source headers start lowercase after the colon
        lead_label = first_header.split(":", 1)[0].strip()
    else:
        headline = None  # weekly headline is set by the caller from the date range
        lead_label = first_header

    lead_id = slugify(lead_label)
    toc.append((lead_id, esc_amp(lead_label)))
    parts.append(f'<section class="entry-lead" id="{lead_id}">')
    parts.append(render_block(first_body))
    parts.append("</section>")

    for n, (header, content) in enumerate(sections[1:], start=2):
        lower = header.lower()
        num = f"{n:02d}"

        if lower.startswith("key levels"):
            label = "Key levels"
            sid = slugify(label)
            period = header.split("(", 1)[1].rstrip(")") if "(" in header else ""
            parts.append(f'<section class="sec sec-levels" id="{sid}">')
            parts.append(f'<h3><span class="sec-num">{num}</span>{esc_amp(label)}'
                         + (f'<span class="sec-note">{esc_amp(period)}</span>' if period else "")
                         + "</h3>")
            parts.append(render_levels(content))
            parts.append("</section>")

        elif lower.startswith("off the beaten path"):
            label = "Off the beaten path"
            sid = slugify(label)
            subtitle = header.split(":", 1)[1].strip() if ":" in header else ""
            parts.append(f'<section class="sec" id="{sid}">')
            parts.append(f'<h3><span class="sec-num">{num}</span>{label}</h3>')
            parts.append('<div class="callout">')
            if subtitle:
                parts.append(f'<p class="callout-sub">{esc_amp(subtitle)}</p>')
            parts.append(render_block(content))
            parts.append("</div>")
            parts.append("</section>")

        else:
            # "Portfolio implications (Ruben's ETFs: ...)" -> keep the parenthetical
            # as a small note rather than dropping it on the floor.
            label = header.split("(")[0].strip() if "(" in header else header
            aside = header.split("(", 1)[1].rstrip(")") if "(" in header else ""
            sid = slugify(label)
            extra = " sec-watch" if lower.startswith("watch next") else ""
            extra += " sec-portfolio" if lower.startswith("portfolio implications") else ""
            parts.append(f'<section class="sec{extra}" id="{sid}">')
            parts.append(f'<h3><span class="sec-num">{num}</span>{esc_amp(label)}'
                         + (f'<span class="sec-note">{esc_amp(aside)}</span>' if aside else "")
                         + "</h3>")
            parts.append(render_block(content))
            parts.append("</section>")

        toc.append((sid, esc_amp(label)))

    return headline, "\n    ".join(parts), toc


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
<div class="progress"><span id="progressBar"></span></div>
<div class="topbar">
  <a class="site-title" href="../index.html">Ruben's Markets Log</a>
  <a class="back-link" href="../index.html">&larr; all briefings</a>
</div>
<div class="article-shell">

  <aside class="rail">
    <div class="rail-sticky">
      <p class="rail-label">In this briefing</p>
      <ol class="toc" id="toc">
{toc_html}
      </ol>
    </div>
  </aside>

  <div class="article-col">
    <article class="entry">
      <header class="entry-head">
        <div class="entry-kicker">
          <span class="tag {tag_class}">{tag_label}</span>
          <span>{date_label}</span>
          <span class="kicker-sep">&middot;</span>
          <span>{read_time} min read</span>
        </div>
        <h2>{headline}</h2>
      </header>

      {body_html}
{sources_html}
    </article>
{related_html}
    <nav class="entry-nav">
      {prev_html}
      {next_html}
    </nav>
  </div>

</div>
<script src="../assets/article.js"></script>
</body>
</html>
"""


def nav_card(entry, direction):
    """Prev/next as a card carrying the actual headline — 'previous' on its own
    tells you nothing about whether it is worth clicking."""
    if entry is None:
        return f'<span class="nav-card disabled">{direction}</span>'
    arrow = "&larr;" if direction == "previous" else "&rarr;"
    label = f"{arrow} {direction}" if direction == "previous" else f"{direction} {arrow}"
    return (f'<a class="nav-card nav-{direction}" href="../briefings/{entry["path"]}">'
            f'<span class="nav-dir">{label}</span>'
            f'<span class="nav-title">{entry["headline"]}</span></a>')


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
        headline, body_html, toc = build_body_html(kind, sections)
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
            "toc": toc,
            "read_time": reading_time(sections),
            "sources_line": sources_line,
        })

    # entries are already in chronological order because filenames sort that way
    BRIEFINGS_DIR.mkdir(exist_ok=True)

    # Weeklies are named for the Sunday they close on, so a briefing and the
    # weekly covering it share a Monday. That mapping drives the "related" block.
    def monday_of(iso):
        d = dt.date.fromisoformat(iso)
        return (d - dt.timedelta(days=d.weekday())).isoformat()

    weekly_by_monday = {monday_of(e["iso_date"]): e
                        for e in entries if e["kind"] == "weekly"}
    dailies_by_monday = {}
    for e in entries:
        if e["kind"] == "daily":
            dailies_by_monday.setdefault(monday_of(e["iso_date"]), []).append(e)

    for i, e in enumerate(entries):
        prev_e = entries[i - 1] if i > 0 else None
        next_e = entries[i + 1] if i < len(entries) - 1 else None

        toc_html = "\n".join(
            f'        <li><a href="#{sid}"><span class="toc-num">{n:02d}</span>{label}</a></li>'
            for n, (sid, label) in enumerate(e["toc"], start=1)
        )

        sources_html = f'      <p class="sources">{e["sources_line"]}</p>' if e["sources_line"] else ""

        # Related: a daily points at its weekly wrap-up, a weekly at its dailies.
        mon = monday_of(e["iso_date"])
        related = []
        if e["kind"] == "daily":
            wk = weekly_by_monday.get(mon)
            if wk:
                related.append((wk, "Weekly wrap-up for this week"))
        else:
            for d in dailies_by_monday.get(mon, []):
                related.append((d, d["short_date"]))

        related_html = ""
        if related:
            items = "\n".join(
                f'        <li><a href="../briefings/{r["path"]}">'
                f'<span class="rel-tag">{tag}</span>'
                f'<span class="rel-title">{r["headline"]}</span></a></li>'
                for r, tag in related
            )
            heading = ("Weekly wrap-up" if e["kind"] == "daily"
                       else "Daily briefs from this week")
            related_html = ('    <section class="related">\n'
                            f'      <p class="rail-label">{heading}</p>\n'
                            f'      <ul>\n{items}\n      </ul>\n'
                            '    </section>\n')

        page = PAGE_SHELL.format(
            page_title=e["headline"],
            tag_class=e["kind"],
            tag_label="Weekly report" if e["kind"] == "weekly" else "Daily brief",
            date_label=e["date_label"],
            read_time=e["read_time"],
            headline=e["headline"],
            body_html=e["body_html"],
            toc_html=toc_html,
            sources_html=sources_html,
            related_html=related_html,
            prev_html=nav_card(prev_e, "previous"),
            next_html=nav_card(next_e, "next"),
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
