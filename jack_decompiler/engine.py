"""
engine.py - Rebuild Jack expressions and statements from straight-line VM code.
==============================================================================

The VM is a stack machine. To turn

    push local 0
    push constant 1
    add
    pop local 0

back into `let x = x + 1;`, we run the code SYMBOLICALLY: instead of numbers,
the stack holds *expressions*. `push local 0` pushes Var("local", 0), `add`
pops two expressions and pushes Binary("+", ...), and `pop local 0` turns the
expression on top into a `let` statement.

Special patterns produced by Jack compilers are recognised on the way:

    call Math.multiply 2 / Math.divide 2   ->  a * b,  a / b
    String.new(n) + n x appendChar(c)      ->  "text"
    pop pointer 1 ... push that 0          ->  arr[i]   (array read)
    pop temp 0; pop pointer 1;             ->  let arr[i] = value;
      push temp 0; pop that 0
    call f n; pop temp 0                   ->  do f(...);

Anything that cannot be written in Jack (for example a statement while
values are still waiting on the stack) raises DecompileError, so the
decompiler never silently produces wrong code.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .jack_ast import (
    Binary, Call, Const, Do, Expr, Index, Let, Return, Stmt, StringLit, This, Unary, Var, walk_expr,
)
from .vm_reader import Instr

BINARY_SYMBOLS = {"add": "+", "sub": "-", "eq": "=", "gt": ">", "lt": "<", "and": "&", "or": "|"}
UNARY_SYMBOLS = {"neg": "-", "not": "~"}
VARIABLE_SEGMENTS = ("local", "argument", "this", "static")


class DecompileError(Exception):
    """VM code that can't be expressed in Jack. `instr` says where."""

    def __init__(self, message: str, instr: Optional[Instr] = None):
        self.message = message
        self.instr = instr
        where = f" ({instr.where()}: {instr.text()})" if instr is not None else ""
        super().__init__(message + where)


def negate(e: Expr) -> Expr:
    """~e, but ~~x simplifies to x."""
    if isinstance(e, Unary) and e.op == "~":
        return e.operand
    return Unary("~", e)


def has_call(e: Expr) -> bool:
    return any(isinstance(x, Call) for x in walk_expr(e))


def array_access(address: Expr) -> Optional[Index]:
    """
    `base + index` as Index(base, index), or None if `address` isn't of that
    shape. The nand2tetris compiler pushes the INDEX first and the array
    second, so the right operand is preferred as the base (this makes
    decompile -> recompile give identical VM code).
    """
    if isinstance(address, Binary) and address.op == "+":
        if isinstance(address.right, Var):
            return Index(address.right, address.left)
        if isinstance(address.left, Var):
            return Index(address.left, address.right)
    return None


