"""engine.py / structure.py / emitter.py: VM code -> Jack statements."""

import pytest

from jack_decompiler import decompile_text
from jack_decompiler.engine import DecompileError, Engine
from jack_decompiler.structure import Structurer, detect_kind
from jack_decompiler.vm_reader import parse_vm

from .helpers import body_lines, jack_of


def fn(body: str, header: str = "function Main.main 0") -> str:
    return f"{header}\n{body.strip()}\n"


def test_arithmetic_and_brackets():
    jack = jack_of(fn("""
push constant 1
push constant 2
push constant 3
call Math.multiply 2
add
push constant 4
sub
pop static 0
push static 0
push constant 5
add
push constant 6
call Math.multiply 2
pop static 0
push constant 0
return"""))
    lines = body_lines(jack)
    assert "let static0 = 1 + (2 * 3) - 4;" in lines  # left-nested + - chains read fine
    assert "let static0 = (static0 + 5) * 6;" in lines  # Jack has no precedence: brackets needed
    assert "return;" in lines and "function void main() {" in lines


def test_true_false_negative_and_not():
    lines = body_lines(jack_of(fn("""
push constant 0
not
pop static 0
push constant 0
pop static 0
push constant 5
neg
pop static 1
push static 0
not
pop static 0
push constant 0
return""")))
    assert "let flag = true;" in lines or "let static0 = true;" in lines
    assert any(line.endswith("= false;") for line in lines)
    assert any(line.endswith("= -5;") for line in lines)
    assert any("~" in line for line in lines)


def test_string_literals_and_do_statements():
    lines = body_lines(jack_of(fn("""
push constant 2
call String.new 1
push constant 72
call String.appendChar 2
push constant 105
call String.appendChar 2
call Output.printString 1
pop temp 0
push constant 0
return""")))
    assert 'do Output.printString("Hi");' in lines


def test_unprintable_string_falls_back_to_calls():
    lines = body_lines(jack_of(fn("""
push constant 1
call String.new 1
push constant 34
call String.appendChar 2
call Output.printString 1
pop temp 0
push constant 0
return""")))
    assert "do Output.printString(String.appendChar(String.new(1), 34));" in lines


def test_array_read_and_write():
    lines = body_lines(jack_of(fn("""
push constant 3
push local 0
add
push constant 2
push local 0
add
pop pointer 1
push that 0
pop temp 0
pop pointer 1
push temp 0
pop that 0
push constant 0
return""", "function Main.main 1")))
    assert "var Array array;" in lines
    assert "let array[3] = array[2];" in lines


def test_unusual_that_access_uses_memory_peek_and_poke():
    lines = body_lines(jack_of(fn("""
push constant 100
pop pointer 1
push that 3
pop pointer 1
push constant 7
pop that 0
push constant 0
return""")))
    assert "do Memory.poke(Memory.peek(100 + 3), 7);" in lines


def test_if_else_nand2tetris_style():
    lines = body_lines(jack_of(fn("""
push argument 0
push constant 0
gt
if-goto IF_TRUE0
goto IF_FALSE0
label IF_TRUE0
push constant 1
return
goto IF_END0
label IF_FALSE0
push constant 2
return
label IF_END0""", "function Main.sign 0")))
    assert lines[1:] == ["function int sign(int arg0) {", "if (arg0 > 0) {", "return 1;", "}", "else {",
                         "return 2;", "}", "}", "}"]


def test_if_and_while_other_compiler_style():
    lines = body_lines(jack_of(fn("""
label L1
push local 0
push constant 10
lt
not
if-goto L2
push local 0
push constant 5
eq
not
if-goto L3
push constant 1
call Output.printInt 1
pop temp 0
label L3
push local 0
push constant 1
add
pop local 0
goto L1
label L2
push constant 0
return""", "function Main.main 1")))
    assert "while (i < 10) {" in lines
    assert "if (i = 5) {" in lines
    assert "let i = i + 1;" in lines


def test_while_true_when_there_is_no_condition():
    lines = body_lines(jack_of(fn("""
label TOP
call Main.tick 0
pop temp 0
goto TOP
function Main.tick 0
push constant 0
return""")))
    assert "while (true) {" in lines and "do Main.tick();" in lines


@pytest.mark.parametrize("body, message", [
    ("label X\npush constant 1\nif-goto X\npush constant 0\nreturn", "do-while"),
    ("goto END\nlabel END\npush constant 0\nreturn", "goto that isn't part of an if or a while"),
    ("push constant 1\npush constant 2\npop local 0\npop local 1\npush constant 0\nreturn", "left on the stack"),
    ("pop local 0\npush constant 0\nreturn", "stack underflow"),
    ("push temp 3\nreturn", "before storing"),
    ("push that 0\nreturn", "without setting 'pointer 1'"),
    ("push constant 1\npop pointer 0\npush constant 0\nreturn", "changes 'this'"),
    ("call A.f 3\nreturn", "only 0 are on the stack"),
    ("label A\nlabel B\npush constant 1\nif-goto A\ngoto B", "conditional jump backwards"),
])
def test_unsupported_code_raises(body, message):
    f = parse_vm(fn(body, "function Main.f 2"))[0]
    with pytest.raises(DecompileError, match=message):
        Structurer(f).run(0)


def test_failed_subroutine_keeps_vm_code_and_others_still_work():
    result = decompile_text("""function Main.bad 0
label X
push constant 1
if-goto X
push constant 0
return
function Main.good 0
push constant 0
return
""", "Main.vm")
    jack = result.classes["Main"].jack
    assert len(result.errors) == 1 and "Main.bad" in result.errors[0] and "Main.vm:4" in result.errors[0]
    assert "//   if-goto X" in jack
    assert "function void good() {" in jack
    assert "could not be decompiled" in result.summary()


def test_fields_in_a_function_are_rejected():
    result = decompile_text("function Main.f 0\npush this 0\nreturn\n", "Main.vm")
    assert "isn't a method or constructor" in result.errors[0]


def test_detect_kind():
    assert detect_kind(parse_vm("function A.new 0\npush constant 3\ncall Memory.alloc 1\npop pointer 0\n"
                                "push pointer 0\nreturn")[0].body) == ("constructor", 3, 3)
    assert detect_kind(parse_vm("function A.m 0\npush argument 0\npop pointer 0\npush constant 0\nreturn")[0].body)[0] \
        == "method"
    assert detect_kind(parse_vm("function A.f 0\npush constant 0\nreturn")[0].body)[0] == "function"


def test_engine_drops_unused_pure_temp_and_reports_side_effects():
    out = []
    e = Engine(out)
    for line in ("push constant 1", "pop temp 0"):
        e.step(parse_vm(f"function A.f 0\n{line}")[0].body[0])
    e.finish(None)
    assert out == []
    e = Engine(out)
    for line in ("push constant 1", "call A.g 0", "add", "pop temp 0"):
        e.step(parse_vm(f"function A.f 0\n{line}")[0].body[0])
    with pytest.raises(DecompileError, match="containing a call is thrown away"):
        e.finish(None)


def test_method_and_constructor_rendering(fixtures):
    from jack_decompiler import decompile_files

    result = decompile_files([fixtures / "square-game"])
    main = body_lines(result.classes["Main"].jack)
    assert "let squareGame = SquareGame.new();" in main
    assert "do squareGame.run();" in main
    square = body_lines(result.classes["Square"].jack)
    assert "constructor Square new(int aX, int aY, int aSize) {" in square
    assert "do draw();" in square and "return this;" in square
    assert "do Memory.deAlloc(this);" in square
