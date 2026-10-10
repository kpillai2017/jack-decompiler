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
    `method void setDead() { let this.k = true; }`    field: dead     75
    loop counter: while (v < ...) { let v = v + 1 }   i, j, k, ...    55
    `let x = Keyboard.keyPressed()` / `getScore()`    key / score     50
    `let v = 16384 + ...` (`let s = 16384;`, Array)   address/screen  48
    (round 2) `if (x > k) { let x = k; }`             k: maxX (minX)  46
    (round 2) callers pass a variable called `size`   param: size     45
    `let v = c - 48`                                  digit           45
    (round 2) every caller passes `ball.getX()`       param: x        40
    `while (~v)` on a boolean                         done            40
    the limit in `while (i < v)` (`let v = i + n`)    count (end)     32
    of type Ball / String / Array / char              ball/str/array  30/20
    `return v;`                                       result          30
    (round 2) passed to Screen.drawCircle's radius    radius          25
    (round 2) next to x / x1 / width / start          y / y1 / height 24
                                                      / end
    nothing known                                     local2, arg1,   0
                                                      field0, static3

Names must be valid Jack identifiers, not keywords, not class names, and
unique: fields and statics in their class; parameters and locals in their
subroutine (and never the same as a field, which they would hide).

Later rounds repeat the guessing once the previous round's names are
known, so names can flow between callers and the subroutines they call,
and between fields and constructor parameters. Rules that use earlier
names are written so they give the same answer round after round (a field
and its constructor parameter are named together: x / aX). A guess that's
only a partner (y, after x) never beats real evidence and never gets a
number: if y is taken, the variable keeps its plain name (arg1).

Subroutine names are kept as they are, EXCEPT meaningless ones such as
`f1` or `func_12`: those get a descriptive name if the body makes one
obvious (getX / setX / dispose / new).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .infer import is_object_type
from .jack_ast import (Binary, Call, Const, If, Index, Let, Return, This, Unary, Var, While, all_exprs,
                       walk_expr, walk_stmts)
from .model import Key, Program, Subroutine
from .os_api import JACK_KEYWORDS, OS_API, RESULT_NAMES

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GENERIC_FUNCTION = re.compile(r"^(f|fn|func|function|sub|subroutine|method|m|proc|routine|l)_?\d+$", re.IGNORECASE)
LOOP_NAMES = ("i", "j", "k", "n", "m")
NAMING_ROUNDS = 4  # later rounds let names flow further (field -> constructor parameter -> caller)
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
SCREEN_ADDRESSES = (16384, 24576)  # the screen's and the keyboard's memory maps
MEMORY_MAPS = {Const(16384): "screen", Const(24576): "keyboard"}
CHAR_ZERO = 48  # the character code of '0': `c - 48` is a digit's value
FLAG_SETTERS = ("set", "mark")  # `method void setDead() { let this.k = true; }`
PARTNERS = {"left": "top", "width": "height", "row": "column", "dx": "dy", "start": "end"}
# x, x1, startX, refX2 ... - but not words such as index or fox
COORDINATE = re.compile(r"^(?:()([xy])|([a-z][A-Za-z0-9]*?)([XY]))(\d*)$")

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


def partners(name: str) -> List[str]:
    """
    Names that usually come right after `name` (or before it) in a parameter
    or variable list: x -> y, x1 -> y1, startX -> startY, left -> top, ...
    Returns [after, before]; either may be "".
    """
    after = before = ""
    m = COORDINATE.match(name)
    if m:
        prefix, axis, digits = m.group(1) or m.group(3) or "", m.group(2) or m.group(4), m.group(5)
        if axis in "xX":
            after = prefix + ("y" if axis == "x" else "Y") + digits
        else:
            before = prefix + ("x" if axis == "y" else "X") + digits
    for first, second in PARTNERS.items():
        if name == first:
            after = second
        elif name == second:
            before = first
    return [after, before]


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


def is_constant_name(name: str) -> bool:
    """START_X, OCTOPUS - but not X (getX's x)."""
    return len(name.replace("_", "")) > 1 and name.replace("_", "").isupper()


def _member_name(derived: str, var: Var) -> str:
    """Statics such as START_X keep their capitals; everything else starts lower case."""
    if var.segment == "static" and is_constant_name(derived):
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


