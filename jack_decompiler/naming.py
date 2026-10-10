"""
naming.py - Give variables (and generic functions) descriptive names.
======================================================================

A .vm file keeps the names of classes and subroutines (`Ball.move`), but
every variable is just a number: `local 2`, `argument 1`, `this 0`,
`static 3`. This module guesses good names from how they're used. Each
variable collects *candidates*, each with a score; the best free one wins.

    evidence                                          name          score
    ------------------------------------------------  ------------  -----
    an OS class's own parameter (e.g. Math.sqrt's x)  x               95
    `method int getLeft() { return this.k; }`         field: left     90
    `method void setSize(int v) { let this.k = v; }`  field: size     90
                                                      param: newSize  85
    constructor `let this.k = argK`                   param: aSize    70
    `let arr[i] = Alien.new(...)`                     arr: aliens     60
    loop counter: while (v < ...) { let v = v + 1 }   i, j, k, ...    55
    `let x = Keyboard.keyPressed()` / `getScore()`    key / score     50
    (round 2) callers pass a variable called `size`   param: size     45
    `while (~v)` on a boolean                         done            40
    of type Ball / String / Array / char              ball/str/array  30/20
    (round 2) passed to Screen.drawCircle's radius    radius          25
    nothing known                                     local2, arg1,   0
                                                      field0, static3

Names must be valid Jack identifiers, not keywords, not class names, and
unique: fields and statics in their class; parameters and locals in their
subroutine (and never the same as a field, which they would hide).

Round 2 repeats the guessing once round 1's names are known, so names can
flow between callers and the subroutines they call.

Subroutine names are kept as they are, EXCEPT meaningless ones such as
`f1` or `func_12`: those get a descriptive name if the body makes one
obvious (getX / setX / dispose / new).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .infer import is_object_type
from .jack_ast import Binary, Call, Const, Index, Let, Return, This, Unary, Var, While, all_exprs, walk_stmts
from .model import Key, Program, Subroutine
from .os_api import JACK_KEYWORDS, OS_API, RESULT_NAMES

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GENERIC_FUNCTION = re.compile(r"^(f|fn|func|function|sub|subroutine|method|m|proc|routine|l)_?\d+$", re.IGNORECASE)
LOOP_NAMES = ("i", "j", "k", "n", "m")
NAMING_ROUNDS = 3  # later rounds let names flow further (field -> constructor parameter -> caller)
RECTANGLE_CALLS = ("Screen.drawRectangle", "Screen.drawLine")
STRIP_PREFIXES = ("get", "read", "calc", "compute", "find", "make", "create", "load", "new")
CHANGE_PREFIXES = ("inc", "dec", "increase", "decrease", "increment", "decrement", "reset", "update", "toggle",
                   "change", "grow", "shrink", "flip")
# Subroutine names starting with these are actions, so they make poor variable names.
VERBS = ("draw", "move", "run", "set", "do", "print", "show", "hide", "update", "init", "dispose", "erase", "check",
         "handle", "process", "add", "remove", "clear", "write", "play", "start", "stop", "wait", "fire", "shoot",
         "kill", "test", "put", "push", "pop", "go", "make", "render", "reset", "inc", "dec", "toggle", "main")
# OS parameters whose names are too generic to pass on to the caller's variables.
NO_PROPAGATE_CLASSES = ("Math",)
KEEP_PREFIXES = ("is", "has", "can")

Candidates = Dict[Key, List[Tuple[int, str]]]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def lower_first(name: str) -> str:
    if not name:
        return name
    if name.isupper():
        return name.lower()
    return name[0].lower() + name[1:]


def upper_first(name: str) -> str:
    return name[:1].upper() + name[1:]


def plural(name: str) -> str:
    if name.endswith(("s", "x", "z", "sh", "ch")):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def strip_verb(name: str) -> Optional[str]:
    """getScore -> score, readLine -> line, isDone -> isDone; None if no such prefix."""
    for prefix in KEEP_PREFIXES:
        if name.startswith(prefix) and name[len(prefix):][:1].isupper():
            return name
    for prefix in STRIP_PREFIXES:
        rest = name[len(prefix):]
        if name.startswith(prefix) and rest[:1].isupper():
            return rest
        if name.startswith(prefix + "_") and rest[1:]:
            return rest[1:]
    return None


def name_for_result(callee: str) -> Optional[str]:
    """A good name for a variable that holds `callee(...)`'s result."""
    if callee in RESULT_NAMES:
        return RESULT_NAMES[callee]
    cls, _, function = callee.partition(".")
    if function == "new":
        return lower_first(cls)
    rest = strip_verb(function)
    if rest:
        return lower_first(rest)
    if not function.lower().startswith(VERBS) and not GENERIC_FUNCTION.match(function):
        return lower_first(function)  # a noun such as Util.mod or Random.next
    return None


