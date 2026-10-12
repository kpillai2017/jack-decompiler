"""
jack_ast.py - The Jack syntax tree the decompiler builds.
=========================================================

The structurer (structure.py) turns VM instructions into these objects; the
emitter (emitter.py) turns them into Jack text.

Variables are kept as raw VM locations - Var("local", 2), Var("this", 0) -
until the very end. Names and types are worked out later (infer.py,
naming.py) because they depend on how a variable is used everywhere in the
program, not just at one place.

Expressions                              Statements
-----------                              ----------
Const(5)           5                     Let(target, value)   let x = 5;
Var("local", 0)    a local variable      Do(call)             do f();
This()             this                  If(cond, then, else) if (...) {...}
Unary("-", e)      -e   ("~" = not)      While(cond, body)    while (...) {...}
Binary("+", a, b)  a + b                 Return(value)        return x;
Call("A.f", args)  A.f(...) / x.f(...)
Index(base, i)     base[i]
StringLit(n, cs)   "text" (String.new(n) + appendChar per char)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple, Union


class Expr:
    pass


@dataclass(frozen=True)
class Const(Expr):
    value: int


@dataclass(frozen=True)
class Var(Expr):
    segment: str  # "local", "argument", "this" or "static"
    index: int


@dataclass(frozen=True)
class This(Expr):
    pass


@dataclass(frozen=True)
class Unary(Expr):
    op: str  # "-" or "~"
    operand: Expr


@dataclass(frozen=True)
class Binary(Expr):
    op: str  # + - * / & | < > =
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Call(Expr):
    name: str  # "Class.subroutine" exactly as in the VM
    args: Tuple[Expr, ...] = ()


@dataclass(frozen=True)
class Index(Expr):
    base: Var
    index: Expr


@dataclass(frozen=True)
class SavedIndex(Index):
    """Array read whose address was saved on the VM stack for an update."""


@dataclass(frozen=True)
class StringLit(Expr):
    """`String.new(capacity)` followed by appendChar(c) for each c in chars."""

    capacity: int
    chars: Tuple[int, ...] = ()

    def literal(self) -> Optional[str]:
        """The text if this can be written as "...", else None."""
        if len(self.chars) != self.capacity:
            return None
        if any(c < 32 or c > 126 or c == 34 for c in self.chars):  # no " or control characters in Jack strings
            return None
        return "".join(chr(c) for c in self.chars)


class Stmt:
    pass


@dataclass
class Let(Stmt):
    target: Union[Var, Index]
    value: Expr
    compound: Optional[str] = None  # RHS only; preserves one array target evaluation


@dataclass
class Do(Stmt):
    call: Call


@dataclass
class If(Stmt):
    cond: Expr
    then: List[Stmt] = field(default_factory=list)
    otherwise: Optional[List[Stmt]] = None  # None = no else branch at all


@dataclass
class While(Stmt):
    cond: Expr
    body: List[Stmt] = field(default_factory=list)


@dataclass
class For(While):
    # Initialisation is emitted as the preceding ordinary statement.
    # None means no condition: unlike while(true), no VM test was emitted.
    update: List[Stmt] = field(default_factory=list)
    has_condition: bool = True


@dataclass
class Break(Stmt):
    pass


@dataclass
class Continue(Stmt):
    pass


@dataclass
class Return(Stmt):
    value: Expr


@dataclass
class Comment(Stmt):
    """Used for subroutines that couldn't be decompiled."""

    text: str


# ---------------------------------------------------------------------------
# Walking helpers
# ---------------------------------------------------------------------------
def children(e: Expr) -> Tuple[Expr, ...]:
    if isinstance(e, Unary):
        return (e.operand,)
    if isinstance(e, Binary):
        return (e.left, e.right)
    if isinstance(e, Call):
        return e.args
    if isinstance(e, Index):
        return (e.base, e.index)
    return ()


def walk_expr(e: Expr) -> Iterator[Expr]:
    """Every expression inside `e` (including `e`), without deep recursion."""
    todo = [e]
    while todo:
        current = todo.pop()
        yield current
        todo.extend(reversed(children(current)))


def walk_stmts(stmts: List[Stmt]) -> Iterator[Stmt]:
    """Every statement, depth first, in program order."""
    for s in stmts:
        yield s
        if isinstance(s, If):
            yield from walk_stmts(s.then)
            if s.otherwise is not None:
                yield from walk_stmts(s.otherwise)
        elif isinstance(s, While):
            yield from walk_stmts(s.body)
            if isinstance(s, For):
                yield from walk_stmts(s.update)


def stmt_exprs(s: Stmt) -> Tuple[Expr, ...]:
    """The expressions directly owned by one statement."""
    if isinstance(s, Let):
        return (s.target, s.value)
    if isinstance(s, Do):
        return (s.call,)
    if isinstance(s, (If, While)):
        return (s.cond,)
    if isinstance(s, Return):
        return (s.value,)
    return ()


def all_exprs(stmts: List[Stmt]) -> Iterator[Expr]:
    for s in walk_stmts(stmts):
        for e in stmt_exprs(s):
            yield from walk_expr(e)