def _bound(cond, then) -> Optional[Tuple[Var, Var, str]]:
    """
    `if (~(v > b)) { ... let v = b; }`  ->  (b, v, "min")   (b is v's lower limit)
    `if (v > b)    { ... let v = b; }`  ->  (b, v, "max")
    """
    negated = isinstance(cond, Unary) and cond.op == "~"
    if negated:
        cond = cond.operand
    if not (isinstance(cond, Binary) and cond.op in "<>" and isinstance(cond.left, Var) and isinstance(cond.right, Var)):
        return None
    for stmt in then:
        if isinstance(stmt, Let) and isinstance(stmt.target, Var):
            for v, b, below in ((cond.left, cond.right, cond.op == "<"), (cond.right, cond.left, cond.op == ">")):
                if stmt.target == v and stmt.value == b and v != b:
                    # v < b (or b > v): v went below b; negated: v went above b
                    return b, v, "max" if negated == below else "min"
    return None


def _contains_const(e, values) -> bool:
    return any(isinstance(x, Const) and x.value in values for x in walk_expr(e))


def _var_plus_const(e) -> Optional[Var]:
    """argK, argK + 6, argK - 6 -> argK"""
    if isinstance(e, Var):
        return e
    if isinstance(e, Binary) and e.op in "+-" and isinstance(e.left, Var) and isinstance(e.right, Const):
        return e.left
    return None


def _result_role(callee: str) -> Optional[str]:
    """getX -> x; None for constants such as Constants.getOCTOPUS (a value, not a role)."""
    rest = strip_verb(callee.partition(".")[2])
    if rest and is_constant_name(rest):
        return None
    return name_for_result(callee)


def _flag_setter(sub: Subroutine) -> Optional[Tuple[Var, str]]:
    """`method void setDead() { let this.k = true; return; }` -> (this.k, "Dead")"""
    body = sub.body
    for prefix in FLAG_SETTERS:
        rest = sub.name[len(prefix):]
        if sub.name.startswith(prefix) and rest[:1].isupper() and sub.n_args == sub.first_param \
                and len(body) == 2 and isinstance(body[0], Let) and isinstance(body[0].target, Var) \
                and body[0].target.segment in ("this", "static") and isinstance(body[1], Return) \
                and body[0].value in (Unary("~", Const(0)), Const(0)):
            return body[0].target, rest
    return None


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
    bounds: List[Tuple[Key, Key, str]] = []  # (limit, variable, "min"/"max"), named in round 2
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

        flag = _flag_setter(sub)
        if flag is not None:
            add(sub.key(flag[0]), 75, _member_name(flag[1], flag[0]))

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
                    if value in MEMORY_MAPS and program.types.get(sub.key(target)) == "Array":
                        add(sub.key(target), 48, MEMORY_MAPS[value])  # let screen = 16384;
                    elif _contains_const(value, SCREEN_ADDRESSES) and program.types.get(sub.key(target), "int") == "int":
                        add(sub.key(target), 48, "address")  # let v = 16384 + (32 * y) + ...
                    if isinstance(value, Binary) and value.op == "-" and value.right == Const(CHAR_ZERO):
                        add(sub.key(target), 45, "digit")  # let v = c - 48
                    source = _var_plus_const(value)  # let this.k = argK (+ 6)
                    if sub.kind == "constructor" and target.segment == "this" and source is not None \
                            and source.segment == "argument":
                        links.append((sub.key(target), sub.key(source)))
                elif isinstance(target, Index) and isinstance(value, Call) and value.name.endswith(".new"):
                    add(sub.key(target.base), 60, plural(lower_first(value.name.split(".")[0])))
            elif isinstance(s, If):
                found_bound = _bound(s.cond, s.then)
                if found_bound is not None and not is_arg0_this(sub, found_bound[0]):
                    bounds.append((sub.key(found_bound[0]), sub.key(found_bound[1]), found_bound[2]))
            elif isinstance(s, Return):
                if isinstance(s.value, Var) and s.value.segment == "local":
                    add(sub.key(s.value), 30, "result")  # return v;
            elif isinstance(s, While):
                compared = _comparison_vars(s.cond)
                for var in compared:
                    if var.segment == "local" and any(_is_step(x, var) for x in walk_stmts(s.body)):
                        for name in LOOP_NAMES:
                            add(sub.key(var), 55, name)
                        for limit in compared:  # while (i < count)  /  let end = i + n; while (i < end)
                            if limit != var and limit.segment in ("local", "argument") \
                                    and not is_arg0_this(sub, limit):
                                from_counter = any(isinstance(x, Let) and x.target == limit
                                                   and var in walk_expr(x.value) for x in walk_stmts(sub.body))
                                add(sub.key(limit), 32, "end" if from_counter else "count")
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
        _propagate(program, earlier, links, add, cands)
        _name_bounds(earlier, bounds, add)
        _name_partners(program, earlier, cands, add)
    return cands


