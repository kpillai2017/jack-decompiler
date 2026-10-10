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
    Ctrl+J  save, then open in the Jack compiler (as in jackvm)
    Ctrl+Q  quit (closing the window works too)
    Up/Down, PgUp/PgDn, Home/End, mouse wheel: scroll (add Shift for the VM panel)

In the picker: Enter opens/decompiles, Ctrl+Enter decompiles the folder,
Backspace/Left goes up, Right goes in, Esc goes back (or quits).

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
from .picker import PAGE, PickerState
from .viewer import ViewerState

WINDOW_SIZE = (1280, 820)
MIN_SIZE = (720, 480)
QUIT, KEEP = False, True


def is_ctrl(mod: int) -> bool:
    return bool(mod & (pygame.KMOD_CTRL | pygame.KMOD_META))


class App(Painter):
    def __init__(self, files: Sequence[Path] = (), start_dir: Optional[Path] = None, rename_functions: bool = True,
                 window_size: Tuple[int, int] = WINDOW_SIZE):
        pygame.init()
        pygame.key.set_repeat(300, 35)
        self.window = pygame.display.set_mode(window_size, pygame.RESIZABLE)
        self.ui_font = pygame.font.SysFont(theme.FONT_NAMES, theme.UI_FONT_SIZE)
        self.code_font = pygame.font.SysFont(theme.FONT_NAMES, theme.CODE_FONT_SIZE)
        self.ui_line = self.ui_font.get_linesize()
        self.code_line = self.code_font.get_linesize()
        self.rename_functions = rename_functions
        self.viewer: Optional[ViewerState] = None
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
        self.viewer = ViewerState(files, self.rename_functions)
        self.mode = "viewer"
        self._update_caption()

    def _update_caption(self) -> None:
        title = self.viewer.title() if self.viewer and self.mode == "viewer" else "Jack decompiler - choose a program"
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
            return self.picker_key(event) if self.mode == "picker" else self.viewer_key(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self.click(event.pos)
        if event.type == pygame.MOUSEWHEEL and self.mode == "viewer" and self.viewer:
            panel = self.panel_at(pygame.mouse.get_pos())
            self.viewer.scroll_by(panel, -3 * event.y, self.visible_rows(panel))
        elif event.type == pygame.MOUSEWHEEL and self.mode == "picker":
            self.picker.move(-event.y)
        return KEEP

    def panel_at(self, pos) -> str:
        vm = self.panel_rects.get("vm")
        return "vm" if vm is not None and vm.collidepoint(pos) else "jack"

    def show_picker(self) -> None:
        self.mode = "picker"
        if self.viewer and self.viewer.files:
            self.picker.change_directory(self.viewer.files[0].parent.resolve())
        self._update_caption()

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
        elif key in (pygame.K_BACKSPACE, pygame.K_LEFT):
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
        if files:
            self.open_program(files)
        return KEEP

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
            elif action == "row":
                files = self.picker.activate(index)
                if files:
                    self.open_program(files)
            elif action == "decompile-entry":
                files = self.picker.decompile_folder_entry(index)
                if files:
                    self.open_program(files)
            elif action == "decompile-here":
                files = self.picker.decompile_folder()
                if files:
                    self.open_program(files)
            elif action == "back":
                return self.leave_picker()
            return KEEP
        return KEEP


def run_gui(files: Sequence[Path] = (), rename_functions: bool = True) -> int:
    """Open the window (the file picker if no files are given)."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if files:
        try:
            from ..vm_reader import resolve_inputs

            files = resolve_inputs([str(f) for f in files])
        except FileNotFoundError as problem:
            print(f"jackdecomp: {problem}")
            return 2
    return App(files, rename_functions=rename_functions).run()
