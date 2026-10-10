"""
The GUI: the logic classes (no window) and the pygame app driven with fake
key presses (SDL's dummy video driver: nothing appears on screen).
"""

import shutil
from pathlib import Path

import pygame
import pytest

from jack_decompiler.gui import compiler_link, theme
from jack_decompiler.gui.app import App
from jack_decompiler.gui.picker import PickerState, list_entries
from jack_decompiler.gui.viewer import ViewerState

CTRL, CMD, SHIFT = pygame.KMOD_CTRL, pygame.KMOD_META, pygame.KMOD_SHIFT


def press(app, key, mod=0):
    return app.handle(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod, unicode=""))


@pytest.fixture
def games(tmp_path, fixtures):
    for name in ("pong", "square-game"):
        shutil.copytree(fixtures / name, tmp_path / name)
    (tmp_path / "empty").mkdir()
    (tmp_path / ".hidden").mkdir()
    return tmp_path


# --- picker logic --------------------------------------------------------------
def test_list_entries(games):
    entries = list_entries(games)
    assert [(e.kind, e.label, e.vm_count) for e in entries][1:] == [
        ("folder", "empty/", 0), ("folder", "pong/", 4), ("folder", "square-game/", 3)]
    assert entries[0].kind == "parent"


def test_picker_navigation(games):
    p = PickerState(games)
    assert p.current.label == "empty/"
    p.move(1)
    assert p.activate() is None and p.directory == games / "pong"  # Enter on a folder opens it
    files = p.decompile_folder()
    assert [f.name for f in files] == ["Ball.vm", "Bat.vm", "Main.vm", "PongGame.vm"]
    p.end()
    assert p.activate() == [games / "pong" / "PongGame.vm"]  # Enter on a file decompiles it
    p.go_up()
    assert p.directory == games and p.current.label == "pong/"
    p.home()
    p.move(1)
    assert p.decompile_folder_entry() is None and "No .vm files" in p.message  # empty/


def test_picker_starts_in_nearest_existing_folder(games):
    assert PickerState(games / "missing" / "deeper").directory == games.resolve()


# --- viewer logic ---------------------------------------------------------------
def test_viewer_state(games):
    found = []
    v = ViewerState([games / "pong"], find_compiler=lambda: found.append(1))
    assert v.class_names == ["Ball", "Bat", "Main", "PongGame"] and v.current_name == "Ball"
    v.previous_class()
    assert v.current_name == "PongGame"  # wraps around
    v.next_class()
    assert v.current_name == "Ball"
    v.scroll_by("jack", 1000, 20)
    assert v.scroll["jack"] == len(v.lines("jack")) - 20
    v.scroll_by("jack", -5000, 20)
    assert v.scroll["jack"] == 0
    assert all(c.ok for c in v.run_verify())
    assert v.status_lines()[1] == ("Round trip: identical after recompiling", "good")
    assert v.save() == games / "pong" and (games / "pong" / "Ball.jack").is_file()
    assert "not found" in v.open_in_compiler() and found == [1]  # saved, then looked for jackc-gui


def test_viewer_reports_bad_vm_and_recovers_on_reload(games):
    main = games / "pong" / "Main.vm"
    good = main.read_text()
    main.write_text("function Main.main 0\npush banana 1\n")
    v = ViewerState([games / "pong"])
    assert v.result is None and "unknown segment" in v.status_lines()[0][0]
    main.write_text(good)
    v.reload()
    assert v.result is not None and v.notice == "Reloaded and decompiled again"


def test_viewer_saves_to_subfolder_when_hand_written_jack_exists(games):
    (games / "pong" / "Bat.jack").write_text("class Bat {}\n")
    v = ViewerState([games / "pong"])
    assert v.save() == games / "pong" / "decompiled"
    assert (games / "pong" / "Bat.jack").read_text() == "class Bat {}\n"


