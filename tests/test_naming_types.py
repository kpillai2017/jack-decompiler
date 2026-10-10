"""infer.py and naming.py: types and descriptive names."""

from jack_decompiler import decompile_files, decompile_text
from jack_decompiler.compiler import compile_jack
from jack_decompiler.naming import lower_first, name_for_result, plural, strip_verb

from .helpers import body_lines


def decompile_jack(source: str, cls: str):
    """Compile Jack (names are lost), decompile, and return the result."""
    return decompile_text(compile_jack(source), f"{cls}.vm")


def test_helpers():
    assert lower_first("PongGame") == "pongGame" and lower_first("ABC") == "abc"
    assert plural("alien") == "aliens" and plural("box") == "boxes" and plural("enemy") == "enemies"
    assert strip_verb("getScore") == "Score" and strip_verb("isDone") == "isDone" and strip_verb("draw") is None
    assert name_for_result("Keyboard.keyPressed") == "key"
    assert name_for_result("Ball.new") == "ball"
    assert name_for_result("Util.mod") == "mod"
    assert name_for_result("Game.drawBoard") is None


def test_getters_setters_and_constructor_parameters():
    result = decompile_jack("""
class Counter {
    field int a, b;
    constructor Counter new(int p, int q) { let a = p; let b = q; return this; }
    method int getTotal() { return a; }
    method void setStep(int z) { let b = z; return; }
}""", "Counter")
    lines = body_lines(result.classes["Counter"].jack)
    assert "field int total, step;" in lines
    assert "constructor Counter new(int aTotal, int aStep) {" in lines
    assert "method void setStep(int newStep) {" in lines


def test_types_from_method_calls_arrays_and_booleans():
    result = decompile_jack("""
class Main {
    function void main() {
        var Ball b; var Array list; var boolean over; var int n;
        let b = Ball.new();
        let list = Array.new(3);
        let over = false;
        while (~over) {
            do b.bounce();
            let list[n] = n;
            let n = n + 1;
            let over = n > 2;
        }
        return;
    }
}""", "Main")
    lines = body_lines(result.classes["Main"].jack)
    assert "var Ball ball;" in lines
    assert "var Array array;" in lines
    assert "var boolean done;" in lines
    assert "while (~done) {" in lines
    assert "do ball.bounce();" in lines  # method syntax because ball's type is known


def test_loop_counters_and_sum():
    result = decompile_jack("""
class Main {
    function int total(Array a, int count) {
        var int x, y, s;
        let x = 0;
        while (x < count) {
            let y = 0;
            while (y < count) { let s = s + a[y]; let y = y + 1; }
            let x = x + 1;
        }
        return s;
    }
}""", "Main")
    lines = body_lines(result.classes["Main"].jack)
    assert "var int i, j, sum;" in lines
    assert "function int total(Array array, int arg1) {" in lines


def test_void_detection():
    result = decompile_jack("""
class Main {
    function Main make() { return null; }
    function int zero() { return 0; }
    function void main() { var int x; let x = Main.zero(); do Main.make(); return; }
}""", "Main")
    lines = body_lines(result.classes["Main"].jack)
    assert "function void make() {" in lines  # only `do Main.make();`: the result is never used
    assert "function int zero() {" in lines and "return 0;" in lines  # zero()'s result IS used


def test_names_are_unique_and_never_keywords_or_class_names():
    result = decompile_jack("""
class Main {
    function void main() {
        var Main a; var Main b; var int c;
        let a = Main.new(); let b = Main.new();
        return;
    }
    constructor Main new() { return this; }
}""", "Main")
    lines = body_lines(result.classes["Main"].jack)
    assert "var Main main, main2;" in lines


def test_generic_function_names_are_renamed():
    vm = compile_jack("""
class Box {
    field int size;
    constructor Box f0() { let size = 1; return this; }
    method int f1() { return size; }
    method void incSize() { let size = size + 1; return; }
    method void f2() { do Memory.deAlloc(this); return; }
    function void main() { var Box b; let b = Box.f0(); do Output.printInt(b.f1()); do b.f2(); return; }
}""")
    result = decompile_text(vm, "Box.vm")
    lines = body_lines(result.classes["Box"].jack)
    assert "constructor Box new() {" in lines
    assert "method int getSize() {" in lines
    assert "method void dispose() {" in lines
    assert "do Output.printInt(box.getSize());" in lines
    kept = body_lines(decompile_text(vm, "Box.vm", rename_functions=False).classes["Box"].jack)
    assert "method int f1() {" in kept


def test_pong_names(fixtures):
    result = decompile_files([fixtures / "pong"])
    bat = body_lines(result.classes["Bat"].jack)
    assert "field int left, y, width, height, direction;" in bat
    assert "constructor Bat new(int aLeft, int aY, int aWidth, int aHeight) {" in bat
    game = result.classes["PongGame"].jack
    assert "bat.setDirection(" in game and "ball.move()" in game
