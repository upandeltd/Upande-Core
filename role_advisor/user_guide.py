# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Build the Role Advisor user guide as a .docx.

Written for the person administering access, not for a developer: tasks and
concepts, no Frappe internals unless a concept is meaningless without one.
"""

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Inches

NAVY = RGBColor(0x1F, 0x33, 0x46)
GREY = RGBColor(0x55, 0x5F, 0x66)
RED = RGBColor(0xA3, 0x1D, 0x1D)

doc = Document()

# Base style: a readable serif at a comfortable size beats Calibri 11 for a
# document people will actually sit and read.
normal = doc.styles["Normal"]
normal.font.name = "Georgia"
normal.font.size = Pt(11)
normal.paragraph_format.space_after = Pt(8)
normal.paragraph_format.line_spacing = 1.25

for name, size, colour, before in (
    ("Heading 1", 20, NAVY, 22),
    ("Heading 2", 15, NAVY, 18),
    ("Heading 3", 12, NAVY, 14),
):
    style = doc.styles[name]
    style.font.name = "Georgia"
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.color.rgb = colour
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.keep_with_next = True


def para(text="", style=None, italic=False, colour=None, size=None):
    p = doc.add_paragraph(style=style)
    run = p.add_run(text)
    run.italic = italic
    if colour:
        run.font.color.rgb = colour
    if size:
        run.font.size = Pt(size)
    return p


def rich(parts):
    """A paragraph mixing bold, code and plain runs."""
    p = doc.add_paragraph()
    for text, kind in parts:
        run = p.add_run(text)
        if kind == "b":
            run.bold = True
        elif kind == "c":
            run.font.name = "Consolas"
            run.font.size = Pt(10)
        elif kind == "i":
            run.italic = True
    return p


def bullets(items, style="List Bullet"):
    for item in items:
        if isinstance(item, tuple):
            p = doc.add_paragraph(style=style)
            p.add_run(item[0]).bold = True
            p.add_run(" — " + item[1])
        else:
            doc.add_paragraph(item, style=style)


def _no_split(row):
    """Stop a table row breaking across a page - it reads as truncated."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def table(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(10)
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(value))
            run.font.size = Pt(10)
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    for row in t.rows:
        _no_split(row)
    # Repeat the header if a long table does spill over.
    t.rows[0]._tr.get_or_add_trPr().append(__import__("docx").oxml.OxmlElement("w:tblHeader"))
    doc.add_paragraph()
    return t


def callout(title, body, colour=NAVY):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(title + "  ")
    run.bold = True
    run.font.color.rgb = colour
    run.font.size = Pt(10)
    run2 = p.add_run(body)
    run2.font.size = Pt(10)
    doc.add_paragraph()


# ───────────────────────────── title ─────────────────────────────
title = para("Role Advisor", "Heading 1")
title.paragraph_format.space_before = Pt(0)
para("A guide for the people who manage who can do what", italic=True, colour=GREY, size=12)
para("Kaitet Group · August 2026 · github.com/ghost-mann/role-advisor", colour=GREY, size=9)

para("What this is for", "Heading 2")
para(
    "Right now, if someone at Karen Roses needs access changed, the request has to go to "
    "Upande. There is no way to let a Karen Roses person handle it, because the only role "
    "that can change access is System Manager — and System Manager can change everything, "
    "for everyone, in every company."
)
para(
    "Role Advisor creates a middle option. A named person can be given the ability to manage "
    "access for their own company only, and to hand out only a specific, pre-approved list of "
    "access levels. Nothing more."
)
rich([
    ("Everything it does is either a report you read, or an assignment you make after seeing "
     "exactly what it will change. ", ""),
    ("It never changes anything silently.", "b"),
])

# ───────────────────────────── concepts ─────────────────────────────
para("The four words you need", "Heading 2")
para(
    "These come from the ERP itself, not from this app, but nothing else makes sense until "
    "they are clear."
)

