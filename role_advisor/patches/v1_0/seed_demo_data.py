# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Seed the Role Advisor demo catalogue, roles and role profiles.

Idempotent: reruns converge rather than duplicating. See role_advisor.demo_data
for what gets created and how to remove it again.
"""

import frappe

from role_advisor.demo_data import seed


def execute():
	seed()
	frappe.db.commit()