# --- the pygame app ----------------------------------------------------------------
def test_app_shortcuts(games):
    app = App([games / "pong"], window_size=(1000, 700))
    app.draw()
    assert app.mode == "viewer"
    press(app, pygame.K_n, CTRL)
    assert app.viewer.current_name == "Bat"
    press(app, pygame.K_p, CMD)  # Cmd works like Ctrl, as in jackvm
    assert app.viewer.current_name == "Ball"
    press(app, pygame.K_TAB)
    press(app, pygame.K_TAB, SHIFT)
    assert app.viewer.current_name == "Ball"
    press(app, pygame.K_PAGEDOWN)
    assert app.viewer.scroll["jack"] > 0
    press(app, pygame.K_END, SHIFT)  # Shift scrolls the VM panel
    assert app.viewer.scroll["vm"] > 0
    press(app, pygame.K_HOME)
    assert app.viewer.scroll["jack"] == 0
    press(app, pygame.K_d, CTRL)
    app.draw()
    assert not app.viewer.show_vm and "vm" not in app.panel_rects
    press(app, pygame.K_t, CTRL)
    assert "4 of 4" in app.viewer.notice
    press(app, pygame.K_s, CTRL)
    assert (games / "pong" / "PongGame.jack").is_file()
    press(app, pygame.K_r, CTRL)
    assert app.viewer.notice.startswith("Reloaded")
    app.draw()
    assert press(app, pygame.K_q, CTRL) is False  # quit


def test_app_picker_and_esc(games):
    app = App(start_dir=games, window_size=(1000, 700))
    app.draw()
    assert app.mode == "picker"
    press(app, pygame.K_DOWN)  # empty/ -> pong/
    press(app, pygame.K_RETURN, CTRL)  # decompile the selected folder
    assert app.mode == "viewer" and app.viewer.current_name == "Ball"
    press(app, pygame.K_ESCAPE)
    assert app.mode == "picker"
    app.draw()
    assert press(app, pygame.K_ESCAPE) is True and app.mode == "viewer"  # Esc goes back to the program
    press(app, pygame.K_o, CTRL)
    assert app.mode == "picker"


def test_esc_in_first_picker_quits(games):
    app = App(start_dir=games)
    assert press(app, pygame.K_ESCAPE) is False


def test_mouse_clicks_on_tabs_and_tags(games):
    app = App([games / "pong"], window_size=(1000, 700))
    app.draw()
    tab = next(rect for rect, action, index in app.hit if action == "tab" and index == 2)
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=tab.center))
    assert app.viewer.current_name == "Main"
    press(app, pygame.K_ESCAPE)  # the picker opens in pong/ ...
    press(app, pygame.K_BACKSPACE)  # ... so go up to see the folders
    app.draw()
    tag = next(rect for rect, action, _ in app.hit if action == "decompile-entry")
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=tag.center))
    assert app.mode == "viewer"


def test_window_close_and_resize(games):
    app = App([games / "pong"])
    app.handle(pygame.event.Event(pygame.VIDEORESIZE, w=300, h=200, size=(300, 200)))
    assert app.window.get_size() == (720, 480)  # never smaller than the minimum
    app.draw()
    assert app.handle(pygame.event.Event(pygame.QUIT)) is False


# --- small pieces ----------------------------------------------------------------------
def test_highlighting():
    spans = dict((text, colour) for text, colour in theme.highlight_jack('    let x = "hi" + 3; // note'))
    assert spans["let"] == "keyword" and spans['"hi"'] == "string" and spans["3"] == "number"
    assert spans["// note"] == "comment"
    vm = theme.highlight_vm("call Math.max 2 // c")
    assert vm[0] == ("call", "keyword") and ("2", "number") in vm and vm[-1] == ("// c", "comment")


def test_find_compiler_gui(tmp_path):
    assert compiler_link.find_compiler_gui({"JACKC_GUI": "off"}) is None
    assert compiler_link.find_compiler_gui({"JACKC_GUI": "my gui"}) == ["my", "gui"]
    folder = tmp_path / "jack-compiler"
    tool = folder / ".venv" / "bin" / "jackc-gui"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    config = tmp_path / "config.ini"
    config.write_text(f"[apps]\njackc = {folder}   ; my checkout\n")
    env = {"JACK_TOOLS_CONFIG": str(config)}
    assert compiler_link.find_compiler_gui(env, which=lambda _: None) == [str(tool)]
    config.write_text("[apps]\njackc = off\n")
    assert compiler_link.find_compiler_gui(env, which=lambda _: "/bin/x") is None
    assert compiler_link.find_compiler_gui({"HOME": str(tmp_path)}, which=lambda _: "/usr/bin/jackc-gui") \
        == ["/usr/bin/jackc-gui"]
    assert compiler_link.find_compiler_gui({"HOME": str(tmp_path)}, which=lambda _: None) is None
    assert "not found" in compiler_link.open_in_compiler(Path("x"), None)
    assert "Couldn't start" in compiler_link.open_in_compiler(Path("x"), [str(tmp_path / "missing-command")])
