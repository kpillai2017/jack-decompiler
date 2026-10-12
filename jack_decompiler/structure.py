"""
structure.py - Turn the jumps of a VM function back into if / while.
=====================================================================

Standard Jack has two kinds of control flow: `if (...) {...} else {...}` and
`while (...) {...}`. Extended Jack also has for/break/continue, recovered below.
Jack compilers turn these constructs into labels and jumps. The
nand2tetris compiler, for example, produces:

    if (c) { A } else { B }          while (c) { A }
    -----------------------          ---------------
        <c>                          label WHILE_EXP0
        if-goto IF_TRUE0                 <c>
        goto IF_FALSE0                   not
    label IF_TRUE0                       if-goto WHILE_END0
        <A>                              <A>
        goto IF_END0                     goto WHILE_EXP0
    label IF_FALSE0                  label WHILE_END0
        <B>
    label IF_END0

Standard if/while recovery looks at the SHAPE of jumps, not their label names.
The companion for-loop update pattern additionally uses its FOR$ label convention.
Code from standard Jack compilers works too:

  * A label that a later `goto` jumps back to starts a loop. If the loop
    begins with a condition that jumps past the end, it's `while (cond)`;
    otherwise it's `while (true)`.
  * A forward `if-goto` starts an if. Both "if-goto THEN; goto ELSE" and
    "not; if-goto ELSE" are understood. If the then-part ends with a jump
    over more code, that code is the else-part.

Any jump that doesn't fit these shapes (e.g. a jump into the middle of a
loop) can't be written in Jack, and raises DecompileError.

Subroutine kinds come from the first instructions ("prologue"):

    push constant N; call Memory.alloc 1; pop pointer 0  -> constructor (N fields)
    push argument 0; pop pointer 0                       -> method
    anything else                                        -> function
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .engine import DecompileError, Engine, negate
from .jack_ast import Const, Stmt, Unary, While, For, Break, Continue, Let, If, Expr
from .vm_reader import Instr, VMFunction


def detect_kind(body: List[Instr]) -> Tuple[str, int, int]:
    """(kind, number of fields for constructors, index of the first real instruction)."""
    sig = [(i.op, i.arg1, i.arg2) for i in body[:3]]
    if len(sig) >= 3 and sig[0][:2] == ("push", "constant") and sig[1] == ("call", "Memory.alloc", 1) \
            and sig[2] == ("pop", "pointer", 0):
        return "constructor", sig[0][2], 3
    if len(sig) >= 2 and sig[0] == ("push", "argument", 0) and sig[1] == ("pop", "pointer", 0):
        return "method", 0, 2
    return "function", 0, 0


class Structurer:
    def __init__(self, function: VMFunction, base_first: Optional[bool] = None):
        self.function = function
        self.code = function.body
        self.base_first = (any(ins.op == "label" and "$" in ins.arg1 for ins in self.code)
                           if base_first is None else base_first)
        self.labels: Dict[str, int] = {}
        self.jumps_to: Dict[str, List[int]] = {}
        self.loops = []  # innermost (break label, continue label)
        for index, ins in enumerate(self.code):
            if ins.op == "label":
                self.labels[ins.arg1] = index
            elif ins.op in ("goto", "if-goto"):
                self.jumps_to.setdefault(ins.arg1, []).append(index)

    def run(self, start: int) -> List[Stmt]:
        return self.block(start, len(self.code))

    # ------------------------------------------------------------------
    def block(self, lo: int, hi: int) -> List[Stmt]:
        """Statements for the instructions code[lo:hi]."""
        out: List[Stmt] = []
        engine = Engine(out, base_first=self.base_first)
        i = lo
        while i < hi:
            ins = self.code[i]
            if ins.op == "label":
                engine.finish(ins)
                back = [j for j in self.jumps_to.get(ins.arg1, []) if i < j < hi]
                if back:
                    loop, i = self.loop(i, back)
                    out.append(loop)
                else:
                    i += 1  # just a place where branches join
            elif ins.op == "if-goto":
                cond = engine.pop(ins)
                engine.finish(ins, "an if")
                statement, i = self.conditional(i, cond, hi)
                out.append(statement)
            elif ins.op == "goto":
                engine.finish(ins)
                if self.loops and ins.arg1 == self.loops[-1][0]:
                    out.append(Break())
                elif self.loops and ins.arg1 == self.loops[-1][1]:
                    out.append(Continue())
                else:
                    raise DecompileError("a goto that isn't part of an if or a while/for loop", ins)
                i += 1
            elif ins.op == "function":
                raise DecompileError("unexpected 'function' inside a function", ins)
            else:
                engine.step(ins)
                i += 1
        engine.finish(self.code[hi - 1] if hi > lo else None, "the end of a block")
        return out

    # ------------------------------------------------------------------
    def loop(self, start: int, back: List[int]) -> Tuple[While, int]:
        """A loop whose header label is at `start`; `back` = jumps back to it."""
        header = self.code[start]
        for j in back:
            if self.code[j].op == "if-goto":
                raise DecompileError("a conditional jump backwards (a do-while loop can't be written in Jack)",
                                     self.code[j])
        end = max(back)  # final unconditional back edge closes the loop
        found = self.scan_condition(start + 1, end)
        cond, body_start = Unary("~", Const(0)), start + 1
        exit_label = None
        has_condition = False
        if found is not None:
            test, k = found
            exit_at = self.labels[self.code[k].arg1]
            if exit_at > end and all(self.code[x].op == "label" for x in range(end + 1, exit_at)):
                cond, body_start = negate(test), k + 1
                exit_label = self.code[k].arg1
                has_condition = True
        if exit_label is None and end + 1 < len(self.code) and self.code[end + 1].op == "label":
            exit_label = self.code[end + 1].arg1
        # The companion compiler emits a separate update marker even when the
        # update is empty. Validate its position; ordinary loops stay label-agnostic.
        updates = [x for x in range(body_start, end) if self.code[x].op == "label"
                   and self.code[x].arg1.startswith("FORUPDATE$")]
        update_at = updates[-1] if header.arg1.startswith("FOR$") and updates else None
        continue_label = self.code[update_at].arg1 if update_at is not None else header.arg1
        self.loops.append((exit_label, continue_label))
        try:
            body = self.block(body_start, update_at if update_at is not None else end)
            update = self.block(update_at + 1, end) if update_at is not None else []
        finally:
            self.loops.pop()
        if update_at is not None:
            if len(update) > 1 or (update and not isinstance(update[0], Let)):
                raise DecompileError("for update is not a single assignment", self.code[update_at])
            return For(cond, body, update, has_condition), end + 1
        return While(cond, body), end + 1

    def scan_condition(self, lo: int, hi: int) -> Optional[Tuple[Expr, int]]:
        """If code[lo:] is just an expression followed by an if-goto, return (expression, index of if-goto)."""
        out: List[Stmt] = []
        engine = Engine(out, base_first=self.base_first)
        for k in range(lo, hi):
            ins = self.code[k]
            if ins.op == "if-goto":
                if not out and not engine.temps and len(engine.stack) == 1:
                    return engine.stack[0], k
                return None
            if ins.op in ("label", "goto", "function", "return"):
                return None
            try:
                engine.step(ins)
            except DecompileError:
                return None
            if out:
                return None
        return None

    # ------------------------------------------------------------------
    def conditional(self, i: int, cond: Expr, hi: int) -> Tuple[If, int]:
        """An if-goto at code[i] (its condition already popped)."""
        ins = self.code[i]
        target = self.labels[ins.arg1]
        if target <= i:
            raise DecompileError("a conditional jump backwards (can't be written in Jack)", ins)
        nxt = self.code[i + 1] if i + 1 < hi else None
        after = self.code[i + 2] if i + 2 < hi else None
        if nxt is not None and nxt.op == "goto" and after is not None and after.op == "label" \
                and after.arg1 == ins.arg1:
            # if-goto THEN; goto ELSE; label THEN   (nand2tetris style)
            false_label, then_lo, condition = nxt.arg1, i + 3, cond
        else:
            # if-goto ELSE   (jump over the then-part when the condition is false)
            false_label, then_lo, condition = ins.arg1, i + 1, negate(cond)
        p = self.labels[false_label]
        if not then_lo <= p < hi:
            raise DecompileError(f"the if's jump to {false_label} leaves the surrounding block", ins)
        if p - 1 >= then_lo and self.code[p - 1].op == "goto":
            end_label = self.code[p - 1].arg1
            q = self.labels[end_label]
            if p < q < hi:
                then = self.block(then_lo, p - 1)
                otherwise = self.block(p + 1, q)
                return If(condition, then, otherwise), q
        return If(condition, self.block(then_lo, p), None), p
