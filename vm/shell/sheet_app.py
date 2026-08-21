#!/usr/bin/env python3
"""
Sheets — open, read and edit spreadsheets. Runs INSIDE the sandbox.

    python3 sheet_app.py [file.xlsx]

Why this exists rather than just launching LibreOffice: Calc takes the better
part of half a minute to cold-start in this VM and occasionally does not come
up at all. Opening a file the clone just produced is the moment someone is
actually watching, so it needs to be instant and it needs to work every time.

openpyxl reads and writes the same files the writer produces, so what opens
here is the real file — not a preview of it.
"""

import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   # noqa: E402

import common   # noqa: E402

MAX_ROWS, MAX_COLS = 500, 60


class SheetApp(Gtk.Window):
    def __init__(self, path=None):
        super().__init__(title="Sheets")
        self.set_default_size(1000, 620)
        self.connect("destroy", Gtk.main_quit)
        self.path = None
        self.book = None
        self.dirty = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        bar = Gtk.Box(spacing=8, margin=10)
        for label, handler in (("Open", self.on_open), ("Save", self.on_save)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            bar.pack_start(b, False, False, 0)

        self.title = Gtk.Label(xalign=0)
        self.title.set_markup("<b>No file open</b>")
        bar.pack_start(self.title, True, True, 6)

        self.note = Gtk.Label(xalign=1)
        self.note.set_opacity(.7)
        bar.pack_end(self.note, False, False, 0)
        root.pack_start(bar, False, False, 0)

        # One tab per worksheet, so a multi-sheet workbook is obviously that.
        self.tabs = Gtk.Notebook()
        self.tabs.get_accessible().set_name("Sheets")
        self.tabs.connect("switch-page", lambda *_: self.note.set_text(""))
        root.pack_start(self.tabs, True, True, 0)

        if path:
            self.load(Path(path))

    # ── open / save ──

    def on_open(self, _b):
        chooser = Gtk.FileChooserDialog(
            title="Open a spreadsheet", transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        chooser.set_current_folder(str(common.WORK))
        f = Gtk.FileFilter()
        f.set_name("Spreadsheets")
        for pattern in ("*.xlsx", "*.xlsm", "*.csv"):
            f.add_pattern(pattern)
        chooser.add_filter(f)
        if chooser.run() == Gtk.ResponseType.OK:
            self.load(Path(chooser.get_filename()))
        chooser.destroy()

    def load(self, path):
        try:
            if path.suffix.lower() == ".csv":
                self.book, sheets = None, [(path.stem, read_csv(path))]
            else:
                from openpyxl import load_workbook
                self.book = load_workbook(path)
                sheets = [(ws.title, read_sheet(ws)) for ws in self.book.worksheets]
        except Exception as e:
            return self.say(f"Could not open {path.name}: {e}")

        self.path = path
        while self.tabs.get_n_pages():
            self.tabs.remove_page(0)
        for name, rows in sheets:
            self.tabs.append_page(self.grid(name, rows), Gtk.Label(label=name))
        self.tabs.show_all()

        total = sum(len(r) for _, r in sheets)
        self.title.set_markup(f"<b>{path.name}</b>")
        self.say(f"{len(sheets)} sheet{'s' if len(sheets) != 1 else ''}, {total} rows")
        self.dirty = False

    def on_save(self, _b):
        if not self.path:
            return self.say("Nothing open.")
        if self.path.suffix.lower() == ".csv":
            return self.say("Saving CSV isn't supported — use Save As in Calc.")
        try:
            page = self.tabs.get_nth_page(self.tabs.get_current_page())
            view = page.get_child()
            ws = self.book.worksheets[self.tabs.get_current_page()]
            store = view.get_model()
            # Row 1 is the header the writer wrote; the grid shows it as the
            # first data row so it can be corrected like anything else.
            for r, row in enumerate(store, start=1):
                for c in range(len(row) - 1):        # last column is the row id
                    ws.cell(row=r, column=c + 1).value = row[c] or None
            self.book.save(self.path)
            self.dirty = False
            self.say(f"Saved {self.path.name}")
        except Exception as e:
            self.say(f"Could not save: {e}")

    # ── grid ──

    def grid(self, name, rows):
        width = max((len(r) for r in rows), default=1)
        width = min(width, MAX_COLS)
        store = Gtk.ListStore(*([str] * width + [int]))
        for i, row in enumerate(rows[:MAX_ROWS]):
            padded = [cell if cell is not None else "" for cell in row[:width]]
            padded += [""] * (width - len(padded))
            store.append(padded + [i])

        view = Gtk.TreeView(model=store)
        view.get_accessible().set_name(f"{name} grid")
        view.set_grid_lines(Gtk.TreeViewGridLines.BOTH)

        for c in range(width):
            renderer = Gtk.CellRendererText(editable=True)
            renderer.connect("edited", self.on_edit, store, c)
            column = Gtk.TreeViewColumn(column_letter(c), renderer, text=c)
            column.set_resizable(True)
            column.set_min_width(90)
            column.set_max_width(340)
            view.append_column(column)

        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        return scroll

    def on_edit(self, _renderer, path, text, store, column):
        store[path][column] = text
        self.dirty = True
        self.say("edited — press Save to write it back")

    def say(self, text):
        self.note.set_text(text)


def read_sheet(ws):
    rows = [list(row) for row in ws.iter_rows(max_row=MAX_ROWS, max_col=MAX_COLS,
                                              values_only=True)]
    # openpyxl reports the sheet's declared extent, which for a written file
    # runs to the row cap and is nearly all empty. Showing "500 rows" for an
    # eleven-row table makes the app look broken; trim the blank tail.
    while rows and all(c is None or str(c).strip() == "" for c in rows[-1]):
        rows.pop()
    return rows


def read_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [row for _, row in zip(range(MAX_ROWS), csv.reader(f))]


def column_letter(i):
    """0 -> A, 25 -> Z, 26 -> AA. Spreadsheet headers, so the grid reads like
    one rather than like a table that happens to have columns."""
    name = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        name = chr(65 + rem) + name
    return name


if __name__ == "__main__":
    SheetApp(sys.argv[1] if len(sys.argv) > 1 else None).show_all()
    Gtk.main()
