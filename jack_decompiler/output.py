"""
output.py - Saving .jack files without destroying anyone's work.
================================================================

Decompiled files are normally saved NEXT TO the .vm files (Ball.vm ->
Ball.jack), which is the usual nand2tetris layout and where jackvm's
Ctrl+J looks for sources.

But that folder may already hold hand-written .jack files. A file is only
overwritten if it was written by this decompiler (its header says so) or
if you ask for it (--force). Otherwise save_result() refuses and lists the
files; the GUI then saves into a `decompiled/` sub-folder instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .decompiler import DecompileResult
from .emitter import HEADER_MARK, TOOL_NAME

SUBFOLDER = "decompiled"


def written_by_us(path: Path) -> bool:
    try:
        start = path.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return False
    return HEADER_MARK in start and TOOL_NAME in start


def conflicts(result: DecompileResult, folder: Path) -> List[Path]:
    """Existing files that saving into `folder` would overwrite and that we didn't write."""
    paths = [Path(folder) / c.jack_file_name for c in result.classes.values()]
    return [p for p in paths if p.exists() and not written_by_us(p)]


def default_folder(result: DecompileResult, vm_folder: Path) -> Path:
    """Next to the .vm files, unless that would overwrite hand-written .jack files."""
    vm_folder = Path(vm_folder)
    return vm_folder if not conflicts(result, vm_folder) else vm_folder / SUBFOLDER


def save_result(result: DecompileResult, folder: Path, force: bool = False) -> List[Path]:
    """Write one .jack file per class into `folder`. Returns the paths written."""
    folder = Path(folder)
    if folder.exists() and not folder.is_dir():
        raise NotADirectoryError(f"{folder} exists and is not a folder")
    clash = [] if force else conflicts(result, folder)
    if clash:
        names = ", ".join(p.name for p in clash)
        raise FileExistsError(f"won't overwrite {names} in {folder} (not written by {TOOL_NAME}; use --force)")
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for cls in result.classes.values():
        path = folder / cls.jack_file_name
        path.write_text(cls.jack, encoding="utf-8")
        written.append(path)
    return written
