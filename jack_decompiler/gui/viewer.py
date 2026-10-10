"""
viewer.py - The state behind the VM / Jack viewer (no pygame here).
===================================================================

Holds the decompiled program, which class is shown, how far each panel is
scrolled, and the messages shown in the STATUS box. Every keyboard
shortcut in app.py calls one method here, so they can all be tested
without opening a window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from ..decompiler import DecompileResult, decompile_files
from ..output import default_folder, save_result
from ..verify import ClassCheck, verify
from ..vm_reader import VMSyntaxError, resolve_inputs
from . import compiler_link


class ViewerState:
    def __init__(self, files: Sequence[Path], rename_functions: bool = True,
                 find_compiler: Callable[[], Optional[List[str]]] = compiler_link.find_compiler_gui):
        self.inputs = [Path(f) for f in files]  # what was asked for: files and/or folders
        self.files: List[Path] = list(self.inputs)  # ...turned into .vm files by load()
        self.rename_functions = rename_functions
        self.find_compiler = find_compiler
        self.result: Optional[DecompileResult] = None
        self.error = ""  # why the program couldn't be decompiled at all
        self.class_index = 0
        self.scroll: Dict[str, int] = {"jack": 0, "vm": 0}
        self.show_vm = True
        self.checks: Dict[str, ClassCheck] = {}
        self.notice = ""
        self.saved_to: Optional[Path] = None
        self.load()

    # --- loading ----------------------------------------------------------
    def load(self) -> bool:
        """(Re)read and decompile the files. False if that failed (see self.error)."""
        current = self.current_name
        self.checks = {}
        try:
            self.files = resolve_inputs([str(p) for p in self.inputs])
            self.result = decompile_files(self.files, self.rename_functions)
            self.error = ""
        except (FileNotFoundError, VMSyntaxError, OSError) as problem:
            self.result = None
            self.error = str(problem)
            return False
        names = self.class_names
        self.class_index = names.index(current) if current in names else 0
        self.scroll = {"jack": 0, "vm": 0}
        return True

    def reload(self) -> None:
        """Ctrl+R."""
        self.notice = "Reloaded and decompiled again" if self.load() else "Reload failed"

    # --- what is shown ----------------------------------------------------------
    @property
    def class_names(self) -> List[str]:
        return list(self.result.classes) if self.result else []

    @property
    def current_name(self) -> Optional[str]:
        names = self.class_names if self.result else []
        return names[self.class_index] if 0 <= self.class_index < len(names) else None

    @property
    def current(self):
        return self.result.classes[self.current_name] if self.current_name else None

    def lines(self, panel: str) -> List[str]:
        cls = self.current
        if cls is None:
            return self.error.splitlines() if panel == "jack" else []
        return (cls.jack if panel == "jack" else cls.vm).splitlines()

    def title(self) -> str:
        if not self.files:
            return "Jack decompiler"
        folder = self.files[0].parent.name
        if len(self.files) == 1:
            return f"Jack decompiler - {self.files[0].name}"
        return f"Jack decompiler - {folder}/ ({len(self.files)} files)"

    def status_lines(self) -> List[tuple]:
        """[(text, colour name)] for the STATUS box."""
        rows = []
        if self.result is None:
            lines = [line.strip() for line in self.error.splitlines() if line.strip()] or ["Nothing loaded"]
            shown = " ".join(lines[:2])  # e.g. "1 problem in the VM code: Main.vm:2: unknown segment ..."
            return [(shown, "error"), ("Fix the VM file and press Ctrl+R, or Ctrl+O for another program", "dim")]
        rows.append((f"Decompiled {self.result.summary()}", "normal"))
        cls = self.current
        if cls is not None and cls.errors:
            rows.append((cls.errors[0], "error"))
        check = self.checks.get(self.current_name or "")
        if check is not None:
            rows.append((f"Round trip: {check.message}", "good" if check.ok else "error"))
        elif self.result.warnings:
            rows.append((f"Warning: {self.result.warnings[0]}", "highlight"))
        if self.notice:
            rows.append((self.notice, "highlight"))
        return rows[:3]

    # --- navigation -------------------------------------------------------------
    def select_class(self, index: int) -> None:
        if self.class_names:
            self.class_index = index % len(self.class_names)
            self.scroll = {"jack": 0, "vm": 0}

    def next_class(self) -> None:
        self.select_class(self.class_index + 1)

    def previous_class(self) -> None:
        self.select_class(self.class_index - 1)

    def scroll_by(self, panel: str, delta: int, visible_rows: int) -> None:
        biggest = max(0, len(self.lines(panel)) - visible_rows)
        self.scroll[panel] = max(0, min(biggest, self.scroll[panel] + delta))

    def scroll_to(self, panel: str, row: int, visible_rows: int) -> None:
        self.scroll[panel] = 0
        self.scroll_by(panel, row, visible_rows)

    def toggle_vm(self) -> None:
        self.show_vm = not self.show_vm

    # --- actions -------------------------------------------------------------------
    def save(self, folder: Optional[Path] = None) -> Optional[Path]:
        """Ctrl+S: write the .jack files (next to the .vm files when that's safe)."""
        if self.result is None:
            self.notice = "Nothing to save"
            return None
        target = Path(folder) if folder else default_folder(self.result, self.files[0].parent)
        try:
            written = save_result(self.result, target)
        except (FileExistsError, OSError) as problem:
            self.notice = f"Not saved: {problem}"
            return None
        self.saved_to = target
        self.notice = f"Saved {len(written)} .jack file{'s' if len(written) != 1 else ''} to {target}"
        return target

    def run_verify(self) -> List[ClassCheck]:
        """Ctrl+T: recompile every class and compare with the original VM."""
        if self.result is None:
            self.notice = "Nothing to check"
            return []
        checks = verify(self.result)
        self.checks = {c.name: c for c in checks}
        good = sum(c.ok for c in checks)
        self.notice = f"Round trip: {good} of {len(checks)} classes recompile to identical VM code"
        return checks

    def open_in_compiler(self) -> str:
        """Ctrl+J: save, then open the folder in jack-compiler's window."""
        folder = self.save()
        if folder is None:
            return self.notice
        self.notice = compiler_link.open_in_compiler(folder, self.find_compiler())
        return self.notice
