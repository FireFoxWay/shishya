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
    return [w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in STOP and len(w) > 1]


class Library:
    """Chunks plus an inverted index. Small enough to rebuild from scratch on
    every change, which removes a whole class of staleness bug."""

    def __init__(self):
        self.chunks = []          # (source, text)
        self.freqs = []           # Counter per chunk
        self.doc_count = Counter()

    def add(self, path):
        text, how = common.extract(path)
        pieces = common.chunk(text)
        for piece in pieces:
            counts = Counter(terms(piece))
            self.chunks.append((Path(path).name, piece))
            self.freqs.append(counts)
            for term in counts:
                self.doc_count[term] += 1
        return len(pieces), how

    def search(self, query, k=4):
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
        return [self.chunks[i] for _, i in scored[:k]]


SYSTEM = (
    "You answer only from the passages you are given. If they do not contain "
    "the answer, say exactly that you cannot find it in the documents — never "
    "fill the gap from your own knowledge. Quote the specific figure, name or "
    "date when there is one. Answer in a few sentences."
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

        found = self.library.search(question)
        if not found:
            return self.show("Nothing in these documents looks related to that.")

        self.askbtn.set_sensitive(False)
        self.show("Reading…")
        common.set_state("working")

        passages = "\n\n".join(f"[from {src}]\n{text}" for src, text in found)
        prompt = f"PASSAGES:\n{passages}\n\nQUESTION: {question}"

        def work():
            try:
                reply = common.ask(prompt, system=SYSTEM)
            except RuntimeError as e:
                reply = str(e)
            sources = "\n".join(f"  · {src}" for src, _ in found)
            GLib.idle_add(self.done, f"{reply.strip()}\n\nRead from:\n{sources}")

        threading.Thread(target=work, daemon=True).start()

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
