"""The submission text, one entry per field on the SIC form.

Rewritten around ONE user. The previous draft named five kinds of beneficiary
— shops, clinics, schools, accountants, government offices — which is a
category, not a customer, and was the sharpest criticism the project received.
A pitch that serves everybody convinces nobody.

The user is now a chemist in a small town. Chosen because it is the vertical
where the evidence is real rather than illustrative: the 17,011-product
purchase history in shared/training/ is an actual pharmacy's, and the
forecaster is trained on it.

Word limits counted rather than eyeballed; the form rejects an over-long
answer at submit time.
"""

THEME = ("ICT, cyber-physical systems, Blockchain, Cognitive computing, "
         "Cloud computing, AI & ML")
NATURE = "Software"
TITLE = "Shishya"
SUBTITLE = ("An apprentice for the small-town chemist — it learns the counter "
            "work by watching, and never leaves the shop")
SCHOOL = "St Andrews High School"

PROBLEM = """
A chemist in a small town stocks around seventeen thousand different products
and orders them from memory. There is no analyst and no buying department;
there is one person who also runs the counter, and who decides on a Tuesday
evening what to reorder based on what they noticed running low.

When they are wrong, somebody goes without. A patient on chronic medication —
blood pressure, thyroid, diabetes — arrives for a monthly refill and the box
is not there. In a town with one pharmacy that means travelling to the next
town, or going without until Thursday. Neither is a small thing when the
prescription is one you are meant to take daily and without a break.

The rest of the day is retyping. Purchase invoices into the stock register.
Stock into the GST return. The same figures entered twice or three times into
software that was written in 2011, runs only on Windows, and has no way to
talk to anything else.

The obvious answer is to put an AI on it, and that is where it stops. Doing so
means uploading the shop's purchase history and its customers' prescription
records to a server the owner does not control, cannot audit, and cannot
delete from. Under the DPDP Act those records are personal data the shop is
answerable for. So the tools that would help are the ones they have the
strongest reason not to touch, and the retyping continues.
"""

NOVELTY = """
Three things together, not found elsewhere in one system.

It learns by being shown. Do the job once; it writes down what it learned as a
numbered procedure in plain English you can correct. Not screen coordinates,
and not a plan re-invented each run — an artefact you can audit before it is
performed.

It trains its own model, on the shop's machine. Running someone else's model
locally is ordinary now; training one is not, and a shop's demand pattern is
private business intelligence that should never go to a vendor. Our forecaster
is written from scratch — forward pass, backpropagation, optimiser — and
trains on the shop's own history in under four seconds.

And it can prove what it did. Every action and refusal lands in an append-only
ledger, and the network lock is measured from inside the sandbox rather than
asserted, so it is testable in ten seconds.
"""

SOLUTION = """
Shishya runs entirely on the chemist's own laptop. No account, no server, no
internet connection.

The AI lives in a sandboxed Linux virtual machine with its own screen and its
own office software. It sees only the folders explicitly mounted into it —
that mount list is the whole security boundary, not a policy enforced in code
— and its outbound network is dropped at the firewall except for the local
model. That lock is re-applied at every boot and reported by asking the
sandbox, never by remembering.

You teach it by doing the job once while it watches. It converts the recording
into a numbered plain-language procedure you can edit, then performs it
against the live application through the accessibility tree, reading each
result back to confirm it landed. That last part is why it works on software
from 2011 that has no API: it reads the window the way a screen reader does.
Where it is unsure it stops and asks rather than guessing.

On top of that sits the counter work: GST billing and tax invoices, a stock
audit against reorder points, monthly reports, and an accounting export. The
forecaster turns reordering from reactive into predictive — not "you have run
out" but "this will run out."

Everything stays a file on the machine, and one command rolls the sandbox back
to clean.
"""

BENEFICIARIES = """
One user, deliberately: the owner-operator of a single-branch pharmacy in a
small town or an urban neighbourhood — the person who runs the counter and
also does the ordering, the GST return and the stock register.
"""

BENEFICIARY_LIST = [
    ("Directly, the chemist",
     "Hours a week of retyping returned, and reordering that is predicted "
     "rather than remembered."),
    ("Their patients",
     "Fewer stockouts of chronic medication in places where the next pharmacy "
     "is in the next town."),
    ("Then, the same shape of business",
     "A general store, a hardware merchant, a small wholesaler — anyone with "
     "many lines, legacy Windows software and records they cannot upload. "
     "India has roughly 63 million MSMEs, almost all below the size that "
     "enterprise automation is ever sold to."),
]

BENEFICIARY_TAIL = (
    "We have deliberately not written this for clinics, schools and government "
    "offices as well. The technique carries to them; the product should earn "
    "one user first.")

DESCRIPTION = """
Shishya is a local AI apprentice for a small pharmacy. It learns a task by
watching the owner do it once, writes down what it learned in plain English
they can edit, then performs it — inside a sandbox, on their own laptop, with
the network switched off and every action recorded in an append-only log. It
also trains its own demand forecaster on the shop's history, on that same
laptop, so the ordering stops being done from memory.
"""

# Only claims demonstrable on the machine, in the room. Anything not yet true
# is stated as not yet true.
EVIDENCE = [
    ("31%", "better than the baseline",
     "Our from-scratch forecaster against 'next month looks like last month', "
     "on a held-out month it never saw. MAE 7.47 against 10.86."),
    ("3.9s", "to train, on the laptop",
     "12,079 products, 17 months, 120,790 training windows. numpy only — no "
     "framework, no GPU, no upload."),
    ("17,011", "real products of history",
     "An actual pharmacy purchase export, 54 columns. Unprompted, it also "
     "found the same supplier spelled two different ways."),
    ("8/8", "steps performed on live software",
     "A taught procedure carried out against a running spreadsheet, each cell "
     "read back to confirm it landed."),
    ("0", "bytes leave the machine",
     "Verified from inside the sandbox: the model answers, github times out. "
     "The lock re-applies itself at every boot."),
    ("24", "automated checks pass",
     "Including a typed-key probe and the network lock read from the guest "
     "rather than remembered."),
]

TEAM = ["K. Umesh", "V. Gowri Shankar", "V. Srothus", "A. Nithya", "T. Sahara"]
