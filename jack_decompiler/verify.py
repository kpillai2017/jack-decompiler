"""
verify.py - Prove a decompilation is right by compiling it back.
================================================================

    original .vm  --decompile-->  .jack  --compile (compiler.py)-->  new .vm
         \_____________________ compare ___________________________/

The two VM programs are compared instruction by instruction. Label names
don't matter (IF_TRUE0 vs L17), so labels are renamed in order of first
appearance before comparing. Functions renamed by the decompiler (f1 ->
getX) are mapped back first.

"identical" means the decompiled Jack is guaranteed to behave exactly like
the original. "differs" doesn't necessarily mean it's wrong - the original
may come from a different compiler that produces other (equivalent) code -
but it points at where to look.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .compiler import JackSyntaxError, compile_jack
from .decompiler import DecompileResult
from .vm_reader import VMFunction, VMSyntaxError, parse_vm


@dataclass
class ClassCheck:
    name: str
    ok: bool
    message: str


def normalise(function: VMFunction, renames: Dict[str, str]) -> List[Tuple[str, str, int]]:
    labels: Dict[str, str] = {}
    result = [("function", renames.get(function.name, function.name), function.n_locals)]
    for ins in function.body:
        arg1 = ins.arg1
        if ins.op in ("label", "goto", "if-goto"):
            arg1 = labels.setdefault(arg1, f"L{len(labels)}")
        elif ins.op == "call":
            arg1 = renames.get(arg1, arg1)
        result.append((ins.op, arg1, ins.arg2))
    return result


def _text(t: Tuple[str, str, int]) -> str:
    op, a, b = t
    if op in ("push", "pop", "function", "call"):
        return f"{op} {a} {b}"
    return f"{op} {a}".strip() if op in ("label", "goto", "if-goto") else (a if op == "arith" else op)


def compare(original: List[VMFunction], rebuilt: List[VMFunction], renames: Dict[str, str]) -> Optional[str]:
    """None if identical, else a description of the first difference."""
    before = [normalise(f, renames) for f in original]
    after = [normalise(f, {}) for f in rebuilt]
    if len(before) != len(after):
        return f"{len(before)} subroutines in the VM, {len(after)} after recompiling"
    for old, new in zip(before, after):
        name = old[0][1]
        for i, (a, b) in enumerate(zip(old, new)):
            if a != b:
                return f"{name}, instruction {i}: VM has '{_text(a)}', recompiled Jack gives '{_text(b)}'"
        if len(old) != len(new):
            return f"{name}: {len(old) - 1} instructions in the VM, {len(new) - 1} after recompiling"
    return None


def verify(result: DecompileResult) -> List[ClassCheck]:
    checks = []
    renames = result.program.renames
    for cls in result.classes.values():
        original = [sub.vm for sub in result.program.classes[cls.name].subs]
        if cls.errors:
            checks.append(ClassCheck(cls.name, False, f"{len(cls.errors)} subroutine(s) could not be decompiled"))
            continue
        try:
            rebuilt = parse_vm(compile_jack(cls.jack, cls.jack_file_name), cls.name + ".vm")
        except JackSyntaxError as error:
            checks.append(ClassCheck(cls.name, False, f"the decompiled Jack doesn't compile: {error}"))
            continue
        except VMSyntaxError as error:  # pragma: no cover - would be a compiler bug
            checks.append(ClassCheck(cls.name, False, f"recompiling gave bad VM code: {error}"))
            continue
        difference = compare(original, rebuilt, renames)
        if difference is not None:
            # Different Jack compilers use different if and array-read shapes.
            # Require exact instruction equality in either dialect; do not
            # weaken verification to a heuristic semantic comparison.
            companion = parse_vm(compile_jack(cls.jack, cls.jack_file_name, dialect="companion"), cls.name + ".vm")
            alternative = compare(original, companion, renames)
            if alternative is None:
                difference = None
        checks.append(ClassCheck(cls.name, difference is None, difference or "identical after recompiling"))
    return checks
