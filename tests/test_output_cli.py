"""output.py (safe saving) and main.py (the command line)."""

import shutil

import pytest

from jack_decompiler import decompile_files
from jack_decompiler.main import main
from jack_decompiler.output import SUBFOLDER, conflicts, default_folder, save_result, written_by_us


@pytest.fixture
def pong(tmp_path, fixtures):
    folder = tmp_path / "pong"
    shutil.copytree(fixtures / "pong", folder)
    return folder


def test_saves_next_to_the_vm_files_and_can_overwrite_own_files(pong):
    result = decompile_files([pong])
    assert default_folder(result, pong) == pong
    written = save_result(result, pong)
    assert sorted(p.name for p in written) == ["Ball.jack", "Bat.jack", "Main.jack", "PongGame.jack"]
    assert written_by_us(pong / "Ball.jack")
    save_result(result, pong)  # our own files may be replaced


def test_never_overwrites_hand_written_jack(pong):
    (pong / "Ball.jack").write_text("class Ball { }  // my own work\n")
    result = decompile_files([pong])
    assert conflicts(result, pong) == [pong / "Ball.jack"]
    with pytest.raises(FileExistsError, match="won't overwrite Ball.jack"):
        save_result(result, pong)
    assert default_folder(result, pong) == pong / SUBFOLDER
    save_result(result, pong, force=True)
    assert written_by_us(pong / "Ball.jack")


def test_save_into_a_file_path_fails(pong):
    with pytest.raises(NotADirectoryError):
        save_result(decompile_files([pong]), pong / "Main.vm")


def test_cli_writes_files(pong, tmp_path, capsys):
    out = tmp_path / "out"
    assert main([str(pong), "-o", str(out)]) == 0
    assert (out / "PongGame.jack").is_file()
    assert "Wrote 4 files" in capsys.readouterr().err


def test_cli_stdout_and_verify(fixtures, capsys):
    assert main([str(fixtures / "hello-world" / "Main.vm"), "--stdout", "--verify"]) == 0
    captured = capsys.readouterr()
    assert 'do Output.printString("Hello world!");' in captured.out
    assert "OK   Main: identical" in captured.err


def test_cli_refuses_to_overwrite(pong, capsys):
    (pong / "Main.jack").write_text("class Main {}\n")
    assert main([str(pong), "-o", str(pong)]) == 2
    assert "won't overwrite" in capsys.readouterr().err
    assert main([str(pong), "-o", str(pong), "--force"]) == 0


def test_cli_errors(tmp_path, capsys):
    assert main([str(tmp_path / "missing"), "--stdout"]) == 2
    assert "Can't find" in capsys.readouterr().err
    bad = tmp_path / "Bad.vm"
    bad.write_text("function Bad.f 0\npush nowhere 1\n")
    assert main([str(bad), "--stdout"]) == 2
    assert "Bad.vm:2: unknown segment" in capsys.readouterr().err


def test_cli_exit_code_1_when_something_could_not_be_decompiled(tmp_path, capsys):
    vm = tmp_path / "Main.vm"
    vm.write_text("function Main.main 0\nlabel X\npush constant 1\nif-goto X\npush constant 0\nreturn\n")
    assert main([str(vm), "--stdout", "--verify"]) == 1
    err = capsys.readouterr().err
    assert "couldn't decompile Main.main" in err and "DIFF Main" in err


def test_cli_warnings(tmp_path, capsys):
    vm = tmp_path / "Other.vm"
    vm.write_text("function Main.main 0\npush constant 0\nreturn\n")
    assert main([str(vm), "--stdout"]) == 0
    assert "warning: Other.vm contains class Main" in capsys.readouterr().err
