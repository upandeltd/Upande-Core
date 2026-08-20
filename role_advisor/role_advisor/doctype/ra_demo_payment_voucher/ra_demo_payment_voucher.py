# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RADemoPaymentVoucher(Document):
	"""Demo doctype shipped only as a safe target for seeded Custom DocPerm rows.

	Custom DocPerm overrides are per-doctype, not per-role: the moment any Custom
	DocPerm row exists for a doctype, its standard DocPerms are discarded for every
	role on the site. Seeding against real doctypes would therefore rewrite live
	permissions, so the demo profiles point here instead.
	"""

	pass
