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


# --- "save as": choosing where the .jack files go ------------------------------------
def test_save_picker_lists_only_folders_and_chooses_one(games):
    from jack_decompiler.gui.picker import SAVE

    (games / "pong" / "out").mkdir()
    p = PickerState(games / "pong", purpose=SAVE)
    assert [e.label for e in p.entries][1:] == ["out/"]  # no .vm files
    assert p.choose_save_folder() == games / "pong" / "out"  # the selected folder row
    assert p.choose_save_folder(here=True) == (games / "pong").resolve()  # the folder being shown
    p.home()  # on ".."
    assert p.choose_save_folder() == (games / "pong").resolve()


def test_viewer_save_as_remembers_the_folder(games):
    v = ViewerState([games / "pong"])
    out = games / "chosen" / "jack"
    assert v.save_as(out) == out and sorted(f.name for f in out.iterdir()) == [
        "Ball.jack", "Bat.jack", "Main.jack", "PongGame.jack"]
    assert v.output_folder == out and v.save_as_start() == out
    assert v.save() == out  # Ctrl+S keeps using the chosen folder
    assert not (games / "pong" / "Ball.jack").exists()


def test_viewer_save_as_keeps_the_old_folder_when_it_fails(games):
    (games / "taken").mkdir()
    (games / "taken" / "Bat.jack").write_text("class Bat {}\n")
    v = ViewerState([games / "pong"])
    assert v.save_as(games / "taken") is None and "won't overwrite" in v.notice
    assert v.output_folder is None


def test_viewer_output_folder_and_force(games):
    out = games / "out"
    out.mkdir()
    (out / "Bat.jack").write_text("class Bat {}\n")
    assert ViewerState([games / "pong"], output_folder=out).save() is None
    assert ViewerState([games / "pong"], output_folder=out, force=True).save() == out
    assert (out / "Bat.jack").read_text() != "class Bat {}\n"  # overwritten, as asked


def test_app_ctrl_shift_s_opens_the_folder_chooser_and_saves(games):
    (games / "dest").mkdir()
    app = App([games / "pong"], window_size=(1000, 700))
    press(app, pygame.K_s, CTRL | SHIFT)
    assert app.mode == "save" and app.save_picker.directory == (games / "pong").resolve()
    app.draw()
    assert any(action == "save-here" for _, action, _ in app.hit)
    press(app, pygame.K_ESCAPE)  # Esc: back to the program, nothing saved
    assert app.mode == "viewer" and not (games / "pong" / "Ball.jack").exists()

    press(app, pygame.K_s, CTRL | SHIFT)
    press(app, pygame.K_BACKSPACE)  # up to games/ (pong/ stays selected) ...
    press(app, pygame.K_HOME)
    press(app, pygame.K_DOWN)  # ... dest/ is the first folder
    assert app.save_picker.current.label == "dest/"
    press(app, pygame.K_RETURN, CTRL)  # save in the selected folder
    assert app.mode == "viewer" and (games / "dest" / "Ball.jack").is_file()
    assert "Saved 4 .jack files" in app.viewer.notice
    press(app, pygame.K_s, CTRL)  # Ctrl+S now saves there too
    assert app.viewer.saved_to == games / "dest"


def test_app_save_chooser_mouse(games):
    (games / "dest").mkdir()
    app = App([games / "pong"], window_size=(1000, 700))
    press(app, pygame.K_s, CTRL | SHIFT)
    press(app, pygame.K_BACKSPACE)
    app.draw()
    row = next(rect for rect, action, i in app.hit if action == "row" and app.save_picker.entries[i].label == "dest/")
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=row.center))  # click: into dest/
    assert app.save_picker.directory == (games / "dest").resolve()
    app.draw()
    button = next(rect for rect, action, _ in app.hit if action == "save-here")
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.center))
    assert app.mode == "viewer" and (games / "dest" / "PongGame.jack").is_file()