table(
    ["Word", "What it means", "Example"],
    [
        ["Role", "One permission bundle. The smallest unit. Rarely handed out on its own.",
         "Gate Guard"],
        ["Role Profile", "A named group of roles. This is what a person is actually given.",
         "Agriculture Supervisor"],
        ["Module Profile", "Which parts of the menu a person sees. Tidies navigation only.",
         "Roses Production Supervisor"],
        ["Designation", "The person's job title, from their employee record.",
         "Spray Supervisor"],
    ],
    widths=[1.1, 3.5, 1.6],
)

callout(
    "Important",
    "A Module Profile only hides menu items. It does not stop anyone reaching those screens by "
    "other means. Real access is controlled by the Role Profile. If you want someone genuinely "
    "unable to touch invoices, that is a Role Profile decision, not a Module Profile one.",
    RED,
)

# ───────────────────────────── getting in ─────────────────────────────
para("Opening it", "Heading 2")
para(
    "Role Advisor is its own application, not a page buried in the ERP menu. There are three "
    "ways in, and they all land in the same place:"
)
bullets([
    ("The apps screen", "the Role Advisor tile, alongside the other applications."),
    ("The address", "type /role-advisor. That is the link to send someone."),
    ("The ERP sidebar", "the User Access entry, which now holds a single button into the app."),
])
para(
    "Once inside, the ERP navigation is gone. Everything Role Advisor does is in its own "
    "sidebar on the left, and the button marked Frappe desk in that sidebar is the way back out."
)

table(
    ["In the sidebar", "What it is for"],
    [
        ["Overview", "The estate in one screen: coverage, module exposure, what needs a decision"],
        ["Anomalies", "Everything wrong or inconsistent, worst first"],
        ["Users / Role Profiles / Modules", "Browse and drill into any of the three"],
        ["Request Access", "Raise a request on someone's behalf"],
        ["Incoming Requests", "The queue: grant, refuse, or re-check what people have asked for"],
        ["Grant Access", "Give someone what they need, working from what they must be able to do"],
        ["Designation Map", "The access level recorded against each job title"],
        ["Bulk Sweep", "Apply the map to everyone it covers, after a preview"],
        ["Reports / Audit Trail", "Read-only history and analysis"],
        ["Delegates & Policy", "System Manager only: who may administer whom"],
    ],
    widths=[1.9, 4.2],
)

# ───────────────────────────── granting ─────────────────────────────
para("Granting access", "Heading 2")
para(
    "The ERP decides what someone may do by looking at the permission rows behind the roles they "
    "hold. So Grant Access asks the question that model can actually answer — what does this "
    "person need to do — and works the access level out from the answer. You do not have to know "
    "the permission model, and you do not have to guess which of eighty-eight names is right."
)

para("How to grant", "Heading 3")
for n, text in enumerate([
    "Pick the person. You immediately see what they can reach today, by area.",
    "Pick an area of the business, then a document within it, then the actions they need — "
    "read, write, create, submit, cancel, delete. Add as many as the job requires.",
    "Read the answer. It names the tightest access level that covers everything you asked for, "
    "how much it grants in total, and how much of that is beyond what you asked for.",
    "Grant it, choose one of the alternatives, or record the whole thing as a request instead.",
], start=1):
    p = doc.add_paragraph(style="List Number")
    p.add_run(text)

para(
    "Only actions that some role on this system genuinely grants are offered. If nothing can "
    "grant what you have asked for, the app says so plainly rather than letting you build a "
    "request that could never be satisfied — and tells you which roles would have to be created "
    "or extended first."
)
para(
    "After the grant, the app re-checks and tells you whether the person can now do each of the "
    "things you asked for. “A profile was assigned” is not the outcome anyone wanted.",
    italic=True,
)

para("Replace, or add?", "Heading 3")
para(
    "Giving someone an access level normally replaces the one they had. That is right "
    "when their job changed, and wrong when their job merely grew — nobody wants to take "
    "away the work someone already does in order to let them do one more thing. So the "
    "answer screen offers both."
)

