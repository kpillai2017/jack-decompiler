"""
model.py - What the decompiler knows about the whole program.
=============================================================

    Program
     +-- ClassModel "Ball"    (fields, statics, file name)
     |    +-- Subroutine "Ball.new"   (kind, parameters, body = Jack AST)
     |    +-- Subroutine "Ball.move"
     +-- ...

Variables are identified by a *key*, a tuple that is the same wherever the
variable is used:

    ("local",    "Ball.move", 2)   local 2 of Ball.move
    ("argument", "Ball.move", 1)   argument 1 (for methods, 0 is `this`)
    ("this",     "Ball", 0)        field 0 of class Ball
    ("static",   "Ball", 3)        static 3 of class Ball
    ("return",   "Ball.move", 0)   (only for types) what Ball.move returns

infer.py fills in `types` and naming.py fills in `names` for these keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .jack_ast import Call, Stmt, Var, all_exprs
from .os_api import OS_API, OS_CLASSES, Signature
from .vm_reader import VMFunction

Key = Tuple[str, str, int]


@dataclass
class Subroutine:
    vm: VMFunction
    kind: str = "function"
    n_fields: int = 0  # constructors: the size passed to Memory.alloc
    body: List[Stmt] = field(default_factory=list)
    error: Optional[str] = None  # why it couldn't be decompiled (None = fine)
    n_args: int = 0  # VM arguments, INCLUDING `this` for methods
    return_type: str = "void"

    @property
    def full_name(self) -> str:
        return self.vm.name

    @property
    def class_name(self) -> str:
        return self.vm.class_name

    @property
    def name(self) -> str:
        return self.vm.short_name

    @property
    def first_param(self) -> int:
        """VM index of the first Jack parameter (1 for methods: 0 is `this`)."""
        return 1 if self.kind == "method" else 0

    @property
    def n_params(self) -> int:
        return max(0, self.n_args - self.first_param)

    def key(self, var: Var) -> Key:
        if var.segment in ("local", "argument"):
            return (var.segment, self.full_name, var.index)
        return (var.segment, self.class_name, var.index)

    def param_keys(self) -> List[Key]:
        return [("argument", self.full_name, i) for i in range(self.first_param, self.n_args)]

    def local_keys(self) -> List[Key]:
        return [("local", self.full_name, i) for i in range(self.vm.n_locals)]


@dataclass
class ClassModel:
    name: str
    file: str
    subs: List[Subroutine] = field(default_factory=list)
    n_fields: int = 0
    n_statics: int = 0

    def field_keys(self) -> List[Key]:
        return [("this", self.name, i) for i in range(self.n_fields)]

    def static_keys(self) -> List[Key]:
        return [("static", self.name, i) for i in range(self.n_statics)]


@dataclass
class Program:
    classes: Dict[str, ClassModel] = field(default_factory=dict)
    subs: Dict[str, Subroutine] = field(default_factory=dict)
    types: Dict[Key, str] = field(default_factory=dict)
    names: Dict[Key, str] = field(default_factory=dict)
    renames: Dict[str, str] = field(default_factory=dict)  # "A.f1" -> "A.getX"
    warnings: List[str] = field(default_factory=list)
    result_used: set = field(default_factory=set)  # subroutines whose return value is used somewhere

    # --- what we know about any subroutine that may be called --------------
    def signature(self, name: str) -> Optional[Signature]:
        sub = self.subs.get(name)
        if sub is not None:
            params = tuple((self.types.get(k, "int"), self.names.get(k, f"arg{k[2]}")) for k in sub.param_keys())
            return Signature(sub.kind, sub.return_type, params)
        if name in OS_API:
            return OS_API[name]
        cls, _, function = name.partition(".")
        if function == "new":  # a class from outside the program: assume the usual constructor
            return Signature("constructor", cls, ())
        return None

    def is_external(self, name: str) -> bool:
        """Neither in the program nor in the Jack OS: we know nothing about it."""
        return name not in self.subs and name not in OS_API

    def kind_of(self, name: str) -> str:
        sig = self.signature(name)
        return sig.kind if sig else "function"

    def class_names(self) -> set:
        """Every class name the program defines or calls."""
        names = set(self.classes)
        for sub in self.subs.values():
            names.update(e.name.split(".")[0] for e in all_exprs(sub.body) if isinstance(e, Call))
        return names | set(OS_CLASSES)

    def display_name(self, full: str) -> str:
        """Function name after any renaming (see naming.rename_generic_functions)."""
        return self.renames.get(full, full)