def test_app_output_folder_applies_to_every_program(games):
    out = games / "out"
    app = App([games / "pong"], output_folder=out)
    press(app, pygame.K_s, CTRL)
    assert (out / "Ball.jack").is_file()
    app.open_program([games / "square-game"])
    press(app, pygame.K_s, CTRL)
    assert (out / "SquareGame.jack").is_file()


def test_cli_passes_the_output_folder_to_the_gui(games, monkeypatch):
    from jack_decompiler import main as main_module
    from jack_decompiler.gui import app as app_module

    seen = []
    monkeypatch.setattr(app_module, "run_gui", lambda files, **kw: seen.append((list(files), kw)) or 0)
    out = games / "out"
    assert main_module.main(["--gui", str(games / "pong"), "-o", str(out), "--force"]) == 0
    assert seen[-1][1]["output_folder"] == out and seen[-1][1]["force"] is True
    assert main_module.main(["-o", str(out)]) == 0  # no .vm files: the GUI, saving in out/
    assert seen[-1] == ([], {"rename_functions": True, "output_folder": out, "force": False})
    assert not out.exists()


# --- "New folder" in the save-as chooser ---------------------------------------------
def test_picker_new_folder_rules(games):
    from jack_decompiler.gui.picker import SAVE, folder_name_problem

    assert folder_name_problem("out") == ""
    for bad in ("", "a/b", "a\\b", ".", "..", ".hidden"):
        assert folder_name_problem(bad), bad
    p = PickerState(games, purpose=SAVE)
    assert p.create_folder() is None  # not naming: nothing happens
    p.start_new_folder()
    p.type_name("a/b")
    assert p.create_folder() is None and "can't contain" in p.message and p.naming == "a/b"  # keep typing
    for _ in range(3):
        p.erase_name()
    p.type_name(" jack out ")
    assert p.create_folder() == games / "jack out" and (games / "jack out").is_dir()
    assert p.naming is None and p.current.path == games / "jack out"
    p.start_new_folder()
    p.type_name("jack out")
    assert p.create_folder() == games / "jack out"  # already there: just selected
    (games / "afile").write_text("")
    p.start_new_folder()
    p.type_name("afile")
    assert p.create_folder() is None and "already a file" in p.message
    p.cancel_new_folder()
    assert p.naming is None and p.message == ""


def test_app_new_folder_by_keys_then_save(games):
    app = App([games / "pong"], window_size=(1000, 700))
    press(app, pygame.K_s, CTRL | SHIFT)
    press(app, pygame.K_n, CTRL)
    assert app.save_picker.naming == ""
    app.handle(pygame.event.Event(pygame.TEXTINPUT, text="jackx"))
    press(app, pygame.K_BACKSPACE)  # edits the name, doesn't go up
    assert app.save_picker.naming == "jack" and app.save_picker.directory == (games / "pong").resolve()
    app.draw()
    press(app, pygame.K_ESCAPE)  # Esc stops naming, stays in the chooser
    assert app.mode == "save" and app.save_picker.naming is None
    press(app, pygame.K_n, CTRL)
    app.handle(pygame.event.Event(pygame.TEXTINPUT, text="src"))
    press(app, pygame.K_RETURN)
    new = (games / "pong" / "src").resolve()
    assert new.is_dir() and app.save_picker.current.path == new and app.mode == "save"
    press(app, pygame.K_RETURN, CTRL)  # save in the new (selected) folder
    assert (new / "Ball.jack").is_file() and app.mode == "viewer"


def test_app_new_folder_button(games):
    app = App([games / "pong"], window_size=(1000, 700))
    press(app, pygame.K_s, CTRL | SHIFT)

    def click(action):
        app.draw()
        rect = next(r for r, a, _ in app.hit if a == action)
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))

    click("new-folder")
    assert app.save_picker.naming == ""
    app.handle(pygame.event.Event(pygame.TEXTINPUT, text="out"))
    click("new-folder")  # now "Create"
    assert (games / "pong" / "out").is_dir() and app.save_picker.naming is None
