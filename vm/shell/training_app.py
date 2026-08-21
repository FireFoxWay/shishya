#!/usr/bin/env python3
"""
Training Data — drop in documents, then ask about them.

Drag any file onto the list (or use Add). It is read, split, and indexed. Then
ask a question in plain language and get an answer drawn only from what was
dropped in, with the passages it used shown underneath.

── Why retrieval is keyword-based rather than embeddings ───────────────────

An embedding model would retrieve better. It would also be a second model to
pull, hold in memory beside the 8B and the VM, and explain. Scored term
overlap with rarity weighting is a few dozen lines, needs nothing extra, and
on a folder of tens of documents — which is what this is for — it is good
enough that the model's reading is the bottleneck, not the retrieval.

The rule that matters more than either: the answer must come from the
documents. Asked something the documents do not cover, it says so.
"""

import math
import re
import threading
from collections import Counter
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk   # noqa: E402

import common   # noqa: E402

STOP = set("""a an the and or but if then than that this these those of in on at to for
from by with without into over under is are was were be been being it its as no not
do does did can could should would will shall may might must have has had i you he she
they we what which who whom when where how why""".split())


def terms(text):
    """Words worth matching on, with plurals folded to the singular.

    Without this, "which supplier gives us the HDMI cables" missed every HDMI
    Cable row: the sheet says "Cable" and the question said "cables", so only
    one term landed and the row filter discarded them all. Crude — it would
    fold "bus" to "bu" if not for the length guard — but the alternative is a
    stemmer, and the failure it prevents is worse than the ones it causes.
    """
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


