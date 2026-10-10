"""
compiler.py - A small Jack -> VM compiler, used to CHECK the decompiler.
========================================================================

If decompiling Foo.vm gives Foo.jack, then compiling Foo.jack should give
Foo.vm back. This module compiles Jack exactly the way the official
nand2tetris compiler does (same instruction patterns and label names), so
verify.py can compare the two instruction by instruction.

It's a classic recursive-descent compiler: the tokenizer splits the text
into tokens, and there is one method per grammar rule (class, subroutine,
statements, expression, term, ...). It reports the first syntax error with
its line number. It isn't meant to replace a full Jack compiler (it checks
less, e.g. it doesn't verify types).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

KEYWORDS = {
    "class", "constructor", "function", "method", "field", "static", "var", "int", "char", "boolean",
    "void", "true", "false", "null", "this", "let", "do", "if", "else", "while", "return",
}
SYMBOLS = set("{}()[].,;+-*/&|<>=~")
OPS = {"+": "add", "-": "sub", "&": "and", "|": "or", "<": "lt", ">": "gt", "=": "eq"}
TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|(\d+)|"([^"\n]*)"|([A-Za-z_]\w*)|(\S)', re.DOTALL)


class JackSyntaxError(Exception):
    def __init__(self, message: str, line: int, file: str = ""):
        self.line = line
        super().__init__(f"{file or '<jack>'}:{line}: {message}")


@dataclass
class Token:
    kind: str  # "int", "string", "keyword", "identifier", "symbol"
    value: str
    line: int


def tokenize(text: str, file: str = "") -> List[Token]:
    tokens: List[Token] = []
    line = 1
    pos = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if m is None or (text.startswith("/*", pos) and not m.group(0).endswith("*/")):  # e.g. an unterminated /* comment or string
            raise JackSyntaxError("unterminated comment or string", line, file)
        number, string, word, symbol = m.groups()
        if number is not None:
            if int(number) > 32767:
                raise JackSyntaxError(f"integer {number} is too big (0..32767)", line, file)
            tokens.append(Token("int", number, line))
        elif string is not None:
            tokens.append(Token("string", string, line))
        elif word is not None:
            tokens.append(Token("keyword" if word in KEYWORDS else "identifier", word, line))
        elif symbol is not None:
            if symbol not in SYMBOLS:
                raise JackSyntaxError(f"unexpected character {symbol!r}", line, file)
            tokens.append(Token("symbol", symbol, line))
        line += m.group(0).count("\n")
        pos = m.end()
    return tokens


class Compiler:
    def __init__(self, text: str, file: str = ""):
        self.file = file
        self.tokens = tokenize(text, file)
        self.pos = 0
        self.out: List[str] = []
        self.class_name = ""
        self.class_vars: Dict[str, Tuple[str, str, int]] = {}  # name -> (segment, type, index)
        self.sub_vars: Dict[str, Tuple[str, str, int]] = {}
        self.counts: Dict[str, int] = {}
        self.if_count = self.while_count = 0

    # --- token helpers --------------------------------------------------------
    def peek(self, offset: int = 0) -> Optional[Token]:
        i = self.pos + offset
        return self.tokens[i] if i < len(self.tokens) else None

    def error(self, message: str) -> JackSyntaxError:
        token = self.peek()
        line = token.line if token else (self.tokens[-1].line if self.tokens else 1)
        found = f" (found {token.value!r})" if token else " (found the end of the file)"
        return JackSyntaxError(message + found, line, self.file)

    def at(self, *values: str) -> bool:
        token = self.peek()
        return token is not None and token.kind in ("keyword", "symbol") and token.value in values

    def expect(self, *values: str) -> str:
        if not self.at(*values):
            raise self.error(f"expected {' or '.join(repr(v) for v in values)}")
        self.pos += 1
        return self.tokens[self.pos - 1].value

    def identifier(self) -> str:
        token = self.peek()
        if token is None or token.kind != "identifier":
            raise self.error("expected a name")
        self.pos += 1
        return token.value

    def type_name(self, allow_void: bool = False) -> str:
        if self.at("int", "char", "boolean") or (allow_void and self.at("void")):
            return self.expect("int", "char", "boolean", "void")
        return self.identifier()

    def emit(self, line: str) -> None:
        self.out.append(line)

    # --- symbol table ----------------------------------------------------------
    def define(self, table: Dict, segment: str, type_: str, name: str) -> None:
        if name in table:
            raise self.error(f"{name!r} is declared twice")
        index = self.counts.get(segment, 0)
        table[name] = (segment, type_, index)
        self.counts[segment] = index + 1

    def lookup(self, name: str) -> Optional[Tuple[str, str, int]]:
        return self.sub_vars.get(name) or self.class_vars.get(name)

    # --- grammar ----------------------------------------------------------------
    def compile_class(self) -> str:
        self.expect("class")
        self.class_name = self.identifier()
        self.expect("{")
        while self.at("static", "field"):
            kind = self.expect("static", "field")
            segment = "static" if kind == "static" else "this"
            type_ = self.type_name()
            self.define(self.class_vars, segment, type_, self.identifier())
            while self.at(","):
                self.expect(",")
                self.define(self.class_vars, segment, type_, self.identifier())
            self.expect(";")
        n_fields = self.counts.get("this", 0)
        while self.at("constructor", "function", "method"):
            self.subroutine(n_fields)
        self.expect("}")
        if self.peek() is not None:
            raise self.error("unexpected text after the end of the class")
        return "\n".join(self.out) + "\n"

    def subroutine(self, n_fields: int) -> None:
        kind = self.expect("constructor", "function", "method")
        self.type_name(allow_void=True)
        name = self.identifier()
        self.sub_vars = {}
        self.counts = {k: v for k, v in self.counts.items() if k in ("static", "this")}
        self.if_count = self.while_count = 0
        if kind == "method":
            self.define(self.sub_vars, "argument", self.class_name, "this")
        self.expect("(")
        if not self.at(")"):
            while True:
                type_ = self.type_name()
                self.define(self.sub_vars, "argument", type_, self.identifier())
                if not self.at(","):
                    break
                self.expect(",")
        self.expect(")")
        self.expect("{")
        while self.at("var"):
            self.expect("var")
            type_ = self.type_name()
            self.define(self.sub_vars, "local", type_, self.identifier())
            while self.at(","):
                self.expect(",")
                self.define(self.sub_vars, "local", type_, self.identifier())
            self.expect(";")
        self.emit(f"function {self.class_name}.{name} {self.counts.get('local', 0)}")
        if kind == "constructor":
            self.emit(f"push constant {n_fields}")
            self.emit("call Memory.alloc 1")
            self.emit("pop pointer 0")
        elif kind == "method":
            self.emit("push argument 0")
            self.emit("pop pointer 0")
        self.statements()
        self.expect("}")

    def statements(self) -> None:
        while self.at("let", "do", "if", "while", "return"):
            getattr(self, "st_" + self.peek().value)()

    def st_let(self) -> None:
        self.expect("let")
        name = self.identifier()
        var = self.lookup(name)
        if var is None:
            raise self.error(f"{name!r} is not declared")
        if self.at("["):
            self.expect("[")
            self.expression()
            self.expect("]")
            self.emit(f"push {var[0]} {var[2]}")
            self.emit("add")
            self.expect("=")
            self.expression()
            self.expect(";")
            self.emit("pop temp 0")
            self.emit("pop pointer 1")
            self.emit("push temp 0")
            self.emit("pop that 0")
            return
        self.expect("=")
        self.expression()
        self.expect(";")
        self.emit(f"pop {var[0]} {var[2]}")

    def st_do(self) -> None:
        self.expect("do")
        self.call(self.identifier())
        self.expect(";")
        self.emit("pop temp 0")

    def st_return(self) -> None:
        self.expect("return")
        if self.at(";"):
            self.emit("push constant 0")
        else:
            self.expression()
        self.expect(";")
        self.emit("return")

    def st_if(self) -> None:
        n = self.if_count
        self.if_count += 1
        self.expect("if")
        self.expect("(")
        self.expression()
        self.expect(")")
        self.emit(f"if-goto IF_TRUE{n}")
        self.emit(f"goto IF_FALSE{n}")
        self.emit(f"label IF_TRUE{n}")
        self.expect("{")
        self.statements()
        self.expect("}")
        if self.at("else"):
            self.expect("else")
            self.emit(f"goto IF_END{n}")
            self.emit(f"label IF_FALSE{n}")
            self.expect("{")
            self.statements()
            self.expect("}")
            self.emit(f"label IF_END{n}")
        else:
            self.emit(f"label IF_FALSE{n}")

    def st_while(self) -> None:
        n = self.while_count
        self.while_count += 1
        self.expect("while")
        self.emit(f"label WHILE_EXP{n}")
        self.expect("(")
        self.expression()
        self.expect(")")
        self.emit("not")
        self.emit(f"if-goto WHILE_END{n}")
        self.expect("{")
        self.statements()
        self.expect("}")
        self.emit(f"goto WHILE_EXP{n}")
        self.emit(f"label WHILE_END{n}")

    def expression(self) -> None:
        self.term()
        while self.at(*"+-*/&|<>="):
            op = self.expect(*"+-*/&|<>=")
            self.term()
            if op == "*":
                self.emit("call Math.multiply 2")
            elif op == "/":
                self.emit("call Math.divide 2")
            else:
                self.emit(OPS[op])

    def term(self) -> None:
        token = self.peek()
        if token is None:
            raise self.error("expected an expression")
        if token.kind == "int":
            self.pos += 1
            self.emit(f"push constant {token.value}")
        elif token.kind == "string":
            self.pos += 1
            self.emit(f"push constant {len(token.value)}")
            self.emit("call String.new 1")
            for c in token.value:
                self.emit(f"push constant {ord(c)}")
                self.emit("call String.appendChar 2")
        elif self.at("true"):
            self.pos += 1
            self.emit("push constant 0")
            self.emit("not")
        elif self.at("false", "null"):
            self.pos += 1
            self.emit("push constant 0")
        elif self.at("this"):
            self.pos += 1
            self.emit("push pointer 0")
        elif self.at("("):
            self.expect("(")
            self.expression()
            self.expect(")")
        elif self.at("-", "~"):
            op = self.expect("-", "~")
            self.term()
            self.emit("neg" if op == "-" else "not")
        elif token.kind == "identifier":
            name = self.identifier()
            if self.at("["):
                var = self.variable(name)
                self.expect("[")
                self.expression()
                self.expect("]")
                self.emit(f"push {var[0]} {var[2]}")
                self.emit("add")
                self.emit("pop pointer 1")
                self.emit("push that 0")
            elif self.at("(", "."):
                self.call(name)
            else:
                var = self.variable(name)
                self.emit(f"push {var[0]} {var[2]}")
        else:
            raise self.error("expected an expression")

    def variable(self, name: str) -> Tuple[str, str, int]:
        var = self.lookup(name)
        if var is None:
            self.pos -= 1
            raise self.error(f"{name!r} is not declared")
        return var

    def call(self, name: str) -> None:
        n_args = 0
        if self.at("."):
            self.expect(".")
            function = self.identifier()
            var = self.lookup(name)
            if var is not None:  # obj.method(...)
                self.emit(f"push {var[0]} {var[2]}")
                target, n_args = f"{var[1]}.{function}", 1
            else:  # Class.function(...)
                target = f"{name}.{function}"
        else:  # method(...) on this object
            self.emit("push pointer 0")
            target, n_args = f"{self.class_name}.{name}", 1
        self.expect("(")
        if not self.at(")"):
            while True:
                self.expression()
                n_args += 1
                if not self.at(","):
                    break
                self.expect(",")
        self.expect(")")
        self.emit(f"call {target} {n_args}")


def compile_jack(text: str, file: str = "") -> str:
    """Compile one Jack class to VM text. Raises JackSyntaxError."""
    return Compiler(text, file).compile_class()
