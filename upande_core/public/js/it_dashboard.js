/* IT dashboard (/it-dashboard) and app store (/app-store). Plain JS on the shared Upande v2 design (it-v2.css).
 * Everything from the server goes in through textContent, never innerHTML. */
(function () {
  'use strict';
  var BASE = '/api/method/';
  var boot = document.getElementById('itd-boot');
  var DEV = boot.getAttribute('data-developer') === '1';
  var STORE = boot.getAttribute('data-page') === 'store';
  var IT = boot.getAttribute('data-it') === '1';
  var view = document.getElementById('view');
  var main = document.getElementById('ph-main');
  var root = document.getElementById('ph2');
  var timer = null;
  var appName = '';
  var appList = [];
  var SVG = 'http://www.w3.org/2000/svg';

  /* ---------- helpers ---------- */
  function flat(list) { return list == null ? [] : [].concat.apply([], [].concat(list).map(function (x) { return Array.isArray(x) ? flat(x) : [x]; })); }  // children may be nested lists
  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.className = v;
      else if (k === 'value') el.value = v;
      else el.setAttribute(k, v === true ? '' : v);
    });
    flat(kids).forEach(function (c) {
      if (c == null || c === false) return;
      el.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
    });
    return el;
  }
  function icon(paths) {
    var s = document.createElementNS(SVG, 'svg');
    s.setAttribute('class', 'ph-ic');
    s.setAttribute('viewBox', '0 0 24 24');
    paths.forEach(function (d) { var p = document.createElementNS(SVG, 'path'); p.setAttribute('d', d); s.appendChild(p); });
    return s;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  var afterMount = [];  // run once the screen is on the page (search boxes taking back focus)
  function mount(nodes, force) {
    nodes = [].concat(nodes).filter(Boolean);
    // While a search is reloading the screen, a loading placeholder would tear the search box out from under the typist
    // (and lose the keys typed meanwhile): the old rows stay until the new screen, which has the box again, is ready.
    if (!force && searchHand && Date.now() - searchHand.at < 10000 && searchHand.screen === (location.hash || '#/overview').slice(2).split('?')[0].split('/')[0]) {
      var keeps = nodes.some(function (n) { return n.querySelector && [].some.call(n.querySelectorAll('input[type=search]'), function (i) { return i.placeholder === searchHand.ph; }); });
      if (!keeps && view.querySelector('input[type=search]')) return;
    }
    clear(view);
    nodes.forEach(function (n) { view.appendChild(n); });
    var todo = afterMount; afterMount = [];
    todo.forEach(function (fn) { fn(); });
  }
  function qs(o) { return Object.keys(o || {}).filter(function (k) { return o[k] !== '' && o[k] != null; }).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(o[k]); }).join('&'); }
  var renderSeq = 0;  // bumped by every render: an answer for an older screen is dropped, never painted over a newer one
  function call(fn, params, post) {
    var mine = renderSeq;
    // Where each call lives: the mobile screens and the people, role and permission screens are in this app, and the app
    // store's list and download stay with the upande_mobile app that owns the APKs.
    var parts = fn.indexOf('.') < 0 ? ['mobile', fn] : fn.split('.');
    var mod = parts[0] === 'itdesk' ? 'mobile' : parts[0];
    var url = BASE + (mod === 'store' ? 'upande_mobile.api.store.' : 'upande_core.it_dashboard.' + mod + '.') + parts[1];
    var opts = { credentials: 'same-origin', headers: { Accept: 'application/json' } };
    var q = qs(params);
    if (post) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/x-www-form-urlencoded';
      opts.headers['X-Frappe-CSRF-Token'] = boot.getAttribute('data-csrf') || '';
      opts.body = q;
    } else if (q) url += '?' + q;
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!post && mine !== renderSeq) return new Promise(function () { /* superseded by a newer screen */ });
        if (!r.ok) {
          var msg = 'Something went wrong (' + r.status + ').';
          try { var m = JSON.parse(j._server_messages || '[]'); if (m.length) msg = JSON.parse(m[0]).message || msg; } catch (e) { /* keep */ }
          if (r.status === 401 || r.status === 403) msg = 'You do not have access to this.';
          throw new Error(msg.replace(/<[^>]+>/g, ''));
        }
        return j.message;
      });
    });
  }
  function toast(text, kind) {
    // inside the dashboard wrapper: the colour and spacing tokens are defined there, so a toast placed on <body>
    // had no background and white text on a white page (invisible)
    var box = (root || document.body).querySelector('.ph-toasts');
    if (!box) { box = h('div', { class: 'ph-toasts' }); (root || document.body).appendChild(box); }
    var t = h('div', { class: 'ph-toast' + (kind ? ' ph-toast--' + kind : ''), role: 'status' }, text);
    box.appendChild(t);
    setTimeout(function () { t.classList.add('is-out'); setTimeout(function () { t.remove(); }, 250); }, 3500);
  }
  function fail(e) { toast(e.message || String(e), 'bad'); }
  function parse(ts) { return ts ? new Date(String(ts).replace(' ', 'T')) : null; }
  function ago(ts) {
    var d = parse(ts);
    if (!d || isNaN(d)) return '—';
    var s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 90) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    var n = Math.round(s / 86400);
    return n + (n === 1 ? ' day ago' : ' days ago');
  }
  function dateOnly(ts) { var d = parse(ts); return d && !isNaN(d) ? d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function days(n) { return n == null ? '—' : (n === 0 ? 'today' : plural(n, 'day')); }
  function dash(v) { return v ? v : h('span', { class: 'ph-muted' }, '—'); }

  /* ---------- design-system components ---------- */
  function badge(text, kind) { return h('span', { class: 'ph-badge' + (kind ? ' ph-badge--' + kind : '') }, text); }
  function head(eyebrow, title, sub, tools) {
    return h('header', { class: 'ph-head' }, [h('div', {}, [h('div', { class: 'ph-head__eyebrow' }, eyebrow), h('h1', { class: 'ph-head__title' }, title), sub ? h('p', { class: 'ph-head__sub' }, sub) : null]), tools ? h('div', { class: 'ph-head__tools' }, tools) : null]);
  }
  function kpis(list) {
    return h('section', { class: 'ph-kpis' }, list.map(function (k) {
      return h('div', { class: 'ph-kpi' + (k.dark ? ' ph-kpi--dark' : '') + (k.onClick ? ' is-link' : '') + (k.active ? ' is-on' : ''), onclick: k.onClick || null }, [
        h('div', { class: 'ph-kpi__label' }, k.label), h('div', { class: 'ph-kpi__value' }, String(k.value)), k.unit ? h('div', { class: 'ph-kpi__unit' }, k.unit) : null
      ]);
    }));
  }
  function pills(options, value, onChange) {
    return h('div', { class: 'ph-pills' }, options.map(function (o) {
      return h('button', { type: 'button', class: o[0] === value ? 'is-on' : '', onclick: function () { onChange(o[0]); } }, [o[1], o[2] != null ? h('span', { class: 'ph-tab__count' }, String(o[2])) : null]);
    }));
  }
  function select(options, value, onChange, label) {
    var s = h('select', { class: 'ph-select', 'aria-label': label || '', onchange: function () { onChange(s.value); } }, options.map(function (o) { return h('option', { value: o[0] }, o[1]); }));
    s.value = value || '';
    return s;
  }
  function appSelect() {
    return select([['', 'All apps']].concat(appList.map(function (a) { return [a, a]; })), appName, function (v) { appName = v; go((location.hash || '#/overview').slice(2)); }, 'App');
  }
  /* A search box that searches as you type: a short pause after the last key, or Enter at once. The screen is rebuilt for the
     new results, so the box hands its focus, caret and any keys typed meanwhile to its successor. `narrow(term)` (optional)
     filters the rows already on the page on every key, before the server answers. */
  var searchHand = null;  // {ph, v, at, screen}: what the box being replaced had typed in it
  function searchState(ph, v) { return { ph: ph, v: v, at: Date.now(), screen: (location.hash || '#/overview').slice(2).split('?')[0].split('/')[0] }; }
  var searchOwn = false;  // set while a search itself moves the page, so go() keeps the hand-over
  function searchBox(placeholder, value, onSearch, narrow) {
    var timer = null, last = String(value || '').trim();
    var i = h('input', { type: 'search', placeholder: placeholder, 'aria-label': placeholder, value: value || '', autocomplete: 'off' });
    function fire() {
      clearTimeout(timer);
      var v = i.value.trim();
      if (v === last) return;
      last = v;
      searchHand = searchState(placeholder, i.value);
      searchOwn = true;
      try { onSearch(v); } finally { searchOwn = false; }
    }
    i.addEventListener('input', function () {
      searchHand = searchState(placeholder, i.value);
      if (narrow) narrow(i.value.trim().toLowerCase());
      clearTimeout(timer);
      timer = setTimeout(fire, 350);
    });
    i.addEventListener('keydown', function (e) { if (e.key === 'Enter') fire(); });
    i.addEventListener('search', function () { if (!i.value) fire(); });  // the browser's clear (x) button
    if (searchHand && searchHand.ph === placeholder) {
      var typed = searchHand.v;
      searchHand = null;
      i.value = typed;
      var restored = false;
      var restore = function () {
        if (restored || !i.isConnected) return;
        restored = true;
        i.focus();
        try { i.setSelectionRange(typed.length, typed.length); } catch (e) { /* type=search keeps its caret */ }
        if (typed.trim() !== last) { searchHand = searchState(placeholder, typed); timer = setTimeout(fire, 0); }
      };
      afterMount.push(restore);  // mount() runs it the moment the box is on the page, so no key lands in between
      setTimeout(restore, 0);
    }
    return h('label', { class: 'ph-search' }, [icon(['M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16z', 'M21 21l-4.35-4.35']), i]);
  }
  function search(placeholder, value, onSearch) { return searchBox(placeholder, value, onSearch); }
  function filters(nodes) { return h('div', { class: 'ph-filters' }, nodes); }
  function card(title, meta, body, flush) {
    return h('section', { class: 'ph-card' + (flush ? ' ph-card--flush' : '') }, [
      title ? h('div', { class: 'ph-card__head' }, [h('div', { class: 'ph-card__title' }, title), meta ? h('div', { class: 'ph-card__meta' }, meta) : null]) : null
    ].concat(body));
  }
  function table(cols, rows) {
    return h('div', { class: 'ph-table-wrap' }, h('table', { class: 'ph-table' }, [
      h('thead', {}, h('tr', {}, cols.map(function (c) { return h('th', { class: c.num ? 'is-num' : '' }, c.label); }))),
      h('tbody', {}, rows)
    ]));
  }
  function empty(title, text) {
    return h('div', { class: 'ph-empty' }, [h('div', { class: 'ph-empty__icon' }, icon(['M20 6L9 17l-5-5'])), h('div', { class: 'ph-empty__title' }, title), text ? h('div', { class: 'ph-empty__text' }, text) : null]);
  }
  function errState(e) {
    return h('div', { class: 'ph-empty ph-empty--error' }, [h('div', { class: 'ph-empty__icon' }, icon(['M12 8v5', 'M12 16h.01'])), h('div', { class: 'ph-empty__title' }, 'Couldn’t load this'), h('div', { class: 'ph-empty__text' }, e.message || String(e))]);
  }
  var openDrawer = null;
  function drawer(title, sub, body) {
    if (openDrawer) openDrawer();
    var overlay, onKey = function (e) { if (e.key === 'Escape') close(); };
    function close() { document.removeEventListener('keydown', onKey); if (overlay) overlay.remove(); overlay = null; openDrawer = null; }
    overlay = h('div', { class: 'ph-overlay ph-overlay--drawer', onclick: function (e) { if (e.target === overlay) close(); } },
      h('div', { class: 'ph-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, [
        h('div', { class: 'ph-modal__head' }, [h('div', { style: 'min-width:0' }, [h('div', { class: 'ph-modal__title' }, title), sub ? h('div', { class: 'ph-modal__sub' }, sub) : null]), h('button', { class: 'ph-iconbtn ph-iconbtn--flat ph-iconbtn--sm', type: 'button', 'aria-label': 'Close', onclick: close }, icon(['M18 6L6 18', 'M6 6l12 12']))]),
        h('div', { class: 'ph-modal__body' }, body)
      ]));
    root.appendChild(overlay);
    document.addEventListener('keydown', onKey);
    openDrawer = close;
    return close;
  }
  /* a confirmation in the page's own modal instead of the browser's dialog: ask(title, text, buttonLabel, danger, onYes) */
  function ask(title, text, label, danger, onYes) {
    var overlay, onKey = function (e) { if (e.key === 'Escape') done(); };
    function done() { document.removeEventListener('keydown', onKey); if (overlay) overlay.remove(); overlay = null; }
    var yes = h('button', { class: 'ph-btn ' + (danger ? 'ph-btn--danger' : 'ph-btn--primary'), type: 'button', onclick: function () { done(); onYes(); } }, label || 'Confirm');
    overlay = h('div', { class: 'ph-overlay', onclick: function (e) { if (e.target === overlay) done(); } },
      h('div', { class: 'ph-modal', role: 'alertdialog', 'aria-modal': 'true', 'aria-label': title, style: 'width:min(440px,100%)' }, [
        h('div', { class: 'ph-modal__head' }, h('div', { class: 'ph-modal__title' }, title)),
        h('div', { class: 'ph-modal__body' }, h('div', {}, text)),
        h('div', { class: 'ph-modal__foot' }, [h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: done }, 'Cancel'), yes])
      ]));
    root.appendChild(overlay);
    document.addEventListener('keydown', onKey);
    yes.focus();
  }
  function kvList(pairs, monoValues) {
    var kv = h('dl', { class: 'ph-kv' });
    pairs.forEach(function (p) { if (p[1] == null || p[1] === '') return; kv.appendChild(h('dt', {}, p[0])); kv.appendChild(h('dd', monoValues ? { class: 'ph-mono' } : {}, String(p[1]))); });
    return kv;
  }
  function who(name, sub) { return h('div', {}, [h('div', { class: 'is-strong ph-strong' }, name), h('div', { class: 'ph-muted', style: 'font-size:12px' }, sub)]); }
  function progress(pct) { return h('div', { class: 'ph-progress' + (pct >= 80 ? ' ph-progress--good' : pct >= 50 ? ' ph-progress--warn' : ' ph-progress--bad') }, h('i', { style: 'width:' + pct + '%' })); }
  function mono(v) { return v ? h('span', { class: 'ph-mono' }, v) : h('span', { class: 'ph-muted' }, '—'); }
  function markUpdated() {
    var u = document.getElementById('ph-updated');
    if (!u) return;
    u.hidden = false;
    u.textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  /* ---------- routing ---------- */
  var TITLES = { overview: 'Overview', updates: 'Updates', devices: 'Devices', crashlytics: 'Crashlytics', support: 'Support', apps: 'Apps', users: 'User management', roles: 'Role management', permissions: 'Doctype permissions', userperms: 'User permissions' };
  function route() {
    var p = (location.hash || '#/overview').slice(2).split('?');
    var q = new URLSearchParams(p[1] || '');
    appName = q.get('app') || '';  // the app filter lives in the address, like every other filter
    return { parts: p[0].split('/').map(decodeURIComponent), q: q };
  }
  // The app filter rides along on every move, so a reload or a shared link keeps it.
  function go(path) {
    if (!searchOwn) searchHand = null;
    var p = String(path).split('?');
    var q = new URLSearchParams(p[1] || '');
    q.delete('app');
    if (appName) q.set('app', appName);
    var next = '#/' + p[0] + (q.toString() ? '?' + q.toString() : '');
    if (location.hash === next) render(); else location.hash = next;
  }
  function setCount(key, n) {
    var el = document.getElementById('count-' + key);
    if (!el) return;
    el.textContent = n > 99 ? '99+' : String(n);
    el.hidden = !n;
  }
  function refreshCounts() {
    return call('today').then(function (d) {
      var by = {};
      d.cards.forEach(function (c) { by[c.key] = c.count; });
      ['updates', 'support', 'crashlytics'].forEach(function (k) { setCount(k, by[k] || 0); });
      return d;
    }).catch(function () { /* counts are a convenience */ });
  }
  function render() {
    renderSeq++;
    clearInterval(timer);
    if (openDrawer) openDrawer();
    var r = route();
    var key = TITLES[r.parts[0]] ? r.parts[0] : 'overview';
    [].forEach.call(document.querySelectorAll('.ph-side__item[data-route]'), function (a) {
      var on = a.getAttribute('data-route') === key;
      a.classList.toggle('is-on', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    document.getElementById('crumb').textContent = TITLES[key];
    var pg = document.querySelector('.ph-page');
    if (pg) pg.classList.toggle('ph-page--wide', key === 'support');
    root.classList.remove('is-drawer-open');
    var screens = { overview: overview, updates: updates, devices: devices, crashlytics: crashlytics, support: support, apps: apps, users: users, roles: roleScreen, permissions: permScreen, userperms: userPermScreen };
    Promise.resolve(screens[key](r)).then(markUpdated).catch(function (e) { mount(errState(e), true); });
    if (key !== 'overview') refreshCounts();
  }

  /* ---------- Overview ---------- */
  function cardCopy(c) {
    var d = c.detail || {};
    if (c.key === 'updates') {
      var parts = [];
      if (d.forgot) parts.push(plural(d.forgot, 'person', 'people') + ' just need to reopen the app');
      if (d.cant_update) parts.push(plural(d.cant_update, 'person', 'people') + ' waiting for the new install');
      return ['People on an old version', parts.join(' · ') + (d.oldest_days ? ' · the release is ' + days(d.oldest_days) + ' old' : ''), 'Open the chase list'];
    }
    if (c.key === 'support') return ['Waiting for an answer', 'The longest wait is ' + plural(d.oldest_hours || 0, 'hour') + ' (' + (d.oldest_user || 'someone') + ')', 'Open the inbox'];
    if (c.key === 'crashlytics') return ['Open issues in the last 2 days', plural(d.people || 0, 'person', 'people') + ' affected' + (d.crashes ? ' · ' + plural(d.crashes, 'crash', 'crashes') : ''), 'Open Crashlytics'];
    if (c.key === 'devices') {
      var bits = [];
      if (d.low_battery) bits.push(d.low_battery + ' low battery');
      if (d.low_storage) bits.push(d.low_storage + ' low storage');
      if (d.offline) bits.push(d.offline + ' offline');
      if (d.outdated_os) bits.push(d.outdated_os + ' old system');
      return ['Devices needing a look', bits.join(' · '), 'Open the devices'];
    }
    return ['Not seen for a long time', 'These people have not opened the app in a while', 'See who'];
  }
  function stat(label, value, unit, extra) {
    var k = { label: label, value: value, unit: unit };
    Object.keys(extra || {}).forEach(function (x) { k[x] = extra[x]; });
    return k;
  }
  /* charts: plain SVG / divs drawn with the design tokens, no library */
  function svgEl(tag, attrs) {
    var el = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }
  function legend(items) {
    return h('div', { class: 'ph-legend ph-mt' }, items.map(function (i) {
      return h('span', {}, [h('i', { class: 'is-bar', style: 'background:' + i[1] }), i[0]]);
    }));
  }
  function hbars(rows) {
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; }).concat([1]));
    return rows.map(function (r) {
      return h('div', { class: 'ph-hb' }, [h('div', { class: 'ph-hb__name' }, r.label), h('div', { class: 'ph-hb__lane' }, h('div', { class: 'ph-hb__act' + (r.cls ? ' ' + r.cls : ''), style: 'width:' + Math.round(r.value * 100 / max) + '%' })), h('div', { class: 'ph-hb__pct' }, String(r.value))]);
    });
  }
  function stackedRows(rows, parts) {
    return h('div', {}, rows.map(function (r) {
      var total = parts.reduce(function (a, p) { return a + (r.segs[p.key] || 0); }, 0);
      return h('div', { class: 'ph-hb', style: 'grid-template-columns:minmax(90px,150px) minmax(0,1fr) 48px' }, [
        h('div', { class: 'ph-hb__name', title: r.label }, r.label),
        h('div', { style: 'display:flex;height:16px;border-radius:var(--r-pill);overflow:hidden;background:var(--tint)' }, parts.map(function (p) {
          var v = r.segs[p.key] || 0;
          return v ? h('span', { title: p.label + ': ' + v, style: 'width:' + (v * 100 / total) + '%;background:' + p.color }) : null;
        })),
        h('div', { class: 'ph-hb__pct' }, String(total))
      ]);
    }));
  }
  function columns(days, parts) {
    var W = 640, H = 190, L = 28, B = 22, T = 8, n = days.length, bw = (W - L) / n;
    var max = Math.max.apply(null, days.map(function (d) { return parts.reduce(function (a, p) { return a + d[p.key]; }, 0); }).concat([1]));
    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': 'Events per day', style: 'display:block' });
    [0, 0.5, 1].forEach(function (f) {
      var y = T + (H - B - T) * (1 - f);
      svg.appendChild(svgEl('line', { x1: L, x2: W, y1: y, y2: y, stroke: 'var(--hairline-2)', 'stroke-width': 1 }));
      var t = svgEl('text', { x: L - 6, y: y + 4, 'text-anchor': 'end', 'font-size': 10, fill: 'var(--ink-mute)' });
      t.textContent = String(Math.round(max * f));
      svg.appendChild(t);
    });
    days.forEach(function (d, i) {
      var y = H - B, x = L + i * bw + bw * 0.18, w = bw * 0.64, tip = d.day + ': ';
      parts.forEach(function (p) {
        var v = d[p.key];
        if (!v) return;
        var hh = (H - B - T) * v / max;
        y -= hh;
        var r = svgEl('rect', { x: x, y: y, width: w, height: hh, rx: 2, style: 'fill:' + p.color });
        var title = svgEl('title');
        title.textContent = d.day + ' · ' + p.label + ': ' + v;
        r.appendChild(title);
        svg.appendChild(r);
      });
      if (i % 2 === (n - 1) % 2) {
        var t = svgEl('text', { x: x + w / 2, y: H - 6, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--ink-mute)' });
        t.textContent = d.day.slice(5);
        svg.appendChild(t);
      }
    });
    return svg;
  }
  function donut(segs, centre, sub) {
    var total = segs.reduce(function (a, x) { return a + x.value; }, 0);
    var svg = svgEl('svg', { viewBox: '0 0 42 42', width: 150, height: 150, role: 'img', 'aria-label': 'Tickets by status' });
    svg.appendChild(svgEl('circle', { cx: 21, cy: 21, r: 15.9155, fill: 'none', stroke: 'var(--tint)', 'stroke-width': 5 }));
    var off = 25;
    segs.forEach(function (x) {
      if (!x.value) return;
      var len = x.value * 100 / total;
      var c = svgEl('circle', { cx: 21, cy: 21, r: 15.9155, fill: 'none', 'stroke-width': 5, 'stroke-dasharray': len + ' ' + (100 - len), 'stroke-dashoffset': off, style: 'stroke:' + x.color });
      var t = svgEl('title'); t.textContent = x.label + ': ' + x.value; c.appendChild(t);
      svg.appendChild(c);
      off -= len;
    });
    var n = svgEl('text', { x: 21, y: 23, 'text-anchor': 'middle', 'font-size': 8, 'font-weight': 600, fill: 'var(--ink)' }); n.textContent = centre; svg.appendChild(n);
    var m = svgEl('text', { x: 21, y: 28.5, 'text-anchor': 'middle', 'font-size': 3.2, fill: 'var(--ink-mute)' }); m.textContent = sub; svg.appendChild(m);
    return svg;
  }
  function overview() {
    mount([
      head('IT dashboard', 'Overview', 'Loading…'),
      filters([appSelect()]),
      h('section', { class: 'ph-kpis is-loading' }, ['People', 'Devices', 'Adoption', 'Open tickets'].map(function (l) { return h('div', { class: 'ph-kpi' }, [h('div', { class: 'ph-kpi__label' }, l), h('div', { class: 'ph-kpi__value' }, '0')]); })),
      card('', '', h('div', { class: 'ph-sk', style: 'height:160px' }))
    ]);
    return call('today', { app: appName }).then(function (d) {
      var s = d.stats;
      var by = {};
      d.cards.forEach(function (c) { by[c.key] = c.count; });
      ['updates', 'support', 'crashlytics'].forEach(function (k) { setCount(k, by[k] || 0); });
      var mixParts = [{ key: 'current', label: 'Up to date', color: 'var(--good)' }, { key: 'behind', label: 'Behind', color: 'var(--warn)' }, { key: 'away', label: 'Not seen lately', color: 'var(--ink-faint)' }, { key: 'unknown', label: 'Unknown', color: 'var(--hairline-3)' }];
      var mixRows = Object.keys(s.app_mix).sort().map(function (k) { return { label: k, segs: s.app_mix[k] }; });
      var kindParts = [{ key: 'crash', label: 'Crashes', color: 'var(--bad)' }, { key: 'error', label: 'Errors', color: 'var(--warn)' }, { key: 'api', label: 'API failures', color: 'var(--signal)' }, { key: 'log', label: 'Logs', color: 'var(--ink-faint)' }];
      var evTotal = s.events_by_day.reduce(function (a, x) { return a + x.crash + x.error + x.api + x.log; }, 0);
      var tk = s.tickets_by_status;
      var healthRows = [['low_battery', 'Low battery'], ['low_storage', 'Low storage'], ['offline', 'Offline'], ['outdated_os', 'Old system'], ['outdated_app', 'Old app']].map(function (x) { return { label: x[1], value: s.health[x[0]] || 0, cls: x[0] === 'outdated_app' ? 'mid' : 'low' }; });
      mount([
        head('IT dashboard', 'Overview', plural(s.apps_total, 'app') + ' · ' + plural(s.people, 'person', 'people') + ' · ' + plural(s.devices_active, 'device') + '.'),
        filters([appSelect()]),
        kpis([
          stat('People', s.people, s.people_current + ' on the current version'),
          stat('Devices', s.devices_active, s.devices_active_7d + ' used this week · ' + s.devices_new_7d + ' new'),
          stat('Adoption', s.adoption == null ? '—' : s.adoption + '%', 'on the current version', { onClick: function () { go('updates'); } }),
          stat('Open tickets', s.tickets_open, s.tickets_waiting + ' waiting for an answer', { onClick: function () { go('support'); }, dark: s.tickets_waiting > 0 })
        ]),
        d.cards.length ? card('Needs attention', plural(d.cards.length, 'item'), h('div', { class: 'ph-list' }, d.cards.map(function (c) {
          var t = cardCopy(c);
          return h('div', { class: 'ph-list__row is-link', style: 'grid-template-columns:minmax(0,1fr) auto auto', tabindex: '0', onclick: function () { go(c.route); }, onkeydown: function (e) { if (e.key === 'Enter') go(c.route); } }, [
            h('div', { style: 'min-width:0' }, [h('div', { class: 'ph-list__name' }, t[0]), h('div', { class: 'ph-list__meta' }, t[1])]),
            badge(String(c.count), c.severity === 'high' ? 'bad' : c.severity === 'medium' ? 'warn' : ''),
            h('span', { class: 'ph-link' }, t[2])
          ]);
        }))) : card('Needs attention', '', empty('All clear', 'Nothing needs attention right now.')),
        h('div', { class: 'ph-row ph-row--2-1' }, [
          card('App versions', 'people by update state', mixRows.length ? [stackedRows(mixRows, mixParts), legend(mixParts.map(function (p) { return [p.label, p.color]; }))] : empty('No people yet')),
          card('Android versions', s.android_versions.length ? plural(s.android_versions.reduce(function (a, x) { return a + x.count; }, 0), 'device') : '', s.android_versions.length ? [h('div', {}, hbars(s.android_versions.map(function (v) { return { label: v.label, value: v.count, cls: v.old ? 'low' : '' }; }))), s.android_versions.some(function (v) { return v.old; }) ? h('div', { class: 'ph-muted', style: 'font-size:12px;margin-top:var(--sp-3)' }, 'Red = older than the supported minimum.') : null] : empty('No Android devices yet'))
        ]),
        h('div', { class: 'ph-row ph-row--2-1' }, [
          card('Events reported', 'last 14 days · ' + evTotal.toLocaleString(), evTotal ? [columns(s.events_by_day, kindParts), legend(kindParts.map(function (p) { return [p.label, p.color]; }))] : empty('Nothing reported', 'No crashes, errors or failed requests in 14 days.')),
          h('div', {}, [
            card('Support tickets', plural(s.tickets_total, 'ticket'), s.tickets_total ? h('div', { class: 'ph-flex', style: 'gap:var(--sp-5)' }, [donut([{ label: 'Waiting', value: tk.waiting, color: 'var(--bad)' }, { label: 'Answered', value: tk.answered, color: 'var(--signal)' }, { label: 'Resolved', value: tk.resolved, color: 'var(--good)' }], String(s.tickets_total), 'tickets'), h('div', { class: 'ph-grow' }, [['Waiting', tk.waiting, 'var(--bad)'], ['Answered', tk.answered, 'var(--signal)'], ['Resolved', tk.resolved, 'var(--good)']].map(function (x) { return h('div', { class: 'ph-flex ph-flex--between', style: 'padding:4px 0' }, [h('span', { class: 'ph-flex', style: 'gap:8px' }, [h('i', { style: 'width:10px;height:10px;border-radius:3px;display:inline-block;background:' + x[2] }), x[0]]), h('b', {}, String(x[1]))]); }))]) : empty('No tickets yet')),
            card('Device health', '', hbars(healthRows))
          ])
        ])
      ]);
    });
  }

  /* ---------- Updates ---------- */
  var BUCKETS = [['', 'Needs chasing'], ['forgot', 'Pending update'], ['cant_update', 'Pending install'], ['away', 'Not seen lately'], ['current', 'Up to date']];
  function updates(r) {
    var bucket = r.q.get('bucket') || '';
    var q = r.q.get('search') || '';
    var selected = {};
    mount([
      head('IT dashboard · Updates', 'Who needs to update', 'People on an older version than the current release.'),
      kpis([1, 2, 3, 4].map(function () { return { label: ' ', value: '0' }; })),
      card('', '', h('div', { class: 'ph-sk', style: 'height:240px' }), true)
    ]);
    [].forEach.call(document.querySelectorAll('.ph-kpis'), function (k) { k.classList.add('is-loading'); });
    return call('updates', { app: appName, bucket: bucket, search: q }).then(function (d) {
      var chased = (d.counts.forgot || 0) + (d.counts.cant_update || 0);
      var everyoneCount = Object.keys(d.counts).reduce(function (a, k) { return a + d.counts[k]; }, 0);
      var actionable = bucket === '' || bucket === 'forgot' || bucket === 'cant_update';
      var sendBtn = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', disabled: true, onclick: function () { send(Object.keys(selected).map(function (k) { return selected[k]; })); } }, 'Remind selected');
      function sync() {
        var n = Object.keys(selected).length;
        sendBtn.disabled = !n;
        sendBtn.textContent = n ? 'Remind ' + n + ' selected' : 'Remind selected';
      }
      function send(list) {
        sendBtn.disabled = true;
        call('remind', { people_list: JSON.stringify(list.map(function (p) { return { user: p.user, app: p.app }; })) }, true).then(function (res) {
          var t = {};
          res.results.forEach(function (x) { t[x.result] = (t[x.result] || 0) + 1; });
          var bits = [];
          if (t.sent) bits.push(t.sent + ' reminded');
          if (t.no_device) bits.push(t.no_device + ' have not allowed notifications');
          if (t.recent) bits.push(t.recent + ' reminded in the last day');
          if (t.not_behind) bits.push(t.not_behind + ' already up to date');
          toast(bits.join(' · ') || 'Nothing sent', t.sent ? 'good' : 'warn');
          render();
        }).catch(function (e) { fail(e); sync(); });
      }
      var all = h('input', { type: 'checkbox', 'aria-label': 'Select everyone', onchange: function () {
        [].forEach.call(document.querySelectorAll('.pick'), function (cb) { cb.checked = all.checked; cb.dispatchEvent(new Event('change')); });
      } });
      var rows = d.rows.map(function (p) {
        var key = p.user + '|' + p.app;
        var can = p.bucket === 'forgot' || p.bucket === 'cant_update';
        var cb = h('input', { type: 'checkbox', class: 'pick', 'aria-label': 'Select ' + p.full_name, onchange: function (ev) { if (ev.target.checked) selected[key] = p; else delete selected[key]; sync(); } });
        return h('tr', {}, [
          h('td', {}, can ? cb : null),
          h('td', {}, who(p.full_name, p.team ? p.team + ' · ' + p.user : p.user)),
          h('td', {}, p.app),
          h('td', {}, [p.installed || '—', ' → ', p.target || '—']),
          h('td', {}, p.bucket === 'cant_update' ? badge('Pending install', 'bad') : p.bucket === 'forgot' ? badge('Pending update', 'warn') : p.bucket === 'away' ? badge('Not seen lately') : badge('Up to date', 'good')),
          h('td', { class: 'is-num' }, p.bucket === 'current' || p.bucket === 'away' ? '—' : days(p.released_days_ago)),
          h('td', {}, ago(p.last_seen)),
          h('td', {}, p.reminded ? (p.reminded === 1 ? 'Once' : p.reminded + ' times') + ' · ' + ago(p.last_reminded) : h('span', { class: 'ph-muted' }, 'Never')),
          h('td', {}, can ? h('button', { class: 'ph-btn ph-btn--ghost ph-btn--sm', type: 'button', onclick: function () { send([p]); } }, 'Remind') : null)
        ]);
      });
      var cols = [{ label: '' }, { label: 'Person' }, { label: 'App' }, { label: 'Has → needs' }, { label: 'State' }, { label: 'Release age', num: true }, { label: 'Last seen' }, { label: 'Reminders' }, { label: '' }];
      mount([
        head('IT dashboard · Updates', 'Who needs to update', 'People on an older version than the current release. Reminders go out as push notifications.'),
        filters([
          pills(BUCKETS.map(function (b) { return [b[0], b[1], b[0] === '' ? chased : (d.counts[b[0]] || 0)]; }), bucket, function (v) { go('updates?' + qs({ bucket: v, search: q })); }),
          appSelect(),
          search('Search a name, email or team', q, function (v) { go('updates?' + qs({ bucket: bucket, search: v })); }),
          h('span', { class: 'ph-filters__spacer' }),
          actionable ? sendBtn : null
        ]),
        kpis([
          stat('People', everyoneCount, 'across ' + (appName || 'all apps')),
          stat('Pending update', d.counts.forgot || 0, 'need to reopen the app', { active: bucket === 'forgot', onClick: function () { go('updates?bucket=forgot'); } }),
          stat('Pending install', d.counts.cant_update || 0, 'need the new install', { active: bucket === 'cant_update', onClick: function () { go('updates?bucket=cant_update'); } }),
          stat('Up to date', everyoneCount ? Math.round(100 * (d.counts.current || 0) / everyoneCount) + '%' : '—', plural(d.counts.current || 0, 'person', 'people'), { active: bucket === 'current', onClick: function () { go('updates?bucket=current'); } })
        ]),
        card('People', d.total > rows.length ? 'showing ' + rows.length + ' of ' + d.total : plural(d.total, 'person', 'people'), rows.length ? table(cols, rows) : (q ? empty('No match', 'Nobody matches this search.') : empty('Nobody here', 'Everyone in this group is sorted.')), true)
      ]);
      var first = document.querySelector('.ph-table th');
      if (first && actionable && rows.length) first.appendChild(all);
    });
  }

  /* ---------- Devices ---------- */
  var FLAG_TEXT = { low_battery: 'Low battery', low_storage: 'Low storage', offline: 'Offline', outdated_os: 'Old system', outdated_app: 'Old app' };
  /* Devices, as a drill-down: model -> device (its Android ID) -> the people who used it. Which rows are open is kept in
     devOpen, so a search or refresh does not fold them. */
  var devOpen = {};
  function devIsOpen(key, dflt) { return Object.prototype.hasOwnProperty.call(devOpen, key) ? devOpen[key] : dflt; }
  function devChevron(on, label) {
    return h('span', { class: 'itd-chev' + (on ? ' is-open' : ''), 'aria-hidden': 'true' }, icon(['M9 6l6 6-6 6']));
  }
  function devHealth(x) {
    var main = x.state !== 'Active' ? badge(x.state, x.state === 'Lost' ? 'bad' : '') : (x.flags.length ? x.flags.map(function (f) { return badge(FLAG_TEXT[f] || f, f === 'outdated_app' ? 'warn' : 'bad'); }) : badge('Healthy', 'good'));
    return x.test ? [main, ' ', badge('Test build', 'outline')] : main;
  }
  /* what a device is linked to: its asset and its custodian */
  function devLinked(x) {
    var bits = [];
    if (x.asset) bits.push(badge(x.asset.asset_name, 'outline'));
    if (x.custodian) bits.push(h('span', { class: x.custodian.via === 'asset' ? 'ph-muted' : '' }, x.custodian.name));
    return bits.length ? h('div', { class: 'ph-flex ph-flex--wrap', style: 'gap:var(--sp-2)' }, bits) : h('span', { class: 'ph-muted' }, '—');
  }
  var DEV_TABS = [['', 'Devices'], ['assets', 'Linked to assets'], ['custodians', 'Linked to custodians']];
  function devTabs(view) { return pills(DEV_TABS, view, function (v) { go('devices' + (v ? '?view=' + v : '')); }); }
  var devLinksReady = true;
  function instIds(x) { return JSON.stringify(x.install_ids || [x.id]); }
  function devToggleRow(key, on, cells, label, redraw) {
    function flip() { devOpen[key] = !on; redraw(); }
    return h('tr', { class: 'is-link' + (on ? ' is-open' : ''), tabindex: 0, role: 'button', 'aria-expanded': on ? 'true' : 'false', 'aria-label': label, onclick: flip, onkeydown: function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } } }, cells);
  }
  function devicePeople(x) {
    return h('div', { class: 'itd-sub' }, x.people.length ? table(
      [{ label: 'Person' }, { label: 'Apps' }, { label: 'First used' }, { label: 'Last used' }, { label: 'Sign-ins', num: true }],
      x.people.map(function (u) {
        return h('tr', {}, [
          h('td', {}, who(u.name, u.name !== u.user ? u.user : '')),
          h('td', {}, u.uses.map(function (a) { return a.app + (a.version ? ' ' + a.version : ''); }).join(', ')),
          h('td', {}, dateOnly(u.first_seen)),
          h('td', {}, ago(u.last_seen)),
          h('td', { class: 'is-num' }, u.logins ? String(u.logins) : '—')
        ]);
      })
    ) : h('div', { class: 'ph-muted', style: 'padding:var(--sp-3) var(--sp-5)' }, 'No sign-ins recorded for this device.'));
  }
  function modelDevices(m, deep, redraw) {
    var rows = [];
    m.devices.forEach(function (x) {
      var key = 'd:' + x.key, on = devIsOpen(key, deep);
      rows.push(devToggleRow(key, on, [
        h('td', {}, h('div', { class: 'ph-flex', style: 'gap:var(--sp-2)' }, [devChevron(on), x.has_id || x.group ? [mono(x.device_id), x.merged ? [' ', badge('Merged', 'outline')] : null] : h('span', {}, [h('span', { class: 'ph-muted' }, 'Not reported '), h('span', { class: 'ph-mono ph-muted' }, x.id.slice(0, 8))])])),
        h('td', {}, [x.serial_number ? mono(x.serial_number) : null, x.serial_number && x.mac_address ? h('br') : null, x.mac_address ? mono(x.mac_address) : null, !x.serial_number && !x.mac_address ? h('span', { class: 'ph-muted' }, '—') : null]),
        h('td', {}, x.platform ? x.platform + ' ' + x.os_version : '—'),
        h('td', {}, [x.apps.join(', '), x.installs > 1 ? h('span', { class: 'ph-muted' }, ' · ' + plural(x.installs, 'install')) : null]),
        h('td', { class: 'is-num' }, String(x.people.length)),
        h('td', {}, devLinked(x)),
        h('td', {}, devHealth(x)),
        h('td', { class: 'is-num' }, x.battery != null ? x.battery + '%' : '—'),
        h('td', { class: 'is-num' }, x.storage_free_gb != null ? x.storage_free_gb + ' GB' : '—'),
        h('td', {}, ago(x.last_seen)),
        h('td', {}, h('button', { class: 'ph-btn ph-btn--ghost ph-btn--sm', type: 'button', onclick: function (e) { e.stopPropagation(); openDevice(x); } }, 'Details'))
      ], 'Device ' + (x.android_id || x.id) + ', ' + plural(x.people.length, 'person', 'people'), redraw));
      if (on) rows.push(h('tr', { class: 'itd-subrow' }, h('td', { colspan: 11 }, devicePeople(x))));
    });
    return h('div', { class: 'itd-sub' }, table(
      [{ label: 'Device ID' }, { label: 'Serial · MAC' }, { label: 'System' }, { label: 'Apps' }, { label: 'People', num: true }, { label: 'Linked to' }, { label: 'Health' }, { label: 'Battery', num: true }, { label: 'Free', num: true }, { label: 'Last seen' }, { label: '' }],
      rows
    ));
  }
  function devices(r) {
    var view_ = r.q.get('view') || '';
    if (view_ === 'assets' || view_ === 'custodians') return deviceLinks(view_, r);
    var state = r.q.get('state') || '', health = r.q.get('health') || '', q = r.q.get('search') || '', tests = r.q.get('tests') || '';
    mount([head('IT dashboard · Devices', 'Devices', 'Loading…'), card('', '', h('div', { class: 'ph-sk', style: 'height:240px' }), true)]);
    return call('devicelink.device_tree', { app: appName, state: state, health: health, search: q, tests: tests }).then(function (d) {
      devLinksReady = d.links_ready !== false;
      function nav(over) { var o = { state: state, health: health, search: q, tests: tests }; Object.keys(over).forEach(function (k) { o[k] = over[k]; }); go('devices?' + qs(o)); }
      var t = d.totals, hc = d.health || {};
      var few = t.devices <= 20;  // a short result opens all the way down, so a search for a person shows them
      var host = h('div');
      function redraw() {
        clear(host);
        if (!d.models.length) { host.appendChild(empty('No devices match', 'Try a different filter or search.')); return; }
        var rows = [];
        d.models.forEach(function (m) {
          var on = devIsOpen('m:' + m.name, !!q && (few || d.models.length <= 3));
          rows.push(devToggleRow('m:' + m.name, on, [
            h('td', {}, h('div', { class: 'ph-flex', style: 'gap:var(--sp-2)' }, [devChevron(on), h('span', { class: 'ph-strong' }, m.name)])),
            h('td', { class: 'is-num' }, String(m.devices.length)),
            h('td', { class: 'is-num' }, String(m.people)),
            h('td', { class: 'is-num' }, String(m.installs)),
            h('td', { class: 'is-num' }, m.issues ? String(m.issues) : '—'),
            h('td', {}, ago(m.last_seen))
          ], m.name + ', ' + plural(m.devices.length, 'device'), redraw));
          if (on) rows.push(h('tr', { class: 'itd-subrow' }, h('td', { colspan: 6 }, modelDevices(m, !!q && few, redraw))));
        });
        host.appendChild(table([{ label: 'Device' }, { label: 'Devices', num: true }, { label: 'People', num: true }, { label: 'Installs', num: true }, { label: 'Need attention', num: true }, { label: 'Last seen' }], rows));
      }
      redraw();
      mount([
        head('IT dashboard · Devices', 'Devices', 'Open a device to see its IDs, and a device ID to see who used it.' + (t.no_id ? ' ' + plural(t.no_id, 'device') + ' report no device ID (Android hides it from some apps), so each counts as its own device.' : '') + (tests ? '' : ' Test builds (Expo Go) are left out.')),
        filters([
          devTabs(''),
          select([['', 'Any state'], ['Active', 'Active'], ['Lost', 'Lost'], ['Retired', 'Retired']], state, function (v) { nav({ state: v }); }, 'State'),
          appSelect(),
          select([['', 'Any health']].concat(Object.keys(FLAG_TEXT).map(function (k) { return [k, FLAG_TEXT[k]]; })), health, function (v) { nav({ health: v }); }, 'Health'),
          search('Search device, ID or person', q, function (v) { nav({ search: v }); }),
          h('span', { class: 'ph-filters__spacer' }),
          (function () {
            var box = h('input', { type: 'checkbox', onchange: function () { nav({ tests: box.checked ? '1' : '' }); } });
            box.checked = !!tests;
            return h('label', { class: 'ph-switch', title: 'Expo Go, the development container, gets its own device ID, so one phone can look like two.' }, [box, h('i'), h('span', {}, 'Include test builds')]);
          })(),
          h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () {
            var allOn = d.models.some(function (m) { return devIsOpen('m:' + m.name, false); });
            d.models.forEach(function (m) { devOpen['m:' + m.name] = !allOn; });
            redraw();
          } }, 'Open or close all')
        ]),
        kpis([{ label: 'Unique devices', value: t.devices, dark: true }, { label: 'Models', value: t.models }, { label: 'People', value: t.people }, { label: 'Installs', value: t.installs }, { label: 'Linked to assets', value: t.with_asset, onClick: function () { go('devices?view=assets'); } }, { label: 'With a custodian', value: t.with_custodian, onClick: function () { go('devices?view=custodians'); } }].concat(Object.keys(FLAG_TEXT).filter(function (k) { return hc[k] != null; }).map(function (k) {
          return { label: FLAG_TEXT[k], value: hc[k], onClick: function () { nav({ health: health === k ? '' : k }); }, active: health === k };
        }))),
        card('', '', host, true)
      ]);
    });
  }
  /* Devices linked to assets / to custodians: the same devices, listed by what they belong to. */
  function devUnlink(x, what, fn) {
    ask('Unlink ' + what, x.device + ' will no longer be linked to this ' + what + '.', 'Unlink', true, function () {
      call('devicelink.' + fn, { install_ids: instIds(x) }, true).then(function () { toast('Unlinked', 'good'); render(); }).catch(fail);
    });
  }
  function deviceLinks(kind, r) {
    var q = r.q.get('search') || '', isAsset = kind === 'assets';
    mount([head('IT dashboard · Devices', 'Devices', 'Loading…'), card('', '', h('div', { class: 'ph-sk', style: 'height:240px' }), true)]);
    return call('devicelink.device_links', { kind: isAsset ? 'asset' : 'custodian', app: appName, search: q }).then(function (d) {
      devLinksReady = d.links_ready !== false;
      var people = {};
      d.rows.forEach(function (x) { if (x.custodian) people[x.custodian.id] = 1; });
      var direct = d.rows.filter(function (x) { return x.custodian && x.custodian.via === 'direct'; }).length;
      var body;
      if (!devLinksReady) body = empty('Not set up yet', 'This site needs a migrate before devices can be linked.');
      else if (!d.rows.length) body = empty(q ? 'No match' : (isAsset ? 'No device is linked to an asset yet' : 'No device has a custodian yet'), q ? 'Try another search.' : 'Open a device on the Devices tab and use Details to link it.');
      else {
        var cols = isAsset
          ? [{ label: 'Asset' }, { label: 'Device' }, { label: 'Device ID' }, { label: 'Custodian' }, { label: 'People who used it' }, { label: 'Last seen' }, { label: '' }]
          : [{ label: 'Custodian' }, { label: 'Device' }, { label: 'Device ID' }, { label: 'Linked through' }, { label: 'People who used it' }, { label: 'Last seen' }, { label: '' }];
        body = table(cols, d.rows.map(function (x) {
          function open() { openDevice(x); }
          var first = isAsset ? who(x.asset.asset_name, x.asset.name + (x.asset.location ? ' · ' + x.asset.location : '')) : who(x.custodian.name, x.custodian.id);
          var unlink = isAsset ? h('button', { class: 'ph-btn ph-btn--ghost ph-btn--sm', type: 'button', onclick: function (e) { e.stopPropagation(); devUnlink(x, 'asset', 'unlink_asset'); } }, 'Unlink')
            : (x.custodian.via === 'direct' ? h('button', { class: 'ph-btn ph-btn--ghost ph-btn--sm', type: 'button', onclick: function (e) { e.stopPropagation(); devUnlink(x, 'custodian', 'unlink_custodian'); } }, 'Unlink') : null);
          return h('tr', { class: 'is-link', tabindex: 0, onclick: open, onkeydown: function (e) { if (e.key === 'Enter') open(); } }, [
            h('td', {}, first),
            h('td', {}, [x.device, x.test ? [' ', badge('Test build', 'outline')] : null]),
            h('td', {}, mono(x.device_id)),
            isAsset ? h('td', {}, x.custodian ? who(x.custodian.name, x.custodian.via === 'asset' ? 'from the asset' : 'set on the device') : dash('')) : h('td', {}, x.custodian.via === 'asset' ? ['Asset ', h('b', {}, x.asset ? x.asset.asset_name : '')] : 'The device itself'),
            h('td', {}, x.people.slice(0, 3).map(function (p) { return p.name; }).join(', ') + (x.people.length > 3 ? ' +' + (x.people.length - 3) : '')),
            h('td', {}, ago(x.last_seen)),
            h('td', {}, unlink)
          ]);
        }));
      }
      mount([
        head('IT dashboard · Devices', 'Devices', isAsset ? 'Devices that are an asset, with the asset’s custodian.' : 'Who has which device: set on the device, or taken from its asset.'),
        filters([
          devTabs(kind),
          appSelect(),
          search(isAsset ? 'Search asset, device or person' : 'Search custodian, device or person', q, function (v) { go('devices?' + qs({ view: kind, search: v })); }),
          h('span', { class: 'ph-filters__spacer' })
        ]),
        kpis(isAsset
          ? [{ label: 'Devices linked to assets', value: d.total, dark: true }, { label: 'With a custodian', value: d.rows.filter(function (x) { return x.custodian; }).length }]
          : [{ label: 'Devices with a custodian', value: d.total, dark: true }, { label: 'Custodians', value: Object.keys(people).length }, { label: 'Set on the device', value: direct }, { label: 'Through an asset', value: d.total - direct }]),
        card('', '', body, true)
      ]);
    });
  }
  /* In a device's details: what it is linked to, and "this is the same device as…". */
  function devLinkBlocks(x, close) {
    if (!devLinksReady) return null;
    function done(msg) { return function () { toast(msg, 'good'); close(); render(); }; }
    function picker(placeholder, fetchFn, label, action) {
      var picked = null;
      var ta = typeahead(placeholder, fetchFn, function (it) { picked = it; });
      var btn = h('button', { class: 'ph-btn', type: 'button', onclick: function () {
        if (!picked) { toast('Pick one from the list.', 'bad'); return; }
        action(picked);
      } }, label);
      return h('div', { class: 'ph-flex', style: 'gap:var(--sp-3);align-items:flex-start' }, [h('div', { class: 'ph-grow' }, ta), btn]);
    }
    var asset = h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Asset'),
      x.asset ? h('div', { class: 'ph-stack' }, [
        kvList([['Asset', x.asset.asset_name + ' (' + x.asset.name + ')'], ['Location', x.asset.location]].filter(function (p) { return p[1]; })),
        h('div', {}, h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () { devUnlink(x, 'asset', 'unlink_asset'); } }, 'Unlink asset'))
      ]) : picker('Find an asset by name', function (term) {
        return call('devicelink.find_assets', { search: term }).then(function (res) { return res.rows.map(function (a) { return { value: a.name, label: (a.asset_name || a.name) + ' · ' + a.name, sub: a.device_id ? 'Already linked to a device' : (a.location || '') }; }); });
      }, 'Link asset', function (it) {
        call('devicelink.link_asset', { install_ids: instIds(x), asset: it.value }, true).then(done('Linked to ' + it.label)).catch(fail);
      }),
      x.asset ? null : h('div', { class: 'ph-field__hint' }, 'The asset keeps this device’s ID, so the link follows it.')]);
    var cust = h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Custodian'),
      x.custodian && x.custodian.via === 'direct' ? h('div', { class: 'ph-stack' }, [
        kvList([['Custodian', x.custodian.name + ' (' + x.custodian.id + ')']]),
        h('div', {}, h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () { devUnlink(x, 'custodian', 'unlink_custodian'); } }, 'Unlink custodian'))
      ]) : h('div', {}, [
        x.custodian ? h('div', { class: 'ph-muted', style: 'margin-bottom:var(--sp-2)' }, x.custodian.name + ' through the asset. Pick someone to set it on the device itself.') : null,
        picker('Find an employee', function (term) {
          return call('devicelink.find_custodians', { search: term }).then(function (res) { return res.rows.map(function (e) { return { value: e.name, label: e.employee_name + ' · ' + e.name, sub: e.department || '' }; }); });
        }, 'Link custodian', function (it) {
          call('devicelink.link_custodian', { install_ids: instIds(x), employee: it.value }, true).then(done('Custodian set')).catch(fail);
        })
      ])]);
    var same = h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Same device as another'),
      picker('Find the other device by model, ID or person', function (term) {
        return call('devicelink.find_devices', { search: term, exclude: instIds(x) }).then(function (res) { return res.rows.map(function (o) { return { value: o.install_ids, label: o.label, sub: o.sub, ids: o.install_ids }; }); });
      }, 'Merge', function (it) {
        ask('Merge devices', 'Treat ' + x.device + ' and ' + it.label + ' as one device? Their people, ID and links come together. A phone often shows twice after a reset or when an app is signed with another key.', 'Merge', false, function () {
          call('devicelink.merge_devices', { install_ids: instIds(x), into_ids: JSON.stringify(it.ids) }, true).then(done('Merged')).catch(fail);
        });
      }),
      x.merged ? h('div', { style: 'margin-top:var(--sp-4)' }, [h('div', { class: 'ph-muted', style: 'font-size:12px;margin-bottom:var(--sp-2)' }, 'IDs behind this device'), h('div', {}, x.ids.map(function (g) {
        return h('div', { class: 'ph-flex ph-flex--between', style: 'padding:var(--sp-2) 0;border-bottom:1px solid var(--hairline)' }, [
          h('div', {}, [mono(g.id || 'not reported'), h('div', { class: 'ph-muted', style: 'font-size:12px' }, g.apps.join(', ') + (g.test ? ' · test build' : ''))]),
          h('button', { class: 'ph-btn ph-btn--ghost ph-btn--sm', type: 'button', onclick: function () {
            ask('Split off', 'Take ' + (g.id || 'this ID') + ' out of this device? It counts as a separate device again.', 'Split off', true, function () {
              call('devicelink.split_device', { install_ids: JSON.stringify(g.install_ids) }, true).then(done('Split off')).catch(fail);
            });
          } }, 'Split off')
        ]);
      }))]) : null]);
    return h('div', { class: 'ph-stack ph-stack--lg' }, [asset, cust, same]);
  }
  function openDevice(x) {
    var notes = h('textarea', { class: 'ph-control', rows: 3, style: 'height:auto;padding:10px 14px', placeholder: 'Who has it, where it is, what was done' }, x.notes);
    var st = select([['Active', 'Active'], ['Lost', 'Lost'], ['Retired', 'Retired']], x.state, function () {}, 'Device status');
    var close;
    var body = h('div', { class: 'ph-stack ph-stack--lg' }, [
      h('div', { class: 'ph-flex ph-flex--wrap' }, x.flags.length ? x.flags.map(function (f) { return badge(FLAG_TEXT[f] || f, f === 'outdated_app' ? 'warn' : 'bad'); }) : [badge('Healthy', 'good')]),
      kvList([['Owner', x.owner_name], ['Email', x.owner], ['App', x.app + ' ' + x.app_version], ['System', x.platform + ' ' + x.os_version], ['Battery', x.battery != null ? x.battery + '%' : ''], ['Free storage', x.storage_free_gb != null ? x.storage_free_gb + ' GB' : ''], ['Network', x.network], ['Last seen', ago(x.last_seen)]]),
      h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Identifiers'), kvList([['Device ID', x.android_id || 'not reported'], ['Serial number', x.serial_number || 'not reported'], ['MAC address', x.mac_address || 'not reported']].concat(x.local_ip && x.ip_seen && x.local_ip !== x.ip_seen ? [['IP on its network', x.local_ip], ['IP the server sees', x.ip_seen]] : [['IP address', x.local_ip || x.ip_seen || 'not reported']]).concat([ ['Build number', x.build_number || 'not reported']]), true)]),
      devLinkBlocks(x, function () { close(); }),
      h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'People who used this device'), x.people && x.people.length ? h('div', {}, x.people.map(function (u) {
        return h('div', { style: 'padding:var(--sp-3) 0;border-bottom:1px solid var(--hairline)' }, [
          h('div', { class: 'ph-flex ph-flex--between' }, [h('div', { class: 'ph-strong' }, u.name), h('span', { class: 'ph-muted', style: 'font-size:12px' }, u.uses.map(function (a) { return a.app + (a.version ? ' ' + a.version : ''); }).join(', '))]),
          u.name !== u.user ? h('div', { class: 'ph-muted', style: 'font-size:12px' }, u.user) : null,
          h('div', { class: 'ph-muted', style: 'font-size:12px' }, 'First used ' + dateOnly(u.first_seen) + ' · last used ' + ago(u.last_seen) + (u.logins ? ' · ' + plural(u.logins, 'sign-in') : ''))
        ]);
      })) : h('div', { class: 'ph-muted' }, 'No sign-ins recorded for this device.')]),
      h('div', { class: 'ph-field' }, [h('label', {}, 'Status'), st, h('div', { class: 'ph-field__hint' }, 'Lost and retired devices stop appearing on the chase list.' + (x.installs > 1 ? ' This applies to all ' + x.installs + ' installs on the device.' : ''))]),
      h('div', { class: 'ph-field' }, [h('label', {}, 'Notes'), notes]),
      h('div', {}, h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
        Promise.all((x.install_ids || [x.id]).map(function (id) { return call('set_device', { id: id, state: st.value, notes: notes.value }, true); })).then(function () { toast('Saved', 'good'); close(); render(); }).catch(fail);
      } }, 'Save'))
    ]);
    if (x.developer) body.appendChild(h('details', { class: 'itd-dev' }, [h('summary', {}, 'Developer details'), kvList([['Install id', x.developer.install_id], ['Runtime', x.developer.runtime], ['First seen', x.developer.first_seen], ['Launches', x.developer.launches]], true)]));
    close = drawer(x.device, x.owner_name || x.owner || '', body);
  }

  /* ---------- Crashlytics ---------- */
  /* ---------- User management ---------- */
  var USERS = boot.getAttribute('data-users') === '1';
  /* a search box that narrows the rows already on the page as you type (no reload, so the cursor stays put);
     Enter asks the server, which also reaches people beyond the rows shown. */
  function liveSearch(placeholder, value, onSearch) {
    return searchBox(placeholder, value, onSearch, function (term) {
      var shown = 0, all = 0;
      [].forEach.call(view.querySelectorAll('tbody tr[data-find]'), function (tr) {
        all++;
        var hit = !term || tr.getAttribute('data-find').indexOf(term) >= 0;
        tr.hidden = !hit;
        if (hit) shown++;
      });
      var n = document.getElementById('um-shown');
      if (n) n.textContent = term ? shown + ' of ' + plural(all, 'person', 'people') : plural(all, 'person', 'people');
    });
  }
  function profileChips(list, locked) {
    return list.length ? list.map(function (p) { return badge(p, locked ? '' : 'signal'); }) : h('span', { class: 'ph-muted' }, 'No role profile');
  }
  function users(r) {
    if (!USERS) return Promise.reject(new Error('User management is for the IT Team and System Managers only.'));
    var status = r.q.get('status') || '', profile = r.q.get('profile') || '', q = r.q.get('search') || '';
    return Promise.all([call('usermgmt.meta'), call('usermgmt.users', { status: status, profile: profile, search: q })]).then(function (res) {
      var m = res[0], d = res[1], s = d.summary;
      function nav(over) { var o = { status: status, profile: profile, search: q }; Object.keys(over).forEach(function (k) { o[k] = over[k]; }); go('users?' + qs(o)); }
      var rows = d.rows.map(function (x) {
        function open() { openUser(x.name, m); }
        return h('tr', { class: 'is-link', tabindex: 0, 'data-find': (x.full_name + ' ' + x.name).toLowerCase(), onclick: open, onkeydown: function (e) { if (e.key === 'Enter') open(); } }, [
          h('td', {}, who(x.full_name, x.name)),
          h('td', {}, h('div', { class: 'ph-flex ph-flex--wrap' }, profileChips(x.profiles, !!x.locked))),
          h('td', {}, x.locked ? badge('Managed in Desk', '') : x.enabled ? badge('Active', 'good') : badge('Disabled', 'bad')),
          h('td', {}, x.last_active ? ago(x.last_active) : h('span', { class: 'ph-muted' }, 'never')),
          h('td', {}, dateOnly(x.created))
        ]);
      });
      var cols = [{ label: 'Person' }, { label: 'Role profiles' }, { label: 'Status' }, { label: 'Last active' }, { label: 'Added' }];
      var add = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () { openAddUser(m); } }, 'Add user');
      mount([
        head('IT dashboard · User management', 'People and access', 'Add people, change their details, turn accounts on or off and give them role profiles. A role profile is a ready-made set of permissions. System roles are never handed out from here.', add),
        filters([
          pills([['', 'All', s.active + s.disabled], ['active', 'Active', s.active], ['disabled', 'Disabled', s.disabled]], status, function (v) { nav({ status: v }); }),
          select([['', 'Any role profile'], ['none', 'No role profile']].concat(m.profiles.map(function (p) { return [p.name, p.name + ' (' + p.users + ')']; })), profile, function (v) { nav({ profile: v }); }, 'Role profile'),
          liveSearch('Search name or email', q, function (v) { nav({ search: v }); }),
          h('span', { class: 'ph-filters__spacer' })
        ]),
        kpis([
          { label: 'People', value: s.active + s.disabled, unit: 'in this list' },
          { label: 'Active', value: s.active, onClick: function () { nav({ status: 'active' }); }, active: status === 'active' },
          { label: 'Disabled', value: s.disabled, onClick: function () { nav({ status: 'disabled' }); }, active: status === 'disabled' },
          { label: 'No role profile', value: s.no_profile, onClick: function () { nav({ profile: 'none' }); }, active: profile === 'none' }
        ]),
        card('', '', rows.length ? table(cols, rows) : empty('No people match', 'Try another search or filter.'), true),
        h('div', { class: 'ph-muted', id: 'um-shown', style: 'font-size:12px;margin-top:var(--sp-3)' }, rows.length ? plural(rows.length, 'person', 'people') : '')
      ]);
    });
  }
  function field(label, control, hint) { return h('div', { class: 'ph-field' }, [h('label', {}, label), control, hint ? h('div', { class: 'ph-field__hint' }, hint) : null]); }
  function input(attrs) { return h('input', Object.assign({ class: 'ph-control', autocomplete: 'off' }, attrs)); }
  function profileChecks(m, picked) {
    var boxes = [];
    var wrap = h('div', { class: 'ph-stack', style: 'gap:var(--sp-2)' }, m.profiles.map(function (p) {
      var cb = h('input', { type: 'checkbox', value: p.name, disabled: !p.assignable });
      cb.checked = picked.indexOf(p.name) >= 0;
      boxes.push(cb);
      return h('label', { class: 'ph-flex', style: 'gap:var(--sp-3);align-items:flex-start;' + (p.assignable ? '' : 'opacity:.55') }, [cb, h('span', {}, [h('span', { class: 'ph-strong' }, p.name), h('span', { class: 'ph-muted', style: 'font-size:12px;display:block' }, p.assignable ? (p.roles.join(', ') || 'No roles') : (p.name === 'IT Team' ? 'Decides who can manage users. Only a System Manager can give it, in Desk.' : 'Includes a system role, so it cannot be given from here.'))])]);
    }));
    wrap.value = function () { return boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; }); };
    return wrap;
  }
  function openAddUser(m) {
    var email = input({ type: 'email', placeholder: 'name@company.com' });
    var name = input({ type: 'text', placeholder: 'Full name' });
    var pw = input({ type: 'text', placeholder: 'Temporary password' });
    var checks = profileChecks(m, []);
    var close;
    var go_ = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
      go_.disabled = true;
      call('usermgmt.create', { email: email.value, full_name: name.value, password: pw.value, role_profiles: JSON.stringify(checks.value()) }, true).then(function (res) { toast('Added ' + (name.value || res.name), 'good'); close(); render(); }).catch(function (e) { go_.disabled = false; fail(e); });
    } }, 'Add user');
    close = drawer('Add user', 'They sign in with this password. Ask them to change it.', h('div', { class: 'ph-stack ph-stack--lg' }, [
      field('Email', email), field('Full name', name), field('Password', pw, 'Use at least 8 characters, with letters and numbers.'),
      field('Role profiles', checks, 'Pick what they need to do. You can change this later.'), h('div', {}, go_)
    ]));
  }
  function openUser(id, m) {
    var close = drawer('Loading…', '', h('div', { class: 'ph-muted' }, 'Loading…'));
    call('usermgmt.detail', { name: id }).then(function (u) { close(); showUser(u, m); }).catch(function (e) { close(); fail(e); });
  }
  function showUser(u, m) {
    var close;
    function reopen() { render(); openUser(u.name, m); }
    var body = h('div', { class: 'ph-stack ph-stack--lg' });
    body.appendChild(h('div', { class: 'ph-flex ph-flex--wrap' }, [u.locked ? badge('Managed in Desk', '') : u.enabled ? badge('Active', 'good') : badge('Disabled', 'bad')].concat(u.is_me ? [badge('You', 'signal')] : [])));
    if (u.locked) {
      body.appendChild(h('div', { class: 'ph-muted' }, u.locked));
      body.appendChild(kvList([['Email', u.name], ['Role profiles', u.profiles.join(', ')], ['Roles', u.roles.join(', ')], ['Last active', u.last_active ? ago(u.last_active) : 'never']]));
      close = drawer(u.full_name, u.name, body);
      return;
    }
    var nm = input({ type: 'text', value: u.full_name });
    var en = select([['1', 'Active — can sign in'], ['0', 'Disabled — cannot sign in']], u.enabled ? '1' : '0', function () {}, 'Account status');
    body.appendChild(field('Full name', nm));
    body.appendChild(field('Account', en, u.is_me ? 'You cannot disable your own account.' : ''));
    body.appendChild(h('div', {}, h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
      call('usermgmt.update', { name: u.name, full_name: nm.value, enabled: en.value }, true).then(function () { toast('Saved', 'good'); close(); reopen(); }).catch(fail);
    } }, 'Save')));
    // role profiles: add one, take one away
    var have = {};
    u.profiles.forEach(function (p) { have[p] = 1; });
    var list = h('div', {}, u.profiles.length ? u.profiles.map(function (p) {
      return h('div', { class: 'ph-flex ph-flex--between', style: 'padding:var(--sp-2) 0;border-bottom:1px solid var(--hairline)' }, [
        h('span', { class: 'ph-strong' }, p),
        u.is_me ? null : h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () {
          ask('Remove role profile', 'Take ' + p + ' away from ' + u.full_name + '?', 'Remove', true, function () {
            call('usermgmt.remove_role_profile', { name: u.name, role_profile: p }, true).then(function () { toast('Removed ' + p, 'good'); close(); reopen(); }).catch(fail);
          });
        } }, 'Remove')
      ]);
    }) : h('div', { class: 'ph-muted' }, 'No role profile, so no access yet.'));
    var avail = m.profiles.filter(function (p) { return p.assignable && !have[p.name]; });
    var pick = select([['', 'Add a role profile…']].concat(avail.map(function (p) { return [p.name, p.name]; })), '', function () {}, 'Role profile to add');
    var section = [h('div', { class: 'ph-label' }, 'Role profiles'), list];
    if (!u.is_me) section.push(h('div', { class: 'ph-flex', style: 'margin-top:var(--sp-3);gap:var(--sp-3)' }, [pick, h('button', { class: 'ph-btn', type: 'button', onclick: function () {
      if (!pick.value) return;
      call('usermgmt.add_role_profile', { name: u.name, role_profile: pick.value }, true).then(function () { toast('Added ' + pick.value, 'good'); close(); reopen(); }).catch(fail);
    } }, 'Add')]));
    else section.push(h('div', { class: 'ph-field__hint' }, 'You cannot change your own role profiles.'));
    body.appendChild(h('div', {}, section));
    body.appendChild(h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'What they can do'), u.roles.length ? h('div', { class: 'ph-flex ph-flex--wrap' }, u.roles.map(function (r) { return badge(r, ''); })) : h('div', { class: 'ph-muted' }, 'No roles.')]));
    body.appendChild(kvList([['Email', u.name], ['Last active', u.last_active ? ago(u.last_active) : 'never'], ['Added', dateOnly(u.created)]]));
    // password
    var pw = input({ type: 'text', placeholder: 'New password' });
    body.appendChild(h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Reset password'), h('div', { class: 'ph-flex', style: 'gap:var(--sp-3)' }, [pw, h('button', { class: 'ph-btn', type: 'button', onclick: function () {
      if (!pw.value) return;
      call('usermgmt.reset_password', { name: u.name, password: pw.value }, true).then(function () { toast('Password changed', 'good'); pw.value = ''; }).catch(fail);
    } }, 'Set')])]));
    if (u.history.length) body.appendChild(h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'What IT changed'), h('div', {}, u.history.map(function (x) { return h('div', { style: 'padding:var(--sp-2) 0;border-bottom:1px solid var(--hairline)' }, [h('div', {}, x.text), h('div', { class: 'ph-muted', style: 'font-size:12px' }, ago(x.at))]); }))]));
    if (!u.is_me) body.appendChild(h('div', { style: 'padding-top:var(--sp-4);border-top:1px solid var(--hairline)' }, [h('button', { class: 'ph-btn ph-btn--danger', type: 'button', onclick: function () {
      ask('Delete user', 'Delete ' + u.full_name + ' (' + u.name + ')? This cannot be undone. To keep their history, disable the account instead.', 'Delete user', true, function () {
        call('usermgmt.delete', { name: u.name }, true).then(function () { toast('Deleted ' + u.name, 'good'); close(); render(); }).catch(fail);
      });
    } }, 'Delete user')]));
    close = drawer(u.full_name, u.name, body);
  }

  /* ---------- Role management, Doctype permissions, User permissions ---------- */
  function guardAccess() { return USERS ? null : Promise.reject(new Error('This is for the IT Team only.')); }
  /* a text box that suggests records as you type: fetchFn(term) -> Promise<[{value, label, sub}]> */
  function typeahead(placeholder, fetchFn, onPick, initial) {
    var wrap = h('div', { class: 'ph-ac' });
    var input = h('input', { class: 'ph-control', type: 'text', placeholder: placeholder, autocomplete: 'off', value: initial || '' });
    var menu = null, timer = null, seq = 0;
    function close() { if (menu) { menu.remove(); menu = null; } }
    function show(items) {
      close();
      menu = h('div', { class: 'ph-ac__menu' }, items.length ? items.map(function (it) {
        return h('div', { class: 'ph-ac__item', onmousedown: function (e) { e.preventDefault(); input.value = it.label; close(); onPick(it); } }, [it.label, it.sub ? h('small', {}, it.sub) : null]);
      }) : h('div', { class: 'ph-ac__empty' }, 'Nothing found'));
      wrap.appendChild(menu);
    }
    function run() { var my = ++seq; fetchFn(input.value.trim()).then(function (items) { if (my === seq) show(items); }).catch(function () { /* the box just stays empty */ }); }
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 250); });
    input.addEventListener('focus', run);
    input.addEventListener('blur', function () { setTimeout(close, 150); });
    wrap.appendChild(input);
    wrap.input = input;
    return wrap;
  }
  function chips(list, max) {
    if (!list.length) return h('span', { class: 'ph-muted' }, '—');
    var shown = list.slice(0, max || 4).map(function (p) { return badge(p, ''); });
    if (list.length > (max || 4)) shown.push(h('span', { class: 'ph-muted', style: 'font-size:12px' }, '+' + (list.length - (max || 4)) + ' more'));
    return h('div', { class: 'ph-flex ph-flex--wrap' }, shown);
  }
  function foot(n, one, many) { return h('div', { class: 'ph-muted', id: 'um-shown', style: 'font-size:12px;margin-top:var(--sp-3)' }, n ? plural(n, one, many) : ''); }

  /* ----- Role management ----- */
  function roleScreen(r) {
    var g = guardAccess(); if (g) return g;
    var view_ = r.q.get('view') || 'roles', q = r.q.get('search') || '';
    return Promise.all([call('rolemgmt.roles', { search: q }), call('rolemgmt.profiles', { search: q })]).then(function (res) {
      var rs = res[0], ps = res[1];
      function nav(over) { var o = { view: view_, search: q }; Object.keys(over).forEach(function (k) { o[k] = over[k]; }); go('roles?' + qs(o)); }
      var body;
      if (view_ === 'profiles') {
        var rows = ps.rows.map(function (p) {
          function open() { openProfile(p); }
          return h('tr', { class: 'is-link', tabindex: 0, 'data-find': p.name.toLowerCase(), onclick: open, onkeydown: function (e) { if (e.key === 'Enter') open(); } }, [
            h('td', {}, h('span', { class: 'ph-strong' }, p.name)), h('td', {}, chips(p.roles, 5)), h('td', { class: 'is-num' }, p.system_roles ? plural(p.system_roles, 'system role') : '—'), h('td', { class: 'is-num' }, String(p.people))
          ]);
        });
        body = [card('', '', rows.length ? table([{ label: 'Role profile' }, { label: 'Roles' }, { label: 'System roles', num: true }, { label: 'People', num: true }], rows) : empty('No role profiles match'), true), foot(rows.length, 'role profile')];
      } else {
        var rows2 = rs.rows.map(function (x) {
          function open() { openRole(x); }
          return h('tr', { class: 'is-link', tabindex: 0, 'data-find': x.name.toLowerCase(), onclick: open, onkeydown: function (e) { if (e.key === 'Enter') open(); } }, [
            h('td', {}, h('span', { class: 'ph-strong' }, x.name)), h('td', {}, x.desk_access ? badge('Desk', 'signal') : badge('Website only', '')), h('td', {}, chips(x.profiles, 3)), h('td', { class: 'is-num' }, String(x.people)), h('td', {}, x.disabled ? badge('Disabled', 'bad') : badge('Active', 'good'))
          ]);
        });
        body = [card('', '', rows2.length ? table([{ label: 'Role' }, { label: 'Access' }, { label: 'In role profiles' }, { label: 'People', num: true }, { label: 'Status' }], rows2) : empty('No roles match'), true), foot(rows2.length, 'role')];
      }
      mount([
        head('IT dashboard · Role management', 'Roles and role profiles', 'Add a role, or add a role to a role profile. Everyone on the profile then gets it. System Manager and Script Manager are not shown.', h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: openNewRole }, 'New role')),
        filters([pills([['roles', 'Roles', rs.total], ['profiles', 'Role profiles', ps.total]], view_, function (v) { nav({ view: v, search: '' }); }), liveSearch(view_ === 'profiles' ? 'Search role profiles' : 'Search roles', q, function (v) { nav({ search: v }); })]),
        kpis([
          { label: 'Roles', value: rs.total },
          { label: 'Desk roles', value: rs.rows.filter(function (x) { return x.desk_access; }).length },
          { label: 'Not in a profile', value: rs.rows.filter(function (x) { return !x.profiles.length; }).length },
          { label: 'Role profiles', value: ps.total }
        ])
      ].concat(body));
    });
  }
  function openNewRole() {
    var name = input({ type: 'text', placeholder: 'e.g. Stores Clerk' });
    var desk = h('input', { type: 'checkbox' }); desk.checked = true;
    var close;
    var btn = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
      btn.disabled = true;
      call('rolemgmt.create_role', { role_name: name.value, desk_access: desk.checked ? 1 : 0 }, true).then(function (res) { toast('Created the role ' + res.name, 'good'); close(); render(); }).catch(function (e) { btn.disabled = false; fail(e); });
    } }, 'Create role');
    close = drawer('New role', 'A role does nothing until it is in a role profile and has permissions.', h('div', { class: 'ph-stack ph-stack--lg' }, [
      field('Role name', name), h('label', { class: 'ph-check' }, [desk, 'Can use the desk (the back office)']), h('div', {}, btn)
    ]));
  }
  function openRole(x) {
    var close = drawer(x.name, x.desk_access ? 'Desk role' : 'Website role', h('div', { class: 'ph-muted' }, 'Loading…'));
    call('rolemgmt.profiles').then(function (ps) {
      close();
      var open_ = ps.rows.filter(function (p) { return x.profiles.indexOf(p.name) < 0; });
      var pick = select([['', 'Add to a role profile…']].concat(open_.map(function (p) { return [p.name, p.name]; })), '', function () {}, 'Role profile');
      var c;
      var body = h('div', { class: 'ph-stack ph-stack--lg' }, [
        kvList([['People with it', x.people], ['Access', x.desk_access ? 'Desk' : 'Website only'], ['Status', x.disabled ? 'Disabled' : 'Active']]),
        h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'In these role profiles'), x.profiles.length ? h('div', { class: 'ph-flex ph-flex--wrap' }, x.profiles.map(function (p) { return badge(p, ''); })) : h('div', { class: 'ph-muted' }, 'None yet, so nobody has this role.')]),
        h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Give it to a role profile'), h('div', { class: 'ph-flex', style: 'gap:var(--sp-3)' }, [pick, h('button', { class: 'ph-btn', type: 'button', onclick: function () {
          if (!pick.value) return;
          ask('Add role to profile', 'Add ' + x.name + ' to ' + pick.value + '? Everyone on that profile will get it.', 'Add role', false, function () {
            call('rolemgmt.add_role_to_profile', { role_profile: pick.value, role: x.name }, true).then(function (res) { toast('Added ' + x.name + ' to ' + res.role_profile + ' (' + plural(res.people, 'person', 'people') + ')', 'good'); c(); render(); }).catch(fail);
          });
        } }, 'Add')])])
      ]);
      c = drawer(x.name, x.desk_access ? 'Desk role' : 'Website role', body);
    }).catch(function (e) { close(); fail(e); });
  }
  function openProfile(p) {
    var c;
    var pickRole = null;
    var typer = typeahead('Search a role to add', function (term) { return call('rolemgmt.roles', { search: term }).then(function (res) { return res.rows.filter(function (x) { return p.roles.indexOf(x.name) < 0; }).slice(0, 12).map(function (x) { return { value: x.name, label: x.name, sub: x.desk_access ? 'Desk' : 'Website only' }; }); }); }, function (it) { pickRole = it.value; });
    var body = h('div', { class: 'ph-stack ph-stack--lg' }, [
      kvList([['People on it', p.people], ['System roles inside', p.system_roles ? plural(p.system_roles, 'system role') + ' (not shown)' : 'none']]),
      h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Roles in this profile'), p.roles.length ? h('div', { class: 'ph-flex ph-flex--wrap' }, p.roles.map(function (x) { return badge(x, ''); })) : h('div', { class: 'ph-muted' }, 'No roles.')]),
      h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Add a role'), typer, h('div', { style: 'margin-top:var(--sp-3)' }, h('button', { class: 'ph-btn', type: 'button', onclick: function () {
        var role = pickRole || typer.input.value.trim();
        if (!role) return;
        ask('Add role to profile', 'Add ' + role + ' to ' + p.name + '? Everyone on this profile (' + plural(p.people, 'person', 'people') + ') will get it.', 'Add role', false, function () {
          call('rolemgmt.add_role_to_profile', { role_profile: p.name, role: role }, true).then(function (res) { toast('Added ' + role + ' to ' + res.role_profile + ' (' + plural(res.people, 'person', 'people') + ')', 'good'); c(); render(); }).catch(fail);
        });
      } }, 'Add role'))])
    ]);
    c = drawer(p.name, 'Role profile', body);
  }

  /* ----- Doctype permissions ----- */
  var PERM_LABEL = { select: 'Select', read: 'Read', write: 'Write', create: 'Create', delete: 'Delete', submit: 'Submit', cancel: 'Cancel', amend: 'Amend', report: 'Report', export: 'Export', import: 'Import', share: 'Share', print: 'Print', email: 'Email', mask: 'Mask' };
  function permScreen(r) {
    var g = guardAccess(); if (g) return g;
    var dt = r.q.get('doctype') || '';
    var picker = typeahead('Search a doctype, e.g. Sales Order', function (term) { return call('permmgmt.doctypes', { search: term }).then(function (res) { return res.rows.map(function (x) { return { value: x.name, label: x.name, sub: x.module || '' }; }); }); }, function (it) { go('permissions?' + qs({ doctype: it.value })); }, dt);
    var tools = h('div', { style: 'min-width:min(340px,100%)' }, picker);
    if (!dt) { mount([head('IT dashboard · Doctype permissions', 'Who can do what', 'Pick a doctype to see which roles can read, write, create or delete it, and change that. Doctypes that hold code, users or permissions are managed in Desk.'), filters([tools]), card('', '', empty('Choose a doctype', 'Search above for the kind of document you want to set permissions for.'))]); return Promise.resolve(); }
    mount([head('IT dashboard · Doctype permissions', dt, 'Loading…'), filters([tools]), card('', '', h('div', { class: 'ph-empty' }, h('div', { class: 'ph-empty__title' }, 'Loading…')))]);
    return call('permmgmt.rules', { doctype: dt }).then(function (d) { drawRules(d, tools, r); }).catch(function (e) {
      mount([head('IT dashboard · Doctype permissions', dt, ''), filters([tools]), card('', '', errState(e))]);
    });
  }
  function drawRules(d, tools, r) {
    var dt = d.doctype;
    var roleQ = (r && r.q.get('search')) || '', lvlQ = (r && r.q.get('level')) || '';
    function apply(res) { drawRules(res, tools, r); }
    function nav(o) { go('permissions?' + qs(Object.assign({ doctype: dt, search: roleQ, level: lvlQ }, o))); }
    var levels = d.rules.map(function (x) { return String(x.permlevel); }).filter(function (v, i, a) { return a.indexOf(v) === i; }).sort();
    var shown = d.rules.filter(function (x) {
      return (!lvlQ || String(x.permlevel) === lvlQ) && (!roleQ || x.role.toLowerCase().indexOf(roleQ.toLowerCase()) >= 0);
    });
    var cols = [{ label: 'Role' }, { label: 'Level', num: true }, { label: 'Own only' }].concat(d.types.map(function (t) { return { label: PERM_LABEL[t], num: true }; })).concat([{ label: '' }]);
    var body = shown.map(function (x) {
      return h('tr', {}, [
        h('td', { class: 'is-strong' }, [h('span', { class: 'ph-strong' }, x.role), x.locked ? h('span', { style: 'margin-left:var(--sp-2)' }, badge('System role', '')) : null]),
        h('td', { class: 'is-num' }, String(x.permlevel)), h('td', {}, x.if_owner ? 'Yes' : '—')
      ].concat(d.types.map(function (t) {
        var off = x.locked || (['submit', 'cancel', 'amend'].indexOf(t) >= 0 && !d.submittable);
        var cb = h('input', { type: 'checkbox', disabled: off, 'aria-label': PERM_LABEL[t] + ' for ' + x.role, onchange: function () {
          cb.disabled = true;
          call('permmgmt.set_permission', { doctype: dt, role: x.role, permlevel: x.permlevel, ptype: t, value: cb.checked ? 1 : 0, if_owner: x.if_owner }, true)
            .then(function (res) { toast(PERM_LABEL[t] + ' ' + (cb.checked ? 'allowed' : 'removed') + ' for ' + x.role + ' on ' + dt, 'good'); apply(res); })
            .catch(function (e) { cb.checked = !cb.checked; cb.disabled = false; fail(e); });
        } });
        cb.checked = !!x[t];
        return h('td', { class: 'is-num' }, cb);
      })).concat([h('td', {}, x.locked ? null : h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () {
        ask('Remove rule', 'Remove the rule for ' + x.role + ' (level ' + x.permlevel + ') on ' + dt + '?', 'Remove rule', true, function () {
          call('permmgmt.remove_rule', { doctype: dt, role: x.role, permlevel: x.permlevel, if_owner: x.if_owner }, true).then(function (res) { toast('Removed the rule for ' + x.role + ' on ' + dt, 'good'); apply(res); }).catch(fail);
        });
      } }, 'Remove'))]));
    });
    var roleBox = typeahead('Role to give access', function (term) { var t = term.toLowerCase(); return Promise.resolve(d.roles.filter(function (n) { return !t || n.toLowerCase().indexOf(t) >= 0; }).slice(0, 12).map(function (n) { return { value: n, label: n }; })); }, function () {});
    var level = input({ type: 'number', min: 0, max: 9, value: 0, 'aria-label': 'Level' });
    var add = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
      var role = roleBox.input.value.trim();
      if (!role) return;
      add.disabled = true;
      call('permmgmt.add_rule', { doctype: dt, role: role, permlevel: level.value || 0 }, true).then(function (res) { toast(role + ' can now read ' + dt, 'good'); apply(res); }).catch(function (e) { add.disabled = false; fail(e); });
    } }, 'Add role');
    mount([
      head('IT dashboard · Doctype permissions', dt, d.customised ? 'These rules have been customised. Changes apply straight away.' : 'These are the rules the doctype shipped with. Your first change makes an editable copy.', h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () {
        ask('Reset to default', 'Put ' + dt + ' back to the rules it shipped with? Your changes to it will be lost.', 'Reset to default', true, function () {
          call('permmgmt.reset_rules', { doctype: dt }, true).then(function (res) { toast(dt + ' is back to its default permissions', 'good'); apply(res); }).catch(fail);
        });
      } }, 'Reset to default')),
      filters([tools, select([['', 'All levels']].concat(levels.map(function (v) { return [v, 'Level ' + v]; })), lvlQ, function (v) { nav({ level: v }); }, 'Level'), search('Search roles', roleQ, function (v) { nav({ search: v.trim() }); })]),
      kpis([
        { label: 'Rules', value: d.rules.length },
        { label: 'Can read', value: d.rules.filter(function (x) { return x.read; }).length, unit: 'rules' },
        { label: 'Can write', value: d.rules.filter(function (x) { return x.write; }).length, unit: 'rules' },
        { label: 'Can delete', value: d.rules.filter(function (x) { return x['delete']; }).length, unit: 'rules' }
      ]),
      card('Rules', shown.length === d.rules.length ? plural(d.rules.length, 'rule') : shown.length + ' of ' + plural(d.rules.length, 'rule'), shown.length ? table(cols, body) : empty(d.rules.length ? 'No matching rules' : 'No rules yet', d.rules.length ? 'Try another role or level.' : 'Add a role below to give it access.'), true),
      card('Give another role access', 'Starts with Read; tick the rest above.', h('div', { class: 'ph-flex ph-flex--wrap', style: 'padding:var(--sp-4);align-items:flex-end' }, [h('div', { style: 'min-width:260px;flex:1' }, roleBox), h('div', { class: 'ph-field' }, [h('label', {}, 'Level'), level]), add]))
    ]);
  }

  /* ----- User permissions ----- */
  function userPermScreen(r) {
    var g = guardAccess(); if (g) return g;
    var q = r.q.get('search') || '', scope = r.q.get('scope') || '', dtype = r.q.get('doctype') || '';
    function nav(o) { go('userperms?' + qs(Object.assign({ search: q, scope: scope, doctype: dtype }, o))); }
    return call('permmgmt.user_permissions', { search: q }).then(function (d) {
      var all = d.rows, people = {}, types = {}, defaults = 0, limited = 0;
      all.forEach(function (x) { people[x.user] = 1; types[x.allow] = 1; if (x.is_default) defaults++; if (!x.all_doctypes) limited++; });
      var list = all.filter(function (x) { return (!dtype || x.allow === dtype) && (scope !== 'default' || x.is_default) && (scope !== 'limited' || !x.all_doctypes); });
      var rows = list.map(function (x) {
        return h('tr', {}, [
          h('td', {}, who(x.full_name, x.user)), h('td', {}, x.allow), h('td', { class: 'is-strong' }, x.for_value),
          h('td', {}, x.all_doctypes ? 'All doctypes' : x.applicable_for), h('td', {}, x.is_default ? badge('Default', 'signal') : h('span', { class: 'ph-muted' }, '—')),
          h('td', {}, dateOnly(x.added)),
          h('td', {}, x.locked ? badge('Managed in Desk', '') : h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () {
            ask('Remove restriction', 'Remove the ' + x.allow + ' ' + x.for_value + ' restriction from ' + x.full_name + '?', 'Remove', true, function () {
              call('permmgmt.remove_user_permission', { name: x.name }, true).then(function () { toast('Removed the restriction from ' + x.full_name, 'good'); render(); }).catch(fail);
            });
          } }, 'Remove'))
        ]);
      });
      mount([
        head('IT dashboard · User permissions', 'Limit people to records', 'A user permission limits a person to certain records, such as one company or one farm. They then only see documents that belong to it.', h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: openNewUserPerm }, 'New user permission')),
        filters([
          pills([['', 'All', all.length], ['default', 'Default', defaults], ['limited', 'One doctype', limited]], scope, function (v) { nav({ scope: v }); }),
          select([['', 'All doctypes']].concat(Object.keys(types).sort().map(function (t) { return [t, t]; })), dtype, function (v) { nav({ doctype: v }); }, 'Doctype'),
          search('Search person, doctype or value', q, function (v) { nav({ search: v.trim() }); })
        ]),
        kpis([{ label: 'Permissions', value: all.length }, { label: 'People', value: Object.keys(people).length }, { label: 'Doctypes', value: Object.keys(types).length }, { label: 'Defaults', value: defaults }]),
        card('Permissions', plural(list.length, 'row'), rows.length ? table([{ label: 'Person' }, { label: 'Restricted doctype' }, { label: 'Value' }, { label: 'Applies to' }, { label: 'Default' }, { label: 'Added' }, { label: '' }], rows) : empty('No user permissions', all.length ? 'Nothing matches these filters.' : 'Nobody is limited to specific records yet.'), true)
      ]);
    });
  }
  function openNewUserPerm() {
    var picked = { user: '', allow: '', value: '', applicable: '' };
    var userBox = typeahead('Search a person', function (term) { return call('usermgmt.users', { search: term }).then(function (res) { return res.rows.filter(function (x) { return !x.locked; }).slice(0, 10).map(function (x) { return { value: x.name, label: x.full_name, sub: x.name }; }); }); }, function (it) { picked.user = it.value; });
    var allowBox = typeahead('Search a doctype, e.g. Company', function (term) { return call('permmgmt.linkable_doctypes', { search: term }).then(function (res) { return res.rows.map(function (x) { return { value: x.name, label: x.name, sub: x.module || '' }; }); }); }, function (it) { picked.allow = it.value; picked.applicable = ''; valueBox.input.value = ''; picked.value = ''; loadApplicable(); });
    var valueBox = typeahead('Search the record', function (term) { if (!picked.allow) return Promise.resolve([]); return call('permmgmt.link_values', { doctype: picked.allow, search: term }).then(function (res) { return res.rows.map(function (n) { return { value: n, label: n }; }); }); }, function (it) { picked.value = it.value; });
    var all = h('input', { type: 'checkbox' }); all.checked = true;
    var dflt = h('input', { type: 'checkbox' });
    var appl = select([['', 'Choose a doctype…']], '', function (v) { picked.applicable = v; }, 'Applies to');
    var applField = field('Applies to', appl, 'Only documents of this doctype are limited.'); applField.hidden = true;
    function loadApplicable() { if (all.checked || !picked.allow) return; call('permmgmt.applicable_doctypes', { allow: picked.allow }).then(function (res) { clear(appl); [['', 'Choose a doctype…']].concat(res.rows.map(function (n) { return [n, n]; })).forEach(function (o) { appl.appendChild(h('option', { value: o[0] }, o[1])); }); }).catch(fail); }
    all.addEventListener('change', function () { applField.hidden = all.checked; loadApplicable(); });
    var close;
    var btn = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
      var forValue = picked.value || valueBox.input.value.trim(), user = picked.user || userBox.input.value.trim(), allow = picked.allow || allowBox.input.value.trim();
      btn.disabled = true;
      call('permmgmt.add_user_permission', { user: user, allow: allow, for_value: forValue, apply_to_all_doctypes: all.checked ? 1 : 0, applicable_for: all.checked ? '' : (picked.applicable || appl.value), is_default: dflt.checked ? 1 : 0 }, true)
        .then(function () { toast('Limited ' + userBox.input.value + ' to ' + allow + ' ' + forValue, 'good'); close(); render(); }).catch(function (e) { btn.disabled = false; fail(e); });
    } }, 'Add user permission');
    close = drawer('New user permission', 'Limit a person to one record.', h('div', { class: 'ph-stack ph-stack--lg' }, [
      field('Person', userBox), field('Doctype to restrict', allowBox, 'For example Company, Farm or Warehouse.'), field('Record', valueBox),
      h('label', { class: 'ph-check' }, [all, 'Apply to all doctypes']), applField, h('label', { class: 'ph-check' }, [dflt, 'Use as their default value']), h('div', {}, btn)
    ]));
  }

  var KIND_BADGE = { crash: 'bad', error: 'warn', api: 'signal', log: '' };
  function viewTabs(view, extra) {
    return pills([['issues', 'Issues'], ['log', 'Error log']], view, function (v) { go('crashlytics?' + qs(Object.assign({ view: v === 'log' ? 'log' : '' }, extra || {}))); });
  }
  /* Crashlytics: a From → To date pair that fills the hash on change; the loading card shows while a list is fetched. */
  function crDates(since, until, onChange) {
    var a = h('input', { type: 'date', 'aria-label': 'From', value: since || '', onchange: function () { onChange({ since: a.value, until: b.value }); } });
    var b = h('input', { type: 'date', 'aria-label': 'To', value: until || '', onchange: function () { onChange({ since: a.value, until: b.value }); } });
    return h('label', { class: 'ph-daterange', title: 'When the report was last seen' }, [a, h('span', { class: 'ph-daterange__sep' }, '→'), b]);
  }
  function crLoading(title, sub) { mount([head('IT dashboard · Crashlytics', title, sub), card('', '', empty('Loading…', ''), true)]); }
  function crashlytics(r) {
    if (r.q.get('view') === 'log') return errorLog(r);
    var status = r.q.get('status') || 'Open', kind = r.q.get('kind') || '', q = r.q.get('search') || '', since = r.q.get('since') || '', until = r.q.get('until') || '';
    crLoading('Crashlytics', 'Crashes, errors and failed requests reported by your apps.');
    return call('problems', { app: appName, status: status, kind: kind, search: q, since: since, until: until }).then(function (d) {
      function nav(over) { var o = { status: status, kind: kind, search: q, since: since, until: until }; Object.keys(over).forEach(function (k) { o[k] = over[k]; }); go('crashlytics?' + qs(o)); }
      var sum = function (key) { return d.rows.reduce(function (a, x) { return a + x[key]; }, 0); };
      var rows = [];
      d.rows.forEach(function (p) {
        function open() { openIssue(p); }
        rows.push(h('tr', { class: 'is-link', tabindex: 0, onclick: open, onkeydown: function (e) { if (e.key === 'Enter') open(); } }, [
          h('td', { class: 'itd-issue' }, [h('div', { class: 'ph-strong itd-clamp' }, p.title || '(no title)'), p.culprit ? h('div', { class: 'ph-mono ph-muted ph-truncate' }, p.culprit) : null]),
          h('td', {}, badge(p.kind, KIND_BADGE[p.kind])),
          h('td', {}, p.app),
          h('td', { class: 'is-num' }, String(p.times)),
          h('td', { class: 'is-num' }, String(p.people)),
          h('td', { class: 'is-num' }, String(p.devices)),
          h('td', {}, p.version ? (p.first_version && p.first_version !== p.version ? p.first_version + ' → ' + p.version : p.version) + (p.fixed_in ? ' · fixed in ' + p.fixed_in : '') : '—'),
          h('td', {}, ago(p.last_seen)),
          h('td', {}, badge(p.status, p.status === 'Open' ? 'warn' : p.status === 'Resolved' ? 'good' : ''))
        ]));
      });
      var cols = [{ label: 'Issue' }, { label: 'Kind' }, { label: 'App' }, { label: 'Events', num: true }, { label: 'Users', num: true }, { label: 'Devices', num: true }, { label: 'Versions' }, { label: 'Last seen' }, { label: 'Status' }];
      var bk = d.by_kind || {};
      mount([
        head('IT dashboard · Crashlytics', 'Crashlytics', 'Crashes, errors and failed requests reported by your apps. Click an issue for the details and to resolve it.'),
        filters([
          viewTabs('issues'),
          pills([['Open', 'Open', (d.by_status || {}).Open || 0], ['Resolved', 'Resolved', (d.by_status || {}).Resolved || 0], ['Ignored', 'Ignored', (d.by_status || {}).Ignored || 0]], status, function (v) { nav({ status: v }); }),
          select([['', 'All kinds'], ['crash', 'Crashes (' + (bk.crash || 0) + ')'], ['error', 'Errors (' + (bk.error || 0) + ')'], ['api', 'API failures (' + (bk.api || 0) + ')'], ['log', 'Logs (' + (bk.log || 0) + ')']], kind, function (v) { nav({ kind: v }); }, 'Kind'),
          appSelect(),
          search('Search an error or file', q, function (v) { nav({ search: v }); }),
          h('div', { class: 'ph-filters__spacer' }),
          crDates(since, until, nav)
        ]),
        kpis([
          stat('Issues', d.total, status.toLowerCase()),
          stat('Crashes', d.rows.filter(function (x) { return x.kind === 'crash'; }).length, 'the app closed', { dark: d.rows.some(function (x) { return x.kind === 'crash'; }) }),
          stat('Events', sum('times'), 'reported in total'),
          stat('Users affected', sum('people'), 'counted per issue')
        ]),
        card('', '', rows.length ? table(cols, rows) : empty('No issues', 'Nothing matches these filters.'), true)
      ]);
    });
  }
  /* The raw event log: who it came from, what it said; words like "payload" are hidden until you bring them back. */
  function errorLog(r) {
    var user = r.q.get('user') || '', kind = r.q.get('kind') || '', q = r.q.get('search') || '', page = parseInt(r.q.get('page') || '0', 10) || 0;
    var since = r.q.get('since') || '', until = r.q.get('until') || '';
    var hideParam = r.q.has('hide') ? r.q.get('hide') : null;
    crLoading('Error log', 'Every report the apps sent, newest first.');
    return call('error_log', { app: appName, user: user, kind: kind, search: q, hide: hideParam, page: page, since: since, until: until }).then(function (d) {
      var hidden = d.hidden || [];
      function nav(over) {
        var o = { view: 'log', user: user, kind: kind, search: q, since: since, until: until, hide: hidden.join(',') || '-', page: 0 };
        Object.keys(over).forEach(function (k) { o[k] = over[k]; });
        go('crashlytics?' + qs(o));
      }
      var rows = d.rows.map(function (x) {
        function open() { openLogEvent(x); }
        return h('tr', { class: 'is-link', tabindex: 0, onclick: open, onkeydown: function (e) { if (e.key === 'Enter') open(); } }, [
          h('td', {}, ago(x.ts)),
          h('td', {}, who(x.person || 'Not signed in', x.user)),
          h('td', {}, badge(x.kind, KIND_BADGE[x.kind])),
          h('td', { class: 'itd-issue' }, [h('div', { class: 'ph-strong itd-clamp' }, x.title), x.screen ? h('div', { class: 'ph-mono ph-muted ph-truncate' }, x.screen) : null]),
          h('td', {}, [x.app, ' ', h('span', { class: 'ph-muted' }, x.version)]),
          h('td', {}, x.device || '—')
        ]);
      });
      var cols = [{ label: 'When' }, { label: 'User' }, { label: 'Kind' }, { label: 'Error' }, { label: 'App' }, { label: 'Device' }];
      var chips = hidden.map(function (t) {
        return h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', title: 'Show these again', onclick: function () { nav({ hide: hidden.filter(function (x) { return x !== t; }).join(',') || '-' }); } }, 'Hiding “' + t + '” ✕');
      });
      var addBox = h('input', { class: 'ph-control', type: 'text', placeholder: 'Hide titles containing…', style: 'max-width:220px', onkeydown: function (e) {
        if (e.key === 'Enter' && addBox.value.trim()) nav({ hide: hidden.concat([addBox.value.trim()]).join(',') });
      } });
      var peopleOptions = [['', 'Everyone']].concat(d.people.map(function (p) { return [p.user, p.name + ' (' + p.count + ')']; }));
      if (user && !d.people.some(function (p) { return p.user === user; })) peopleOptions.push([user, user]);
      var pager = [];
      if (page > 0) pager.push(h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () { nav({ page: page - 1 }); } }, 'Newer'));
      if (d.more) pager.push(h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () { nav({ page: page + 1 }); } }, 'Older'));
      mount([
        head('IT dashboard · Crashlytics', 'Error log', 'Every report the apps sent, newest first. Filter by the person it came from or by what the title says. Click an entry for the full message.'),
        filters([
          viewTabs('log'),
          select(peopleOptions, user, function (v) { nav({ user: v }); }, 'Created by'),
          select([['', 'All kinds'], ['crash', 'Crashes'], ['error', 'Errors'], ['api', 'API failures'], ['log', 'Logs']], kind, function (v) { nav({ kind: v }); }, 'Kind'),
          appSelect(),
          search('Search the title, message or screen', q, function (v) { nav({ search: v }); }),
          h('div', { class: 'ph-filters__spacer' }),
          crDates(since, until, nav)
        ]),
        kpis([
          stat('Entries', d.shown, 'shown' + (d.more || page ? ' · page ' + (page + 1) : '')),
          stat('People', d.people.length, 'who reported'),
          stat('Hidden', d.hidden_count || 0, hidden.length ? 'by your hide list' : 'nothing hidden')
        ]),
        h('div', { class: 'ph-flex ph-flex--wrap', style: 'align-items:center;gap:var(--sp-2);margin:var(--sp-3) 0' }, chips.concat([addBox, d.hidden_count ? h('span', { class: 'ph-muted' }, plural(d.hidden_count, 'entry', 'entries') + ' hidden') : null])),
        card('', plural(d.shown, 'entry', 'entries'), rows.length ? table(cols, rows) : empty('No entries', 'Nothing matches these filters.'), true),
        pager.length ? h('div', { class: 'ph-flex', style: 'gap:var(--sp-2);margin-top:var(--sp-3)' }, pager) : null
      ]);
    });
  }
  function openLogEvent(x) {
    var body = h('div', { class: 'ph-stack ph-stack--lg' }, [
      h('div', { class: 'ph-flex ph-flex--wrap' }, [badge(x.kind, KIND_BADGE[x.kind]), badge(x.app, 'outline'), x.fatal ? badge('Fatal', 'bad') : null]),
      kvList([['When', x.ts], ['User', x.person ? x.person + (x.user && x.user !== x.person ? ' (' + x.user + ')' : '') : 'Not signed in'], ['Screen', x.screen], ['App version', x.version], ['Device', x.device], ['System', x.platform], ['Request', x.request]]),
      h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Message'), h('pre', { class: 'itd-code' }, x.message || x.title)])
    ]);
    if (x.stack) body.appendChild(h('details', { class: 'itd-dev', open: true }, [h('summary', {}, 'Developer details'), h('pre', { class: 'itd-code' }, x.stack)]));
    drawer(x.title, ago(x.ts), body);
  }
  function openIssue(p) {
    var who_ = h('div', { class: 'ph-muted' }, 'Loading…');
    call('problem_people', { name: p.name }).then(function (res) { who_.textContent = res.rows.length ? res.rows.map(function (x) { return x.name + (x.times > 1 ? ' (' + x.times + '×)' : ''); }).join(', ') : 'No signed-in people recorded.'; }).catch(function () { who_.textContent = ''; });
    var close;
    function setStatus(st) { call('set_problem_status', { name: p.name, status: st }, true).then(function () { toast('Marked ' + st.toLowerCase(), 'good'); close(); render(); }).catch(fail); }
    var body = h('div', { class: 'ph-stack ph-stack--lg' }, [
      h('div', { class: 'ph-flex ph-flex--wrap' }, [badge(p.kind, KIND_BADGE[p.kind]), badge(p.status, p.status === 'Open' ? 'warn' : p.status === 'Resolved' ? 'good' : ''), badge(p.app, 'outline')]),
      p.culprit ? h('div', { class: 'ph-mono ph-muted', style: 'overflow-wrap:anywhere' }, p.culprit) : null,
      kvList([['Events', p.times], ['Users affected', p.people], ['Devices', p.devices], ['First seen', ago(p.first_seen)], ['Last seen', ago(p.last_seen)], ['First version', p.first_version], ['Last version', p.version], ['Fixed in', p.fixed_in]]),
      h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'Who was affected'), who_]),
      h('div', { class: 'ph-flex ph-flex--wrap' }, [
        p.status === 'Open' ? h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () { setStatus('Resolved'); } }, 'Mark resolved') : h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () { setStatus('Open'); } }, 'Reopen'),
        p.status === 'Open' ? h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () { setStatus('Ignored'); } }, 'Ignore') : null
      ])
    ]);
    if (p.developer) body.appendChild(problemDev(p));
    close = drawer(p.title || '(no title)', plural(p.times, 'event') + ' · last seen ' + ago(p.last_seen), body);
  }
  function problemDev(p) {
    var inner = h('div', {}, h('span', { class: 'ph-muted', style: 'font-size:12px' }, 'Open to load.'));
    var loaded = false;
    var d = h('details', { class: 'itd-dev', open: true, ontoggle: function () {
      if (!d.open || loaded) return;
      loaded = true;
      clear(inner);
      var kv = h('dl', { class: 'ph-kv' });
      [['Level', p.level], ['Issue id', p.name], ['Last event id', p.developer.last_event]].forEach(function (x) { kv.appendChild(h('dt', {}, x[0])); kv.appendChild(h('dd', { class: 'ph-mono' }, x[1] || '—')); });
      inner.appendChild(kv);
      call('itdesk.problem_event', { name: p.name }).then(function (res) {
        var ev = res.latest;
        if (ev && (ev.stack || ev.message)) inner.appendChild(h('pre', { class: 'itd-code' }, ev.stack || ev.message));
      }).catch(function () { /* the summary above is enough */ });
    } }, [h('summary', {}, 'Developer details'), inner]);
    return d;
  }

  /* ---------- Support (inbox + chat) ---------- */
  function initials(name) {
    var parts = String(name || '?').replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean);
    return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  }
  var spListTop = 0, spInfoOpen = false, spDrafts = {};
  function spDayStart(d) { var k = new Date(d); k.setHours(0, 0, 0, 0); return k; }
  function spDaysAgo(d) { return Math.round((spDayStart(new Date()) - spDayStart(d)) / 86400000); }
  function spClock(ts) { var d = parse(ts); return d && !isNaN(d) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''; }
  function spDay(ts) {
    var d = parse(ts); if (!d || isNaN(d)) return '';
    var n = spDaysAgo(d);
    if (n === 0) return 'Today';
    if (n === 1) return 'Yesterday';
    return d.toLocaleDateString(undefined, n < 7 ? { weekday: 'long' } : { day: 'numeric', month: 'short', year: 'numeric' });
  }
  function spStamp(ts) {
    var d = parse(ts); if (!d || isNaN(d)) return '';
    var n = spDaysAgo(d);
    return n === 0 ? spClock(ts) : n === 1 ? 'Yesterday' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }
  function spPending(title, text) { return h('div', { class: 'itd-pending' }, h('div', { class: 'ph-empty' }, [h('div', { class: 'ph-empty__title' }, title), text ? h('div', { class: 'ph-empty__text' }, text) : null])); }
  function support(r) {
    var status = r.q.get('status') || '';
    var onlyWaiting = r.q.get('waiting') === '1';
    var q = r.q.get('search') || '';
    var open = r.parts[1] || '';
    return call('inbox', { app: appName, status: status }).then(function (d) {
      var all = d.rows, chat = null;
      var isAccess = {}; all.forEach(function (c) { if (c.kind === 'access') isAccess[c.id] = 1; });
      function visible() {
        var needle = q.trim().toLowerCase();
        return all.filter(function (c) {
          if (onlyWaiting && !c.waiting) return false;
          return !needle || [c.person, c.user, c.email, c.subject, c.preview].join(' ').toLowerCase().indexOf(needle) >= 0;
        });
      }
      if (!open && window.innerWidth > 1000) { var firstChat = visible().filter(function (c) { return c.kind !== 'access'; })[0]; open = firstChat ? firstChat.id : ''; }
      function hashFor(id, over) { var o = { status: status, waiting: onlyWaiting ? '1' : '', search: q }; Object.keys(over || {}).forEach(function (k) { o[k] = over[k]; }); return 'support' + (id ? '/' + encodeURIComponent(id) : '') + '?' + qs(o); }
      function nav(over) { go(hashFor('', over)); }
      var listBody = h('div', { class: 'itd-list' });
      var countEl = h('div', { class: 'itd-inbox__count' });
      function paintList() {
        var rows = visible(), top = listBody.scrollTop;
        countEl.textContent = plural(rows.length, 'conversation');
        clear(listBody);
        if (!rows.length) { listBody.appendChild(empty('No conversations', onlyWaiting ? 'Nobody is waiting for an answer.' : (q ? 'Nothing matches your search.' : 'Reports and chats from the apps appear here.'))); return; }
        rows.forEach(function (c) {
          var done = c.status === 'Resolved' || c.status === 'Closed';
          var access = c.kind === 'access';
          listBody.appendChild(h('button', { type: 'button', class: 'itd-thread' + (c.id === open ? ' is-on' : ''), onclick: function () { if (access) openAccessRequest(c.id); else go(hashFor(c.id)); } }, [
            h('div', { class: 'ph-avatar' }, initials(c.person || c.user)),
            h('div', { class: 'itd-thread__main' }, [
              h('div', { class: 'itd-thread__top' }, [h('b', {}, c.person || c.user), h('span', { class: 'itd-thread__time' }, spStamp(c.last_activity))]),
              h('div', { class: 'itd-thread__bot' }, [
                h('p', {}, c.subject + (c.preview ? ' — ' + c.preview : '')),
                access ? badge('Access', 'signal') : (c.waiting ? badge(c.waiting_hours < 1 ? 'Waiting' : 'Waiting ' + c.waiting_hours + ' h', c.waiting_hours >= 24 ? 'bad' : 'warn') : badge(done ? c.status : 'Answered', done ? 'good' : ''))
              ])
            ])
          ]));
        });
        listBody.scrollTop = top;
      }
      var searchBox = h('input', { type: 'search', placeholder: 'Search a person or subject', value: q, oninput: function () {
        q = searchBox.value;
        try { history.replaceState(null, '', '#/' + hashFor(open)); } catch (e) { /* the list still filters */ }
        paintList();
      } });
      var list = h('section', { class: 'itd-inbox' }, [
        h('div', { class: 'itd-inbox__tools' }, [
          h('div', { class: 'itd-inbox__row' }, [pills([['', 'All', all.length], ['1', 'Waiting', d.waiting]], onlyWaiting ? '1' : '', function (v) { nav({ waiting: v }); })]),
          h('div', { class: 'itd-inbox__row' }, [appSelect(), d.statuses.length ? select([['', 'Any status']].concat(d.statuses.map(function (x) { return [x, x]; })), status, function (v) { nav({ status: v }); }, 'Status') : null]),
          h('label', { class: 'ph-search' }, [icon(['M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16z', 'M21 21l-4.35-4.35']), searchBox])
        ]),
        countEl, listBody
      ]);
      var chatSlot = h('section', { class: 'itd-chatpane' }, spPending(open && !isAccess[open] ? 'Loading…' : 'Pick a conversation', open && !isAccess[open] ? '' : 'Read it and answer here. The answer reaches their phone as a notification.'));
      var showChat = !!open && !isAccess[open];
      mount(h('div', { class: 'itd-msgr' + (showChat ? ' has-chat' : '') }, [list, chatSlot]));
      paintList(); listBody.scrollTop = spListTop;
      listBody.addEventListener('scroll', function () { spListTop = listBody.scrollTop; });
      if (open && isAccess[open]) openAccessRequest(open);
      else if (open) openConversation(open, chatSlot, function () { go(hashFor('', {})); }).then(function (c) { chat = c; });
      // New messages join the open chat in place: the typed draft and the scroll position are not touched.
      timer = setInterval(function () {
        if (document.hidden) return;
        call('inbox', { app: appName, status: status }).then(function (n) { all = n.rows; paintList(); }).catch(function () { /* the next tick tries again */ });
        if (chat) chat.pull();
      }, 30000);
    });
  }
  /* A request for access to a doctype: who, what, what they have now, and the one step that gives it. */
  var PTYPE_WORDS = { select: 'Find', read: 'Read', write: 'Edit', create: 'Create', delete: 'Delete', submit: 'Submit', cancel: 'Cancel', amend: 'Amend', print: 'Print', email: 'Email', report: 'Reports', import: 'Import', export: 'Export', share: 'Share', mask: 'See hidden values' };
  function openAccessRequest(id) {
    return call('access.detail', { name: id }).then(function (d) {
      var close;
      var chosen = {}; d.asked.forEach(function (p) { chosen[p] = 1; });
      var checks = d.applicable.map(function (p) {
        var have = d.have[p];
        var box = h('input', { type: 'checkbox', disabled: have || d.closed || !!d.refusal, onchange: function () { if (box.checked) chosen[p] = 1; else delete chosen[p]; } });
        box.checked = have || !!chosen[p];
        return h('label', { class: 'ph-flex', style: 'gap:8px;align-items:center;padding:4px 0' }, [box, h('span', {}, PTYPE_WORDS[p] || p), have ? badge('has it', 'good') : (d.asked.indexOf(p) >= 0 ? badge('asked for', 'warn') : null)]);
      });
      // The narrow role made for this doctype is the default: an existing role also gives whatever else it carries.
      var mode = 'new';
      var roleSel = select(d.suggested.map(function (r) { return [r.role, r.role + ' · gives ' + r.gives.join(', ') + (r.all ? '' : ' (not all)')]; }), d.suggested.length ? d.suggested[0].role : '', function () { mode = 'role'; modeRole.checked = true; }, 'Role');
      var modeRole = h('input', { type: 'radio', name: 'arm', disabled: !d.suggested.length, onchange: function () { mode = 'role'; } }), modeNew = h('input', { type: 'radio', name: 'arm', onchange: function () { mode = 'new'; } });
      modeRole.checked = mode === 'role'; modeNew.checked = mode === 'new';
      function give() {
        var picked = Object.keys(chosen).filter(function (p) { return !d.have[p]; });
        if (!picked.length) { toast('Tick what to give.', 'bad'); return; }
        var args = { name: d.id, ptypes: JSON.stringify(picked) };
        if (mode === 'role') args.role = roleSel.value;
        btnGive.disabled = true;
        call('access.grant', args, true).then(function () { toast('Access given to ' + d.person, 'good'); close(); render(); }).catch(function (e) { btnGive.disabled = false; fail(e); });
      }
      var note = h('input', { class: 'ph-control', type: 'text', placeholder: 'Why not (optional)' });
      var btnGive = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: give }, 'Give access');
      var btnNo = h('button', { class: 'ph-btn ph-btn--ghost', type: 'button', onclick: function () {
        call('access.decline', { name: d.id, note: note.value }, true).then(function () { toast('Request closed', 'good'); close(); render(); }).catch(fail);
      } }, 'Decline');
      var body = h('div', { class: 'ph-stack ph-stack--lg' }, [
        h('div', { class: 'ph-flex ph-flex--wrap' }, [badge('Access request', 'signal'), badge(d.status, d.closed ? 'good' : 'warn'), badge(d.doctype, 'outline')]),
        kvList([['Person', d.person + (d.user !== d.person ? ' (' + d.user + ')' : '')], ['Doctype', d.doctype], ['Document', d.document], ['Where it happened', d.route], ['Asked for', d.asked.join(', ')], ['Still missing', d.lacking.join(', ') || 'nothing'], ['Their role profiles', d.profiles_now.join(', ')]]),
        d.reason ? h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, 'What they said'), h('div', { class: 'ph-muted', style: 'white-space:pre-wrap' }, d.reason)]) : null,
        d.refusal ? h('div', { class: 'ph-note ph-note--warn' }, d.refusal) : null,
        d.closed ? h('div', { class: 'ph-note' }, 'This request is ' + d.status.toLowerCase() + '.') : null,
        h('div', {}, [h('div', { class: 'ph-label', style: 'margin-bottom:var(--sp-2)' }, d.closed ? 'Access on ' + d.doctype : 'What to give'), h('div', {}, checks)]),
        d.closed || d.refusal ? null : h('div', { class: 'ph-stack' }, [
          h('div', { class: 'ph-label' }, 'Give it through'),
          h('label', { class: 'ph-flex', style: 'gap:8px;align-items:center' }, [modeRole, h('span', {}, 'An existing role'), roleSel]),
          d.suggested.length ? h('div', { class: 'ph-muted', style: 'font-size:12px;margin:-4px 0 0 24px' }, 'An existing role also gives everything else it carries, on other doctypes too.') : null,
          h('label', { class: 'ph-flex', style: 'gap:8px;align-items:center' }, [modeNew, h('span', {}, 'A role made for this doctype: ' + d.new_role + (d.new_role_exists ? ' (exists; it is extended)' : ''))]),
          h('div', { class: 'ph-muted', style: 'font-size:12px' }, 'The person gets it through a role profile of the same name, like any other access. Write, create and delete also give read.')
        ]),
        d.closed ? null : h('div', { class: 'ph-flex ph-flex--wrap' }, d.refusal ? [note, btnNo] : [btnGive, note, btnNo])
      ]);
      close = drawer('Access to ' + d.doctype, d.person + ' · ' + d.asked.join(', '), body);
    }).catch(fail);
  }
  function openConversation(id, chatSlot, onBack) {
    return call('conversation', { id: id }).then(function (c) {
      var sendBtn, statusSel, seen = {}, lastDay = '', stick = true, ctrl = {};
      var msgs = h('div', { class: 'itd-msgs', onscroll: function () { stick = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80; } });
      function toEnd() { msgs.scrollTop = msgs.scrollHeight; }
      function bubble(m) {
        var who = m.mine ? '' : (m.from_staff ? (m.by || 'Support') : '');
        return h('div', { class: 'itd-msg ' + (m.mine ? 'staff' : m.from_staff ? 'colleague' : 'person') }, [
          who ? h('span', { class: 'itd-msg__by' }, who) : null,
          m.image ? h('a', { href: m.image, target: '_blank', rel: 'noopener' }, h('img', { src: m.image, alt: 'Screenshot sent with the message', loading: 'lazy', onload: function () { if (stick) toEnd(); } })) : null,
          m.text ? h('div', { class: 'itd-msg__text' }, m.text) : null,
          h('time', {}, spClock(m.sent_at))
        ]);
      }
      // adds only the messages not on screen yet; true when something new arrived
      function addMsgs(list) {
        var fresh = false;
        list.forEach(function (m) {
          var key = m.id || (m.sent_at + m.text);
          if (seen[key]) return;
          seen[key] = 1; fresh = true;
          var day = spDay(m.sent_at);
          if (day !== lastDay) { lastDay = day; msgs.appendChild(h('div', { class: 'itd-day' }, day)); }
          msgs.appendChild(bubble(m));
        });
        return fresh;
      }
      ctrl.pull = function () {
        return call('conversation', { id: id }).then(function (n) {
          var was = stick;
          if (addMsgs(n.messages) && was) toEnd();
          if (statusSel && n.status) statusSel.value = n.status;
        }).catch(function () { /* the next tick tries again */ });
      };
      var text = h('textarea', { class: 'ph-control', rows: 1, placeholder: 'Write an answer…', 'aria-label': 'Your answer', oninput: function () { spDrafts[id] = text.value; text.style.height = 'auto'; text.style.height = Math.min(text.scrollHeight, 160) + 'px'; }, onkeydown: function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendBtn.click(); } } });
      sendBtn = h('button', { class: 'ph-iconbtn itd-send', type: 'button', title: 'Send', 'aria-label': 'Send', onclick: function () {
        var v = text.value.trim();
        if (!v) return;
        sendBtn.disabled = true;
        call('send', { id: id, text: v }, true).then(function () {
          text.value = ''; text.style.height = ''; delete spDrafts[id];
          stick = true; sendBtn.disabled = false;
          return ctrl.pull();
        }).catch(function (e) { fail(e); sendBtn.disabled = false; });
      } }, icon(['M22 2L11 13', 'M22 2l-7 20-4-9-9-4 20-7z']));
      if (spDrafts[id]) text.value = spDrafts[id];
      var details = h('aside', { class: 'itd-details' + (spInfoOpen ? ' is-open' : ''), 'aria-label': 'Details' });
      var infoBtn = h('button', { class: 'ph-iconbtn ph-iconbtn--flat ph-iconbtn--sm', type: 'button', title: 'Details', 'aria-label': 'Show or hide details', onclick: function () { spInfoOpen = !spInfoOpen; details.classList.toggle('is-open', spInfoOpen); } }, icon(['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v5', 'M12 8h.01']));
      statusSel = c.statuses.length ? select(c.statuses.map(function (x) { return [x, x]; }), c.status, function (v) { call('set_conversation_status', { id: id, status: v }, true).then(function () { toast('Status: ' + v, 'good'); render(); }).catch(fail); }, 'Status') : null;
      var chat = h('div', { class: 'itd-chat' }, [
        h('div', { class: 'itd-chathead' }, [
          h('button', { class: 'ph-iconbtn ph-iconbtn--flat ph-iconbtn--sm itd-back', type: 'button', title: 'Back', 'aria-label': 'Back to conversations', onclick: onBack }, icon(['M15 18l-6-6 6-6'])),
          h('div', { class: 'ph-avatar' }, initials(c.person)),
          h('div', { class: 'itd-chathead__who' }, [h('b', {}, c.person), h('small', {}, (c.email && c.email !== c.person ? c.email + ' · ' : '') + c.subject)]),
          statusSel, infoBtn
        ]),
        h('div', { class: 'itd-chatmain' }, [msgs, h('div', { class: 'itd-compose' }, [text, sendBtn]), details])
      ]);
      clear(chatSlot);
      chatSlot.appendChild(chat);
      addMsgs(c.messages);
      toEnd();
      if (spDrafts[id]) { text.style.height = Math.min(text.scrollHeight, 160) + 'px'; }
      if (window.innerWidth > 1000) text.focus({ preventScroll: true });
      var kv = h('dl', { class: 'ph-kv' });
      [['Name', c.person], ['Email', c.email], ['App', c.app], ['App version', c.app_version], ['Device', c.device], ['System', c.os], ['Status', c.status]].forEach(function (p) {
        if (!p[1]) return;
        kv.appendChild(h('dt', {}, p[0]));
        kv.appendChild(h('dd', {}, p[1]));
      });
      details.appendChild(h('div', { class: 'itd-details__head' }, [h('div', { class: 'ph-card__title' }, 'Details'), h('button', { class: 'ph-iconbtn ph-iconbtn--flat ph-iconbtn--sm', type: 'button', title: 'Close', 'aria-label': 'Close details', onclick: function () { spInfoOpen = false; details.classList.remove('is-open'); } }, icon(['M18 6L6 18', 'M6 6l12 12']))]));
      details.appendChild(kv);
      if (c.developer) details.appendChild(h('details', { class: 'itd-dev' }, [h('summary', {}, 'Developer details'), h('pre', { class: 'itd-code' }, JSON.stringify(c.developer.diagnostics || {}, null, 2)), h('a', { class: 'ph-link', href: c.developer.desk_url }, 'Open in Desk')]));
      return ctrl;
    }).catch(function (e) { clear(chatSlot); chatSlot.appendChild(h('div', { class: 'itd-pending' }, errState(e))); return null; });
  }

  /* ---------- Apps ---------- */
  function apps(r) {
    var scope = (r && r.q.get('scope')) || '', aq = (r && r.q.get('search')) || '';
    var APP_SCOPES = [['', 'All'], ['behind', 'Behind'], ['issues', 'With issues'], ['tickets', 'Open tickets']];
    mount([head('IT dashboard · Apps', 'Your apps', 'Adoption is the share of people on the current version.'), card('', '', h('div', { class: 'ph-muted', style: 'padding:var(--sp-4)' }, 'Loading…'), true)]);
    return call('apps').then(function (d) {
      var all = d.rows;
      var tot = all.reduce(function (a, x) { a.people += x.people; a.behind += x.behind; a.problems += x.problems; a.tickets += x.open_tickets; return a; }, { people: 0, behind: 0, problems: 0, tickets: 0 });
      var cnt = { '': all.length, behind: all.filter(function (x) { return x.behind; }).length, issues: all.filter(function (x) { return x.problems; }).length, tickets: all.filter(function (x) { return x.open_tickets; }).length };
      var shown = all.filter(function (x) {
        if (scope === 'behind' && !x.behind) return false;
        if (scope === 'issues' && !x.problems) return false;
        if (scope === 'tickets' && !x.open_tickets) return false;
        return !aq || x.app.toLowerCase().indexOf(aq.toLowerCase()) >= 0;
      });
      var rows = shown.map(function (a) {
        return h('tr', {}, [
          h('td', {}, who(a.app, a.version ? 'Version ' + a.version + (a.released_days_ago != null ? ' · released ' + days(a.released_days_ago) + (a.released_days_ago ? ' ago' : '') : '') : 'No release found yet')),
          h('td', { style: 'min-width:160px' }, a.adoption == null ? '—' : h('div', { class: 'ph-flex' }, [h('div', { class: 'ph-grow' }, progress(a.adoption)), h('span', { class: 'ph-strong' }, a.adoption + '%')])),
          h('td', { class: 'is-num' }, String(a.people)),
          h('td', { class: 'is-num' }, a.behind ? badge(String(a.behind), 'warn') : '0'),
          h('td', { class: 'is-num' }, String(a.away)),
          h('td', { class: 'is-num' }, a.problems ? badge(plural(a.problems, 'issue') + ' · ' + a.people_hurt + ' users', 'bad') : '0'),
          h('td', { class: 'is-num' }, String(a.open_tickets))
        ]);
      });
      var cols = [{ label: 'App' }, { label: 'On current version' }, { label: 'People', num: true }, { label: 'Behind', num: true }, { label: 'Away', num: true }, { label: 'Issues', num: true }, { label: 'Open tickets', num: true }];
      mount([
        head('IT dashboard · Apps', 'Your apps', 'Adoption is the share of people on the current version.', [checkButton(render)]),
        filters([
          pills(APP_SCOPES.map(function (s) { return [s[0], s[1], cnt[s[0]]]; }), scope, function (v) { go('apps?' + qs({ scope: v, search: aq })); }),
          search('Search an app', aq, function (v) { go('apps?' + qs({ scope: scope, search: v })); })
        ]),
        kpis([{ label: 'Apps', value: all.length }, { label: 'People', value: tot.people }, { label: 'Behind', value: tot.behind }, { label: 'Open tickets', value: tot.tickets }]),
        card('', '', rows.length ? table(cols, rows) : empty(all.length ? 'No apps match' : 'No apps yet', all.length ? 'Try another filter.' : 'Apps show up once they are registered.'), true)
      ]);
    });
  }

  /* ---------- App store ---------- */
  var BUCKET_BADGE = { current: ['Up to date', 'good'], forgot: ['Needs update', 'warn'], cant_update: ['Can’t update', 'bad'], away: ['Not seen lately', ''], unknown: ['Unknown', ''] };
  function openInstallers(a) {
    var body = h('div', {}, h('div', { class: 'ph-muted' }, 'Loading…'));
    drawer(a.app, 'Who has installed it', body);
    call('installers', { app: a.app }).then(function (d) {
      clear(body);
      var behind = d.people.filter(function (p) { return p.bucket === 'forgot' || p.bucket === 'cant_update'; }).length;
      body.appendChild(h('div', { class: 'ph-muted', style: 'margin-bottom:var(--sp-3)' }, plural(d.people.length, 'person', 'people') + (d.latest ? ' · current version ' + d.latest : '') + (behind ? ' · ' + behind + ' behind' : '')));
      if (!d.people.length) { body.appendChild(empty('Nobody yet', 'Nobody has opened this app on a registered device.')); return; }
      d.people.forEach(function (p) {
        var b = BUCKET_BADGE[p.bucket] || BUCKET_BADGE.unknown;
        body.appendChild(h('div', { style: 'padding:var(--sp-3) 0;border-bottom:1px solid var(--hairline)' }, [
          h('div', { class: 'ph-flex ph-flex--between' }, [h('div', { class: 'ph-strong' }, p.name), badge(b[0], b[1])]),
          h('div', { class: 'ph-muted', style: 'font-size:12px' }, (p.name !== p.user ? p.user + ' · ' : '') + (p.team ? p.team + ' · ' : '') + (p.version ? 'version ' + p.version : 'version unknown')),
          h('div', { class: 'ph-muted', style: 'font-size:12px' }, (p.device ? p.device + ' · ' : '') + 'last opened ' + ago(p.last_seen))
        ]));
      });
    }).catch(function (e) { clear(body); body.appendChild(errState(e)); });
  }
  function checkButton(after) {
    var btn = h('button', { class: 'ph-btn ph-btn--primary', type: 'button', onclick: function () {
      var before = {};
      btn.disabled = true;
      btn.textContent = 'Checking…';
      call('store.apps').then(function (d) { d.apps.forEach(function (a) { before[a.app] = a.version; }); }).catch(function () { /* compare against nothing */ }).then(function () {
        return call('store.check_updates', {}, true);
      }).then(function (res) {
        var changed = res.apps.filter(function (a) { return before[a.app] && before[a.app] !== a.version; }).map(function (a) { return a.app + ' ' + a.version; });
        if (!res.refreshed) toast('Checked a moment ago. Try again in ' + res.retry_in + ' s.', 'warn');
        else toast(changed.length ? 'New: ' + changed.join(', ') : 'Everything is up to date.', 'good');
        after();
      }).catch(function (e) { fail(e); btn.disabled = false; btn.textContent = 'Check for updates'; });
    } }, 'Check for updates');
    return btn;
  }
  function store() {
    return call('store.apps').then(function (d) {
      var stApps = d.apps || [], stQ = '', stGrid = h('div', {});
      var stMb = stApps.reduce(function (n, a) { return n + (Number(a.size_mb) || 0); }, 0);
      var stNewest = stApps.map(function (a) { return a.released; }).filter(Boolean).sort().pop();
      var tile = function (a) {
        return h('div', { class: 'ph-tile' }, [
          h('div', { class: 'ph-tile__head' }, [h('div', {}, [h('div', { class: 'ph-tile__name' }, a.app), h('div', { class: 'ph-tile__sub' }, 'Version ' + a.version)]), badge('Android', 'signal')]),
          h('div', { class: 'ph-tile__stats' }, [
            h('div', {}, [h('small', {}, 'Version'), h('b', {}, a.version)]),
            h('div', {}, [h('small', {}, 'Released'), h('b', {}, dateOnly(a.released))]),
            h('div', {}, [h('small', {}, 'Size'), h('b', {}, a.size_mb ? a.size_mb + ' MB' : '—')])
          ]),
          h('div', { class: 'ph-stack' }, [
            h('a', { class: 'ph-btn ph-btn--primary ph-btn--block', href: BASE + 'store.download?' + qs({ app: a.app }), download: a.file }, 'Download APK'),
            IT ? h('button', { class: 'ph-btn ph-btn--ghost ph-btn--block', type: 'button', onclick: function () { openInstallers(a); } }, 'Who installed it') : null
          ])
        ]);
      };
      var stPaint = function () {
        clear(stGrid);
        var list = stApps.filter(function (a) { return !stQ || String(a.app).toLowerCase().indexOf(stQ) >= 0; });
        if (!stApps.length) stGrid.appendChild(card('', '', empty('No apps to install yet', 'An app appears here once it has a published Android build.')));
        else if (!list.length) stGrid.appendChild(card('', '', empty('No matching apps', 'Try a different name.')));
        else stGrid.appendChild(h('div', { class: 'ph-tiles' }, list.map(tile)));
      };
      var stInp = h('input', { type: 'search', placeholder: 'Find an app', 'aria-label': 'Find an app', oninput: function () { stQ = stInp.value.trim().toLowerCase(); stPaint(); } });
      stPaint();
      mount([
        head('Install', 'App store', 'The newest version of every app. Download it on your phone and open the file to install.', [checkButton(function () { store().catch(function (e) { mount(errState(e)); }); })]),
        filters([h('label', { class: 'ph-search' }, [icon(['M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16z', 'M21 21l-4.35-4.35']), stInp])]),
        kpis([{ label: 'Apps', value: stApps.length }, { label: 'Newest release', value: stNewest ? dateOnly(stNewest) : '—' }, { label: 'Total size', value: Math.round(stMb * 10) / 10, unit: 'MB' }]),
        h('div', { class: 'ph-notice ph-notice--signal' }, 'When Android asks, allow your browser to install apps from this source. Only the newest version is listed; installing over an existing app keeps its data.'),
        stGrid
      ]);
    });
  }

  /* ---------- boot ---------- */
  function wireShell() {
    var collapse = document.getElementById('ph-collapse');
    if (collapse) collapse.addEventListener('click', function () {
      var on = root.classList.toggle('is-collapsed');
      try { localStorage.setItem('ph2SideCollapsed', on ? '1' : '0'); } catch (e) { /* storage blocked */ }
    });
    var menu = document.getElementById('ph-menu-btn');
    if (menu) menu.addEventListener('click', function () { root.classList.add('is-drawer-open'); });
    var scrim = document.getElementById('ph-scrim');
    if (scrim) scrim.addEventListener('click', function () { root.classList.remove('is-drawer-open'); });
    if (main) main.addEventListener('scroll', function () { main.classList.toggle('is-scrolled', main.scrollTop > 4); }, { passive: true });
    var refresh = document.getElementById('ph-refresh');
    if (refresh) refresh.addEventListener('click', render);
  }
  wireShell();
  if (STORE) {
    store().then(markUpdated).catch(function (e) { mount(errState(e)); });
    return;
  }
  call('apps').then(function (d) { appList = d.rows.map(function (a) { return a.app; }); }).catch(function () { /* filter stays on All apps */ }).then(function () {
    window.addEventListener('hashchange', render);
    render();
  });
})();
