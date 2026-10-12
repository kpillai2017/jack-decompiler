"""Extended compiler VM patterns and public companion OS contracts."""

import itertools
from pathlib import Path

import pytest

from jack_decompiler import decompile_text
from jack_decompiler.compiler import compile_jack, JackSyntaxError
from jack_decompiler.os_api import OS_API
from jack_decompiler.os_extensions import DECLARATIONS
from jack_decompiler.verify import verify


def check_roundtrip(source):
    code = compile_jack(source, dialect="companion")
    result = decompile_text(code, "Main.vm")
    assert not result.errors
    assert all(check.ok for check in verify(result)), verify(result)
    return result.classes["Main"].jack


@pytest.mark.parametrize("condition,update", list(itertools.product([False, True], repeat=2)))
def test_optional_for_clauses(condition, update):
    cond = "i < 3" if condition else ""
    step = "let i += 1" if update else ""
    source = "class Main { function void main() { var int i; for (; " + cond + "; " + step + ") { break; } return; } }"
    jack = check_roundtrip(source)
    assert "for (" in jack and "break;" in jack and "--extensions" in jack


@pytest.mark.parametrize("body", [
    "while (i < 5) { let i = i + 1; if (i = 2) { continue; } if (i = 4) { break; } }",
    "for (let i = 0; i < 5; let i += 1) { if (i = 2) { continue; } if (i = 4) { break; } }",
    "for (;;) { while (true) { break; } break; }",
    "for (; i < 3; let i += 1) { for (; j < 3; let j += 1) { if (j = 1) { continue; } break; } continue; }",
    "while (true) { if (i = 1) { break; } else { continue; } }",
])
def test_nested_loop_controls(body):
    check_roundtrip("class Main { function void main() { var int i, j; " + body + " return; } }")


@pytest.mark.parametrize("op", ["+=", "-=", "*=", "/=", "&=", "|="])
def test_array_compound_keeps_index_call_once(op):
    source = "class Main { function int index() { return 0; } function void main() { var Array a; let a = Array.new(1); let a[Main.index()] " + op + " 3; return; } }"
    jack = check_roundtrip(source)
    assert op in jack
    assert jack.count("Main.index()") == 1


def test_array_compound_rhs_call():
    check_roundtrip("class Main { function int rhs(Array a) { let a[0] = 99; return 3; } function void main() { var Array a; let a = Array.new(1); let a[0] = 7; let a[0] += Main.rhs(a); return; } }")


@pytest.mark.parametrize("keyword", ["break", "continue"])
def test_checking_compiler_rejects_control_outside_loop(keyword):
    with pytest.raises(JackSyntaxError):
        compile_jack("class Main { function void main() { " + keyword + "; return; } }")


def test_malformed_for_update_keeps_vm_as_comments():
    code = "function Main.main 0\nlabel FOR$0\nlabel FORUPDATE$1\ncall Output.println 0\npop temp 0\ngoto FOR$0\nlabel ENDFOR$2\npush constant 0\nreturn\n"
    result = decompile_text(code, "Main.vm")
    assert result.errors and "single assignment" in result.errors[0]


@pytest.mark.parametrize("cls,declaration", [(cls, decl) for cls, decls in DECLARATIONS.items() for decl in decls])
def test_every_extended_os_signature_and_call(cls, declaration):
    head, params = declaration.rstrip(")").split("(")
    kind, ret, name = head.split()
    parameters = tuple(tuple(p.strip().split()) for p in params.split(",") if p.strip())
    sig = OS_API[cls + "." + name]
    assert (sig.kind, sig.return_type, sig.params) == (kind, ret, parameters)
    prefix = "var " + cls + " object; " if kind == "method" else ""
    receiver = "object" if kind == "method" else cls
    arguments = ", ".join("0" for _ in parameters)
    source = "class Main { function void main() { " + prefix + "do " + receiver + "." + name + "(" + arguments + "); return; } }"
    jack = check_roundtrip(source)
    if kind == "method":
        assert "." + name + "(" in jack
        assert "var " + cls + " " in jack


