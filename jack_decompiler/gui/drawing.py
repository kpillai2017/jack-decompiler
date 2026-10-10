"""
drawing.py - Everything the window draws (used by app.App).
===========================================================

Kept apart from the event handling so each file stays short. Every
clickable thing that gets drawn is recorded in `self.hit` as
(rectangle, action, index); app.App.click() looks the mouse up there.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import pygame

from . import theme

MARGIN, GAP, PADDING, RADIUS = 14, 8, 6, 6


class Painter:
    # --- primitives ------------------------------------------------------------
    def text(self, font, text: str, colour: str, pos) -> int:
        """Draw text; returns its width. Rendered lines are cached (drawing text is slow)."""
        key = (id(font), text, colour)
        surface = self._cache.get(key)
        if surface is None:
            if len(self._cache) > 6000:
                self._cache.clear()
            surface = font.render(text, True, theme.COLOURS[colour])
            self._cache[key] = surface
        self.window.blit(surface, pos)
        return surface.get_width()

    def box(self, rect: pygame.Rect, title: str, title_colour: str = "title") -> pygame.Rect:
        """A jackvm-style box. Returns the rectangle inside it, below the title strip."""
        pygame.draw.rect(self.window, theme.BOX, rect, border_radius=RADIUS)
        header = pygame.Rect(rect.x, rect.y, rect.width, self.header_height())
        pygame.draw.rect(self.window, theme.BOX_HEADER, header, border_top_left_radius=RADIUS,
                         border_top_right_radius=RADIUS)
        pygame.draw.rect(self.window, theme.BORDER, rect, width=1, border_radius=RADIUS)
        self.text(self.ui_font, title, title_colour, (rect.x + PADDING, rect.y + 3))
        return pygame.Rect(rect.x + PADDING, header.bottom + PADDING, rect.width - 2 * PADDING,
                           rect.height - header.height - 2 * PADDING)

    def flow_rows(self, items: Sequence[str], width: int) -> List[str]:
        """Wrap items into rows that fit `width` pixels (like jackvm's SHORTCUTS box)."""
        rows, current = [], ""
        for item in items:
            candidate = item if not current else current + "   " + item
            if current and self.ui_font.size(candidate)[0] > width:
                rows.append(current)
                current = item
            else:
                current = candidate
        return rows + ([current] if current else [])

    def box_height(self, rows: int) -> int:
        return self.header_height() + 2 * PADDING + rows * self.ui_line

    # --- the whole window ---------------------------------------------------------
    def draw(self) -> None:
        self.window.fill(theme.BACKGROUND)
        self.hit = []
        if self.mode == "picker":
            self.draw_picker()
        else:
            self.draw_viewer()

    def draw_bottom_boxes(self, status: List[Tuple[str, str]], help_items: Sequence[str]) -> int:
        """STATUS and SHORTCUTS boxes along the bottom. Returns the y where they start."""
        width, height = self.window.get_size()
        inner = width - 2 * MARGIN - 2 * PADDING
        rows = self.flow_rows(help_items, inner)
        help_rect = pygame.Rect(MARGIN, 0, width - 2 * MARGIN, self.box_height(len(rows)))
        help_rect.bottom = height - MARGIN
        status_rect = pygame.Rect(MARGIN, 0, width - 2 * MARGIN, self.box_height(max(1, len(status))))
        status_rect.bottom = help_rect.top - GAP
        area = self.box(status_rect, "STATUS")
        for i, (line, colour) in enumerate(status):
            self.clipped(self.ui_font, line, colour, area, i)
        area = self.box(help_rect, "SHORTCUTS")
        for i, row in enumerate(rows):
            self.text(self.ui_font, row, "dim", (area.x, area.y + i * self.ui_line))
        return status_rect.top

    def clipped(self, font, line: str, colour: str, area: pygame.Rect, row: int) -> None:
        previous = self.window.get_clip()
        self.window.set_clip(area)
        self.text(font, line, colour, (area.x, area.y + row * self.ui_line))
        self.window.set_clip(previous)

    # --- viewer ----------------------------------------------------------------------
    def draw_viewer(self) -> None:
        v = self.viewer
        width, _ = self.window.get_size()
        bottom = self.draw_bottom_boxes(v.status_lines(), self.viewer_help())

        # Class tabs (one per class; red = couldn't decompile, green = verified).
        x, y = MARGIN, MARGIN
        tab_h = self.ui_line + 8
        for i, name in enumerate(v.class_names):
            cls = v.result.classes[name]
            check = v.checks.get(name)
            colour = "error" if cls.errors or (check and not check.ok) else "good" if check else "normal"
            w = self.ui_font.size(name)[0] + 16
            if x + w > width - MARGIN:
                x, y = MARGIN, y + tab_h + 4
            rect = pygame.Rect(x, y, w, tab_h)
            pygame.draw.rect(self.window, theme.SELECTED if i == v.class_index else theme.BOX, rect, border_radius=4)
            pygame.draw.rect(self.window, theme.BORDER, rect, width=1, border_radius=4)
            self.text(self.ui_font, name, "highlight" if i == v.class_index else colour, (x + 8, y + 4))
            self.hit.append((rect, "tab", i))
            x += w + 4
        top = y + tab_h + GAP if v.class_names else MARGIN

        panels_height = bottom - GAP - top
        full = pygame.Rect(MARGIN, top, width - 2 * MARGIN, panels_height)
        self.panel_rects = {}
        cls = v.current
        if v.show_vm and cls is not None:
            left = pygame.Rect(full.x, full.y, int(full.width * 0.4) - GAP // 2, full.height)
            right = pygame.Rect(left.right + GAP, full.y, full.right - left.right - GAP, full.height)
            self.panel_rects["vm"] = left
            self.draw_code(left, f"VM: {cls.file}", v.lines("vm"), v.scroll["vm"], theme.highlight_vm)
        else:
            right = full
        self.panel_rects["jack"] = right
        title = f"JACK: {cls.jack_file_name}" if cls else "ERROR"
        highlighter = theme.highlight_jack if cls else (lambda line: [(line, "error")])
        self.draw_code(right, title, v.lines("jack"), v.scroll["jack"], highlighter)

    def viewer_help(self) -> List[str]:
        return list(theme.VIEWER_HELP)

    def draw_code(self, rect: pygame.Rect, title: str, lines: List[str], scroll: int, highlighter) -> None:
        rows = max(1, (rect.height - self.header_height() - 2 * PADDING) // self.code_line)
        shown = f"{title}   lines {min(len(lines), scroll + 1)}-{min(len(lines), scroll + rows)} of {len(lines)}"
        area = self.box(rect, shown)
        gutter = self.code_font.size("0000 ")[0]
        previous = self.window.get_clip()
        self.window.set_clip(area)
        for row, number in enumerate(range(scroll, min(len(lines), scroll + rows))):
            y = area.y + row * self.code_line
            self.text(self.code_font, f"{number + 1:4d}", "dim", (area.x, y))
            x = area.x + gutter
            for chunk, colour in highlighter(lines[number].expandtabs(4)):
                if chunk:
                    x += self.text(self.code_font, chunk, colour, (x, y))
                if x > area.right:
                    break
        self.window.set_clip(previous)
        if len(lines) > rows:  # a simple scroll bar
            track = pygame.Rect(rect.right - 5, area.y, 3, area.height)
            thumb_h = max(12, track.height * rows // len(lines))
            thumb_y = track.y + (track.height - thumb_h) * scroll // max(1, len(lines) - rows)
            pygame.draw.rect(self.window, theme.BORDER, (track.x, thumb_y, 3, thumb_h), border_radius=2)

    # --- picker ---------------------------------------------------------------------------
    def draw_picker(self) -> None:
        p = self.picker
        width, _ = self.window.get_size()
        back = "back to program" if self.viewer else "quit"
        help_items = [item.format(back=back) for item in theme.PICKER_HELP]
        status = [(p.message, "error")] if p.message else [("Choose a .vm file, or a folder of .vm files", "normal")]
        bottom = self.draw_bottom_boxes(status, help_items)

        button_h = self.ui_line + 10
        buttons_y = bottom - GAP - button_h
        rect = pygame.Rect(MARGIN, MARGIN, width - 2 * MARGIN, buttons_y - GAP - MARGIN)
        area = self.box(rect, f"OPEN  {p.directory}")
        rows = max(1, area.height // self.ui_line)
        first = max(0, min(p.selected - rows // 2, len(p.entries) - rows))
        previous = self.window.get_clip()
        self.window.set_clip(area)
        for row, index in enumerate(range(first, min(len(p.entries), first + rows))):
            entry = p.entries[index]
            y = area.y + row * self.ui_line
            line_rect = pygame.Rect(area.x - 2, y, area.width + 4, self.ui_line)
            if index == p.selected:
                pygame.draw.rect(self.window, theme.SELECTED, line_rect, border_radius=3)
            colour = "dim" if entry.kind == "folder" and not entry.vm_count else "normal"
            self.text(self.ui_font, entry.label, colour, (area.x + 4, y))
            self.hit.append((line_rect, "row", index))
            if entry.kind == "folder" and entry.vm_count:
                tag = f"[decompile {entry.vm_count} file{'s' if entry.vm_count != 1 else ''}]"
                tag_w = self.ui_font.size(tag)[0]
                tag_rect = pygame.Rect(area.right - tag_w - 6, y, tag_w + 4, self.ui_line)
                self.text(self.ui_font, tag, "title", (tag_rect.x, y))
                self.hit.append((tag_rect, "decompile-entry", index))
        self.window.set_clip(previous)

        count = p.current_folder_vm_count()
        label = f"Decompile this folder ({count} .vm)" if count else "Decompile this folder"
        x = MARGIN
        for text, action, enabled in ((label, "decompile-here", bool(count)),
                                      ("Back" if self.viewer else "Quit", "back", True)):
            w = self.ui_font.size(text)[0] + 24
            button = pygame.Rect(x, buttons_y, w, button_h)
            pygame.draw.rect(self.window, theme.BOX_HEADER if enabled else theme.BOX, button, border_radius=5)
            pygame.draw.rect(self.window, theme.BORDER, button, width=1, border_radius=5)
            self.text(self.ui_font, text, "normal" if enabled else "dim", (x + 12, buttons_y + 5))
            if enabled:
                self.hit.append((button, action, 0))
            x += w + GAP

