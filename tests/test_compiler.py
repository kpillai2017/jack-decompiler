"""compiler.py: the checking compiler must match the nand2tetris compiler."""

import pytest

from jack_decompiler.compiler import JackSyntaxError, compile_jack, tokenize


def test_tokenizer_skips_comments_and_counts_lines():
    tokens = tokenize('/** doc\n */ class // hi\n X { "a b" 12 }')
    assert [(t.kind, t.value, t.line) for t in tokens] == [
        ("keyword", "class", 2), ("identifier", "X", 3), ("symbol", "{", 3), ("string", "a b", 3),
        ("int", "12", 3), ("symbol", "}", 3)]


def test_compiles_like_the_official_compiler(fixtures):
    source = """
class Main {
    function void main() {
        var SquareGame game;
        let game = SquareGame.new();
        do game.run();
        do game.dispose();
        return;
    }
}"""
    assert compile_jack(source) == (fixtures / "square-game" / "Main.vm").read_text()


@pytest.mark.parametrize("source, message", [
    ("class A { function void f() { let x = 1; return; } }", "'x' is not declared"),
    ("class A { function void f() { return } }", "expected an expression"),
    ("class A { function void f() { return 1 } }", "expected ';'"),
    ("class A { field int x, x; }", "declared twice"),
    ("class A { function void f() { do Output.printInt(99999); return; } }", "too big"),
    ("class A { } extra", "after the end of the class"),
    ("class A { function void f() { return 1 $ 2; } }", "unexpected character"),
    ("class A { /* never closed", "unterminated"),
])
def test_syntax_errors(source, message):
    with pytest.raises(JackSyntaxError, match=message):
        compile_jack(source)


def test_error_has_line_number():
    with pytest.raises(JackSyntaxError) as info:
        compile_jack("class A {\n function void f() {\n  let y = 2;\n }\n}", "A.jack")
    assert info.value.line == 3 and "A.jack:3" in str(info.value)
