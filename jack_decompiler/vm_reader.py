"""
vm_reader.py - Read the TEXT of .vm files into checked instruction objects.
==========================================================================

This is the first stage of the decompiler:

    .vm text  --vm_reader-->  VMFunction objects  --structure-->  Jack AST ...

Every line of a .vm file is one instruction, e.g.

    function Main.main 1      // start of a function with 1 local variable
    push constant 7
    call Output.printInt 1
    pop temp 0
    return

The reader is strict. It collects EVERY problem it finds (with the file name
and line number) and then raises a single `VMSyntaxError` that lists them
all. That's friendlier than stopping at the first mistake, and it means the
later stages can rely on the input being well formed:

  * unknown commands, segments or operators
  * the wrong number of words, or indexes that aren't whole numbers
  * out-of-range indexes (constant 0..32767, temp 0..7, pointer 0..1)
  * `pop constant` (there's nowhere to pop a constant to)
  * instructions before the first `function`
  * labels defined twice in one function, or jumps to labels that don't exist
  * the same function defined twice
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

SEGMENTS = ("constant", "local", "argument", "this", "that", "pointer", "temp", "static")
BINARY_OPERATORS = ("add", "sub", "eq", "gt", "lt", "and", "or")
UNARY_OPERATORS = ("neg", "not")
OPERATORS = BINARY_OPERATORS + UNARY_OPERATORS

MAX_CONSTANT = 32767  # push constant takes a 15-bit number
MAX_INDEX = 32767  # a generous limit for the other segments
SEGMENT_LIMITS = {"temp": 7, "pointer": 1}

NAME = re.compile(r"^[A-Za-z_.:$][A-Za-z0-9_.:$]*$")


@dataclass(frozen=True)
class Instr:
    """
    One VM instruction.

    op   : "push", "pop", "arith", "label", "goto", "if-goto", "function",
           "call" or "return"
    arg1 : the segment ("local"), operator ("add") or name ("Main.main")
    arg2 : the index / count, or 0 when the instruction has none
    """

    op: str
    arg1: str = ""
    arg2: int = 0
    line: int = 0
    file: str = ""

    def text(self) -> str:
        """The instruction as it would appear in a .vm file."""
        if self.op in ("push", "pop", "function", "call"):
            return f"{self.op} {self.arg1} {self.arg2}"
        if self.op in ("label", "goto", "if-goto"):
            return f"{self.op} {self.arg1}"
        if self.op == "arith":
            return self.arg1
        return self.op

    def where(self) -> str:
        return f"{self.file or '<text>'}:{self.line}"


@dataclass
class VMFunction:
    """A `function Class.name nLocals` header and the instructions after it."""

    name: str
    n_locals: int
    body: List[Instr] = field(default_factory=list)
    file: str = ""
    line: int = 0

    @property
    def class_name(self) -> str:
        return self.name.split(".", 1)[0]

    @property
    def short_name(self) -> str:
        return self.name.split(".", 1)[1]


@dataclass
class Problem:
    file: str
    line: int
    message: str
    text: str = ""

    def __str__(self) -> str:
        where = f"{self.file or '<text>'}:{self.line}"
        return f"{where}: {self.message}" + (f"   -->  {self.text}" if self.text else "")


class VMSyntaxError(Exception):
    """Raised when the VM text contains one or more mistakes."""

    def __init__(self, problems: List[Problem]):
        self.problems = problems
        count = len(problems)
        listed = "\n".join(f"  {p}" for p in problems[:50])
        more = f"\n  ... and {count - 50} more" if count > 50 else ""
        super().__init__(f"{count} problem{'s' if count != 1 else ''} in the VM code:\n{listed}{more}")


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


def _parse_int(word: str) -> int:
    if not re.fullmatch(r"\d+", word):
        raise ValueError(f"{word!r} is not a whole number (0 or more)")
    return int(word)


def parse_line(words: Sequence[str], line: int, file: str) -> Instr:
    """Turn the words of one line into an Instr. Raises ValueError with a helpful message."""
    op = words[0]
    if op in ("push", "pop"):
        if len(words) != 3:
            raise ValueError(f"'{op}' needs a segment and an index, e.g. '{op} local 0'")
        segment = words[1]
        if segment not in SEGMENTS:
            raise ValueError(f"unknown segment {segment!r} (expected one of: {', '.join(SEGMENTS)})")
        index = _parse_int(words[2])
        if op == "pop" and segment == "constant":
            raise ValueError("can't 'pop constant' - constants aren't memory")
        limit = MAX_CONSTANT if segment == "constant" else SEGMENT_LIMITS.get(segment, MAX_INDEX)
        if index > limit:
            raise ValueError(f"index {index} is too big for segment {segment!r} (0..{limit})")
        return Instr(op, segment, index, line, file)
    if op in OPERATORS:
        if len(words) != 1:
            raise ValueError(f"'{op}' takes no arguments")
        return Instr("arith", op, 0, line, file)
    if op in ("label", "goto", "if-goto"):
        if len(words) != 2:
            raise ValueError(f"'{op}' needs exactly one label name")
        if not NAME.match(words[1]):
            raise ValueError(f"{words[1]!r} is not a valid label name")
        return Instr(op, words[1], 0, line, file)
    if op in ("function", "call"):
        if len(words) != 3:
            raise ValueError(f"'{op}' needs a name and a number, e.g. '{op} Main.main 0'")
        name = words[1]
        if not NAME.match(name) or name.count(".") != 1 or name.startswith(".") or name.endswith("."):
            raise ValueError(f"{name!r} is not a valid function name (expected Class.name)")
        return Instr(op, name, _parse_int(words[2]), line, file)
    if op == "return":
        if len(words) != 1:
            raise ValueError("'return' takes no arguments")
        return Instr("return", "", 0, line, file)
    raise ValueError(f"unknown command {op!r}")


def parse_vm(text: str, file: str = "") -> List[VMFunction]:
    """Parse one .vm file's text. Raises VMSyntaxError listing every problem found."""
    problems: List[Problem] = []
    functions: List[VMFunction] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line:
            continue
        try:
            ins = parse_line(line.split(), number, file)
        except ValueError as error:
            problems.append(Problem(file, number, str(error), raw.strip()))
            if line.split()[0] == "function":  # keep going inside a placeholder function,
                functions.append(VMFunction(f"<function on line {number}>", 0, [], file, number))  # so later lines still parse
            continue
        if ins.op == "function":
            functions.append(VMFunction(ins.arg1, ins.arg2, [], file, number))
        elif not functions:
            problems.append(Problem(file, number, "instruction outside any function", raw.strip()))
        else:
            functions[-1].body.append(ins)
    for function in functions:
        problems.extend(_check_labels(function))
    if problems:
        raise VMSyntaxError(problems)
    return functions


