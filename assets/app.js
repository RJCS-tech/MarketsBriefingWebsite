/* Ruben's Markets Log — index page behaviour.
   Reads the JSON that build_site.py inlines into index.html (so the page
   works from file:// too — no fetch, no server needed) and renders the
   briefing calendar plus the portfolio performance card. */
(function () {
  var DATA = window.SITE_DATA;
  if (!DATA) return;

  var MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
  var DOW = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  // Dates are handled as plain 'YYYY-MM-DD' strings and UTC Date objects so
  // the grid never shifts by a day depending on the reader's timezone.
  function iso(d) { return d.toISOString().slice(0, 10); }
  function parse(s) {
    var p = s.split('-');
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
  }
  function addDays(d, n) {
    return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + n));
  }
  function mondayOf(d) {
    return addDays(d, -((d.getUTCDay() + 6) % 7)); // getUTCDay: 0=Sun
  }

  /* ---------------- Calendar ---------------- */

  var dailyBy = {};   // 'YYYY-MM-DD' -> entry
  var weeklyBy = {};  // Monday of the covered week -> entry
  DATA.briefings.forEach(function (b) {
    if (b.kind === 'weekly') weeklyBy[iso(mondayOf(parse(b.date)))] = b;
    else dailyBy[b.date] = b;
  });

  var all = DATA.briefings.map(function (b) { return b.date; }).sort();
  var first = parse(all[0]), last = parse(all[all.length - 1]);
  var minMonth = first.getUTCFullYear() * 12 + first.getUTCMonth();
  var maxMonth = last.getUTCFullYear() * 12 + last.getUTCMonth();
  var cursor = maxMonth;

  var elMonth = document.getElementById('calMonth');
  var elGrid = document.getElementById('calGrid');
  var elPrev = document.getElementById('calPrev');
  var elNext = document.getElementById('calNext');
  var elPreview = document.getElementById('calPreview');

  var todayISO = DATA.today;
  var pinned = null; // entry shown in the preview when nothing is hovered

  function showPreview(entry) {
    if (!entry) {
      elPreview.className = 'cal-preview is-empty';
      elPreview.innerHTML = '<p class="cp-kicker">No briefing</p>' +
        '<p class="cp-title">Nothing published on this date.</p>';
      return;
    }
    elPreview.className = 'cal-preview';
    elPreview.innerHTML =
      '<p class="cp-kicker">' + (entry.kind === 'weekly' ? 'Weekly report' : 'Daily brief') +
      ' &middot; ' + entry.long + '</p>' +
      '<p class="cp-title"><a href="' + entry.href + '">' + entry.headline + '</a></p>';
  }

  function renderMonth() {
    var y = Math.floor(cursor / 12), m = cursor % 12;
    elMonth.textContent = MONTHS[m] + ' ' + y;
    elPrev.disabled = cursor <= minMonth;
    elNext.disabled = cursor >= maxMonth;

    var html = '';
    DOW.forEach(function (d) { html += '<div class="cal-dow">' + d + '</div>'; });
    html += '<div class="cal-dow">wk</div>';

    var firstOfMonth = new Date(Date.UTC(y, m, 1));
    var gridStart = mondayOf(firstOfMonth);
    var daysInMonth = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    var weeks = Math.ceil(((firstOfMonth.getUTCDay() + 6) % 7 + daysInMonth) / 7);

    for (var w = 0; w < weeks; w++) {
      var rowStart = addDays(gridStart, w * 7);
      for (var i = 0; i < 7; i++) {
        var day = addDays(rowStart, i);
        var key = iso(day);
        if (day.getUTCMonth() !== m) { html += '<div class="cal-day pad"></div>'; continue; }
        var e = dailyBy[key];
        var cls = 'cal-day ' + (e ? 'has' : 'empty') + (key === todayISO ? ' today' : '');
        var num = day.getUTCDate();
        if (e) {
          html += '<a class="' + cls + '" href="' + e.href + '" data-date="' + key +
                  '" title="' + e.headline.replace(/"/g, '&quot;') + '">' +
                  num + '<span class="cal-dot"></span></a>';
        } else {
          html += '<div class="' + cls + '" data-date="' + key + '">' + num + '</div>';
        }
      }
      var wk = weeklyBy[iso(rowStart)];
      html += wk
        ? '<a class="cal-week has" href="' + wk.href + '" data-date="' + wk.date +
          '" title="' + wk.headline.replace(/"/g, '&quot;') + '">W</a>'
        : '<div class="cal-week"></div>';
    }
    elGrid.innerHTML = html;
  }

  function entryFor(el) {
    var d = el.getAttribute('data-date');
    if (!d) return null;
    return el.classList.contains('cal-week')
      ? weeklyBy[iso(mondayOf(parse(d)))]
      : dailyBy[d] || null;
  }

  elGrid.addEventListener('mouseover', function (ev) {
    var el = ev.target.closest('[data-date]');
    if (el) showPreview(entryFor(el));
  });
  elGrid.addEventListener('mouseleave', function () { showPreview(pinned); });
  elPrev.addEventListener('click', function () { cursor--; renderMonth(); });
  elNext.addEventListener('click', function () { cursor++; renderMonth(); });

  renderMonth();
  // Open on the most recent briefing so the panel is never blank.
  pinned = DATA.briefings.slice().sort(function (a, b) {
    return a.date < b.date ? 1 : -1;
  })[0];
  showPreview(pinned);

  /* ---------------- Portfolio performance ---------------- */

  var P = DATA.prices;
  if (!P || !P.tickers || !P.tickers.length) return;

  var elRows = document.getElementById('perfRows');
  var elWindow = document.getElementById('perfWindow');
  var switchBtns = Array.prototype.slice.call(
    document.querySelectorAll('#perfSwitch button'));

  // Latest date across every series — the "as of" point for all windows.
  var latestISO = '';
  P.tickers.forEach(function (t) {
    var ds = Object.keys(P.series[t.ticker] || {});
    ds.forEach(function (d) { if (d > latestISO) latestISO = d; });
  });

  function anchorFor(range) {
    var end = parse(latestISO);
    if (range === 'ytd') return iso(new Date(Date.UTC(end.getUTCFullYear(), 0, 1)));
    if (range === '1m') {
      return iso(new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - 1, end.getUTCDate())));
    }
    return iso(addDays(end, -7));
  }

  // Prices only exist on trading days, so a window's start is the last close
  // at or before the anchor (YTD falls back to the first close of the year).
  function windowSlice(series, fromISO) {
    var dates = Object.keys(series).sort();
    var startIdx = -1;
    for (var i = 0; i < dates.length; i++) {
      if (dates[i] <= fromISO) startIdx = i; else break;
    }
    if (startIdx === -1) startIdx = 0;
    return dates.slice(startIdx).map(function (d) {
      return { d: d, v: series[d] };
    });
  }

  function sparkline(points, up) {
    var w = 62, h = 22, pad = 2;
    if (points.length < 2) return '<svg class="perf-spark" viewBox="0 0 62 22"></svg>';
    var vals = points.map(function (p) { return p.v; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var span = (hi - lo) || 1;
    var d = points.map(function (p, i) {
      var x = pad + (i / (points.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (p.v - lo) / span) * (h - pad * 2);
      return (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
    }).join(' ');
    var stroke = up ? 'var(--up)' : 'var(--down)';
    return '<svg class="perf-spark" viewBox="0 0 ' + w + ' ' + h +
           '" preserveAspectRatio="none" aria-hidden="true">' +
           '<path d="' + d + '" fill="none" stroke="' + stroke +
           '" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  }

  function fmtRange(fromISO) {
    function s(x) {
      var d = parse(x);
      return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()].slice(0, 3) + ' ' + d.getUTCFullYear();
    }
    return s(fromISO) + ' → ' + s(latestISO);
  }

  function render(range) {
    var anchor = anchorFor(range);
    var html = '';
    var shownFrom = null;

    P.tickers.forEach(function (t) {
      var series = P.series[t.ticker] || {};
      var pts = windowSlice(series, anchor);
      if (pts.length < 2) {
        html += '<div class="perf-row"><span class="perf-tkr">' + t.ticker +
                '</span><span class="perf-name">' + t.short +
                '</span><span></span><span class="perf-chg flat">n/a</span></div>';
        return;
      }
      if (!shownFrom || pts[0].d < shownFrom) shownFrom = pts[0].d;
      var base = pts[0].v, now = pts[pts.length - 1].v;
      var pct = ((now / base) - 1) * 100;
      var cls = pct > 0.05 ? 'up' : (pct < -0.05 ? 'down' : 'flat');
      var sign = pct > 0 ? '+' : '';
      html += '<div class="perf-row">' +
        '<span class="perf-tkr">' + t.ticker + '</span>' +
        '<span class="perf-name" title="' + t.name + '">' + t.short + '</span>' +
        sparkline(pts, pct >= 0) +
        '<span class="perf-chg ' + cls + '">' + sign + pct.toFixed(1) + '%</span>' +
      '</div>';
    });

    elRows.innerHTML = html;
    elWindow.textContent = shownFrom ? fmtRange(shownFrom) : '';
    switchBtns.forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.range === range));
    });
  }

  switchBtns.forEach(function (b) {
    b.addEventListener('click', function () { render(b.dataset.range); });
  });
  render('ytd');
})();