table(
    ["", "What happens", "Use it when"],
    [
        ["Replace with …",
         "They end up holding exactly the access level that covers the ask, and lose "
         "anything it does not cover.",
         "The job changed. A packer became a supervisor."],
        ["Add to what they have",
         "Their existing roles are kept and the smallest set of roles that covers the "
         "ask is added. A profile carrying both is created, or reused if one already "
         "exists. Nothing is taken away.",
         "The job grew. A buyer now also approves leave."],
    ],
    widths=[1.5, 3.0, 1.7],
)

para(
    "The addition is roles, not another whole access level. Borrowing somebody else's "
    "access level to get at one permission inside it hands over everything else in it too."
)

callout(
    "Why the same addition reuses a profile",
    "If five people each need the same extra permission, adding it five times would create "
    "five access levels that permit exactly the same things — which the Anomalies screen "
    "would then report as a problem, correctly. So an identical one is found and reused "
    "instead, and the name tells you what it is: Purchase + Leave Approver.",
)

para(
    "Delegated administrators cannot do this unless a System Manager switches it on, and "
    "even then only from roles that are already inside the access levels they are allowed "
    "to hand out. Otherwise the allowlist would stop meaning anything.",
    italic=True,
)

para("If you already know which access level you want", "Heading 3")
para(
    "Switch to By profile at the top of the screen. That lists what you may hand out, smallest "
    "first, with the same preview and confirmation as before."
)

callout(
    "Read the “loses” list",
    "Giving someone a new profile replaces their old one — it does not add to it. Anything the "
    "old profile allowed and the new one does not is removed immediately. The preview shows you "
    "this before you commit, and it is the most common surprise.",
)

para(
    "Every assignment is recorded in Access Assignment Log: who did it, to whom, what changed, "
    "and when. Including assignments that changed nothing. The log cannot be edited or deleted "
    "by anyone."
)

# ───────────────────────────── limits ─────────────────────────────
para("What you cannot do (by design)", "Heading 2")
bullets([
    "Reach anyone outside your company.",
    "Hand out an access level that is not on your list.",
    "Hand out anything that would let the recipient change permissions themselves — refused "
    "even if it were on your list by mistake.",
    "Turn someone into a different kind of user, or touch their password or API keys.",
    "Reach anyone with no employee record. Service accounts and contractors are invisible to "
    "you, deliberately.",
    "Change your own company scope, or widen your own list.",
])
para(
    "Your list of grantable profiles is set by a System Manager on your Delegated User Admin "
    "record. You can see your own record but not change it, and not see anyone else's.",
    italic=True,
)

# ───────────────────────────── map ─────────────────────────────
para("The Designation Access Map", "Heading 2")
para(
    "Rather than deciding access one person at a time forever, the map records the decision "
    "once per job title: a Spray Supervisor at Karen Roses gets Agriculture Supervisor. New "
    "starters can then be assigned in bulk."
)
para(
    "The map has been pre-filled by looking at what people with each job title already hold. "
    "That is evidence, not a recommendation — the existing assignments are known to be "
    "inconsistent, so each row carries a confidence rating and the reasoning behind it."
)

table(
    ["Confidence", "Meaning", "Rows"],
    [
        ["High", "Colleagues in the same job and company overwhelmingly agree.", "4"],
        ["Medium", "Some agreement, but a real split. Needs a decision.", "29"],
        ["Low", "Based on a single colleague. Weak evidence.", "45"],
    ],
    widths=[1.2, 3.8, 0.8],
)

rich([
    ("Only High-confidence rows are switched on. ", "b"),
    ("The other 74 are switched off and will not be used until a human reviews them. Open ", ""),
    ("Designation Access Map", "c"),
    (", filter Is Active to No, and read the Evidence column on each row.", ""),
])

