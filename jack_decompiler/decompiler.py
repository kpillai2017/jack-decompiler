"""
decompiler.py - The whole pipeline in one place.
================================================

    .vm files
       |  vm_reader.read_files()        parse + check every line
       v
    VMFunction objects
       |  structure.Structurer          jumps -> if / while, stack -> expressions
       v
    Program (model.py)                  classes, subroutines, Jack AST
       |  infer.infer_types()           int / boolean / Ball / Array ...
       |  naming.name_everything()      local2 -> score, this 0 -> x ...
       v
    emitter.Emitter                     Jack text, one class per file

Use it from Python:

    from jack_decompiler import decompile_files
    result = decompile_files([Path("games/pong")])
    print(result.classes["Ball"].jack)

A subroutine that can't be decompiled does NOT stop the others: it's
written with its VM code in comments, and listed in `result.errors`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .emitter import Emitter
from .engine import DecompileError
from .infer import infer_types
from .jack_ast import Let, Var, walk_stmts
from .model import ClassModel, Program, Subroutine
from .naming import name_everything
from .structure import Structurer, detect_kind
from .vm_reader import VMFunction, VMSyntaxError, check_duplicates, group_by_class, parse_vm, read_files, resolve_inputs


@dataclass
class ClassResult:
    name: str
    file: str  # the .vm file it came from, e.g. "Ball.vm"
    jack: str  # the decompiled source
    vm: str = ""  # the original VM text (for showing side by side)
    errors: List[str] = field(default_factory=list)  # subroutines that couldn't be decompiled

    @property
    def jack_file_name(self) -> str:
        return f"{self.name}.jack"


@dataclass
class DecompileResult:
    program: Program
    classes: Dict[str, ClassResult] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def errors(self) -> List[str]:
        return [e for c in self.classes.values() for e in c.errors]

    @property
    def subroutine_count(self) -> int:
        return len(self.program.subs)

    def summary(self) -> str:
        n_classes, n_subs = len(self.classes), self.subroutine_count
        text = f"{n_classes} class{'es' if n_classes != 1 else ''}, {n_subs} subroutine{'s' if n_subs != 1 else ''}"
        if self.errors:
            text += f", {len(self.errors)} could not be decompiled"
        if self.warnings:
            text += f", {len(self.warnings)} warning{'s' if len(self.warnings) != 1 else ''}"
        return text


# ---------------------------------------------------------------------------
def analyse_subroutine(function: VMFunction) -> Subroutine:
    kind, n_fields, start = detect_kind(function.body)
    sub = Subroutine(function, kind, n_fields)
    try:
        sub.body = Structurer(function).run(start)
        _check_jack_rules(sub)
    except DecompileError as error:
        sub.body = []
        sub.error = str(error)
    return sub


def _check_jack_rules(sub: Subroutine) -> None:
    """Things that are fine in VM code but impossible in Jack."""
    for ins in sub.vm.body:
        if sub.kind == "function" and ins.arg1 == "this" and ins.op in ("push", "pop"):
            raise DecompileError("uses fields ('this' segment) but isn't a method or constructor", ins)
    if sub.kind == "method":
        for s in walk_stmts(sub.body):
            if isinstance(s, Let) and s.target == Var("argument", 0):
                raise DecompileError("assigns to argument 0 (`this`) of a method")


def _count_arguments(program: Program, functions: Sequence[VMFunction]) -> None:
    calls: Dict[str, set] = defaultdict(set)
    for function in functions:
        for ins in function.body:
            if ins.op == "call":
                calls[ins.arg1].add(ins.arg2)
    for sub in program.subs.values():
        used = [ins.arg2 + 1 for ins in sub.vm.body if ins.arg1 == "argument" and ins.op in ("push", "pop")]
        counts = calls.get(sub.full_name, set())
        sub.n_args = max([*used, *counts, 1 if sub.kind == "method" else 0])
        if len(counts) > 1:
            program.warnings.append(f"{sub.full_name} is called with different numbers of arguments: "
                                    f"{', '.join(map(str, sorted(counts)))}")
        if sub.kind == "method" and 0 in counts:
            program.warnings.append(f"{sub.full_name} looks like a method but is called with no arguments")


def _size_classes(program: Program) -> None:
    for cls in program.classes.values():
        fields = [sub.n_fields for sub in cls.subs if sub.kind == "constructor"]
        statics = []
        for sub in cls.subs:
            for ins in sub.vm.body:
                if ins.op in ("push", "pop") and ins.arg1 == "this":
                    fields.append(ins.arg2 + 1)
                elif ins.op in ("push", "pop") and ins.arg1 == "static":
                    statics.append(ins.arg2 + 1)
        cls.n_fields = max(fields, default=0)
        cls.n_statics = max(statics, default=0)
        sizes = {sub.n_fields for sub in cls.subs if sub.kind == "constructor"}
        if len(sizes) > 1:
            program.warnings.append(f"constructors of {cls.name} allocate different sizes: {sorted(sizes)}")


def decompile_functions(functions: Sequence[VMFunction], rename_functions: bool = True,
                        vm_texts: Optional[Dict[str, str]] = None) -> DecompileResult:
    """Decompile already-parsed functions (all files of one program together)."""
    duplicates = check_duplicates(functions)
    if duplicates:
        raise VMSyntaxError(duplicates)
    program = Program()
    for class_name, members in group_by_class(functions).items():
        files = sorted({f.file for f in members})
        cls = ClassModel(class_name, members[0].file)
        if len(files) > 1:
            program.warnings.append(f"class {class_name} is spread over several files: {', '.join(files)}")
        elif files[0] and Path(files[0]).stem != class_name:
            program.warnings.append(f"{files[0]} contains class {class_name} (expected {class_name}.vm)")
        for function in members:
            sub = analyse_subroutine(function)
            cls.subs.append(sub)
            program.subs[sub.full_name] = sub
        program.classes[class_name] = cls

    _count_arguments(program, functions)
    _size_classes(program)
    infer_types(program)
    name_everything(program, rename_functions)

    emitter = Emitter(program)
    result = DecompileResult(program, warnings=program.warnings)
    for cls in program.classes.values():
        errors = [f"{sub.full_name}: {sub.error}" for sub in cls.subs if sub.error]
        vm = (vm_texts or {}).get(cls.file, "")
        result.classes[cls.name] = ClassResult(cls.name, cls.file, emitter.class_text(cls), vm, errors)
    return result


def decompile_text(text: str, file_name: str = "Main.vm", rename_functions: bool = True) -> DecompileResult:
    """Decompile the text of ONE .vm file."""
    return decompile_functions(parse_vm(text, file_name), rename_functions, {file_name: text})


def decompile_files(paths: Sequence[Path], rename_functions: bool = True) -> DecompileResult:
    """Decompile .vm files and/or folders of .vm files (one program)."""
    files = resolve_inputs([str(p) for p in paths])
    functions = read_files(files)
    texts = {}
    for path in files:
        texts[path.name] = path.read_text(encoding="utf-8")
    return decompile_functions(functions, rename_functions, texts)
