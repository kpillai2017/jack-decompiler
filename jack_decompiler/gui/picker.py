"""
picker.py - The "choose a program" logic (no pygame here, so it's easy to test).
================================================================================

Works like jackvm's file picker:

    Choose a .vm file, or a folder of .vm files, to decompile
    /Users/you/jackvm-py/games
    ------------------------------------------------------------
     ..  (parent folder)
     average/                               [decompile 9 files]
     pong/                                  [decompile 4 files]
     Main.vm
    ------------------------------------------------------------

Keys: Up/Down/PgUp/PgDn/Home/End move, Enter opens a folder or decompiles a
file, Ctrl+Enter decompiles the selected folder (or this one), Backspace or
Left goes up, Right goes into a folder. Esc goes back (see app.py).

The same class also chooses WHERE to save the .jack files (Ctrl+Shift+S,
"save as"): `PickerState(folder, purpose=SAVE)` lists only folders; Enter
opens one, and Ctrl+Enter / "[save here]" / the "Save here" button picks
the selected folder (or the one being shown) - see choose_save_folder().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..vm_reader import vm_files_in

PAGE = 15  # rows moved by PgUp / PgDn
OPEN, SAVE = "open", "save"  # what a PickerState chooses: a program, or a folder to save into


@dataclass(frozen=True)
class Entry:
    kind: str  # "parent", "folder" or "vm"
    path: Path
    vm_count: int = 0  # folders: how many .vm files are directly inside

    @property
    def label(self) -> str:
        if self.kind == "parent":
            return "..  (parent folder)"
        return self.path.name + ("/" if self.kind == "folder" else "")


def safe_vm_files(folder: Path) -> List[Path]:
    try:
        return vm_files_in(folder)
    except OSError:  # e.g. no permission
        return []


def list_entries(directory: Path, folders_only: bool = False) -> List[Entry]:
    """Parent first, then folders, then .vm files (unless folders_only); hidden items are skipped."""
    entries: List[Entry] = []
    if directory.parent != directory:
        entries.append(Entry("parent", directory.parent))
    folders, files = [], []
    try:
        children = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        children = []
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            if child.is_dir():
                folders.append(Entry("folder", child, len(safe_vm_files(child))))
            elif child.suffix.lower() == ".vm" and not folders_only:
                files.append(Entry("vm", child))
        except OSError:
            continue
    return entries + folders + files


class PickerState:
    """Which folder we're in and which row is selected. Actions return .vm files to open, or None."""

    def __init__(self, directory: Path, purpose: str = OPEN):
        self.purpose = purpose
        self.message = ""
        self.entries: List[Entry] = []
        self.selected = 0
        self.directory = Path(directory)
        self.change_directory(self._existing(Path(directory).expanduser().resolve()))

    @staticmethod
    def _existing(path: Path) -> Path:
        while not path.is_dir() and path.parent != path:
            path = path.parent
        return path

    def change_directory(self, directory: Path, select: Optional[Path] = None) -> None:
        self.directory = directory
        self.entries = list_entries(directory, folders_only=self.purpose == SAVE)
        self.selected = 0
        if select is not None:
            for i, entry in enumerate(self.entries):
                if entry.path == select:
                    self.selected = i
        elif len(self.entries) > 1 and self.entries[0].kind == "parent":
            self.selected = 1  # the first real item, not ".."

    # --- moving -------------------------------------------------------------
    def move(self, delta: int) -> None:
        if self.entries:
            self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def home(self) -> None:
        self.selected = 0

    def end(self) -> None:
        self.selected = max(0, len(self.entries) - 1)

    @property
    def current(self) -> Optional[Entry]:
        return self.entries[self.selected] if 0 <= self.selected < len(self.entries) else None

    # --- actions --------------------------------------------------------------
    def go_up(self) -> None:
        if self.directory.parent != self.directory:
            self.message = ""
            self.change_directory(self.directory.parent, select=self.directory)

    def enter_folder(self) -> None:
        entry = self.current
        if entry is not None and entry.kind in ("folder", "parent"):
            self.activate()

    def activate(self, index: Optional[int] = None) -> Optional[List[Path]]:
        """Enter / click: open a folder, or decompile a .vm file."""
        if index is not None:
            self.selected = index
        entry = self.current
        if entry is None:
            return None
        self.message = ""
        if entry.kind == "parent":
            self.go_up()
            return None
        if entry.kind == "folder":
            if not entry.path.is_dir():
                self.message = f"{entry.path.name} can't be opened"
                return None
            self.change_directory(entry.path)
            return None
        return [entry.path]

    def decompile_folder_entry(self, index: Optional[int] = None) -> Optional[List[Path]]:
        """Ctrl+Enter / the [decompile] tag: the selected folder's .vm files (or this folder's)."""
        if index is not None:
            self.selected = index
        entry = self.current
        folder = entry.path if entry is not None and entry.kind == "folder" else self.directory
        return self.decompile_folder(folder)

    def decompile_folder(self, folder: Optional[Path] = None) -> Optional[List[Path]]:
        folder = folder or self.directory
        files = safe_vm_files(folder)
        if not files:
            self.message = f"No .vm files in {folder.name or folder}/"
            return None
        return files

    def choose_save_folder(self, index: Optional[int] = None, here: bool = False) -> Path:
        """Save as: the selected folder row (or, with here=True or on "..", the folder being shown)."""
        if index is not None:
            self.selected = index
        entry = self.current
        if not here and entry is not None and entry.kind == "folder":
            return entry.path
        return self.directory

    def current_folder_vm_count(self) -> int:
        return len(safe_vm_files(self.directory))
