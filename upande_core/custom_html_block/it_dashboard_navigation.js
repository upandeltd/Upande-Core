(function () {
  // Poppins, matching the other Upande navigation blocks. Document-level so it
  // reaches this block's shadow root.
  try {
    if (!document.querySelector('link[data-upande-poppins]')) {
      var pf = document.createElement('link');
      pf.rel = 'stylesheet';
      pf.setAttribute('data-upande-poppins', '1');
      pf.href = 'https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap';
      document.head.appendChild(pf);
    }
  } catch (e) {}

  // Role-gate the tiles: data-roles="" shows for everyone; otherwise the tile
  // shows only if the user holds one of the listed roles. System Manager and
  // Administrator always see everything.
  var roles = (window.frappe && frappe.user_roles) || [];
  var isAdmin = roles.indexOf('System Manager') >= 0
    || roles.indexOf('Administrator') >= 0
    || (window.frappe && frappe.user && frappe.user.name === 'Administrator');
  root_element.querySelectorAll('.itn-tile').forEach(function (tile) {
    var req = (tile.getAttribute('data-roles') || '')
      .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (req.length === 0) return;
    var ok = isAdmin || req.some(function (r) { return roles.indexOf(r) >= 0; });
    if (!ok) tile.classList.add('itn-hide');
  });

  // A tile for a record the person may not read is hidden, and never counted: asking the server for it would answer
  // "Insufficient Permission" in a dialog, once per tile. Pages (no data-count) are never hidden here; the dashboard page
  // gates itself.
  var canRead = (window.frappe && frappe.boot && frappe.boot.user && frappe.boot.user.can_read) || null;
  // Only a tile that opens a record in Desk is hidden; a dashboard page tile stays (the dashboard reads on the server
  // and gates itself), it just shows no count.
  root_element.querySelectorAll('.itn-tile[data-count]').forEach(function (tile) {
    var dt = tile.getAttribute('data-count');
    var opensRecord = (tile.getAttribute('href') || '').indexOf('/desk/') === 0;
    if (canRead && dt && canRead.indexOf(dt) < 0) tile.classList.add(opensRecord ? 'itn-hide' : 'itn-nocount');
  });
  // A section whose tiles are all hidden loses its heading too.
  root_element.querySelectorAll('.itn-grid').forEach(function (grid) {
    if (!grid.querySelector('.itn-tile:not(.itn-hide)')) {
      grid.classList.add('itn-hide');
      var title = grid.previousElementSibling;
      if (title && title.classList.contains('itn-title')) title.classList.add('itn-hide');
    }
  });

  // Live counts on the record tiles, so the page reports workload rather than just offering links. Deliberately
  // additive and silent: a count that cannot be read (no permission, missing doctype, offline) never appears and never
  // raises a dialog, and the tile is exactly as useful as it was without it.
  try {
    if (!(window.frappe && frappe.call)) return;
    root_element.querySelectorAll('.itn-tile[data-count]:not(.itn-hide):not(.itn-nocount)').forEach(function (tile) {
      var doctype = tile.getAttribute('data-count');
      if (!doctype) return;
      frappe.call({
        method: 'frappe.client.get_count',
        args: { doctype: doctype },
        type: 'GET',
        silent: true,
        error: function () {},
        callback: function (r) {
          var n = r && r.message;
          if (!(n > 0)) return;
          var badge = document.createElement('span');
          badge.className = 'itn-n';
          badge.textContent = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
          tile.appendChild(badge);
        },
      });
    });
  } catch (e) {}
})();
