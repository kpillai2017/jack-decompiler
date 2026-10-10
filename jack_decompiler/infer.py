"""
infer.py - Work out the type of every variable, parameter and return value.
===========================================================================

VM code has no types: everything is a 16-bit number. But Jack needs a type
in every declaration, and the type matters: `x.draw()` compiles to
`call Square.draw` only if `x` is declared as a Square.

So the types are *inferred* from how each variable is used. Every use casts
a weighted "vote":

    evidence                                   vote            weight
    -----------------------------------------  --------------  ------
    push x; ...; call Square.draw 1  (method)  Square            10
    x[i]  (x + i used as an address)           Array              4
    let x = <expression of type T>             T                  3
    return <expression of type T>              T (return type)    3
    passed where a parameter of type T goes    T                  2
    if (x) / while (~x)                        boolean            2

The votes are counted several times over, because one answer feeds another
(once we know `b` is a Ball, `let a = b` tells us `a` is one too). The type
with the most votes wins; ties go to the more specific type (a class beats
Array beats String beats boolean beats char beats int). No votes: int.

Return types: constructors return their class; a subroutine is `void` if it
only ever returns 0 and nobody uses its result.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Optional, Set

from .jack_ast import (
    Binary, Call, Const, Do, Expr, If, Index, Let, Return, StringLit, This, Unary, Var, While,
    all_exprs, stmt_exprs, walk_expr, walk_stmts,
)
from .model import Key, Program, Subroutine
from .os_api import PRIMITIVE_TYPES

ROUNDS = 4


def type_rank(t: str) -> int:
    if t == "int":
        return 0
    if t == "char":
        return 1
    if t == "boolean":
        return 2
    if t == "String":
        return 3
    if t == "Array":
        return 4
    return 5  # a class


def pick(votes: Counter) -> str:
    return max(votes.items(), key=lambda item: (item[1], type_rank(item[0])))[0]


def find_used_results(program: Program) -> Set[str]:
    """Names of subroutines whose return value is used (not just `do f();`)."""
    used: Set[str] = set()
    for sub in program.subs.values():
        if sub.error is not None:  # look at the raw VM instead
            body = sub.vm.body
            for position, ins in enumerate(body):
                nxt = body[position + 1] if position + 1 < len(body) else None
                if ins.op == "call" and not (nxt is not None and nxt.op == "pop" and nxt.arg1 == "temp"):
                    used.add(ins.arg1)
            continue
        for s in walk_stmts(sub.body):
            roots = s.call.args if isinstance(s, Do) else stmt_exprs(s)
            for root in roots:
                used.update(e.name for e in walk_expr(root) if isinstance(e, Call))
    return used


class TypeContext:
    def __init__(self, program: Program, guesses: Dict[Key, str]):
        self.program = program
        self.guesses = guesses

    def var_type(self, sub: Subroutine, var: Var) -> Optional[str]:
        if sub.kind == "method" and var.segment == "argument" and var.index == 0:
            return sub.class_name
        return self.guesses.get(sub.key(var))

    def expr_type(self, sub: Subroutine, e: Expr) -> Optional[str]:
        if isinstance(e, Const):
            return "int" if e.value else None
        if isinstance(e, Unary):
            if e.op == "-":
                return "int"
            if isinstance(e.operand, Const) and e.operand.value == 0:
                return "boolean"
            inner = self.expr_type(sub, e.operand)
            return "boolean" if inner == "boolean" else ("int" if inner else None)
        if isinstance(e, Binary):
            if e.op in "<>=":
                return "boolean"
            if e.op in "&|":
                sides = (self.expr_type(sub, e.left), self.expr_type(sub, e.right))
                return "boolean" if "boolean" in sides else "int"
            return "int"
        if isinstance(e, StringLit):
            return "String"
        if isinstance(e, This):
            return sub.class_name
        if isinstance(e, Var):
            return self.var_type(sub, e)
        if isinstance(e, Call):
            sig = self.program.signature(e.name)
            if sig is None or sig.return_type == "void":
                return None
            return sig.return_type
        return None  # Index: arrays can hold anything


def _cast_votes(ctx: TypeContext, sub: Subroutine, votes: Dict[Key, Counter]) -> None:
    program = ctx.program

    def vote(key: Key, t: Optional[str], weight: int) -> None:
        if t and t != "void":
            votes[key][t] += weight

    def vote_var(e: Expr, t: Optional[str], weight: int) -> None:
        if isinstance(e, Var) and not (sub.kind == "method" and e.segment == "argument" and e.index == 0):
            vote(sub.key(e), t, weight)

    for s in walk_stmts(sub.body):
        if isinstance(s, Let) and isinstance(s.target, Var):
            vote_var(s.target, ctx.expr_type(sub, s.value), 3)
            if isinstance(s.value, Call) and s.value.name in program.subs:
                vote(("return", s.value.name, 0), ctx.guesses.get(sub.key(s.target)), 1)
        elif isinstance(s, (If, While)):
            cond = s.cond.operand if isinstance(s.cond, Unary) and s.cond.op == "~" else s.cond
            vote_var(cond, "boolean", 2)
        elif isinstance(s, Return):
            vote(("return", sub.full_name, 0), ctx.expr_type(sub, s.value), 3)

    for e in all_exprs(sub.body):
        if isinstance(e, Index):
            vote_var(e.base, "Array", 4)
        elif isinstance(e, Call):
            sig = program.signature(e.name)
            callee = program.subs.get(e.name)
            args = e.args
            if sig is not None and sig.kind == "method" and args:
                vote_var(args[0], e.name.split(".")[0], 10)
                args = args[1:]
            elif sig is None and args:  # unknown class: x.f() is likely a method of x's class
                vote_var(args[0], e.name.split(".")[0], 1)
            for position, arg in enumerate(args):
                if callee is not None:
                    vm_index = position + callee.first_param
                    if vm_index < callee.n_args:
                        param = ("argument", callee.full_name, vm_index)
                        vote(param, ctx.expr_type(sub, arg), 2)
                        vote_var(arg, ctx.guesses.get(param), 2)
                elif sig is not None and position < len(sig.params):
                    vote_var(arg, sig.params[position][0], 2)


def _return_type(ctx: TypeContext, sub: Subroutine, votes: Dict[Key, Counter]) -> str:
    if sub.kind == "constructor":
        return sub.class_name
    used = sub.full_name in ctx.program.result_used
    if sub.error is not None:
        return "int" if used else "void"
    returns = [s.value for s in walk_stmts(sub.body) if isinstance(s, Return)]
    if not used and all(isinstance(v, Const) and v.value == 0 for v in returns):
        return "void"
    counter = votes.get(("return", sub.full_name, 0))
    return pick(counter) if counter else "int"


def infer_types(program: Program) -> None:
    """Fill in program.types and every subroutine's return_type."""
    program.result_used = find_used_results(program)
    guesses: Dict[Key, str] = {}
    for sub in program.subs.values():
        sub.return_type = sub.class_name if sub.kind == "constructor" else "int"
    for _ in range(ROUNDS):
        votes: Dict[Key, Counter] = defaultdict(Counter)
        ctx = TypeContext(program, guesses)
        for sub in program.subs.values():
            if sub.error is None:
                _cast_votes(ctx, sub, votes)
        guesses = {key: pick(counter) for key, counter in votes.items() if key[0] != "return"}
        program.types = guesses  # used by program.signature() in the next round
        for sub in program.subs.values():
            sub.return_type = _return_type(ctx, sub, votes)

    # Everything declared gets a type (int when there was no evidence).
    final: Dict[Key, str] = {}
    for cls in program.classes.values():
        for key in cls.field_keys() + cls.static_keys():
            final[key] = guesses.get(key, "int")
        for sub in cls.subs:
            for key in sub.param_keys() + sub.local_keys():
                final[key] = guesses.get(key, "int")
            if sub.kind == "method":
                final[("argument", sub.full_name, 0)] = sub.class_name
    program.types = final


def is_object_type(t: Optional[str]) -> bool:
    return bool(t) and t not in PRIMITIVE_TYPES and t != "void"
