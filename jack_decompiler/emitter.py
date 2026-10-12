"""
emitter.py - Write the Jack source text.
========================================

Turns the analysed Program (AST + types + names) into one .jack file per
class. Two goals, in this order:

1. **Correct**: compiling the output with a nand2tetris-style Jack compiler
   gives back the same VM code (verify.py checks this). For example:
     * declarations keep the VM's order, because the order decides each
       variable's index (`field int x, y;` -> this 0, this 1);
     * `x.move()` is only used when x's declared type is the method's
       class; otherwise the always-correct `Ball.move(x)` form is used;
     * Jack has no operator precedence (a + b * c means (a + b) * c), so
       brackets are added wherever the tree needs them.
2. **Readable**: `true`/`false`/`null` instead of `~0`/`0` where the type
   says so, "string literals", `a * b` instead of Math.multiply(a, b), and
   brackets that make mixed operators obvious.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .infer import is_object_type
from .jack_ast import (
    Binary, Call, Comment, Const, Do, Expr, For, Break, Continue, If, Index, Let, Return, Stmt, StringLit, This, Unary, Var, While, walk_stmts, all_exprs,
)
from .model import ClassModel, Program, Subroutine

INDENT = "    "
HEADER_MARK = "Decompiled from"
TOOL_NAME = "jack-decompiler"
TOOL_URL = "https://github.com/kpillai2017/jack-decompiler"
CHAINS = ({"+", "-"}, {"*"}, {"&"}, {"|"})  # left-nested runs that read fine without brackets


def header(cls: ClassModel) -> List[str]:
    return [
        "/**",
        f" * {cls.name}.jack - {HEADER_MARK} {cls.file or cls.name + '.vm'} by {TOOL_NAME}",
        f" * ({TOOL_URL}).",
        " * Variable names and types are educated guesses based on how they are used.",
        " */",
    ]


class Emitter:
    def __init__(self, program: Program):
        self.program = program
        self.extended = False

    # --- names and types ---------------------------------------------------
    def var_name(self, sub: Subroutine, var: Var) -> str:
        if sub.kind == "method" and var.segment == "argument" and var.index == 0:
            return "this"
        key = sub.key(var)
        return self.program.names.get(key, f"{var.segment}{var.index}")

    def var_type(self, sub: Subroutine, var: Var) -> str:
        return self.program.types.get(sub.key(var), "int")

    def type_of(self, sub: Subroutine, e: Expr) -> Optional[str]:
        if isinstance(e, Var):
            return self.var_type(sub, e)
        if isinstance(e, This):
            return sub.class_name
        if isinstance(e, StringLit):
            return "String"
        if isinstance(e, Call):
            sig = self.program.signature(e.name)
            return sig.return_type if sig else None
        if isinstance(e, Binary) and e.op in "<>=":
            return "boolean"
        return None

    # --- expressions -----------------------------------------------------------
    def expr(self, sub: Subroutine, e: Expr, expect: Optional[str] = None) -> str:
        if isinstance(e, Const):
            if e.value == 0 and expect == "boolean":
                return "false"
            if e.value == 0 and is_object_type(expect):
                return "null"
            return str(e.value)
        if isinstance(e, Var):
            return self.var_name(sub, e)
        if isinstance(e, This):
            return "this"
        if isinstance(e, Unary):
            if e.op == "~" and e.operand == Const(0):
                return "~0" if expect in ("int", "char") else "true"
            inner_expect = "boolean" if e.op == "~" and expect == "boolean" else None
            return e.op + self.term(sub, e.operand, inner_expect)
        if isinstance(e, Binary):
            return self.binary(sub, e)
        if isinstance(e, Index):
            return f"{self.var_name(sub, e.base)}[{self.expr(sub, e.index)}]"
        if isinstance(e, StringLit):
            return self.string(sub, e)
        if isinstance(e, Call):
            return self.call(sub, e)
        raise TypeError(f"unknown expression {e!r}")

    def term(self, sub: Subroutine, e: Expr, expect: Optional[str] = None) -> str:
        """An operand that must be a single Jack 'term': bracket it if needed."""
        text = self.expr(sub, e, expect)
        return f"({text})" if self.needs_brackets(e) else text

    @staticmethod
    def needs_brackets(e: Expr) -> bool:
        if isinstance(e, Binary):
            return True
        if isinstance(e, Unary):  # but not for true or -5
            return not (e.op == "~" and e.operand == Const(0)) and not (e.op == "-" and isinstance(e.operand, Const))
        return False

    def binary(self, sub: Subroutine, e: Binary) -> str:
        left_expect = right_expect = None
        if e.op == "=":
            left_expect, right_expect = self.type_of(sub, e.right), self.type_of(sub, e.left)
        elif e.op in "&|":
            if "boolean" in (self.type_of(sub, e.left), self.type_of(sub, e.right)):
                left_expect = right_expect = "boolean"
        left = self.expr(sub, e.left, left_expect)
        if isinstance(e.left, Binary) and not any(e.left.op in c and e.op in c for c in CHAINS):
            left = f"({left})"
        elif isinstance(e.left, Unary) and self.needs_brackets(e.left):
            left = f"({left})"
        return f"{left} {e.op} {self.term(sub, e.right, right_expect)}"

    def string(self, sub: Subroutine, s: StringLit) -> str:
        if self.extended and len(s.chars) == s.capacity and all(0 <= c <= 32767 for c in s.chars):
            escapes = {0: r"\0", 8: r"\b", 9: r"\t", 10: r"\n", 12: r"\f", 13: r"\r", 34: r'\"', 92: r"\\"}
            return '"' + ''.join(escapes.get(c, chr(c)) for c in s.chars) + '"'
        text = s.literal()
        if text is not None:
            return '"' + text + '"'
        result = f"String.new({s.capacity})"  # built step by step - no deep recursion
        for c in s.chars:
            result = f"String.appendChar({result}, {c})"
        return result

    def call(self, sub: Subroutine, c: Call) -> str:
        program = self.program
        cls, _, function = program.display_name(c.name).partition(".")
        sig = program.signature(c.name)
        params = [t for t, _ in sig.params] if sig else []
        maybe_method = sig is None and program.is_external(c.name)  # unknown: method syntax if the type fits
        if (sig is not None and sig.kind == "method" or maybe_method) and c.args:
            receiver, rest = c.args[0], c.args[1:]
            if isinstance(receiver, This) and cls == sub.class_name:
                return f"{function}({self.args(sub, rest, params)})"
            if isinstance(receiver, Var) and self.var_name(sub, receiver) != "this" \
                    and self.var_type(sub, receiver) == c.name.split(".")[0]:
                return f"{self.var_name(sub, receiver)}.{function}({self.args(sub, rest, params)})"
            if sig is not None:
                params = [c.name.split(".")[0]] + params
        return f"{cls}.{function}({self.args(sub, c.args, params)})"

    def args(self, sub: Subroutine, args: Sequence[Expr], types: Sequence[str]) -> str:
        return ", ".join(self.expr(sub, a, types[i] if i < len(types) else None) for i, a in enumerate(args))

    # --- statements ------------------------------------------------------------
    def statements(self, sub: Subroutine, body: List[Stmt], depth: int) -> List[str]:
        pad = INDENT * depth
        lines: List[str] = []
        for s in body:
            if isinstance(s, Let):
                if isinstance(s.target, Var):
                    target, expect = self.var_name(sub, s.target), self.var_type(sub, s.target)
                else:
                    target, expect = self.expr(sub, s.target), None
                lines.append(f"{pad}let {target} {s.compound or '='} {self.expr(sub, s.value, expect)};")
            elif isinstance(s, Do):
                lines.append(f"{pad}do {self.call(sub, s.call)};")
            elif isinstance(s, If):
                lines.append(f"{pad}if ({self.expr(sub, s.cond, 'boolean')}) {{")
                lines += self.statements(sub, s.then, depth + 1)
                if s.otherwise is not None:
                    lines.append(f"{pad}}}")
                    lines.append(f"{pad}else {{")
                    lines += self.statements(sub, s.otherwise, depth + 1)
                lines.append(f"{pad}}}")
            elif isinstance(s, For):
                update = self.statements(sub, s.update, 0)
                if len(update) > 1 or (update and not update[0].startswith("let ")):
                    raise ValueError("for update must be a single assignment")
                update_text = update[0][:-1] if update else ""
                condition = self.expr(sub, s.cond, 'boolean') if s.has_condition else ""
                lines.append(f"{pad}for (; {condition}; {update_text}) {{")
                lines += self.statements(sub, s.body, depth + 1)
                lines.append(f"{pad}}}")
            elif isinstance(s, Break):
                lines.append(f"{pad}break;")
            elif isinstance(s, Continue):
                lines.append(f"{pad}continue;")
            elif isinstance(s, While):
                lines.append(f"{pad}while ({self.expr(sub, s.cond, 'boolean')}) {{")
                lines += self.statements(sub, s.body, depth + 1)
                lines.append(f"{pad}}}")
            elif isinstance(s, Return):
                if sub.return_type == "void" and s.value == Const(0):
                    lines.append(f"{pad}return;")
                else:
                    lines.append(f"{pad}return {self.expr(sub, s.value, sub.return_type)};")
            elif isinstance(s, Comment):
                lines += [f"{pad}// {line}".rstrip() for line in s.text.splitlines()]
        return lines

    # --- declarations ----------------------------------------------------------
    @staticmethod
    def grouped(keyword: str, pairs: List[Tuple[str, str]], pad: str) -> List[str]:
        """[("int","x"),("int","y"),("Ball","b")] -> 'field int x, y;' and 'field Ball b;' (order kept)."""
        lines: List[str] = []
        run: List[str] = []
        current = None
        for t, name in pairs + [("", "")]:
            if t != current and run:
                lines.append(f"{pad}{keyword} {current} {', '.join(run)};")
                run = []
            current = t
            run.append(name)
        return lines

    def subroutine(self, sub: Subroutine) -> List[str]:
        p = self.program
        params = ", ".join(f"{p.types.get(k, 'int')} {p.names.get(k, f'arg{k[2]}')}" for k in sub.param_keys())
        name = p.display_name(sub.full_name).split(".", 1)[1]
        lines = [f"{INDENT}{sub.kind} {sub.return_type} {name}({params}) {{"]
        locals_ = [(p.types.get(k, "int"), p.names.get(k, f"local{k[2]}")) for k in sub.local_keys()]
        lines += self.grouped("var", locals_, INDENT * 2)
        if sub.error is not None:
            lines += self.failed_body(sub)
        else:
            lines += self.statements(sub, sub.body, 2)
        lines.append(f"{INDENT}}}")
        return lines

    def failed_body(self, sub: Subroutine) -> List[str]:
        pad = INDENT * 2
        lines = [f"{pad}// {TOOL_NAME} could not turn this subroutine into Jack:",
                 f"{pad}//   {sub.error}",
                 f"{pad}// The original VM code is kept below so nothing is lost:"]
        lines += [f"{pad}//   {ins.text()}" for ins in sub.vm.body]
        if sub.return_type == "void":
            lines.append(f"{pad}return;")
        elif is_object_type(sub.return_type) and sub.kind != "constructor":
            lines.append(f"{pad}return null;")
        elif sub.kind == "constructor":
            lines.append(f"{pad}return this;")
        else:
            lines.append(f"{pad}return 0;")
        return lines

    def class_text(self, cls: ClassModel) -> str:
        p = self.program
        lines = header(cls)
        self.extended = any(isinstance(s, (For, Break, Continue)) or isinstance(s, Let) and s.compound
                            for sub in cls.subs for s in walk_stmts(sub.body))
        self.extended = self.extended or any(
            isinstance(e, StringLit) and len(e.chars) == e.capacity and e.literal() is None
            for sub in cls.subs for e in all_exprs(sub.body))
        if self.extended:
            lines.append("// Requires jackc --extensions (loop controls, compound updates, or escaped strings).")
        lines += [f"class {cls.name} {{"]
        statics = [(p.types.get(k, "int"), p.names.get(k, f"static{k[2]}")) for k in cls.static_keys()]
        fields = [(p.types.get(k, "int"), p.names.get(k, f"field{k[2]}")) for k in cls.field_keys()]
        declarations = self.grouped("static", statics, INDENT) + self.grouped("field", fields, INDENT)
        lines += declarations
        for sub in cls.subs:
            if declarations or sub is not cls.subs[0]:
                lines.append("")
            lines += self.subroutine(sub)
        lines.append("}")
        return "\n".join(lines) + "\n"