def _check_labels(function: VMFunction) -> List[Problem]:
    problems = []
    seen: Dict[str, Instr] = {}
    for ins in function.body:
        if ins.op == "label":
            if ins.arg1 in seen:
                problems.append(Problem(ins.file, ins.line, f"label {ins.arg1!r} defined twice in {function.name}"
                                        f" (first at line {seen[ins.arg1].line})"))
            seen[ins.arg1] = ins
    for ins in function.body:
        if ins.op in ("goto", "if-goto") and ins.arg1 not in seen:
            problems.append(Problem(ins.file, ins.line, f"jump to label {ins.arg1!r}, which {function.name} doesn't define",
                                    ins.text()))
    return problems


def read_files(paths: Iterable[Path]) -> List[VMFunction]:
    """
    Read and parse several .vm files. Problems from ALL files are reported
    together, plus functions defined more than once across the files.
    """
    problems: List[Problem] = []
    functions: List[VMFunction] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(Problem(str(path), 0, "not a text file (couldn't read it as UTF-8)"))
            continue
        except OSError as error:
            problems.append(Problem(str(path), 0, f"couldn't read the file: {error.strerror or error}"))
            continue
        try:
            functions.extend(parse_vm(text, path.name))
        except VMSyntaxError as error:
            problems.extend(error.problems)
    problems.extend(check_duplicates(functions))
    if problems:
        raise VMSyntaxError(problems)
    return functions


def check_duplicates(functions: Sequence[VMFunction]) -> List[Problem]:
    first: Dict[str, VMFunction] = {}
    problems = []
    for function in functions:
        if function.name in first:
            other = first[function.name]
            problems.append(Problem(function.file, function.line,
                                    f"function {function.name} is defined twice (also at {other.file}:{other.line})"))
        else:
            first[function.name] = function
    return problems


def group_by_class(functions: Sequence[VMFunction]) -> Dict[str, List[VMFunction]]:
    """{class name: its functions, in file order}; classes in first-seen order."""
    classes: Dict[str, List[VMFunction]] = {}
    for function in functions:
        classes.setdefault(function.class_name, []).append(function)
    return classes


def vm_files_in(folder: Path) -> List[Path]:
    """All .vm files directly inside `folder`, sorted by name (case-insensitive)."""
    return sorted((p for p in Path(folder).glob("*.vm") if p.is_file()), key=lambda p: p.name.lower())


def resolve_inputs(names: Sequence[str]) -> List[Path]:
    """Turn files and/or folders typed by the user into a list of .vm files."""
    files: List[Path] = []
    for name in names:
        path = Path(name).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Can't find {name!r}: no such file or folder")
        if path.is_dir():
            found = vm_files_in(path)
            if not found:
                raise FileNotFoundError(f"No .vm files in folder {path}")
            files.extend(found)
        elif path.suffix.lower() != ".vm":
            raise FileNotFoundError(f"{path} is not a .vm file")
        else:
            files.append(path)
    if not files:
        raise FileNotFoundError("No .vm files given")
    return files


def instructions_signature(function: VMFunction) -> List[Tuple[str, str, int]]:
    """The instructions as plain tuples (no line numbers) - handy for comparing."""
    return [(i.op, i.arg1, i.arg2) for i in function.body]