@pytest.fixture
def companion_compile(tmp_path):
    compiler = pytest.importorskip("jack_compiler.compiler")
    import inspect
    if "extensions" not in inspect.signature(compiler.JackCompiler).parameters:
        pytest.skip("installed compiler predates language extensions")

    def compile_source(source):
        path = tmp_path / "Main.jack"
        path.write_text(source, encoding="utf-8")
        code = compiler.JackCompiler(extensions=True).compile_source(str(path))
        result = decompile_text(code, "Main.vm")
        assert not result.errors
        assert all(check.ok for check in verify(result)), verify(result)
        # Also use the actual companion compiler: its semantic checker and
        # literal rules must accept the recovered source, not only our checker.
        path.write_text(result.classes["Main"].jack, encoding="utf-8")
        rebuilt = compiler.JackCompiler(extensions="// Requires jackc --extensions" in result.classes["Main"].jack).compile_source(str(path))
        from jack_decompiler.vm_reader import parse_vm
        from jack_decompiler.verify import compare
        original = [sub.vm for sub in result.program.classes["Main"].subs]
        assert compare(original, parse_vm(rebuilt, "Main.vm"), result.program.renames) is None
        return result

    return compile_source


def test_actual_compiler_literals_constants_initialisers(companion_compile):
    companion_compile(r'''class Main {
        const int MASK = 0xFF;
        enum E { FIRST, LAST = 3 }
        function void main() {
            var int x = MASK;
            var char c = 'A';
            if (x >= 0b10) { let x += E.LAST; }
            if (x <= 300) { do Output.printChar(c); }
            if (x != 0) { do Output.printString("quote\"\\\n"); }
            return;
        }
    }''')


def test_actual_compiler_array_loop_side_effects(companion_compile):
    companion_compile("class Main { function int index() { return 0; } function void main() { var int i = 0; var Array a = Array.new(1); for (i = 0; i < 3; i += 1) { if (i = 1) { continue; } let a[Main.index()] += 2; if (i = 2) { break; } } return; } }")


def test_extension_strings_preserve_literal_backslashes(companion_compile):
    result = companion_compile(r'''class Main { function void main() { for (;;) { break; } do Output.printString("literal\\n and quote\" and slash\\"); return; } }''')
    assert r'literal\\n' in result.classes["Main"].jack
    assert r'quote\"' in result.classes["Main"].jack


def test_companion_base_first_array_read_with_label_free_helper(companion_compile):
    result = companion_compile("class Main { function int get(Array a, int i) { return a[i]; } function void main() { var Array a = Array.new(1); if (true) { do Output.printInt(Main.get(a, 0)); } return; } }")
    assert "get(Array" in result.classes["Main"].jack


def test_combined_teaching_lesson(companion_compile):
    import jack_compiler
    root = Path(jack_compiler.__file__).resolve().parents[1]
    lesson = root / "teaching" / "extensions" / "Main.jack"
    if not lesson.exists():
        pytest.skip("compiler checkout teaching source is not installed")
    result = companion_compile(lesson.read_text())
    assert "for (" in result.classes["Main"].jack
    assert "+=" in result.classes["Main"].jack


def test_full_extended_os_round_trip():
    runtime = pytest.importorskip("jackvm")
    path = Path(runtime.__file__).parent / "os" / "JackOS.vm"
    assert path.is_file()
    result = decompile_text(path.read_text(), "JackOS.vm")
    assert not result.errors
    assert all(check.ok for check in verify(result)), [check for check in verify(result) if not check.ok]


def test_os_signature_consistency_with_compiler():
    compiler = pytest.importorskip("jack_compiler.checker")
    if "fill" not in compiler.OS_SUBROUTINES["Memory"]:
        pytest.skip("installed compiler predates extended OS signatures")
    for cls, declarations in DECLARATIONS.items():
        for declaration in declarations:
            name = declaration.split("(")[0].split()[-1]
            theirs = compiler.OS_SUBROUTINES[cls][name]
            ours = OS_API[cls + "." + name]
            assert (ours.kind, ours.return_type, len(ours.params)) == (theirs.kind, theirs.type, theirs.parameter_count)