def _propagate(program: Program, earlier: Dict[Key, Tuple[str, int]], links, add, cands: Candidates) -> None:
    """Round 2: let names flow along calls and constructor assignments."""
    passed: Dict[Key, Counter] = defaultdict(Counter)
    results: Dict[Key, Counter] = defaultdict(Counter)  # f(missle.getX()): names of the calls passed
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
                if isinstance(arg, Call) and callee is not None:  # f(missle.getX()): f's parameter is x
                    vm_index = position + callee.first_param
                    if vm_index < callee.n_args:
                        results[("argument", callee.full_name, vm_index)][_result_role(arg.name)] += 1
                    continue
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
    for param, counter in results.items():
        if len(counter) == 1:  # every caller agrees (and it's a role, not a constant such as getOCTOPUS())
            add(param, 40, next(iter(counter)))
    for field_key, arg_key in links:  # constructor: let this.x = aX;
        base = _pair_name(earlier, field_key, arg_key)
        if base:
            # Decided together, in one round, so the pair can't take turns. If
            # base is the parameter's sure name (String.new's maxLength), the
            # field may have it too: the parameter becomes aMaxLength.
            sure = any(score >= SURE and name == base for score, name in cands.get(arg_key, []))
            add(field_key, SURE if sure else 44, base)
            add(arg_key, 70, "a" + upper_first(base))


def _pair_name(earlier: Dict[Key, Tuple[str, int]], field_key: Key, arg_key: Key) -> str:
    """The shared name of a field and the constructor parameter it's set from: x for (x, aX)."""
    fname, fscore = earlier.get(field_key, ("", 0))
    aname, ascore = earlier.get(arg_key, ("", 0))
    if aname[:1] == "a" and aname[1:2].isupper():  # aX: already named after the field
        return lower_first(aname[1:])
    if fscore >= 20 and fname != fallback_name(field_key):
        return fname
    if ascore >= 45:
        return aname
    return ""


SURE = 90  # names this good are kept, even if a field would like the same name
MEANINGFUL = 25  # names scoring at least this say something about the variable
# Just below MEANINGFUL: a partner name only fills a gap (it never beats real
# evidence, and never makes partners of its own), and stays put round after round.
PARTNER_SCORE = MEANINGFUL - 1


def _name_bounds(earlier: Dict[Key, Tuple[str, int]], bounds, add) -> None:
    """`if (~(x > k)) { let x = k; }`: k is minX (round 2, once x has a name)."""
    for limit, var, kind in bounds:
        name, score = earlier.get(var, ("", 0))
        if score >= MEANINGFUL and name not in ("this",):
            add(limit, 46, kind + upper_first(name))


def _is_candidate(cands: Candidates, key: Key, name: str) -> bool:
    return any(n == name for _, n in cands.get(key, []))


def _name_partners(program: Program, earlier: Dict[Key, Tuple[str, int]], cands: Candidates, add) -> None:
    """Parameters and locals: int x, ?  ->  int x, y   (and ?, y -> x, y; width, ? -> width, height ...)"""
    sequences: List[List[Key]] = []  # (not fields: they're often listed in no particular order)
    for cls in program.classes.values():
        sequences += [sub.param_keys() for sub in cls.subs] + [sub.local_keys() for sub in cls.subs]
    for keys in sequences:
        for first, second in zip(keys, keys[1:]):
            if program.types.get(first, "int") != program.types.get(second, "int"):
                continue
            (name1, score1), (name2, score2) = earlier.get(first, ("", 0)), earlier.get(second, ("", 0))
            # (a name numbered to avoid a clash, such as x2, isn't one to pair with)
            name1 = name1 if _is_candidate(cands, first, name1) else ""
            name2 = name2 if _is_candidate(cands, second, name2) else ""
            if score1 >= MEANINGFUL and score2 < MEANINGFUL and partners(name1)[0]:
                add(second, PARTNER_SCORE, partners(name1)[0])
            if score2 >= MEANINGFUL and score1 < MEANINGFUL and partners(name2)[1]:
                add(first, PARTNER_SCORE, partners(name2)[1])


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
            score, base = next(((sc, n) for sc, n in opts if sc != PARTNER_SCORE), (0, fallback_name(key)))
            if score == 0 and base == fallback_name(key) and base not in used:
                used.add(base)
                result[key] = (base, 0)
                continue
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
        # A parameter's sure name (e.g. the OS's own `text`, 95) mustn't be lost
        # to a guess for a field or static (which the parameter couldn't then use).
        sure = {name for sub in cls.subs for key in sub.param_keys() + sub.local_keys()
                for score, name in cands.get(key, []) if score >= SURE}
        members = {key: [(score, name) for score, name in cands.get(key, []) if score >= SURE or name not in sure]
                   for key in cls.field_keys() + cls.static_keys()}
        _assign(cls.field_keys() + cls.static_keys(), members, used, forbidden, result)
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
