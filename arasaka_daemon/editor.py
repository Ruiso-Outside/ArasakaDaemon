"""
ARASAKA DAEMON // editor de codigo.

QPlainTextEdit com numeros de linha, marcadores de erro, linha atual,
pares de colchetes, indentacao automatica, fechamento de pares, comentar
linhas, mover/duplicar linhas, autocompletar (LSP ou palavras do arquivo)
e eventos para hover / ir para definicao.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRect, QSize, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QStandardItem, QStandardItemModel,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QTextEdit, QToolTip, QWidget

from . import languages
from .highlighter import Highlighter
from .kit import FONTS

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`"}
CLOSERS = {")", "]", "}"}
TWO_SPACE = {"javascript", "typescript", "json", "yaml", "html", "xml", "css", "ruby", "dart", "lua", "vue"}
TABS = {"go", "makefile"}

KIND_ICON = {1: "txt", 2: "fn()", 3: "fn()", 4: "new", 5: "fld", 6: "var", 7: "cls", 8: "ifc", 9: "mod",
             10: "prop", 12: "val", 13: "enum", 14: "kw", 15: "snip", 17: "file", 18: "ref", 19: "dir",
             20: "enum", 21: "const", 22: "struct", 23: "evt", 24: "op", 25: "T"}


def read_file(path: Path) -> tuple[str, str, str]:
    """Retorna (texto, encoding, quebra de linha)."""
    raw = Path(path).read_bytes()
    enc = "utf-8"
    if raw.startswith(b"\xef\xbb\xbf"):
        enc, raw = "utf-8-sig", raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = "latin-1"
        text = raw.decode("latin-1")
    nl = "\r\n" if "\r\n" in text[:20000] else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc, nl


class Gutter(QWidget):
    def __init__(self, ed: "CodeEditor"):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_gutter(e)

    def mousePressEvent(self, e):
        c = self.ed.cursorForPosition(e.position().toPoint())
        c.movePosition(QTextCursor.StartOfBlock)
        c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        self.ed.setTextCursor(c)


class CodeEditor(QPlainTextEdit):
    cursor_moved = Signal(int, int)
    text_changed_debounced = Signal()
    hover_requested = Signal(int, int, object)       # linha, coluna, QPoint global
    definition_requested = Signal(int, int)
    completion_requested = Signal(int, int, str)     # linha, coluna, caractere gatilho

    def __init__(self, path: Path | None = None, settings: dict | None = None):
        super().__init__()
        self.path = Path(path) if path else None
        self.settings = settings or {}
        self.lang = languages.detect(path) if path else languages.PLAIN
        self.encoding = "utf-8"
        self.newline = "\n"
        self.version = 1
        self.diagnostics: list[dict] = []
        self.search_hits: list[QTextCursor] = []
        self.untitled_name = ""
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self.set_font_size(int(self.settings.get("font_size", 14)))
        self.gutter = Gutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._cursor_changed)
        self._update_gutter_width()
        if path:
            text, self.encoding, self.newline = read_file(self.path)
            self.setPlainText(text)
        self.document().setModified(False)
        self.highlighter = Highlighter(self.document(), self.lang)
        self.indent_unit = "\t" if self.lang.id in TABS else " " * (2 if self.lang.id in TWO_SPACE else
                                                                     int(self.settings.get("tab_size", 4)))
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * 4)
        # debounce para LSP / status
        self._deb = QTimer(self)
        self._deb.setSingleShot(True)
        self._deb.setInterval(350)
        self._deb.timeout.connect(self.text_changed_debounced.emit)
        self.textChanged.connect(self._on_text)
        # hover
        self._hover = QTimer(self)
        self._hover.setSingleShot(True)
        self._hover.setInterval(650)
        self._hover.timeout.connect(self._fire_hover)
        self._hover_pos = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # autocompletar
        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self.model, self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated[str].connect(self.insert_completion)
        pop = self.completer.popup()
        pop.setStyleSheet(f"QListView {{ background: #070708; border: 1px solid #e3121f; color: #ececf0;"
                          f" font-family: '{FONTS['code']}'; font-size: {self.font().pointSize()}pt; }}"
                          "QListView::item { padding: 4px 8px; }"
                          "QListView::item:selected { background: rgba(227,18,31,0.45); }")
        self._complete_timer = QTimer(self)
        self._complete_timer.setSingleShot(True)
        self._complete_timer.setInterval(180)
        self._complete_timer.timeout.connect(lambda: self.request_completion(""))
        self._cursor_changed()

    # ------------------------------------------------------------ util
    def title(self) -> str:
        return self.path.name if self.path else (self.untitled_name or "sem titulo")

    def set_font_size(self, size: int):
        size = max(7, min(40, size))
        f = QFont(FONTS["code"])
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(size)
        self.setFont(f)
        # o stylesheet global define fonte para '*': o do editor precisa repetir a fonte de codigo
        self.setStyleSheet(f"QPlainTextEdit {{ background: #0a0a0c; color: #d8d8de; border: none;"
                           f" font-family: '{FONTS['code']}'; font-size: {size}pt;"
                           f" selection-background-color: rgba(227,18,31,0.45); selection-color: #ffffff; }}")
        self.setTabStopDistance(QFontMetricsF(f).horizontalAdvance(" ") * 4)
        if hasattr(self, "gutter"):
            self._update_gutter_width()

    def zoom(self, delta: int):
        self.set_font_size(self.font().pointSize() + delta)

    def set_language(self, lang):
        self.lang = lang
        self.highlighter.setDocument(None)
        self.highlighter = Highlighter(self.document(), lang)

    def save(self, path: Path | None = None) -> None:
        if path:
            self.path = Path(path)
            if self.lang.id == "plaintext":
                self.set_language(languages.detect(self.path))
        text = self.toPlainText()
        if self.settings.get("trim_whitespace", True):
            text = re.sub(r"[ \t]+(?=\n)", "", text)
        if self.settings.get("final_newline", True) and text and not text.endswith("\n"):
            text += "\n"
        data = text.replace("\n", self.newline).encode(self.encoding if self.encoding != "latin-1" else "latin-1",
                                                       errors="replace")
        self.path.write_bytes(data)
        self.document().setModified(False)

    def reload(self):
        if not self.path or not self.path.exists():
            return
        text, self.encoding, self.newline = read_file(self.path)
        c = self.textCursor()
        pos = c.position()
        self.setPlainText(text)
        c = self.textCursor()
        c.setPosition(min(pos, len(text)))
        self.setTextCursor(c)
        self.document().setModified(False)

    def line_col(self) -> tuple[int, int]:
        c = self.textCursor()
        return c.blockNumber(), c.positionInBlock()

    def goto(self, line: int, col: int = 0, select_len: int = 0):
        b = self.document().findBlockByNumber(max(0, line))
        c = QTextCursor(b)
        c.movePosition(QTextCursor.Right, n=min(col, max(0, b.length() - 1)))
        if select_len:
            c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, select_len)
        self.setTextCursor(c)
        self.centerCursor()
        self.setFocus()

    def cursor_at(self, line: int, col: int) -> QTextCursor:
        b = self.document().findBlockByNumber(max(0, min(line, self.document().blockCount() - 1)))
        c = QTextCursor(b)
        c.movePosition(QTextCursor.Right, n=min(col, max(0, b.length() - 1)))
        return c

    def _on_text(self):
        self.version += 1
        self._deb.start()

    # ------------------------------------------------------------ gutter
    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return int(24 + QFontMetricsF(self.font()).horizontalAdvance("9") * digits)

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, e):
        p = QPainter(self.gutter)
        p.fillRect(e.rect(), QColor(7, 7, 8))
        p.setPen(QColor(42, 10, 13))
        p.drawLine(self.gutter.width() - 1, e.rect().top(), self.gutter.width() - 1, e.rect().bottom())
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        diag_lines = {}
        for d in self.diagnostics:
            ln = d["range"]["start"]["line"]
            sev = d.get("severity", 1)
            diag_lines[ln] = min(sev, diag_lines.get(ln, 9))
        fh = self.fontMetrics().height()
        f = QFont(self.font())
        p.setFont(f)
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and bottom >= e.rect().top():
                if num in diag_lines:
                    col = QColor(255, 46, 64) if diag_lines[num] == 1 else QColor(255, 179, 71)
                    p.fillRect(4, top + fh // 2 - 3, 6, 6, col)
                p.setPen(QColor(255, 46, 64) if num == cur else QColor(78, 78, 88))
                p.drawText(0, top, self.gutter.width() - 10, fh, Qt.AlignRight | Qt.AlignVCenter, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    # ------------------------------------------------------------ selecoes extras
    def _cursor_changed(self):
        self.update_extra()
        ln, col = self.line_col()
        self.cursor_moved.emit(ln, col)
        self.gutter.update()

    def update_extra(self):
        sels = []
        cur = QTextEdit.ExtraSelection()
        cur.format.setBackground(QColor(22, 8, 11))
        cur.format.setProperty(QTextFormat.FullWidthSelection, True)
        cur.cursor = self.textCursor()
        cur.cursor.clearSelection()
        sels.append(cur)
        for hit in self.search_hits:
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(255, 179, 71, 70))
            s.cursor = hit
            sels.append(s)
        for d in self.diagnostics:
            r = d["range"]
            c = self.cursor_at(r["start"]["line"], r["start"]["character"])
            end = self.cursor_at(r["end"]["line"], r["end"]["character"])
            if end.position() <= c.position():
                end = QTextCursor(c)
                end.movePosition(QTextCursor.EndOfWord)
                if end.position() <= c.position():
                    end.movePosition(QTextCursor.Right)
            c.setPosition(end.position(), QTextCursor.KeepAnchor)
            s = QTextEdit.ExtraSelection()
            s.format.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
            sev = d.get("severity", 1)
            s.format.setUnderlineColor(QColor(255, 46, 64) if sev == 1 else
                                       QColor(255, 179, 71) if sev == 2 else QColor(143, 193, 196))
            s.cursor = c
            sels.append(s)
        sels += self._bracket_match()
        self.setExtraSelections(sels)

    def _bracket_match(self):
        doc = self.document()
        pos = self.textCursor().position()
        opens, closes = "([{", ")]}"
        out = []
        for p in (pos, pos - 1):
            if p < 0:
                continue
            ch = doc.characterAt(p)
            if ch in opens or ch in closes:
                fwd = ch in opens
                mate = closes[opens.index(ch)] if fwd else opens[closes.index(ch)]
                depth, i = 0, p
                limit = 200000
                while 0 <= i < doc.characterCount() and limit:
                    c = doc.characterAt(i)
                    if c == ch:
                        depth += 1
                    elif c == mate:
                        depth -= 1
                        if depth == 0:
                            for q in (p, i):
                                s = QTextEdit.ExtraSelection()
                                s.format.setBackground(QColor(227, 18, 31, 70))
                                s.format.setForeground(QColor(255, 255, 255))
                                s.cursor = QTextCursor(doc)
                                s.cursor.setPosition(q)
                                s.cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
                                out.append(s)
                            return out
                    i += 1 if fwd else -1
                    limit -= 1
                return out
        return out

    def set_diagnostics(self, diags: list[dict]):
        self.diagnostics = diags
        self.update_extra()
        self.gutter.update()

    # ------------------------------------------------------------ teclado
    def keyPressEvent(self, e):
        pop = self.completer.popup()
        if pop.isVisible():
            if e.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab):
                idx = pop.currentIndex()
                if idx.isValid():
                    self.insert_completion(idx.data(Qt.UserRole + 1) or idx.data())
                pop.hide()
                return
            if e.key() in (Qt.Key_Escape, Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
                if e.key() == Qt.Key_Escape:
                    pop.hide()
                    return
                e.ignore()
                return
        key, mod, txt = e.key(), e.modifiers(), e.text()
        ctrl = bool(mod & Qt.ControlModifier)
        shift = bool(mod & Qt.ShiftModifier)
        alt = bool(mod & Qt.AltModifier)
        c = self.textCursor()

        if ctrl and key == Qt.Key_Space:
            self.request_completion("")
            return
        if ctrl and key == Qt.Key_Slash:
            self.toggle_comment()
            return
        if ctrl and key == Qt.Key_D:
            self.duplicate_line()
            return
        if ctrl and shift and key == Qt.Key_K:
            self.delete_line()
            return
        if alt and key in (Qt.Key_Up, Qt.Key_Down):
            self.move_line(-1 if key == Qt.Key_Up else 1)
            return
        if key == Qt.Key_Tab and not ctrl:
            if c.hasSelection() and " " in c.selectedText():
                self.indent_lines(1)
            else:
                c.insertText(self.indent_unit if self.indent_unit == "\t" else
                             " " * (len(self.indent_unit) - c.positionInBlock() % len(self.indent_unit)))
            return
        if key == Qt.Key_Backtab:
            self.indent_lines(-1)
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and not ctrl:
            self.newline_indent()
            return
        if key == Qt.Key_Backspace and not c.hasSelection() and not ctrl:
            line = c.block().text()[:c.positionInBlock()]
            nxt = self.document().characterAt(c.position())
            if line and line[-1] in PAIRS and PAIRS[line[-1]] == nxt:
                c.deleteChar()
                c.deletePreviousChar()
                return
            if line and not line.strip() and self.indent_unit != "\t":
                n = len(line) % len(self.indent_unit) or len(self.indent_unit)
                for _ in range(n):
                    c.deletePreviousChar()
                return
        if key == Qt.Key_Home and not ctrl:
            line = c.block().text()
            ind = len(line) - len(line.lstrip())
            target = ind if c.positionInBlock() != ind else 0
            c.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor if shift else QTextCursor.MoveAnchor)
            c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor if shift else QTextCursor.MoveAnchor, target)
            self.setTextCursor(c)
            return
        # fechamento automatico de pares
        if txt and self.settings.get("auto_close", True):
            nxt = self.document().characterAt(c.position())
            if txt in CLOSERS or (txt in "\"'`" and nxt == txt):
                if nxt == txt and not c.hasSelection():
                    c.movePosition(QTextCursor.Right)
                    self.setTextCursor(c)
                    return
            if txt in PAIRS and (txt not in "\"'`" or self._quote_ok(c, txt)):
                if c.hasSelection():
                    sel = c.selectedText()
                    c.insertText(txt + sel + PAIRS[txt])
                    return
                if not nxt.strip() or nxt in ")]};,":
                    c.insertText(txt + PAIRS[txt])
                    c.movePosition(QTextCursor.Left)
                    self.setTextCursor(c)
                    return
        super().keyPressEvent(e)
        # gatilhos de autocompletar
        if txt and self.settings.get("autocomplete", True):
            if txt in (".", ":", ">", "/", "@") and self._trigger_ok(txt):
                self.request_completion(txt)
            elif re.match(r"\w", txt):
                prefix = self.word_prefix()
                if len(prefix) >= 2 or self.completer.popup().isVisible():
                    self._complete_timer.start()
            elif self.completer.popup().isVisible():
                self.completer.popup().hide()

    def _quote_ok(self, c: QTextCursor, q: str) -> bool:
        before = c.block().text()[:c.positionInBlock()]
        return not (before and (before[-1].isalnum() or before[-1] == "\\"))

    def _trigger_ok(self, ch: str) -> bool:
        before = self.textCursor().block().text()[:self.textCursor().positionInBlock()]
        if ch == ".":
            return bool(re.search(r"[\w)\]]\.$", before))
        if ch == ":":
            return before.endswith("::")
        if ch == ">":
            return before.endswith("->")
        return ch in "/@" and self.lang.id in ("html", "css", "javascript", "typescript", "python")

    def newline_indent(self):
        c = self.textCursor()
        line = c.block().text()
        before = line[:c.positionInBlock()]
        after = line[c.positionInBlock():]
        indent = re.match(r"[ \t]*", line).group(0)
        if c.positionInBlock() < len(indent):
            indent = indent[:c.positionInBlock()]
        stripped = before.rstrip()
        extra = ""
        if stripped.endswith((":",)) and self.lang.id in ("python", "yaml"):
            extra = self.indent_unit
        elif stripped.endswith(("{", "[", "(")) or (self.lang.id == "lua" and re.search(r"\b(then|do)$", stripped)):
            extra = self.indent_unit
        elif self.lang.markup and re.search(r"<([\w-]+)[^>/]*>$", stripped) and not re.search(r"</", stripped[-3:]):
            extra = self.indent_unit
        c.beginEditBlock()
        if extra and after.strip()[:1] in ("}", "]", ")") or (extra and self.lang.markup and after.startswith("</")):
            c.insertText("\n" + indent + extra + "\n" + indent)
            c.movePosition(QTextCursor.Up)
            c.movePosition(QTextCursor.EndOfBlock)
        else:
            c.insertText("\n" + indent + extra)
        c.endEditBlock()
        self.setTextCursor(c)

    def _selected_blocks(self):
        c = self.textCursor()
        doc = self.document()
        start = doc.findBlock(c.selectionStart())
        end = doc.findBlock(c.selectionEnd() if not (c.hasSelection() and c.selectionEnd() ==
                                                     doc.findBlock(c.selectionEnd()).position()) else
                            c.selectionEnd() - 1)
        blocks = []
        b = start
        while b.isValid():
            blocks.append(b)
            if b == end:
                break
            b = b.next()
        return blocks

    def indent_lines(self, direction: int):
        c = self.textCursor()
        c.beginEditBlock()
        for b in self._selected_blocks():
            bc = QTextCursor(b)
            if direction > 0:
                bc.insertText(self.indent_unit)
            else:
                t = b.text()
                n = 1 if t.startswith("\t") else min(len(self.indent_unit), len(t) - len(t.lstrip(" ")))
                for _ in range(n):
                    bc.deleteChar()
        c.endEditBlock()

    def toggle_comment(self):
        lc = self.lang.line_comment
        bc = self.lang.block_comment
        blocks = self._selected_blocks()
        c = self.textCursor()
        c.beginEditBlock()
        if lc:
            tok = lc.rstrip() if lc.strip() else lc
            texts = [b.text() for b in blocks if b.text().strip()]
            all_commented = texts and all(t.lstrip().startswith(tok) for t in texts)
            ind = min((len(t) - len(t.lstrip()) for t in texts), default=0)
            for b in blocks:
                t = b.text()
                if not t.strip():
                    continue
                bc_ = QTextCursor(b)
                if all_commented:
                    i = t.index(tok)
                    n = len(tok) + (1 if t[i + len(tok):i + len(tok) + 1] == " " else 0)
                    bc_.movePosition(QTextCursor.Right, n=i)
                    bc_.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, n)
                    bc_.removeSelectedText()
                else:
                    bc_.movePosition(QTextCursor.Right, n=ind)
                    bc_.insertText(tok + " ")
        elif bc:
            first, last = blocks[0], blocks[-1]
            t0, t1 = first.text(), last.text()
            if t0.lstrip().startswith(bc[0]) and t1.rstrip().endswith(bc[1]):
                e = QTextCursor(last)
                e.movePosition(QTextCursor.EndOfBlock)
                for _ in range(len(bc[1]) + (1 if t1.rstrip().endswith(" " + bc[1]) else 0)):
                    e.deletePreviousChar()
                s = QTextCursor(first)
                i = t0.index(bc[0])
                s.movePosition(QTextCursor.Right, n=i)
                s.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor,
                               len(bc[0]) + (1 if t0[i + len(bc[0]):i + len(bc[0]) + 1] == " " else 0))
                s.removeSelectedText()
            else:
                s = QTextCursor(first)
                s.movePosition(QTextCursor.Right, n=len(t0) - len(t0.lstrip()))
                s.insertText(bc[0] + " ")
                e = QTextCursor(last)
                e.movePosition(QTextCursor.EndOfBlock)
                e.insertText(" " + bc[1])
        c.endEditBlock()

    def duplicate_line(self):
        c = self.textCursor()
        if c.hasSelection():
            t = c.selectedText()
            c.setPosition(c.selectionEnd())
            c.insertText(t)
            return
        t = c.block().text()
        col = c.positionInBlock()
        c.movePosition(QTextCursor.EndOfBlock)
        c.insertText("\n" + t)
        c.movePosition(QTextCursor.StartOfBlock)
        c.movePosition(QTextCursor.Right, n=col)
        self.setTextCursor(c)

    def delete_line(self):
        c = self.textCursor()
        c.beginEditBlock()
        blocks = self._selected_blocks()
        c.setPosition(blocks[0].position())
        last = blocks[-1]
        if last.next().isValid():
            c.setPosition(last.next().position(), QTextCursor.KeepAnchor)
        else:
            c.setPosition(last.position() + last.length() - 1, QTextCursor.KeepAnchor)
            if blocks[0].previous().isValid():
                c2 = QTextCursor(c)
                c.setPosition(blocks[0].previous().position() + blocks[0].previous().length() - 1)
                c.setPosition(c2.position(), QTextCursor.KeepAnchor)
        c.removeSelectedText()
        c.endEditBlock()

    def move_line(self, d: int):
        blocks = self._selected_blocks()
        first, last = blocks[0], blocks[-1]
        other = first.previous() if d < 0 else last.next()
        if not other.isValid():
            return
        c = self.textCursor()
        col = c.positionInBlock()
        lines = [b.text() for b in blocks]
        ot = other.text()
        c.beginEditBlock()
        s = QTextCursor(first if d > 0 else other)
        e_block = other if d > 0 else last
        s.setPosition(e_block.position() + e_block.length() - 1, QTextCursor.KeepAnchor)
        new = ([ot] + lines) if d > 0 else (lines + [ot])
        s.insertText("\n".join(new))
        c.endEditBlock()
        target = self.document().findBlockByNumber(first.blockNumber() + d)
        nc = QTextCursor(target)
        nc.movePosition(QTextCursor.Right, n=min(col, len(target.text())))
        self.setTextCursor(nc)

    # ------------------------------------------------------------ autocompletar
    def word_prefix(self) -> str:
        c = self.textCursor()
        before = c.block().text()[:c.positionInBlock()]
        m = re.search(r"[\w$]+$", before)
        return m.group(0) if m else ""

    def request_completion(self, trigger: str):
        ln, col = self.line_col()
        self.completion_requested.emit(ln, col, trigger)

    def show_completions(self, items: list[dict]):
        """items: [{'label','insert','detail','kind'}]"""
        prefix = self.word_prefix()
        if not items:
            items = self.word_items(prefix)
        self.model.clear()
        seen = set()
        for it in items[:400]:
            lab = it["label"]
            if lab in seen:
                continue
            seen.add(lab)
            kind = KIND_ICON.get(it.get("kind"), "")
            row = QStandardItem(f"{lab}" + (f"    {it.get('detail', '')[:40]}" if it.get("detail") else ""))
            row.setData(it.get("insert") or lab, Qt.UserRole + 1)
            row.setData(lab, Qt.UserRole + 2)
            if kind:
                row.setToolTip(kind)
            self.model.appendRow(row)
        if not self.model.rowCount():
            self.completer.popup().hide()
            return
        self.completer.setCompletionRole(Qt.UserRole + 2)
        self.completer.setCompletionPrefix(prefix)
        if self.completer.completionCount() == 0:
            self.completer.popup().hide()
            return
        if self.completer.completionCount() == 1 and self.completer.currentCompletion() == prefix:
            self.completer.popup().hide()
            return
        cr = self.cursorRect()
        cr.setWidth(max(320, self.completer.popup().sizeHintForColumn(0) + 30))
        cr.translate(self.gutter_width(), 4)
        self.completer.complete(cr)
        self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))

    def word_items(self, prefix: str) -> list[dict]:
        words = set(re.findall(r"[A-Za-z_][\w]{2,}", self.toPlainText()))
        words.update(w for w in (self.lang.keywords + " " + self.lang.builtins + " " + self.lang.types).split())
        words.discard(prefix)
        return [{"label": w, "insert": w} for w in sorted(words) if not prefix or prefix.lower() in w.lower()]

    def insert_completion(self, text: str):
        idx = self.completer.popup().currentIndex()
        insert = idx.data(Qt.UserRole + 1) if idx.isValid() else text
        insert = insert or text
        prefix = self.word_prefix()
        c = self.textCursor()
        c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(prefix))
        c.insertText(insert)
        self.setTextCursor(c)
        self.completer.popup().hide()

    # ------------------------------------------------------------ mouse: hover e Ctrl+clique
    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        self._hover_pos = e.position().toPoint()
        self._hover.start()
        self.viewport().setCursor(Qt.PointingHandCursor if e.modifiers() & Qt.ControlModifier else Qt.IBeamCursor)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.modifiers() & Qt.ControlModifier and e.button() == Qt.LeftButton:
            c = self.cursorForPosition(e.position().toPoint())
            self.definition_requested.emit(c.blockNumber(), c.positionInBlock())

    def leaveEvent(self, e):
        self._hover.stop()
        super().leaveEvent(e)

    def _fire_hover(self):
        if self._hover_pos is None:
            return
        c = self.cursorForPosition(self._hover_pos)
        ln, col = c.blockNumber(), c.positionInBlock()
        gp = self.viewport().mapToGlobal(self._hover_pos)
        msgs = []
        for d in self.diagnostics:
            r = d["range"]
            if r["start"]["line"] <= ln <= r["end"]["line"]:
                src = f" [{d['source']}]" if d.get("source") else ""
                msgs.append(("ERRO" if d.get("severity", 1) == 1 else "AVISO") + ": " + d.get("message", "") + src)
        if msgs:
            QToolTip.showText(gp, "\n".join(msgs[:6]), self)
            return
        line = c.block().text()
        if col < len(line) and re.match(r"\w", line[col]):
            self.hover_requested.emit(ln, col, gp)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(1 if e.angleDelta().y() > 0 else -1)
            return
        super().wheelEvent(e)

    # ------------------------------------------------------------ busca
    def find_all(self, text: str, case: bool, regex: bool, whole: bool) -> int:
        self.search_hits = []
        if text:
            flags = QTextDocument.FindFlag(0)
            if case:
                flags |= QTextDocument.FindCaseSensitively
            if whole:
                flags |= QTextDocument.FindWholeWords
            doc = self.document()
            from PySide6.QtCore import QRegularExpression
            needle = QRegularExpression(text, QRegularExpression.NoPatternOption if case else
                                        QRegularExpression.CaseInsensitiveOption) if regex else text
            c = QTextCursor(doc)
            while True:
                c = doc.find(needle, c, flags)
                if c.isNull() or len(self.search_hits) > 5000:
                    break
                if c.selectionStart() == c.selectionEnd():
                    c.movePosition(QTextCursor.Right)
                    continue
                self.search_hits.append(QTextCursor(c))
        self.update_extra()
        return len(self.search_hits)

    def find_step(self, forward: bool):
        if not self.search_hits:
            return
        pos = self.textCursor().selectionEnd() if forward else self.textCursor().selectionStart()
        hits = self.search_hits
        target = None
        if forward:
            target = next((h for h in hits if h.selectionStart() >= pos), hits[0])
        else:
            target = next((h for h in reversed(hits) if h.selectionEnd() <= pos), hits[-1])
        self.setTextCursor(QTextCursor(target))
        self.centerCursor()

    def replace_current(self, find: str, repl: str, case, regex, whole):
        c = self.textCursor()
        if c.hasSelection() and any(h.selectionStart() == c.selectionStart() and h.selectionEnd() == c.selectionEnd()
                                    for h in self.search_hits):
            if regex:
                repl = re.sub(find, repl, c.selectedText(), count=1, flags=0 if case else re.I)
            c.insertText(repl)
        self.find_all(find, case, regex, whole)
        self.find_step(True)

    def replace_all(self, find: str, repl: str, case, regex, whole) -> int:
        n = self.find_all(find, case, regex, whole)
        c = self.textCursor()
        c.beginEditBlock()
        for h in reversed(self.search_hits):
            t = re.sub(find, repl, h.selectedText(), count=1, flags=0 if case else re.I) if regex else repl
            h.insertText(t)
        c.endEditBlock()
        self.search_hits = []
        self.update_extra()
        return n

    # ------------------------------------------------------------ edicoes LSP
    def apply_edits(self, edits: list[dict]):
        """Aplica TextEdits do LSP (de tras para frente)."""
        def key(ed):
            s = ed["range"]["start"]
            return (s["line"], s["character"])
        c = self.textCursor()
        c.beginEditBlock()
        for ed in sorted(edits, key=key, reverse=True):
            r = ed["range"]
            a = self.cursor_at(r["start"]["line"], r["start"]["character"])
            b = self.cursor_at(r["end"]["line"], r["end"]["character"])
            if r["end"]["line"] >= self.document().blockCount():
                b = QTextCursor(self.document())
                b.movePosition(QTextCursor.End)
            a.setPosition(b.position(), QTextCursor.KeepAnchor)
            a.insertText(ed["newText"].replace("\r\n", "\n"))
        c.endEditBlock()
