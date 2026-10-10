"""
app.py - The decompiler's window (pygame), with jackvm-style shortcuts.
=======================================================================

    +- Ball  Bat  Main  PongGame ----------------------------------+
    | +-- VM: Ball.vm --------+  +-- JACK: Ball.jack ------------+ |
    | | function Ball.new 0   |  | class Ball {                  | |
    | | ...                   |  |     field int x, y, ...       | |
    | +-----------------------+  +-------------------------------+ |
    | +-- STATUS ---------------------------------------------------+ |
    | +-- SHORTCUTS ------------------------------------------------+ |
    +---------------------------------------------------------------+

Hold Ctrl (or Cmd on a Mac) for the shortcuts, as in jackvm:

    Ctrl+O  open another program (the file picker)   Esc  same, back to the picker
    Ctrl+D  show / hide the VM panel (like jackvm's debugger panel)
    Ctrl+R  reload the .vm files and decompile again (like jackvm's restart)
    Ctrl+N / Ctrl+P  next / previous class (Tab / Shift+Tab, or click a tab)
    Ctrl+S  save the .jack files       Ctrl+T  test: recompile and compare
    Ctrl+Shift+S  save as: choose the folder to save the .jack files in
    Ctrl+J  save, then open in the Jack compiler (as in jackvm)
    Ctrl+Q  quit (closing the window works too)
    Up/Down, PgUp/PgDn, Home/End, mouse wheel: scroll (add Shift for the VM panel)

In the picker: Enter opens/decompiles, Ctrl+Enter decompiles the folder,
Backspace/Left goes up, Right goes in, Esc goes back (or quits).
In the "save as" folder chooser: Enter opens a folder, Ctrl+Enter (or
"[save here]" / the "Save here" button) saves there, Ctrl+N (or "New
folder") makes a folder - type its name, Enter creates it - and Esc goes back.

All the decisions live in picker.py and viewer.py; this file only draws
them and turns events into method calls.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from . import theme
from .drawing import PADDING, Painter
from .picker import PAGE, SAVE, PickerState
from .viewer import ViewerState

WINDOW_SIZE = (1280, 820)
MIN_SIZE = (720, 480)
QUIT, KEEP = False, True


def is_ctrl(mod: int) -> bool:
    return bool(mod & (pygame.KMOD_CTRL | pygame.KMOD_META))


class App(Painter):
    def __init__(self, files: Sequence[Path] = (), start_dir: Optional[Path] = None, rename_functions: bool = True,
                 window_size: Tuple[int, int] = WINDOW_SIZE, output_folder: Optional[Path] = None,
                 force: bool = False):
        pygame.init()
        pygame.key.set_repeat(300, 35)
        self.window = pygame.display.set_mode(window_size, pygame.RESIZABLE)
        self.ui_font = pygame.font.SysFont(theme.FONT_NAMES, theme.UI_FONT_SIZE)
        self.code_font = pygame.font.SysFont(theme.FONT_NAMES, theme.CODE_FONT_SIZE)
        self.ui_line = self.ui_font.get_linesize()
        self.code_line = self.code_font.get_linesize()
        self.rename_functions = rename_functions
        self.output_folder = output_folder  # -o: where every program opened here is saved
        self.force = force
        self.viewer: Optional[ViewerState] = None
        self.save_picker: Optional[PickerState] = None  # the "save as" folder chooser, while it's open
        self.picker = PickerState(start_dir or (Path(files[0]).parent if files else Path.cwd()))
        self.mode = "picker"
        self._cache: Dict[Tuple[str, str], pygame.Surface] = {}
        self.hit: List[Tuple[pygame.Rect, str, int]] = []  # clickable areas found while drawing
        self.panel_rects: Dict[str, pygame.Rect] = {}
        if files:
            self.open_program(files)
        self._update_caption()

    # ------------------------------------------------------------------
    def open_program(self, files: Sequence[Path]) -> None:
        self.viewer = ViewerState(files, self.rename_functions, output_folder=self.output_folder, force=self.force)
        self.mode = "viewer"
        self._update_caption()

    def _update_caption(self) -> None:
        if self.mode == "save":
            title = "Jack decompiler - choose where to save the .jack files"
        elif self.viewer and self.mode == "viewer":
            title = self.viewer.title()
        else:
            title = "Jack decompiler - choose a program"
        pygame.display.set_caption(title)

    def visible_rows(self, panel: str) -> int:
        rect = self.panel_rects.get(panel)
        if rect is None:
            return 30
        return max(1, (rect.height - self.header_height() - 2 * PADDING) // self.code_line)

    def header_height(self) -> int:
        return self.ui_line + 6

    # --- events ------------------------------------------------------------
    def run(self) -> int:
        clock = pygame.time.Clock()
        running = True
        while running:
            self.draw()
            pygame.display.flip()
            event = pygame.event.wait()
            events = [event] + pygame.event.get()
            for e in events:
                if self.handle(e) is QUIT:
                    running = False
                    break
            clock.tick(60)
        pygame.quit()
        return 0

    def handle(self, event) -> bool:
        """React to one pygame event. Returns QUIT (False) to close the window."""
        if event.type == pygame.QUIT:
            return QUIT
        if event.type == pygame.VIDEORESIZE:
            size = (max(MIN_SIZE[0], event.w), max(MIN_SIZE[1], event.h))
            self.window = pygame.display.set_mode(size, pygame.RESIZABLE)
            return KEEP
        if event.type == pygame.KEYDOWN:
            if is_ctrl(event.mod) and event.key == pygame.K_q:
                return QUIT
            if self.mode == "picker":
                return self.picker_key(event)
            return self.save_key(event) if self.mode == "save" else self.viewer_key(event)
        if event.type == pygame.TEXTINPUT and self.mode == "save" and self.save_picker:
            self.save_picker.type_name(event.text)  # ignored unless a new folder is being named
            return KEEP
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self.click(event.pos)
        if event.type == pygame.MOUSEWHEEL and self.mode == "viewer" and self.viewer:
            panel = self.panel_at(pygame.mouse.get_pos())
            self.viewer.scroll_by(panel, -3 * event.y, self.visible_rows(panel))
        elif event.type == pygame.MOUSEWHEEL and self.mode in ("picker", "save"):
            self.active_picker.move(-event.y)
        return KEEP

    def panel_at(self, pos) -> str:
        vm = self.panel_rects.get("vm")
        return "vm" if vm is not None and vm.collidepoint(pos) else "jack"

    def show_picker(self) -> None:
        self.mode = "picker"
        if self.viewer and self.viewer.files:
            self.picker.change_directory(self.viewer.files[0].parent.resolve())
        self._update_caption()

    @property
    def active_picker(self) -> PickerState:
        """The picker on screen: the "save as" folder chooser, or the open-a-program one."""
        return self.save_picker if self.mode == "save" and self.save_picker else self.picker

    def show_save_picker(self) -> None:
        """Ctrl+Shift+S: choose the folder to save the .jack files in."""
        if self.viewer is None or self.viewer.result is None:
            if self.viewer:
                self.viewer.notice = "Nothing to save"
            return
        self.save_picker = PickerState(self.viewer.save_as_start(), purpose=SAVE)
        self.mode = "save"
        self._update_caption()

    def leave_save_picker(self) -> bool:
        self.save_picker = None
        self.mode = "viewer"
        self._update_caption()
        return KEEP

    def start_new_folder(self) -> bool:
        """Ctrl+N / "New folder" in the folder chooser: type a name, Enter creates it."""
        self.save_picker.start_new_folder()
        pygame.key.start_text_input()  # so typing arrives as TEXTINPUT events
        return KEEP

    def save_into(self, folder: Path) -> bool:
        """The folder chooser picked `folder`: save there and go back to the program."""
        if self.viewer is not None:
            self.viewer.save_as(folder)
        return self.leave_save_picker()

    def leave_picker(self) -> bool:
        """Esc / Back in the picker: back to the program, or quit if there is none."""
        if self.viewer is None:
            return QUIT
        self.mode = "viewer"
        self._update_caption()
        return KEEP

    def picker_key(self, event) -> bool:
        p, key, ctrl = self.picker, event.key, is_ctrl(event.mod)
        files = None
        if key == pygame.K_ESCAPE:
            return self.leave_picker()
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            files = p.decompile_folder_entry() if ctrl else p.activate()
        else:
            self.navigate(p, key)
        if files:
            self.open_program(files)
        return KEEP

    def save_key(self, event) -> bool:
        """Keys in the "save as" folder chooser."""
        p, key, ctrl = self.save_picker, event.key, is_ctrl(event.mod)
        if p.naming is not None:  # typing a new folder's name (the text comes as TEXTINPUT)
            if key == pygame.K_ESCAPE:
                p.cancel_new_folder()
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                p.create_folder()
            elif key == pygame.K_BACKSPACE:
                p.erase_name()
            return KEEP
        if ctrl and key == pygame.K_n:
            return self.start_new_folder()
        if key == pygame.K_ESCAPE:
            return self.leave_save_picker()
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if ctrl:
                return self.save_into(p.choose_save_folder())
            p.activate()  # into the folder (or up, on "..")
        else:
            self.navigate(p, key)
        return KEEP

    @staticmethod
    def navigate(p: PickerState, key: int) -> None:
        """Moving around a picker (the same keys in both)."""
        if key in (pygame.K_BACKSPACE, pygame.K_LEFT):
            p.go_up()
        elif key == pygame.K_RIGHT:
            p.enter_folder()
        elif key == pygame.K_UP:
            p.move(-1)
        elif key == pygame.K_DOWN:
            p.move(1)
        elif key == pygame.K_PAGEUP:
            p.move(-PAGE)
        elif key == pygame.K_PAGEDOWN:
            p.move(PAGE)
        elif key == pygame.K_HOME:
            p.home()
        elif key == pygame.K_END:
            p.end()

    def viewer_key(self, event) -> bool:
        v, key, ctrl = self.viewer, event.key, is_ctrl(event.mod)
        shift = bool(event.mod & pygame.KMOD_SHIFT)
        if v is None:
            return KEEP
        if key == pygame.K_ESCAPE or (ctrl and key == pygame.K_o):
            self.show_picker()
        elif ctrl and key == pygame.K_d:
            v.toggle_vm()
        elif ctrl and key == pygame.K_r:
            v.reload()
        elif (ctrl and key == pygame.K_n) or (key == pygame.K_TAB and not shift):
            v.next_class()
        elif (ctrl and key == pygame.K_p) or (key == pygame.K_TAB and shift):
            v.previous_class()
        elif ctrl and shift and key == pygame.K_s:
            self.show_save_picker()
        elif ctrl and key == pygame.K_s:
            v.save()
        elif ctrl and key == pygame.K_t:
            v.run_verify()
        elif ctrl and key == pygame.K_j:
            v.open_in_compiler()
        else:
            panel = "vm" if shift and v.show_vm else "jack"
            rows = self.visible_rows(panel)
            moves = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -rows, pygame.K_PAGEDOWN: rows}
            if key in moves:
                v.scroll_by(panel, moves[key], rows)
            elif key == pygame.K_HOME:
                v.scroll_to(panel, 0, rows)
            elif key == pygame.K_END:
                v.scroll_to(panel, len(v.lines(panel)), rows)
        self._update_caption()
        return KEEP

    def click(self, pos) -> bool:
        for rect, action, index in reversed(self.hit):
            if not rect.collidepoint(pos):
                continue
            if action == "tab" and self.viewer:
                self.viewer.select_class(index)
            elif action == "row" and self.mode == "save":
                self.save_picker.activate(index)
            elif action == "row":
                files = self.picker.activate(index)
                if files:
                    self.open_program(files)
            elif action == "save-entry":
                return self.save_into(self.save_picker.choose_save_folder(index))
            elif action == "new-folder":
                if self.save_picker.naming is None:
                    return self.start_new_folder()
                self.save_picker.create_folder()
            elif action == "save-here":
                return self.save_into(self.save_picker.choose_save_folder(here=True))
            elif action == "decompile-entry":
                files = self.picker.decompile_folder_entry(index)
                if files:
                    self.open_program(files)
            elif action == "decompile-here":
                files = self.picker.decompile_folder()
                if files:
                    self.open_program(files)
            elif action == "back":
                return self.leave_save_picker() if self.mode == "save" else self.leave_picker()
            return KEEP
        return KEEP


def run_gui(files: Sequence[Path] = (), rename_functions: bool = True, output_folder: Optional[Path] = None,
            force: bool = False) -> int:
    """Open the window (the file picker if no files are given). `output_folder` is where Ctrl+S saves (-o)."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if files:
        try:
            from ..vm_reader import resolve_inputs

            files = resolve_inputs([str(f) for f in files])
        except FileNotFoundError as problem:
            print(f"jackdecomp: {problem}")
            return 2
    return App(files, rename_functions=rename_functions, output_folder=output_folder, force=force).run()