para("Rows worth looking at first", "Heading 3")
bullets([
    ("Irrigator", "currently points at a profile with approval rights. An irrigator should "
     "almost certainly not approve anything."),
    ("Quality Controller", "most colleagues hold a broader profile than the job needs."),
    ("Task Worker", "points at a scouting profile, which looks like a mistake."),
    ("Eight job titles have no precedent at all", "including Executive Director and Stores "
     "Accountant. These need a decision from scratch."),
])

# ───────────────────────────── anomalies ─────────────────────────────
para("Anomalies and discrepancies", "Heading 2")
para(
    "The Anomalies screen is the one to open on a Monday. It runs fifteen checks over every "
    "person, access level and permission row on the system, and it distinguishes between two "
    "different kinds of problem — because they need different responses."
)

table(
    ["", "What it means", "Example"],
    [
        ["Anomaly",
         "The access is wrong on its own terms.",
         "An access level that permits nothing, held by 53 people"],
        ["Discrepancy",
         "The access disagrees with something else that is also true.",
         "Two people with the same job in the same company holding different access"],
    ],
    widths=[1.0, 2.6, 2.5],
)

para(
    "Discrepancies are listed first. They are the expensive ones to find by hand, and they are "
    "the ones where somebody has almost certainly made a mistake — an anomaly might be a "
    "deliberate arrangement nobody wrote down."
)

para("What it is finding today", "Heading 3")
table(
    ["", "Finding", "Count"],
    [
        ["Discrepancy", "Job groups that disagree with themselves", "12 groups, 38 people"],
        ["Discrepancy", "People whose access contradicts the designation map", "7"],
        ["Discrepancy", "Accounts holding roles their access level does not grant", "17"],
        ["Anomaly", "Security Guard grants nothing at all", "53 holders"],
        ["Anomaly", "Accounts that can change permissions themselves", "25"],
        ["Anomaly", "Disabled accounts that still carry their access", "66"],
        ["Anomaly", "Enabled accounts with no access level set", "38"],
        ["Anomaly", "Sets of access levels that are identical", "4 sets"],
        ["Anomaly", "Granted accounts unused for six months or more", "88"],
        ["Anomaly", "Access levels nobody holds", "14"],
    ],
    widths=[1.0, 3.4, 1.7],
)

para(
    "Every row can be opened. Clicking a person opens everything known about their access; "
    "clicking Show the other… lists every case rather than the sample. Each finding also carries "
    "a one-line suggestion of what to do about it."
)

callout(
    "Same job, different access",
    "This is the finding worth acting on first. Where a job title in a company has settled on one "
    "access level, the exceptions are either a deliberate variation nobody recorded, or a "
    "mistake — and the app cannot tell which, so it reports rather than decides. A group of two "
    "is never reported: two people doing the same job differently is a coin toss, not a pattern.",
)

# ───────────────────────────── reports ─────────────────────────────
para("The five reports", "Heading 2")
para("All read-only. None of them changes anything.")

table(
    ["Report", "The question it answers", "What it found"],
    [
        ["Designation Gap", "Who has no access level set at all?",
         "68 people, most of whom have no employee record"],
        ["Role Profile Overgrant", "What can each access level actually do?",
         "Upande Team allows almost everything"],
        ["Module Exposure", "Whose menu is untidy?",
         "357 people see every part of the system"],
        ["System Manager Audit", "Who has unrestricted access, and should they?",
         "25 accounts, including a service account and two test logins"],
        ["Role Drift", "Is anyone about to lose access unexpectedly?",
         "17 accounts hold roles no profile accounts for"],
    ],
    widths=[1.5, 2.4, 2.3],
)

callout(
    "The one to read first",
    "Role Profile Overgrant. It is the only report that describes what people can actually do, "
    "rather than what they can see. Everything else is context.",
)

# ───────────────────────────── findings ─────────────────────────────
para("What the review has already turned up", "Heading 2")
para("Findings from the existing setup, in rough order of how much they matter.")

