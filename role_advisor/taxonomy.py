# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Parse a Role Profile name into job family, variant and scope.

Kaitet's profile names cram two unrelated dimensions into one parenthetical
slot: `…-Approver (Simotwo)` is a place, `…-Approver (Restricted)` is an
authority level. Nothing can be sorted or reasoned about while both live in the
same position, so this module pulls them apart.

The `variant` axis holds only the qualifiers that *differentiate* otherwise
identical job families - `Approver`, `Restricted`, `Temporary`. Seniority words
like `Supervisor`, `Manager` and `Clerk` stay in the job family, because they
are the job, not a modifier of it: `Production Supervisor` and `Farm Manager`
are different jobs, not different authority levels of one job.

Everything here is pure - no database, no Frappe - so it is cheap to test
against the awkward real names.
"""

import re

SEPARATOR = " | "
SCOPE_JOIN = " - "

# Qualifiers that distinguish variants of the same job family. Deliberately
# narrow: adding `Supervisor` or `Manager` here would strip the job itself.
# Longest first so `That Can Purchase` is matched before `Purchase`.
VARIANT_TOKENS = (
	"That Can Purchase",
	"Approver",
	"Restricted",
	"Verifier",
	"Temporary",
	"COO",
	"HOD",
)

# Place qualifiers seen in the data: companies, farms and branches. Longest
# first so `Karen Roses` wins over `Karen`, and `Kaitet LTD` over `Kaitet`.
SCOPE_TOKENS = (
	"Karen Roses",
	"Kaitet LTD",
	"Lokitela",
	"Endebess",
	"Chepsito",
	"Kaptumbo",
	"Westwood",
	"Simotwo",
	"Torongo",
	"Saboti",
	"Ravine",
	"Kaitet",
	"Karen",
	"Valle",
)

# Acronyms that must survive case normalisation.
ACRONYMS = frozenset(
	{"HR", "QC", "IT", "CFO", "COO", "HOD", "KR", "CFU", "CSU", "LTD", "ICT"}
)


def _normalise_case(text: str) -> str:
	"""Fix all-caps and all-lowercase names without mangling acronyms."""
	words = []
	for word in text.split():
		if word.upper() in ACRONYMS:
			words.append(word.upper())
		elif word.isupper() or word.islower():
			words.append(word.capitalize())
		else:
			words.append(word)

	return " ".join(words)


def _take(text: str, tokens: tuple[str, ...]) -> tuple[str, list[str]]:
	"""Remove each matching token from `text`, preserving the order it appeared.

	Removal is in place, so the remaining words keep their original sequence -
	extracting `Approver` from `Supervisor-Approver (Simotwo)` must not reorder
	`Agriculture Production Supervisor`.
	"""
	hits = []
	for token in tokens:
		pattern = re.compile(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", re.IGNORECASE)
		match = pattern.search(text)
		if match:
			hits.append((match.start(), token))
			text = pattern.sub(" ", text, count=1)

	return text, [token for _position, token in sorted(hits)]


def parse(name: str) -> dict:
	"""Split a profile name into job_family, variant, scope and issue flags.

	Issues are machine-readable flags rather than prose so the workbook can
	filter on them.
	"""
	issues = []

	if name != name.strip():
		issues.append("padding_whitespace")
	if name.isupper() or name.islower():
		issues.append("case_anomaly")
	# ` - ` in one name and `-` in its sibling makes the family unsortable.
	if re.search(r"\s-\S|\S-\s", name):
		issues.append("inconsistent_separator")
	if "/" in name:
		issues.append("composite_name")
	if "+" in name:
		issues.append("conjunction_name")

	working = re.sub(r"[()]", " ", name)
	working = working.replace("/", " ").replace("+", " ")
	working = re.sub(r"\s*-\s*", " ", working)

	working, scope = _take(working, SCOPE_TOKENS)
	working, variant = _take(working, VARIANT_TOKENS)

	# A trailing `User`/`Users` says nothing once the axes are explicit, but a
	# leading or middle one can be part of the job (`Accounting User`).
	words = working.split()
	while words and words[-1].lower() in ("user", "users"):
		words.pop()

	job_family = _normalise_case(" ".join(words)).strip()

	if len(variant) > 1:
		issues.append("multiple_variant")
	if not job_family:
		issues.append("no_job_family")

	return {
		"job_family": job_family,
		"variant": _normalise_case(" ".join(variant)),
		"scope": SCOPE_JOIN.join(scope),
		"issues": issues,
	}


def canonical_name(name: str) -> tuple[str, list[str]]:
	"""Return the proposed `Job Family | Variant | Scope` name and its issues.

	An unparsable name yields an empty proposal rather than a plausible-looking
	guess: a blank cell asks for a human, a wrong string hides from one.
	"""
	parsed = parse(name)
	issues = list(parsed["issues"])

	if "no_job_family" in issues:
		return "", [*issues, "unparsed"]

	segments = (parsed["job_family"], parsed["variant"], parsed["scope"])

	return SEPARATOR.join(s for s in segments if s), issues