def name_for_type(t: str) -> Tuple[int, Optional[str]]:
    if t == "String":
        return 20, "str"
    if t == "Array":
        return 20, "array"
    if t == "char":
        return 20, "c"
    if is_object_type(t):
        return 30, lower_first(t)
    return 0, None


def fallback_name(key: Key) -> str:
    segment, _, index = key
    prefix = {"local": "local", "argument": "arg", "this": "field", "static": "static"}[segment]
    return f"{prefix}{index}"


def without_parameter_prefix(name: str) -> str:
    """aWidth / newWidth (made from a field's name) -> width."""
    for prefix in ("a", "new"):
        if name.startswith(prefix) and name[len(prefix):][:1].isupper():
            return lower_first(name[len(prefix):])
    return name


def is_valid_name(name: str, forbidden: Set[str]) -> bool:
    return bool(IDENTIFIER.match(name)) and name not in JACK_KEYWORDS and name not in forbidden


def is_arg0_this(sub: Subroutine, var: Var) -> bool:
    return sub.kind == "method" and var.segment == "argument" and var.index == 0


# ---------------------------------------------------------------------------
# Collecting candidates
# ---------------------------------------------------------------------------
def accessor(sub: Subroutine) -> Optional[Tuple[str, Var, Optional[Var]]]:
    """
    ("get", var, None) for `return this.k;` / `return static k;` bodies,
    ("set", var, argument) for `let this.k = argument; return;` bodies.
    """
    body = sub.body
    if len(body) == 1 and isinstance(body[0], Return) and isinstance(body[0].value, Var) \
            and body[0].value.segment in ("this", "static"):
        return "get", body[0].value, None
    if len(body) == 2 and isinstance(body[0], Let) and isinstance(body[1], Return) \
            and isinstance(body[0].target, Var) and body[0].target.segment in ("this", "static") \
            and isinstance(body[0].value, Var) and body[0].value.segment == "argument" \
            and not is_arg0_this(sub, body[0].value) and body[1].value == Const(0):
        return "set", body[0].target, body[0].value
    return None


def _member_name(derived: str, var: Var) -> str:
    """Statics such as START_X keep their capitals; everything else starts lower case."""
    if var.segment == "static" and derived.isupper():
        return derived
    return lower_first(derived)


def _comparison_vars(cond) -> List[Var]:
    if isinstance(cond, Unary) and cond.op == "~":
        cond = cond.operand
    if isinstance(cond, Binary) and cond.op in "<>=":
        return [side for side in (cond.left, cond.right) if isinstance(side, Var)]
    return []


def _is_step(stmt, var: Var) -> bool:
    """let v = v + c;  or  let v = v - c;"""
    return (isinstance(stmt, Let) and stmt.target == var and isinstance(stmt.value, Binary)
            and stmt.value.op in "+-" and stmt.value.left == var)


def declared_keys(program: Program) -> Iterable[Key]:
    for cls in program.classes.values():
        yield from cls.field_keys()
        yield from cls.static_keys()
        for sub in cls.subs:
            yield from sub.param_keys()
            yield from sub.local_keys()


