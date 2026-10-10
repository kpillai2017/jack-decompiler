"""
theme.py - Colours, fonts and syntax highlighting (shared look with jackvm).
==========================================================================

The colours are jackvm's debugger colours, so the two tools feel like one
family: dark boxes with a lighter title strip and a blue title.
"""

from __future__ import annotations

import re
from typing import List, Tuple

BACKGROUND = (30, 30, 36)
BOX = (40, 42, 52)
BOX_HEADER = (50, 54, 70)
BORDER = (88, 96, 120)
SELECTED = (62, 70, 100)
COLOURS = {
    "normal": (230, 230, 230),
    "dim": (130, 130, 140),
    "title": (120, 190, 255),
    "highlight": (255, 210, 90),
    "error": (255, 110, 110),
    "good": (120, 220, 140),
    # syntax colours
    "keyword": (200, 140, 255),
    "type": (110, 200, 230),
    "string": (230, 190, 120),
    "number": (180, 220, 140),
    "comment": (120, 125, 140),
    "symbol": (190, 190, 200),
    "label": (255, 170, 100),
    "call": (120, 190, 255),
}
VIEWER_HELP = ["Ctrl+O open", "Ctrl+D VM panel", "Ctrl+R reload", "Ctrl+N/P next/prev class", "Ctrl+S save",
               "Ctrl+Shift+S save as...", "Ctrl+T test round trip", "Ctrl+J open in compiler", "Esc picker", "Ctrl+Q quit"]
PICKER_HELP = ["Enter: open", "Ctrl+Enter: decompile folder", "Backspace: up", "Right: into folder",
               "Esc: {back}", "Ctrl+Q: quit"]
SAVE_HELP = ["Enter: open folder", "Ctrl+Enter: save in selected folder", "Ctrl+N: new folder", "Backspace: up",
             "Right: into folder", "Esc: back to program", "Ctrl+Q: quit"]
FONT_NAMES = "menlo,consolas,dejavusansmono,couriernew,monospace"
UI_FONT_SIZE = 13
CODE_FONT_SIZE = 14

JACK_KEYWORDS = {"class", "constructor", "function", "method", "field", "static", "var", "let", "do", "if", "else",
                 "while", "return", "true", "false", "null", "this"}
JACK_TYPES = {"int", "char", "boolean", "void"}
JACK_TOKEN = re.compile(r'(//.*|/\*.*?\*/|/\*\*.*|^\s*\*.*)|("[^"]*")|(\d+)|([A-Za-z_]\w*)|(\s+)|(.)')
VM_FLOW = {"label", "goto", "if-goto"}
VM_FUNCTION = {"function", "call", "return"}

Spans = List[Tuple[str, str]]


def highlight_jack(line: str) -> Spans:
    spans: Spans = []
    for m in JACK_TOKEN.finditer(line):
        comment, string, number, word, space, other = m.groups()
        if comment is not None:
            spans.append((comment, "comment"))
        elif string is not None:
            spans.append((string, "string"))
        elif number is not None:
            spans.append((number, "number"))
        elif word is not None:
            if word in JACK_KEYWORDS:
                spans.append((word, "keyword"))
            elif word in JACK_TYPES or word[:1].isupper():
                spans.append((word, "type"))
            else:
                spans.append((word, "normal"))
        elif space is not None:
            spans.append((space, "normal"))
        else:
            spans.append((other, "symbol"))
    return spans


def highlight_vm(line: str) -> Spans:
    code, sep, comment = line.partition("//")
    words = code.split(" ")
    spans: Spans = []
    if words and words[0].strip():
        first = words[0]
        colour = "label" if first.strip() in VM_FLOW else "keyword" if first.strip() in VM_FUNCTION else "normal"
        spans.append((first, colour))
        for word in words[1:]:
            spans.append((" ", "normal"))
            spans.append((word, "number" if word.isdigit() else ("call" if colour != "normal" else "type")))
    else:
        spans.append((code, "normal"))
    if sep:
        spans.append(("//" + comment, "comment"))
    return spans
