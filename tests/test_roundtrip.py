"""
Round trips: the strongest test of the decompiler.

    VM --decompile--> Jack --compile--> VM'      VM' must equal VM

for the bundled sample programs, for every game in a jackvm-py checkout
next to this repository (if there is one), and for hand-written Jack.
"""

import os
from pathlib import Path

import pytest

from jack_decompiler import decompile_files
from jack_decompiler.verify import verify

from .helpers import round_trip

FIXTURES = Path(__file__).parent / "fixtures"
JACKVM_GAMES = Path(os.environ.get("JACKVM_GAMES", Path(__file__).resolve().parents[2] / "jackvm-py" / "games"))


def programs(folder: Path):
    return sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []


@pytest.mark.parametrize("program", programs(FIXTURES), ids=lambda p: p.name)
def test_bundled_programs_round_trip(program):
    result = decompile_files([program])
    assert result.errors == [] and result.warnings == []
    failed = [c for c in verify(result) if not c.ok]
    assert failed == []


@pytest.mark.skipif(not JACKVM_GAMES.is_dir(), reason="no jackvm-py checkout next to this repository")
@pytest.mark.parametrize("program", programs(JACKVM_GAMES), ids=lambda p: p.name)
def test_jackvm_games_round_trip(program):
    result = decompile_files([program])
    assert result.errors == []
    assert [c for c in verify(result) if not c.ok] == []


JACK_PROGRAMS = {
    "nesting": """
class Main {
    static int total;
    function void main() {
        var int i, j;
        let i = 0;
        while (i < 10) {
            if (i = 3) { let total = total + 1; }
            else {
                if (~(i > 5)) { let j = 0; while (j < i) { let j = j + 1; } }
                else { }
            }
            let i = i + 1;
        }
        return;
    }
}""",
    "expressions": """
class Main {
    function int f(int a, int b, Array c) {
        var String s;
        let s = "Hello, world! 123";
        let c[a + 1] = c[b] - (a * (b / 2));
        let c[c[0]] = -a + ~b & (a | b);
        if ((a < b) & ((b > 0) | (a = -1))) { return a - (b - (a - b)); }
        return s.length() + Main.f(b, a, c) + Math.max(a, b);
    }
}""",
    "objects": """
class Main {
    field int x;
    field Main next;
    constructor Main new(int ax) { let x = ax; let next = null; return this; }
    method void link(Main other) { let next = other; do other.touch(this); return; }
    method void touch(Main from) { let x = x + 1; do Output.printInt(from.value()); return; }
    method int value() { return x; }
    method void dispose() { if (~(next = null)) { do next.dispose(); } do Memory.deAlloc(this); return; }
}""",
}


@pytest.mark.parametrize("name", sorted(JACK_PROGRAMS))
def test_hand_written_jack_round_trips(name):
    result, checks = round_trip(JACK_PROGRAMS[name])
    assert result.errors == []
    assert all(c.ok for c in checks), [c.message for c in checks]
