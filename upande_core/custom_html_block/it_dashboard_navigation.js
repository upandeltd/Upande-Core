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

  // Live counts on the record tiles, so the page reports workload rather than
  // just offering links. Deliberately additive: a count that cannot be read —
  // no permission, missing doctype, offline — simply never appears, and the
  // tile is exactly as useful as it was without it.
  try {
    if (!(window.frappe && frappe.db && frappe.db.count)) return;
    root_element.querySelectorAll('.itn-tile[data-count]').forEach(function (tile) {
      var doctype = tile.getAttribute('data-count');
      if (!doctype) return;
      frappe.db.count(doctype).then(function (n) {
        if (!(n > 0)) return;
        var badge = document.createElement('span');
        badge.className = 'itn-n';
        badge.textContent = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
        tile.appendChild(badge);
      }).catch(function () {});
    });
  } catch (e) {}
})();