def collect_candidates(program: Program, earlier: Optional[Dict[Key, Tuple[str, int]]] = None) -> Candidates:
    cands: Candidates = defaultdict(list)

    def add(key: Key, score: int, name: Optional[str]) -> None:
        if name:
            cands[key].append((score, name))

    links: List[Tuple[Key, Key]] = []  # (field, constructor argument) pairs
    for sub in program.subs.values():
        if sub.error is not None:
            continue
        own = OS_API.get(sub.full_name)  # e.g. the program brings its own Math.vm
        if own is not None and len(own.params) == sub.n_params:
            for key, (_, name) in zip(sub.param_keys(), own.params):
                add(key, 95, name)

        found = accessor(sub)
        if found is not None:
            how, var, arg = found
            if how == "get":
                derived = strip_verb(sub.name)
                if derived and not derived.startswith(KEEP_PREFIXES):
                    add(sub.key(var), 90, _member_name(derived, var))
                elif derived or not GENERIC_FUNCTION.match(sub.name):
                    add(sub.key(var), 80, _member_name(derived or sub.name, var))
            elif sub.name.startswith("set") and sub.name[3:4].isupper():
                rest = sub.name[3:]
                add(sub.key(var), 90, _member_name(rest, var))
                add(sub.key(arg), 85, "new" + upper_first(rest))

        changed = {s.target for s in walk_stmts(sub.body) if isinstance(s, Let) and isinstance(s.target, Var)
                   and s.target.segment in ("this", "static")}
        for prefix in CHANGE_PREFIXES:
            rest = sub.name[len(prefix):]
            if sub.name.startswith(prefix) and rest[:1].isupper() and len(changed) == 1:
                var = next(iter(changed))
                add(sub.key(var), 65, _member_name(rest, var))
                break

        for s in walk_stmts(sub.body):
            if isinstance(s, Let):
                target, value = s.target, s.value
                if isinstance(target, Var) and not is_arg0_this(sub, target):
                    if target.segment == "local" and isinstance(value, Binary) and value.op == "+" \
                            and value.left == target and not isinstance(value.right, Const):
                        add(sub.key(target), 42, "sum")  # let v = v + something: an accumulator
                    if isinstance(value, Call):
                        add(sub.key(target), 50, name_for_result(value.name))
                    if sub.kind == "constructor" and target.segment == "this" and isinstance(value, Var) \
                            and value.segment == "argument":
                        links.append((sub.key(target), sub.key(value)))
                elif isinstance(target, Index) and isinstance(value, Call) and value.name.endswith(".new"):
                    add(sub.key(target.base), 60, plural(lower_first(value.name.split(".")[0])))
            elif isinstance(s, While):
                for var in _comparison_vars(s.cond):
                    if var.segment == "local" and any(_is_step(x, var) for x in walk_stmts(s.body)):
                        for name in LOOP_NAMES:
                            add(sub.key(var), 55, name)
                cond = s.cond
                if isinstance(cond, Unary) and cond.op == "~" and isinstance(cond.operand, Var) \
                        and program.types.get(sub.key(cond.operand)) == "boolean":
                    add(sub.key(cond.operand), 40, "done")

        for e in all_exprs(sub.body):  # drawRectangle(x, y, x + width, y + height)
            if isinstance(e, Call) and e.name in RECTANGLE_CALLS and len(e.args) == 4:
                for start, end, name in ((e.args[0], e.args[2], "width"), (e.args[1], e.args[3], "height")):
                    if isinstance(end, Binary) and end.op == "+" and end.left == start and isinstance(end.right, Var) \
                            and not is_arg0_this(sub, end.right):
                        add(sub.key(end.right), 35, name)

    for key in declared_keys(program):
        t = program.types.get(key, "int")
        score, name = name_for_type(t)
        add(key, score, name)
        if t == "boolean":
            add(key, 10, "flag")
        add(key, 0, fallback_name(key))

    if earlier:
        _propagate(program, earlier, links, add)
    return cands


def _propagate(program: Program, earlier: Dict[Key, Tuple[str, int]], links, add) -> None:
    """Round 2: let names flow along calls and constructor assignments."""
    passed: Dict[Key, Counter] = defaultdict(Counter)
    for sub in program.subs.values():
        if sub.error is not None:
            continue
        for e in all_exprs(sub.body):
            if not isinstance(e, Call):
                continue
            callee = program.subs.get(e.name)
            sig = program.signature(e.name)
            args = e.args[1:] if sig is not None and sig.kind == "method" else e.args
            for position, arg in enumerate(args):
                if not isinstance(arg, Var) or is_arg0_this(sub, arg):
                    continue
                arg_key = sub.key(arg)
                if callee is not None:
                    vm_index = position + callee.first_param
                    if vm_index >= callee.n_args:
                        continue
                    param = ("argument", callee.full_name, vm_index)
                    name, score = earlier.get(arg_key, ("", 0))
                    if score >= 30:
                        passed[param][name] += 1
                    pname, pscore = earlier.get(param, ("", 0))
                    if pscore >= 45:
                        add(arg_key, 25, without_parameter_prefix(pname))
                elif sig is not None and position < len(sig.params) \
                        and e.name.split(".")[0] not in NO_PROPAGATE_CLASSES:
                    add(arg_key, 25, sig.params[position][1].rstrip("0123456789"))
    for param, counter in passed.items():
        add(param, 45, counter.most_common(1)[0][0])
    for field_key, arg_key in links:
        fname, fscore = earlier.get(field_key, ("", 0))
        if fscore >= 20:
            add(arg_key, 70, "a" + upper_first(fname))
        aname, ascore = earlier.get(arg_key, ("", 0))
        derived_from_field = aname[:1] == "a" and aname[1:2].isupper()
        if ascore >= 45 and not derived_from_field:
            add(field_key, 44, aname)