class Engine:
    """Symbolic execution of one straight-line piece of code."""

    def __init__(self, out: List[Stmt]):
        self.out = out  # statements are appended here
        self.stack: List[Expr] = []
        # temp n -> (value, stack depth when stored). Kept until read with
        # `push temp n`; if never read, a call becomes a `do` statement.
        self.temps: Dict[int, Tuple[Expr, int]] = {}
        self.that: Optional[Expr] = None  # what `pop pointer 1` last stored

    # --- helpers ---------------------------------------------------------
    def pop(self, ins: Instr) -> Expr:
        if not self.stack:
            raise DecompileError("the stack is empty here (stack underflow)", ins)
        return self.stack.pop()

    def _require_empty_stack(self, ins: Optional[Instr], what: str) -> None:
        if self.stack:
            raise DecompileError(f"{len(self.stack)} value(s) left on the stack at {what} - not possible in Jack", ins)

    def _flush_temp(self, index: int, ins: Optional[Instr]) -> None:
        value, depth = self.temps.pop(index)
        if isinstance(value, Call):
            if depth:
                raise DecompileError("a call's result is thrown away while other values wait on the stack", ins)
            self.out.append(Do(value))
        elif has_call(value):
            raise DecompileError("an expression containing a call is thrown away - Jack's `do` needs a plain call", ins)
        # A pure expression stored and never read has no effect: drop it.

    def flush_temps(self, ins: Optional[Instr]) -> None:
        for index in sorted(self.temps):
            self._flush_temp(index, ins)

    def emit(self, stmt: Stmt, ins: Instr) -> None:
        self._require_empty_stack(ins, "a statement")
        self.flush_temps(ins)
        self.out.append(stmt)

    def finish(self, ins: Optional[Instr], what: str = "a jump or label") -> None:
        """End of a straight-line piece: everything must be settled."""
        self._require_empty_stack(ins, what)
        self.flush_temps(ins)
        self.that = None

    # --- one instruction -----------------------------------------------------
    def step(self, ins: Instr) -> None:
        op = ins.op
        if op == "push":
            self.stack.append(self._push_value(ins))
        elif op == "pop":
            self._pop(ins)
        elif op == "arith":
            if ins.arg1 in UNARY_SYMBOLS:
                self.stack.append(Unary(UNARY_SYMBOLS[ins.arg1], self.pop(ins)))
            else:
                right = self.pop(ins)
                left = self.pop(ins)
                self.stack.append(Binary(BINARY_SYMBOLS[ins.arg1], left, right))
        elif op == "call":
            self.stack.append(self._call(ins))
        elif op == "return":
            value = self.pop(ins)
            self.emit(Return(value), ins)
        else:  # label / goto / if-goto / function are handled by the structurer
            raise DecompileError(f"unexpected '{op}' inside straight-line code", ins)

    def _push_value(self, ins: Instr) -> Expr:
        segment, index = ins.arg1, ins.arg2
        if segment == "constant":
            return Const(index)
        if segment in VARIABLE_SEGMENTS:
            return Var(segment, index)
        if segment == "pointer":
            if index == 0:
                return This()
            if self.that is None:
                raise DecompileError("reads the THAT pointer before setting it", ins)
            return self.that
        if segment == "temp":
            if index not in self.temps:
                raise DecompileError(f"reads temp {index} before storing anything in it", ins)
            return self.temps.pop(index)[0]
        # segment == "that"
        address = self._that_address(ins)
        return array_access(address) or Call("Memory.peek", (address,))

    def _that_address(self, ins: Instr) -> Expr:
        if self.that is None:
            raise DecompileError("uses the 'that' segment without setting 'pointer 1' first", ins)
        return self.that if ins.arg2 == 0 else Binary("+", self.that, Const(ins.arg2))

    def _pop(self, ins: Instr) -> None:
        segment, index = ins.arg1, ins.arg2
        value = self.pop(ins)
        if segment in VARIABLE_SEGMENTS:
            self.emit(Let(Var(segment, index), value), ins)
        elif segment == "temp":
            if index in self.temps:
                self._flush_temp(index, ins)
            self.temps[index] = (value, len(self.stack))
        elif segment == "pointer":
            if index == 0:
                raise DecompileError("changes 'this' (pointer 0) in the middle of a subroutine", ins)
            self.that = value
        else:  # that
            address = self._that_address(ins)
            target = array_access(address)
            self.emit(Let(target, value) if target else Do(Call("Memory.poke", (address, value))), ins)

    def _call(self, ins: Instr) -> Expr:
        count = ins.arg2
        if count > len(self.stack):
            raise DecompileError(f"calls {ins.arg1} with {count} arguments but only {len(self.stack)} are on the stack", ins)
        args = tuple(self.stack[len(self.stack) - count:])
        del self.stack[len(self.stack) - count:]
        name = ins.arg1
        if name in ("Math.multiply", "Math.divide") and count == 2:
            return Binary("*" if name == "Math.multiply" else "/", args[0], args[1])
        if name == "String.new" and count == 1 and isinstance(args[0], Const):
            return StringLit(args[0].value)
        if (name == "String.appendChar" and count == 2 and isinstance(args[0], StringLit)
                and isinstance(args[1], Const) and len(args[0].chars) < args[0].capacity):
            return StringLit(args[0].capacity, args[0].chars + (args[1].value,))
        return Call(name, args)
