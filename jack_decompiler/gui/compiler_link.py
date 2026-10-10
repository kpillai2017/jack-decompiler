"""
compiler_link.py - Find the Jack compiler's window (jackc-gui) for Ctrl+J.
==========================================================================

Ctrl+J saves the decompiled .jack files and opens them in
jack-compiler's GUI (https://github.com/kpillai2017/jack-compiler), just
like Ctrl+J in jackvm. It's found the same way jackvm finds it, so one
setting works for all the Jack tools:

  1. $JACKC_GUI - a command (or "off")
  2. the shared config file ~/.config/jack-tools/config.ini (or
     $JACK_TOOLS_CONFIG; %APPDATA%\\jack-tools\\config.ini on Windows):
         [apps]
         jackc = ~/code/jack-compiler      ; a folder (its bin/ or .venv is searched)
         jackc-gui = /full/path/to/jackc-gui   ; or the command itself
  3. `jackc-gui` on the PATH

This module never imports jack-compiler; it only runs its command.
"""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Mapping, Optional

EXECUTABLE = "jackc-gui"
ENV_VAR = "JACKC_GUI"
OFF_VALUES = ("off", "none", "no", "false", "0")
INSTALL_HINT = "git clone https://github.com/kpillai2017/jack-compiler.git && pip install -e './jack-compiler[gui]'"


def config_path(environ: Mapping[str, str]) -> Optional[Path]:
    explicit = environ.get("JACK_TOOLS_CONFIG", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt" and environ.get("APPDATA"):
        return Path(environ["APPDATA"]) / "jack-tools" / "config.ini"
    base = environ.get("XDG_CONFIG_HOME") or (environ.get("HOME") and str(Path(environ["HOME"]) / ".config"))
    return Path(base) / "jack-tools" / "config.ini" if base else None


def read_apps(path: Optional[Path]) -> Mapping[str, str]:
    if path is None or not path.is_file():
        return {}
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return {}
    return dict(parser["apps"]) if parser.has_section("apps") else {}


def command_in_folder(folder: Path) -> Optional[List[str]]:
    names = [EXECUTABLE, EXECUTABLE + ".exe"]
    places = [folder, folder / "bin", folder / "Scripts"]
    for venv in (".venv", "venv", "env"):
        places += [folder / venv / "bin", folder / venv / "Scripts"]
    for place in places:
        for name in names:
            candidate = place / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return [str(candidate)]
    return None


def find_compiler_gui(environ: Optional[Mapping[str, str]] = None,
                      which: Callable[[str], Optional[str]] = shutil.which) -> Optional[List[str]]:
    """The command that starts jackc-gui, or None."""
    environ = os.environ if environ is None else environ
    override = environ.get(ENV_VAR, "").strip()
    if override:
        return None if override.lower() in OFF_VALUES else shlex.split(override)
    apps = read_apps(config_path(environ))
    for key in (EXECUTABLE, "jackc"):
        value = apps.get(key, "").strip()
        if not value:
            continue
        if value.lower() in OFF_VALUES:
            return None
        path = Path(value).expanduser()
        if path.is_dir():
            found = command_in_folder(path)
            if found:
                return found
        elif key == EXECUTABLE:
            return shlex.split(value)
    on_path = which(EXECUTABLE)
    return [on_path] if on_path else None


def open_in_compiler(folder: Path, command: Optional[List[str]]) -> str:
    """Start jackc-gui on `folder`. Returns a message for the user."""
    if command is None:
        return f"Jack compiler GUI not found - set {ENV_VAR}, or install it: {INSTALL_HINT}"
    try:
        subprocess.Popen([*command, str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        return f"Couldn't start the Jack compiler: {error}"
    return f"Opened {folder.name}/ in the Jack compiler"