# ---------------------------------------------------------------------------
# Choosing: best candidate that is valid and still free in its scope
# ---------------------------------------------------------------------------
def _assign(keys: List[Key], cands: Candidates, used: Set[str], forbidden: Set[str],
            result: Dict[Key, Tuple[str, int]]) -> None:
    def options(key: Key) -> List[Tuple[int, str]]:
        best: Dict[str, int] = {}
        for score, name in cands.get(key, []):
            if is_valid_name(name, forbidden):
                best[name] = max(score, best.get(name, -1))
        # sort by score, keeping the order candidates were added for equal scores
        order: Dict[str, int] = {}
        for i, (_, name) in enumerate(cands.get(key, [])):
            order.setdefault(name, i)
        return sorted(((s, n) for n, s in best.items()), key=lambda c: (-c[0], order[c[1]]))

    listed = [(key, options(key) or [(0, fallback_name(key))]) for key in keys]
    order = sorted(range(len(listed)), key=lambda i: (-listed[i][1][0][0], i))
    for i in order:
        key, opts = listed[i]
        for score, name in opts:
            # A taken good name + a number (main2) beats a meaningless fallback (local1).
            if name not in used and (score > 0 or opts[0][0] == 0):
                break
        else:
            score, base = opts[0]
            n = 2
            while f"{base}{n}" in used or not is_valid_name(f"{base}{n}", forbidden):
                n += 1
            name = f"{base}{n}"
        used.add(name)
        result[key] = (name, score)


def resolve(program: Program, cands: Candidates) -> Dict[Key, Tuple[str, int]]:
    forbidden = program.class_names() | {"this"}
    result: Dict[Key, Tuple[str, int]] = {}
    for cls in program.classes.values():
        used: Set[str] = set()
        _assign(cls.field_keys() + cls.static_keys(), cands, used, forbidden, result)
        class_level = set(used)
        for sub in cls.subs:
            _assign(sub.param_keys() + sub.local_keys(), cands, set(class_level), forbidden, result)
            if sub.kind == "method":
                result[("argument", sub.full_name, 0)] = ("this", 100)
    return result


def rename_generic_functions(program: Program) -> None:
    """f1 -> getX / setX / dispose / new, when the body makes it obvious."""
    for cls in program.classes.values():
        taken = {sub.name for sub in cls.subs}
        for sub in cls.subs:
            if sub.error is not None or not GENERIC_FUNCTION.match(sub.name):
                continue
            new_name = None
            found = accessor(sub)
            if sub.kind == "constructor":
                new_name = "new"
            elif found is not None:
                member = program.names.get(sub.key(found[1]), "")
                if member and not member.startswith(("field", "static")):
                    new_name = ("get" if found[0] == "get" else "set") + upper_first(member)
            elif sub.kind == "method" and any(
                    isinstance(e, Call) and e.name == "Memory.deAlloc" and e.args == (This(),)
                    for e in all_exprs(sub.body)):
                new_name = "dispose"
            if new_name and new_name not in taken:
                taken.add(new_name)
                program.renames[sub.full_name] = f"{cls.name}.{new_name}"


def name_everything(program: Program, rename_functions: bool = True) -> None:
    """Fill in program.names (and program.renames)."""
    names = resolve(program, collect_candidates(program))
    for _ in range(NAMING_ROUNDS - 1):
        names = resolve(program, collect_candidates(program, names))
    final = names
    program.names = {key: name for key, (name, _) in final.items()}
    if rename_functions:
        rename_generic_functions(program)
