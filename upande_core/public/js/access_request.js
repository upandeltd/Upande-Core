/* Desk side of doctype access requests (see access_requests/detect.py).
   1. A blocked call comes back with `_access_denied` in its JSON, or lands on a route that is a doctype the person cannot read
      (Desk then looks for a Page of that name, and the error does not name the doctype): offer the request in place of
      Frappe's bare "Not permitted" box. Whenever there is nothing to offer, Frappe's own message is shown as usual.
   2. A call that came back with hidden (masked) values carries `X-Access-Masked`: say so once per doctype per session.
   Uses frappe.request.on_error, Frappe's own hook for this; registering a handler is what replaces its default box. */
(function () {
  if (typeof frappe === 'undefined' || !frappe.request || !frappe.request.on_error) return;

  var WORDS = { select: 'find', read: 'open', write: 'edit', create: 'create', delete: 'delete', submit: 'submit', cancel: 'cancel', amend: 'amend', print: 'print', email: 'email', report: 'report on', import: 'import', export: 'export', share: 'share', mask: 'see the hidden values of' };
  var shown = {};
  var guessing = false;

  function offer(hit) {
    var key = hit.doctype + '|' + (hit.ptypes || []).join(',');
    if (shown[key]) return; // one box per thing, however many calls were blocked
    shown[key] = 1;
    var what = (hit.ptypes || []).map(function (p) { return WORDS[p] || p; }).join(', ');
    var d = new frappe.ui.Dialog({
      title: __('You need access'),
      fields: [{ fieldtype: 'HTML', options: '<p>' + __('You cannot {0} <b>{1}</b>.', [what, frappe.utils.escape_html(__(hit.doctype))]) + '</p><p class="text-muted">' + __('You can ask IT for it. It takes a minute.') + '</p>' }],
      primary_action_label: __('Ask for access'),
      primary_action: function () { window.location.href = hit.page; },
      secondary_action_label: __('Close'),
      secondary_action: function () { d.hide(); }
    });
    d.onhide = function () { delete shown[key]; };
    d.show();
    // Frappe's own 403 handling may show its "Not permitted" box beside this one, before or after: take it away.
    [0, 150, 500].forEach(function (ms) { setTimeout(function () { if (frappe.msg_dialog && frappe.msg_dialog.display) frappe.hide_msgprint(); }, ms); });
  }

  // Frappe's own message, for when there is nothing better to say.
  function usual(r) {
    try {
      var messages = r && r._server_messages ? JSON.parse(r._server_messages) : null;
      if (messages) { frappe.hide_msgprint(); frappe.msgprint(messages); }
      else frappe.msgprint({ title: __('Not permitted'), indicator: 'red', message: __('You do not have permission to do that.') });
    } catch (e) { /* nothing more to do */ }
  }

  frappe.request.on_error('PermissionError', function (r) {
    var hit = r && r._access_denied;
    // A refused Page is Desk's fallback lookup for an address, not what the person was after; the route says more (below).
    if (hit && hit.page && hit.doctype !== 'Page') return offer(hit);
    // Desk sends a person to a doctype they cannot read as if it were a page; see ask.doctype_for_route.
    var route = (frappe.get_route && frappe.get_route()) || [];
    var slug = route[0] === 'List' || route[0] === 'Form' ? route[1] : route[0];
    if (!slug || guessing || frappe.session.user === 'Guest') return usual(r);
    guessing = true;
    frappe.call({
      method: 'upande_core.access_requests.ask.doctype_for_route',
      args: { slug: String(slug).toLowerCase() },
      type: 'GET',
      silent: true,
      callback: function (res) {
        guessing = false;
        var found = res && res.message;
        if (found && found.doctype) {
          offer({ doctype: found.doctype, ptypes: found.ptypes, page: '/access-request?doctype=' + encodeURIComponent(found.doctype) + '&ptype=' + found.ptypes.join(',') + '&from=' + encodeURIComponent(window.location.pathname) });
        } else usual(r);
      },
      error: function () { guessing = false; usual(r); }
    });
  });

  var told = {};
  $(document).ajaxComplete(function (_e, xhr) {
    var header = xhr && xhr.getResponseHeader && xhr.getResponseHeader('X-Access-Masked');
    if (!header) return;
    header.split(',').forEach(function (doctype) {
      if (!doctype || told[doctype]) return;
      told[doctype] = 1;
      frappe.show_alert({
        message: __('Some values in {0} are hidden from you.', [frappe.utils.escape_html(__(doctype))]) + ' <a href="/access-request?doctype=' + encodeURIComponent(doctype) + '&ptype=mask">' + __('Ask for access') + '</a>',
        indicator: 'orange'
      }, 12);
    });
  });
})();
