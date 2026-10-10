"""
test_naming_rules.py - the naming rules that look at how variables are used.
============================================================================

Each test compiles some Jack (which throws every variable name away),
decompiles it, and checks the names the decompiler came up with.
"""

from pathlib import Path

from jack_decompiler import decompile_files
from jack_decompiler.compiler import compile_jack
from jack_decompiler.naming import partners

from .helpers import body_lines


def decompile_classes(tmp_path: Path, **sources: str) -> dict:
    """Compile each class to tmp_path/<Class>.vm, decompile them together: {class: body lines}."""
    for name, source in sources.items():
        (tmp_path / f"{name}.vm").write_text(compile_jack(source, f"{name}.jack"))
    result = decompile_files(sorted(tmp_path.glob("*.vm")))
    return {name: body_lines(cls.jack) for name, cls in result.classes.items()}


def test_partners_pair_up_coordinates_but_not_ordinary_words():
    assert partners("x") == ["y", ""] and partners("y") == ["", "x"]
    assert partners("x1") == ["y1", ""] and partners("startX") == ["startY", ""] and partners("maxY") == ["", "maxX"]
    assert partners("width") == ["height", ""] and partners("top") == ["", "left"] and partners("end") == ["", "start"]
    for word in ("index", "fox", "box", "X", "key"):
        assert partners(word) == ["", ""]


BALL = """
class Ball {
    field int a, b, c, d;
    constructor Ball new(int p, int q, int r) {
        let a = p; let b = q; let c = r - 6; let d = 0;
        return this;
    }
    method int getX() { return a; }
    method void move() {
        let a = a + 1;
        if (~(a > b)) { let d = 1; let a = b; }
        if (a > c) { let d = 2; let a = c; }
        return;
    }
}
"""


def test_limits_are_named_after_what_they_limit(tmp_path):
    lines = decompile_classes(tmp_path, Ball=BALL)["Ball"]
    # if (~(x > k)) { let x = k; }  /  if (x > k) ...   (and d isn't guessed to be maxY: fields aren't paired up)
    assert "field int x, minX, maxX, field3;" in lines
    # constructor parameters follow their fields - even `let maxX = r - 6`
    assert "constructor Ball new(int aX, int aMinX, int aMaxX) {" in lines


def test_field_and_constructor_parameter_names_are_stable_pairs(tmp_path):
    """A sure parameter name (here the OS's own String.new(maxLength)) and its field: maxLength + aMaxLength."""
    string = """
class String {
    field int f; field Array a;
    constructor String new(int n) { let a = Array.new(n); let f = n; return this; }
}
"""
    lines = decompile_classes(tmp_path, String=string)["String"]
    assert "field int maxLength;" in lines and "constructor String new(int aMaxLength) {" in lines


def test_parameters_are_named_after_the_calls_passed_to_them(tmp_path):
    main = """
class Main {
    function void main() {
        var Ball b;
        let b = Ball.new(1, 2, 3);
        do Main.hit(b.getX(), 7);
        do Main.hit(b.getX(), 8);
        do Main.make(Main.getSQUID());
        do Main.make(Main.getCRAB());
        return;
    }
    function void hit(int p, int q) { do Output.printInt(p + q); return; }
    function void make(int kind) { do Output.printInt(kind); return; }
    function int getSQUID() { return 1; }
    function int getCRAB() { return 2; }
}
"""
    lines = decompile_classes(tmp_path, Ball=BALL, Main=main)["Main"]
    # p is always given getX()'s result, and q sits next to x: y
    assert "function void hit(int x, int y) {" in lines
    # constants such as getSQUID() / getCRAB() are values, not what the parameter is for
    # (so the name comes from Output.printInt(number) instead)
    assert "function void make(int number) {" in lines


def test_partner_guesses_never_get_a_number(tmp_path):
    main = """
class Main {
    static int s;
    function void main() { do Main.hit(Main.getX(), 2); return; }
    function int getX() { return s; }
    function int getY() { return 4; }
    function void hit(int p, int q) { var int y; let y = Main.getY(); do Output.printInt(p + q + y); return; }
}
"""
    lines = decompile_classes(tmp_path, Main=main)["Main"]
    assert "static int x;" in lines  # getX(): x (X would look like a constant)
    assert "function void hit(int x2, int arg1) {" in lines  # not y2: y is the local's name
    assert "var int y;" in lines


def test_common_idioms(tmp_path):
    main = """
class Main {
    static Array s;
    function void init() { let s = 16384; let s[0] = 0; return; }
    function void plot(int p, int q) {
        var int a;
        let a = 16384 + (32 * q) + (p / 16);
        do Memory.poke(a, 1);
        return;
    }
    function int value(String t) {
        var int i, n, d;
        let i = 0;
        while (i < t.length()) { let d = t.charAt(i) - 48; let n = (n * 10) + d; let i = i + 1; }
        return n;
    }
    function int total(int m) {
        var int i, s2, e;
        let i = 0;
        let e = i + m;
        while (i < e) { let s2 = s2 + i; let i = i + 1; }
        return s2;
    }
}
"""
    lines = decompile_classes(tmp_path, Main=main)["Main"]
    assert "static Array screen;" in lines  # let s = 16384;
    assert "var int address;" in lines  # 16384 + (32 * y) + (x / 16)
    assert "var int i, result, digit;" in lines  # c - 48, return v;
    assert "var int i, sum, end;" in lines  # let e = i + m; while (i < e)


def test_loop_bounds_and_flag_setters(tmp_path):
    ship = """
class Ship {
    field boolean f; field int n;
    constructor Ship new() { let f = false; let n = 0; return this; }
    method void setDead() { let f = true; return; }
    method void fill(int m) { var int i; let i = 0; while (i < m) { let n = n + i; let i = i + 1; } return; }
}
"""
    lines = decompile_classes(tmp_path, Ship=ship)["Ship"]
    assert "field boolean dead;" in lines  # setDead() { let this.k = true; }
    assert "method void fill(int count) {" in lines  # while (i < count)
