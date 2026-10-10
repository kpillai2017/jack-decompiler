"""vm_reader.py: parsing and error checking of .vm text."""

import pytest

from jack_decompiler.vm_reader import (
    VMSyntaxError, group_by_class, parse_vm, read_files, resolve_inputs,
)


def problems(text):
    with pytest.raises(VMSyntaxError) as info:
        parse_vm(text, "X.vm")
    return [p.message for p in info.value.problems]


def test_parses_functions_and_instructions():
    functions = parse_vm("// comment\nfunction Main.main 2\n  push constant 7 // seven\nadd\nlabel L\ngoto L\nreturn\n")
    assert len(functions) == 1
    f = functions[0]
    assert (f.name, f.n_locals, f.class_name, f.short_name) == ("Main.main", 2, "Main", "main")
    assert [i.text() for i in f.body] == ["push constant 7", "add", "label L", "goto L", "return"]
    assert f.body[0].line == 3


@pytest.mark.parametrize("line, message", [
    ("push constant", "needs a segment and an index"),
    ("push nowhere 1", "unknown segment"),
    ("push local -1", "not a whole number"),
    ("pop constant 1", "can't 'pop constant'"),
    ("push temp 8", "too big for segment 'temp'"),
    ("push pointer 2", "too big for segment 'pointer'"),
    ("push constant 32768", "too big for segment 'constant'"),
    ("add 1", "takes no arguments"),
    ("return 0", "takes no arguments"),
    ("label 1abc", "not a valid label name"),
    ("goto", "needs exactly one label name"),
    ("call Foo 1", "not a valid function name"),
    ("call A.b", "needs a name and a number"),
    ("jump L", "unknown command 'jump'"),
])
def test_reports_bad_lines(line, message):
    found = problems(f"function A.f 0\n{line}\nreturn\n")
    assert any(message in m for m in found), found


def test_reports_all_problems_with_line_numbers():
    with pytest.raises(VMSyntaxError) as info:
        parse_vm("push constant 1\nfunction A.f 0\nfoo\nbar\n", "A.vm")
    lines = [(p.line, p.file) for p in info.value.problems]
    assert lines == [(1, "A.vm"), (3, "A.vm"), (4, "A.vm")]
    assert "3 problems" in str(info.value)
    assert "A.vm:3" in str(info.value)


def test_labels_are_checked_per_function():
    found = problems("function A.f 0\nlabel L\nlabel L\ngoto MISSING\nreturn\nfunction A.g 0\ngoto L\nreturn\n")
    assert any("defined twice" in m for m in found)
    assert any("MISSING" in m for m in found)
    assert any("'L'" in m and "A.g" in m for m in found)  # L belongs to A.f, not A.g


def test_a_bad_function_line_does_not_cascade():
    found = problems("function Foo 0\npush constant 1\nreturn\n")
    assert len(found) == 1


def test_duplicate_functions_across_files(tmp_path):
    (tmp_path / "A.vm").write_text("function A.f 0\nreturn\n")
    (tmp_path / "B.vm").write_text("function A.f 0\nreturn\n")
    with pytest.raises(VMSyntaxError, match="defined twice"):
        read_files(resolve_inputs([str(tmp_path)]))


def test_unreadable_and_binary_files(tmp_path):
    (tmp_path / "Bin.vm").write_bytes(b"\xff\xfe\x00\x81")
    with pytest.raises(VMSyntaxError, match="not a text file"):
        read_files([tmp_path / "Bin.vm"])
    with pytest.raises(VMSyntaxError, match="couldn't read"):
        read_files([tmp_path / "Missing.vm"])


def test_resolve_inputs(tmp_path, fixtures):
    assert [p.name for p in resolve_inputs([str(fixtures / "pong")])] == ["Ball.vm", "Bat.vm", "Main.vm", "PongGame.vm"]
    with pytest.raises(FileNotFoundError, match="no such file"):
        resolve_inputs([str(tmp_path / "nope")])
    with pytest.raises(FileNotFoundError, match="No .vm files"):
        resolve_inputs([str(tmp_path)])
    (tmp_path / "x.txt").write_text("hi")
    with pytest.raises(FileNotFoundError, match="not a .vm file"):
        resolve_inputs([str(tmp_path / "x.txt")])


def test_group_by_class_keeps_order():
    functions = parse_vm("function B.x 0\nreturn\nfunction A.y 0\nreturn\nfunction B.z 0\nreturn\n")
    assert {k: [f.short_name for f in v] for k, v in group_by_class(functions).items()} == {"B": ["x", "z"], "A": ["y"]}
