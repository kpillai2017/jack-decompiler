"""
os_api.py - What the decompiler knows about the Jack OS.
========================================================

Most programs only contain their OWN classes; the Jack OS (Math, String,
Array, Output, Screen, Keyboard, Memory, Sys) comes from the VM. To write
`s.length()` instead of `String.length(s)`, and to give variables good
names, the decompiler needs to know each OS subroutine's kind, return type
and parameters. Standard signatures are from the nand2tetris Jack OS API;
public companion additions are loaded from os_extensions.py.

Parameter names are chosen to be descriptive, because they're used as name
suggestions: a local passed to `Screen.drawCircle(x, y, radius)` as the
third argument is a good candidate for the name `radius`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class Signature:
    kind: str  # "function", "method" or "constructor"
    return_type: str  # "void", "int", "char", "boolean", or a class name
    params: Tuple[Tuple[str, str], ...] = ()  # (type, name), NOT counting `this`


def _sig(kind: str, ret: str, *params: str) -> Signature:
    return Signature(kind, ret, tuple(tuple(p.split()) for p in params))  # type: ignore[misc]


OS_API: Dict[str, Signature] = {
    # Math
    "Math.init": _sig("function", "void"),
    "Math.abs": _sig("function", "int", "int x"),
    "Math.multiply": _sig("function", "int", "int x", "int y"),
    "Math.divide": _sig("function", "int", "int x", "int y"),
    "Math.min": _sig("function", "int", "int a", "int b"),
    "Math.max": _sig("function", "int", "int a", "int b"),
    "Math.sqrt": _sig("function", "int", "int x"),
    # String
    "String.new": _sig("constructor", "String", "int maxLength"),
    "String.dispose": _sig("method", "void"),
    "String.length": _sig("method", "int"),
    "String.charAt": _sig("method", "char", "int index"),
    "String.setCharAt": _sig("method", "void", "int index", "char c"),
    "String.appendChar": _sig("method", "String", "char c"),
    "String.eraseLastChar": _sig("method", "void"),
    "String.intValue": _sig("method", "int"),
    "String.setInt": _sig("method", "void", "int number"),
    "String.backSpace": _sig("function", "char"),
    "String.doubleQuote": _sig("function", "char"),
    "String.newLine": _sig("function", "char"),
    # Array
    "Array.new": _sig("function", "Array", "int size"),
    "Array.dispose": _sig("method", "void"),
    # Output
    "Output.init": _sig("function", "void"),
    "Output.moveCursor": _sig("function", "void", "int row", "int column"),
    "Output.printChar": _sig("function", "void", "char c"),
    "Output.printString": _sig("function", "void", "String text"),
    "Output.printInt": _sig("function", "void", "int number"),
    "Output.println": _sig("function", "void"),
    "Output.backSpace": _sig("function", "void"),
    # Screen
    "Screen.init": _sig("function", "void"),
    "Screen.clearScreen": _sig("function", "void"),
    "Screen.setColor": _sig("function", "void", "boolean color"),
    "Screen.drawPixel": _sig("function", "void", "int x", "int y"),
    "Screen.drawLine": _sig("function", "void", "int x1", "int y1", "int x2", "int y2"),
    "Screen.drawRectangle": _sig("function", "void", "int x1", "int y1", "int x2", "int y2"),
    "Screen.drawCircle": _sig("function", "void", "int x", "int y", "int radius"),
    # Keyboard
    "Keyboard.init": _sig("function", "void"),
    "Keyboard.keyPressed": _sig("function", "char"),
    "Keyboard.readChar": _sig("function", "char"),
    "Keyboard.readLine": _sig("function", "String", "String message"),
    "Keyboard.readInt": _sig("function", "int", "String message"),
    # Memory
    "Memory.init": _sig("function", "void"),
    "Memory.peek": _sig("function", "int", "int address"),
    "Memory.poke": _sig("function", "void", "int address", "int value"),
    "Memory.alloc": _sig("function", "Array", "int size"),
    "Memory.deAlloc": _sig("function", "void", "Array object"),
    # Sys
    "Sys.init": _sig("function", "void"),
    "Sys.halt": _sig("function", "void"),
    "Sys.error": _sig("function", "void", "int errorCode"),
    "Sys.wait": _sig("function", "void", "int duration"),
}

# Recognition does not supply runtime implementations: these need the
# companion extended OS, not the stock nand2tetris library.
from .os_extensions import DECLARATIONS

for cls, declarations in DECLARATIONS.items():
    for declaration in declarations:
        head, params = declaration.rstrip(")").split("(")
        kind, return_type, name = head.split()
        OS_API[cls + "." + name] = _sig(kind, return_type,
                                       *(p.strip() for p in params.split(",") if p.strip()))

OS_CLASSES = frozenset(name.split(".")[0] for name in OS_API)

# A good name for a variable that holds the result of calling one of these.
RESULT_NAMES: Dict[str, str] = {
    "Keyboard.keyPressed": "key",
    "Keyboard.readChar": "c",
    "Keyboard.readLine": "line",
    "Keyboard.readInt": "number",
    "String.length": "length",
    "String.charAt": "c",
    "String.intValue": "number",
    "Math.divide": "quotient",
    "Math.multiply": "product",
    "Math.sqrt": "root",
    "Math.abs": "absolute",
    "Math.min": "minimum",
    "Math.max": "maximum",
    "Memory.alloc": "block",
    "Memory.peek": "value",
    "Array.new": "array",
    "String.new": "str",
}

RESULT_NAMES.update({
    "Input.key": "key", "Input.pressed": "pressed", "Input.released": "released",
    "Random.next": "randomValue", "Random.range": "randomValue",
    "IntQueue.dequeue": "value", "IntQueue.length": "length",
    "IntStack.pop": "value", "IntStack.peek": "value", "IntStack.length": "length",
    "Timer.remaining": "remaining", "Timer.expired": "expired",
    "Clock.supported": "supported", "Clock.now": "start", "Clock.elapsed": "elapsed",
    "Output.cursorRow": "row", "Output.cursorColumn": "column",
    "String.capacity": "capacity", "String.copy": "copy", "String.substring": "text",
})

PRIMITIVE_TYPES = ("int", "char", "boolean")

JACK_KEYWORDS = frozenset(
    "class constructor function method field static var int char boolean void "
    "true false null this let do if else while return for break continue const enum".split()
)