bullets([
    ("Almost everyone can reach almost everything", "316 of roughly 385 people with an access "
     "level can reach Accounts; 309 can reach HR. A handful of modules are properly scoped; the "
     "core business ones are wide open."),
    ("Security Guard grants nothing", "53 people hold an access level that permits no action at "
     "all. Either it is incomplete, or those people need a different one."),
    ("Access levels are duplicated", "Upande Team, Upande Team - COO and Upande Team HR Users "
     "allow exactly the same things, and three other sets do too. The different names promise a difference that does "
     "not exist."),
    ("Temporary staff have more access than permanent", "Temporary -Mechanic allows considerably "
     "more than Mechanic."),
    ("Two test logins have unrestricted access to live", "eric@test.com and test@upande.com both "
     "hold System Manager on the production system, alongside a service account."),
    ("66 disabled accounts still hold access levels", "They cannot log in today, but every "
     "permission is intact. Re-enable one and it silently gets everything back."),
    ("Naming is inconsistent", "40 of 87 access levels have a naming problem — mixed "
     "capitalisation, inconsistent punctuation, and place names mixed with authority levels in "
     "the same position."),
])

# ───────────────────────────── glossary of screens ─────────────────────────────
para("Where everything lives", "Heading 2")
para(
    "Everything below is inside Role Advisor, in the sidebar. Nothing here needs the ERP menu."
)
table(
    ["Screen", "Use it to"],
    [
        ["Grant Access", "Give one person what they need, working from what they must be able to do"],
        ["Anomalies", "Find what is wrong or inconsistent, worst first"],
        ["Incoming Requests", "Answer what people have asked for"],
        ["Designation Map", "Record and review the access level for each job title"],
        ["Bulk Sweep", "Apply the map to everyone it covers, after a preview"],
        ["Audit Trail", "See every change ever made, by whom"],
        ["Delegates & Policy", "System Manager only: who may administer whom, and the thresholds"],
        ["Reports", "Understand the current state before changing it"],
        ["My Access", "Your own access, and how to ask for more. Available to everybody."],
    ],
    widths=[2.2, 4.0],
)

para("If something is refused", "Heading 2")
para(
    "The app explains why rather than failing silently. The common ones:"
)
bullets([
    ("“You are not configured as a delegated user administrator”", "you have no Delegated User "
     "Admin record, or it is switched off. A System Manager sets this up."),
    ("“… is outside the users you administer”", "that person belongs to another company, or has "
     "no employee record."),
    ("“… is not one of the role profiles you may grant”", "ask for it to be added to your list, "
     "if it is appropriate."),
    ("“… cannot be delegated”", "that access level would let the recipient change permissions. "
     "It can only be given by a System Manager."),
    ("“… covers this but is not one of the profiles you may grant”", "the app found an answer "
     "and is telling you before you click, rather than after. Ask for it to be added to your "
     "list, or record the whole thing as a request."),
    ("“Administrator cannot be assigned a role profile”", "assigning an access level replaces "
     "the holder's roles, so pointing it at Administrator would prune the one account "
     "guaranteed to be able to undo it. Refused for everyone."),
    ("“… already covers every one of these. Nothing to add”", "they can already do it. "
     "Check whether the real problem is a user permission or a company restriction rather "
     "than an access level."),
    ("“Composing a new profile is switched off for delegated administrators”", "a System "
     "Manager can enable it in Access Settings, and even then only from roles inside the "
     "delegate's own allowlist."),
])

para("A note on the current stage", "Heading 2")
para(
    "The app is installed and working, but no restrictions apply to anyone until a Delegated "
    "User Admin record is created for them. Until then, everything behaves exactly as it did "
    "before. The first two people intended for this are the Karen Roses IT staff, who already "
    "hold the User Manager role and currently cannot complete the task it implies.",
)

def build(path: str | None = None) -> str:
    """Regenerate the guide. Run after any change to the workflow it describes."""
    import os

    if not path:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(app_dir, "docs", "Role Advisor - User Guide.docx")

    doc.save(path)
    print(path)

    return path


if __name__ == "__main__":
    build()