class Library:
    """Chunks plus an inverted index, and — for spreadsheets — a row index.

    The row index exists because prose chunking is wrong for tables. A 1000
    row sheet cut into overlapping 1400-character windows gives the model
    fragments of many unrelated rows at once, and it blends them: asked for
    the HDMI Cable it confidently returned a product id belonging to Golf
    Tees, with a supplier and reorder point that were never in the same row
    as each other.

    So table rows are kept whole and searched as rows. A question that names
    something in the table gets the actual matching lines, with their header,
    and nothing else — there is nothing adjacent for the model to blend in.
    """

    def __init__(self):
        self.chunks = []          # (source, text)
        self.freqs = []           # Counter per chunk
        self.doc_count = Counter()
        self.tables = []          # (source, sheet, header, [row strings])

    def add(self, path):
        text, how = common.extract(path)

        # A sheet arrives as "## Sheet: name" followed by pipe-separated rows.
        if "## Sheet:" in text:
            self._add_table(Path(path).name, text)

        pieces = common.chunk(text)
        for piece in pieces:
            counts = Counter(terms(piece))
            self.chunks.append((Path(path).name, piece))
            self.freqs.append(counts)
            for term in counts:
                self.doc_count[term] += 1
        return len(pieces), how

    def _add_table(self, source, text):
        for block in text.split("## Sheet:"):
            block = block.strip()
            if not block:
                continue
            lines = [l for l in block.splitlines() if l.strip()]
            if len(lines) < 2:
                continue
            sheet, header, rows = lines[0].strip(), lines[1], lines[2:]
            self.tables.append((source, sheet, header, rows))

    # ── searching ───────────────────────────────────────────────────────────

    def search(self, query, k=4):
        rows = self.search_rows(query)
        chunks = self.search_chunks(query, k)
        # Matching rows first: they are exact, and the model reads what comes
        # first most carefully. Prose chunks still follow, because the answer
        # often needs a policy as well as a row.
        return rows + chunks[: max(1, k - len(rows))]

    def search_rows(self, query, limit=30):
        """Rows containing the query's distinctive words, kept verbatim.

        Matching keys on rarity, not on every word. A question says "the
        reorder point and supplier for PRD-1031" — but "reorder" and
        "supplier" are column headings that appear in no row at all, while
        "1031" appears in exactly one. Requiring every word matched nothing;
        requiring any word would return most of the sheet. So a row must
        contain at least one term that is rare within this table, and rows
        are then ranked by how much of the query they cover.
        """
        wanted = set(terms(query))
        if not wanted or not self.tables:
            return []

        out = []
        for source, sheet, header, rows in self.tables:
            counts = self._term_counts(source, sheet, rows)
            total = max(1, len(rows))
            # Rare inside this table: fewer than one row in twenty.
            rare = {t for t in wanted if 0 < counts.get(t, 0) <= max(1, total // 20)}
            if not rare:
                continue

            scored = []
            for row in rows:
                cells = set(terms(row))
                hit_rare = rare & cells
                if not hit_rare:
                    continue
                # Two words must land, not one. Asked whether a student with
                # 68% attendance may sit an exam, a single coincidental "68"
                # in an inventory sheet was enough to drag thirty product rows
                # into a question about school policy. An identifier like
                # PRD-1031 still qualifies — it is two terms, "prd" and "1031".
                if len(wanted & cells) < 2:
                    continue
                scored.append((len(wanted & cells), len(hit_rare), row))
            if not scored:
                continue

            scored.sort(key=lambda r: (-r[1], -r[0]))
            hits = [row for _, _, row in scored[:limit]]
            note = ("" if len(scored) <= limit
                    else f"\n({len(scored)} rows match; the {limit} closest are shown)")
            out.append((f"{source} — {sheet}",
                        f"{header}\n" + "\n".join(hits) + note))
        return out

    def _term_counts(self, source, sheet, rows):
        """How many rows each term appears in, computed once per table."""
        key = (source, sheet)
        cached = getattr(self, "_counts_cache", None)
        if cached is None:
            cached = self._counts_cache = {}
        if key not in cached:
            c = Counter()
            for row in rows:
                for t in set(terms(row)):
                    c[t] += 1
            cached[key] = c
        return cached[key]

    def search_chunks(self, query, k=4):
        wanted = Counter(terms(query))
        if not wanted or not self.chunks:
            return []
        n = len(self.chunks)
        scored = []
        for i, counts in enumerate(self.freqs):
            score = 0.0
            for term, want in wanted.items():
                if term in counts:
                    # Rare terms carry the query. A shared "district" says far
                    # less about relevance than a shared "APP-2291".
                    idf = math.log(1 + n / (1 + self.doc_count[term]))
                    score += want * math.log(1 + counts[term]) * idf
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        if not scored:
            return []

        # Drop the weak tail. Asked which supplier provides HDMI cables, the
        # search was returning two blocks of an unrelated macOS-versus-Windows
        # PDF simply because they were the next best of a bad lot — nearly
        # 3,000 characters the model then has to read and reason past. A
        # passage worth a fifth of the best one is noise, and noise is what
        # what makes it think until it runs out of room.
        best = scored[0][0]
        keep = [(score, i) for score, i in scored[:k] if score >= best * 0.4]
        return [self.chunks[i] for _, i in keep]


# ─── asking vs asking-for ───────────────────────────────────────────────────
# People type what they want into whichever window is already open. Told to
# "create a comparison table in Excel", a question-answering app that replies
# "I cannot find it in the documents" is technically obedient and plainly
# wrong. So the app reads intent first and hands creation work to the document
# writer, using the same documents as source.
#
# Keyword matching rather than asking the model: it is instant, it is
# predictable, and a misfire here would send someone's question off to build a
# spreadsheet — a surprise far more annoying than a missed shortcut.

MAKE_VERBS = ("create", "make", "build", "generate", "draft", "produce",
              "prepare", "write me", "give me", "put together", "compile")

MAKE_KINDS = {
    "Spreadsheet": ("excel", "xlsx", "spreadsheet", "sheet", "table", "grid",
                    "comparison table", "csv"),
    "Presentation": ("powerpoint", "ppt", "pptx", "presentation", "deck",
                     "slides", "slide"),
    "Document": ("word", "docx", "document", "report", "brief", "note",
                 "letter", "summary document", "write-up"),
}


def wants_a_file(question):
    """Returns the kind to build, or None if this is an ordinary question."""
    q = question.lower()
    if not any(v in q for v in MAKE_VERBS):
        return None
    # Spreadsheet before Document: "comparison table in a report" is a table.
    for kind in ("Spreadsheet", "Presentation", "Document"):
        if any(word in q for word in MAKE_KINDS[kind]):
            return kind
    return None


SYSTEM = (
    "You answer using the passages you are given.\n"
    "Every fact, figure, name and date must come from them — never from your "
    "own knowledge, and never invented.\n"
    "You may compare, weigh up and draw a conclusion the passages support, "
    "even when they state no conclusion themselves. If a question asks which "
    "is better and the passages give strengths on both sides, say that, and "
    "say what each is better at.\n"
    "Only say you cannot find it in the documents when they genuinely do not "
    "cover the subject at all.\n"
    "Answer in a few sentences, in plain language."
)


class TrainingApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Training Data")
        self.set_default_size(860, 640)
        self.connect("destroy", Gtk.main_quit)
        self.library = Library()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        head = Gtk.Box(spacing=10, margin=14)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Training Data</b>")
        head.pack_start(title, False, False, 0)
        self.count = Gtk.Label(label="nothing yet", xalign=0)
        self.count.set_opacity(.65)
        head.pack_start(self.count, True, True, 0)

        add = Gtk.Button(label="Add documents")
        add.get_accessible().set_name("Add documents")
        add.connect("clicked", self.on_add)
        head.pack_end(add, False, False, 0)
        root.pack_start(head, False, False, 0)

        # ── the documents ──
        self.store = Gtk.ListStore(str, str, str)
        view = Gtk.TreeView(model=self.store)
        view.get_accessible().set_name("Documents")
        for i, col in enumerate(("Document", "Pieces", "How it was read")):
            view.append_column(Gtk.TreeViewColumn(col, Gtk.CellRendererText(), text=i))
        scroll = Gtk.ScrolledWindow(margin_start=14, margin_end=14)
        scroll.set_size_request(-1, 190)
        scroll.add(view)
        root.pack_start(scroll, False, False, 0)

        # Drop anywhere on the window, not just the list — people aim at the
        # window, and a drop that lands two pixels wide and does nothing reads
        # as the feature being broken.
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drop)

        hint = Gtk.Label(label="Drop files anywhere on this window — text, PDF, "
                               "spreadsheets, documents", margin=8)
        hint.set_opacity(.55)
        root.pack_start(hint, False, False, 0)

        # ── ask ──
        ask_row = Gtk.Box(spacing=8, margin_start=14, margin_end=14)
        self.entry = Gtk.Entry(placeholder_text="Ask something about these documents")
        self.entry.get_accessible().set_name("Question")
        self.entry.connect("activate", self.on_ask)
        ask_row.pack_start(self.entry, True, True, 0)
        self.askbtn = Gtk.Button(label="Ask")
        self.askbtn.get_accessible().set_name("Ask")
        self.askbtn.connect("clicked", self.on_ask)
        ask_row.pack_end(self.askbtn, False, False, 0)
        root.pack_start(ask_row, False, False, 0)

        self.answer = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD,
                                   left_margin=10, right_margin=10, top_margin=8)
        self.answer.get_accessible().set_name("Answer")
        answer_scroll = Gtk.ScrolledWindow(margin=14)
        answer_scroll.add(self.answer)
        root.pack_start(answer_scroll, True, True, 0)

        self.load_existing()

    # ── documents in ──

    def load_existing(self):
        common.TRAINING.mkdir(parents=True, exist_ok=True)
        for p in sorted(common.TRAINING.iterdir()):
            if p.is_file():
                self.ingest(p)

    def on_add(self, _btn):
        chooser = Gtk.FileChooserDialog(
            title="Add documents", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        chooser.set_select_multiple(True)
        if chooser.run() == Gtk.ResponseType.OK:
            for name in chooser.get_filenames():
                self.ingest(Path(name))
        chooser.destroy()

    def on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        for uri in data.get_uris():
            path = uri[7:] if uri.startswith("file://") else uri
            self.ingest(Path(GLib.uri_unescape_string(path, None) or path))

    def ingest(self, path):
        if not path.is_file():
            return
        pieces, how = self.library.add(path)
        self.store.append([path.name, str(pieces), how])
        docs = len(self.store)
        self.count.set_text(f"{docs} document{'s' if docs != 1 else ''}, "
                            f"{len(self.library.chunks)} pieces indexed")

    # ── questions ──

    def on_ask(self, _w):
        question = self.entry.get_text().strip()
        if not question:
            return
        if not self.library.chunks:
            return self.show("Add some documents first — I only answer from what is here.")

        kind = wants_a_file(question)
        # Building something needs the whole picture, not the four best-matching
        # fragments — a comparison table drawn from a quarter of the document
        # comes out with a quarter of the rows.
        found = self.library.search(question, k=10 if kind else 4)
        if not found:
            return self.show("Nothing in these documents looks related to that.")

        self.askbtn.set_sensitive(False)
        self.show(f"Building the {kind.lower()}…" if kind else "Reading…")
        common.set_state("working")

        passages = "\n\n".join(f"[from {src}]\n{text}" for src, text in found)
        # A spreadsheet answers as both a table and a text chunk, so it
        # arrives under two labels — "file.xlsx" and "file.xlsx — Sheet1".
        # The reader only cares which document it came from.
        sources = "\n".join(
            f"  · {src}" for src in sorted({src.split(" — ")[0] for src, _ in found}))

        def work():
            if kind:
                GLib.idle_add(self.done, self.build(kind, question, passages, sources))
                return
            try:
                reply = common.ask_job("answers", f"PASSAGES:\n{passages}\n\nQUESTION: {question}",
                                   system=SYSTEM)
            except RuntimeError as e:
                reply = str(e)
            GLib.idle_add(self.done, f"{reply.strip()}\n\nRead from:\n{sources}")

        threading.Thread(target=work, daemon=True).start()

    def build(self, kind, question, passages, sources):
        """Same writers the Make a Document app uses — one implementation, so a
        file built from here is identical to one built from there."""
        import json
        import make_app

        prompt = (f"{make_app.ASKS[kind]}\n\nWHAT IS NEEDED:\n{question}\n\n"
                  f"SOURCE MATERIAL — build this from the facts below and do "
                  f"not invent competing ones:\n{passages}\n\n"
                  f"Give it a short, sensible filename with no extension.")
        try:
            spec = json.loads(common.ask_job("answers", prompt, schema=make_app.SCHEMAS[kind]))
            path = make_app.WRITERS[kind](spec)
        except (json.JSONDecodeError, KeyError) as e:
            return f"The model returned something I could not turn into a file: {e}"
        except Exception as e:
            return f"Could not write the file: {e}"
        return (f"Made {path.name}\n\nIt is in Work/ — open the Work folder on "
                f"the desktop.\n\nBuilt from:\n{sources}")

    def done(self, text):
        self.show(text)
        self.askbtn.set_sensitive(True)
        common.set_state("idle")
        return False

    def show(self, text):
        self.answer.get_buffer().set_text(text)


if __name__ == "__main__":
    TrainingApp().show_all()
    Gtk.main()
