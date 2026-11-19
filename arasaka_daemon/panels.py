"""
ARASAKA DAEMON // paineis: terminal, saida, problemas, busca em arquivos,
icones do explorador, abrir rapido / paleta de comandos, barra de busca.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from PySide6.QtCore import QFileInfo, QProcess, QProcessEnvironment, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileIconProvider, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import languages
from .kit import FONTS, button, label, spaced

IGNORE_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build",
               "target", ".idea", ".vscode", ".mypy_cache", ".pytest_cache", "bin", "obj", ".gradle", ".next",
               ".cache", ".tox", "out"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def walk_files(root: Path, limit: int = 30000):
    n = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".") or d == ".github")
        for f in sorted(files):
            yield Path(dirpath) / f
            n += 1
            if n >= limit:
                return


def mono_font(size: int = 12) -> QFont:  # noqa: D401
    f = QFont(FONTS["code"])
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(size)
    return f


# ================================================================ icones
_ICON_CACHE: dict = {}


def lang_icon(lang: languages.Language) -> QIcon:
    if lang.id in _ICON_CACHE:
        return _ICON_CACHE[lang.id]
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(lang.color)
    if c.lightness() < 60:
        c = c.lighter(260)
    p.fillRect(QRectF(2, 6, 28, 20), QColor(c.red(), c.green(), c.blue(), 60))
    p.setPen(QPen(c, 2))
    p.drawRect(QRectF(2, 6, 28, 20))
    f = QFont(FONTS["ui"])
    f.setPixelSize(11 if len(lang.abbr) > 2 else 13)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(240, 240, 245))
    p.drawText(QRectF(0, 6, 32, 20), Qt.AlignCenter, lang.abbr)
    p.end()
    ic = QIcon(pm)
    _ICON_CACHE[lang.id] = ic
    return ic


def folder_icon(open_: bool = False) -> QIcon:
    key = "__dir_open" if open_ else "__dir"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(227, 18, 31), 2))
    p.setBrush(QColor(227, 18, 31, 90 if open_ else 40))
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    p.drawPolygon(QPolygonF([QPointF(3, 8), QPointF(13, 8), QPointF(16, 11), QPointF(29, 11), QPointF(29, 26),
                             QPointF(3, 26)]))
    p.end()
    ic = QIcon(pm)
    _ICON_CACHE[key] = ic
    return ic


class IconProvider(QFileIconProvider):
    def icon(self, arg):
        if isinstance(arg, QFileInfo):
            if arg.isDir():
                return folder_icon()
            return lang_icon(languages.detect(arg.fileName()))
        return super().icon(arg)


# ================================================================ terminal
class Terminal(QWidget):
    """Terminal simples: um shell persistente (bash / PowerShell) com entrada de linha."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.out = QPlainTextEdit()
        self.out.setObjectName("console")
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(5000)
        self.out.setFont(mono_font(13))
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        row.setContentsMargins(8, 4, 8, 4)
        self.prompt = label("▶", "red", 0, 13, True)
        row.addWidget(self.prompt)
        self.inp = QLineEdit()
        self.inp.setFont(mono_font(13))
        self.inp.setPlaceholderText("digite um comando e Enter  (setas: historico)")
        self.inp.returnPressed.connect(self.submit)
        self.inp.installEventFilter(self)
        row.addWidget(self.inp, 1)
        row.addWidget(button("CTRL+C", "ghost", self.interrupt, "Interrompe o comando atual"))
        row.addWidget(button("REINICIAR", "ghost", self.restart))
        lay.addLayout(row)
        self.history: list[str] = []
        self.hidx = 0
        self.cwd = Path.home()
        self.proc: QProcess | None = None

    def start(self, cwd: Path):
        self.cwd = Path(cwd)
        self.restart()

    def restart(self):
        if self.proc:
            self.proc.kill()
            self.proc.waitForFinished(500)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setWorkingDirectory(str(self.cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("TERM", "dumb")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._read)
        argv = languages.interactive_shell()
        self.proc.start(argv[0], argv[1:])
        self.append(f"■ shell: {Path(argv[0]).name}  ·  {self.cwd}\n", "#ff2e40")

    def _read(self):
        data = bytes(self.proc.readAllStandardOutput())
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp850" if os.name == "nt" else "latin-1", errors="replace")
        self.append(ANSI.sub("", text).replace("\r\n", "\n").replace("\r", ""))

    def append(self, text: str, color: str | None = None):
        c = self.out.textCursor()
        c.movePosition(QTextCursor.End)
        if color:
            fmt = c.charFormat()
            fmt.setForeground(QColor(color))
            c.insertText(text, fmt)
        else:
            fmt = c.charFormat()
            fmt.setForeground(QColor("#c9c9cf"))
            c.insertText(text, fmt)
        self.out.setTextCursor(c)
        self.out.ensureCursorVisible()

    def run(self, command: str):
        if not self.proc or self.proc.state() == QProcess.NotRunning:
            self.restart()
        self.append(f"\n$ {command}\n", "#ececf0")
        self.proc.write((command + "\n").encode("utf-8"))

    def submit(self):
        cmd = self.inp.text()
        self.inp.clear()
        if cmd.strip():
            self.history.append(cmd)
        self.hidx = len(self.history)
        if cmd.strip() in ("clear", "cls"):
            self.out.clear()
            return
        self.run(cmd)

    def interrupt(self):
        self.append("\n^C (reiniciando o shell)\n", "#ff2e40")
        self.restart()

    def eventFilter(self, obj, e):
        if obj is self.inp and e.type() == e.Type.KeyPress and e.key() in (Qt.Key_Up, Qt.Key_Down) and self.history:
            self.hidx = max(0, min(len(self.history), self.hidx + (-1 if e.key() == Qt.Key_Up else 1)))
            self.inp.setText(self.history[self.hidx] if self.hidx < len(self.history) else "")
            return True
        return False

    def shutdown(self):
        if self.proc:
            self.proc.kill()


class OutputPanel(QPlainTextEdit):
    """Saida de execucao do arquivo atual (F5)."""
    finished = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("console")
        self.setReadOnly(True)
        self.setMaximumBlockCount(20000)
        self.setFont(mono_font(13))
        self.proc: QProcess | None = None
        self.t0 = 0.0

    def append_color(self, text: str, color="#c9c9cf"):
        c = self.textCursor()
        c.movePosition(QTextCursor.End)
        fmt = c.charFormat()
        fmt.setForeground(QColor(color))
        c.insertText(text, fmt)
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def running(self) -> bool:
        return bool(self.proc and self.proc.state() != QProcess.NotRunning)

    def run(self, argv: list[str], cwd: Path, title: str, env_extra: dict | None = None):
        import time
        self.stop()
        self.clear()
        self.append_color(f"■ {title}\n", "#ff2e40")
        self.append_color(f"{' '.join(argv[-1:]) if len(argv) > 2 else ' '.join(argv)}\n\n", "#55555e")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.proc.setWorkingDirectory(str(cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        for k, v in (env_extra or {}).items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.append_color(self._dec(self.proc.readAllStandardOutput())))
        self.proc.readyReadStandardError.connect(
            lambda: self.append_color(self._dec(self.proc.readAllStandardError()), "#ff6b7a"))
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and
                                        self.append_color(f"!! nao foi possivel iniciar {argv[0]}\n", "#ff2e40"))
        self.t0 = time.time()
        if os.name == "nt" and argv[:1] == ["cmd"]:
            # o cmd.exe tem regras proprias de aspas: passa a linha de comando crua
            self.proc.setProgram("cmd.exe")
            self.proc.setNativeArguments(" ".join(argv[1:-1]) + ' "' + argv[-1] + '"')
            self.proc.start()
        else:
            self.proc.start(argv[0], argv[1:])

    @staticmethod
    def _dec(b) -> str:
        data = bytes(b)
        try:
            t = data.decode("utf-8")
        except UnicodeDecodeError:
            t = data.decode("cp850" if os.name == "nt" else "latin-1", errors="replace")
        return ANSI.sub("", t).replace("\r\n", "\n")

    def _done(self, code, _st):
        import time
        dt = time.time() - self.t0
        self.append_color(f"\n■ processo finalizado · codigo {code} · {dt:.2f}s\n",
                          "#ececf0" if code == 0 else "#ff2e40")
        self.finished.emit(code)

    def stop(self):
        if self.running():
            self.proc.kill()
            self.proc.waitForFinished(800)
            self.append_color("\n■ interrompido\n", "#ff2e40")

    def write_input(self, text: str):
        if self.running():
            self.proc.write((text + "\n").encode("utf-8"))
            self.append_color(text + "\n", "#ffd08a")


class ProblemsPanel(QTreeWidget):
    open_location = Signal(str, int, int)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setFont(mono_font(12))
        self.itemActivated.connect(self._act)
        self.itemClicked.connect(self._act)
        self.data: dict[str, list] = {}

    def set_file(self, path: str, diags: list):
        if diags:
            self.data[path] = diags
        else:
            self.data.pop(path, None)
        self.rebuild()

    def rebuild(self):
        self.clear()
        for path, diags in sorted(self.data.items()):
            top = QTreeWidgetItem([f"{Path(path).name}   {len(diags)}"])
            top.setIcon(0, lang_icon(languages.detect(path)))
            top.setToolTip(0, path)
            for d in sorted(diags, key=lambda x: (x.get("severity", 1), x["range"]["start"]["line"])):
                s = d["range"]["start"]
                sev = d.get("severity", 1)
                tag = "ERRO " if sev == 1 else "AVISO" if sev == 2 else "INFO "
                it = QTreeWidgetItem([f"{tag}  {d.get('message', '').splitlines()[0][:160]}   "
                                      f"[{s['line'] + 1}:{s['character'] + 1}]"])
                it.setForeground(0, QColor("#ff2e40") if sev == 1 else QColor("#ffb347") if sev == 2
                                 else QColor("#8fc1c4"))
                it.setData(0, Qt.UserRole, (path, s["line"], s["character"]))
                top.addChild(it)
            self.addTopLevelItem(top)
            top.setExpanded(True)

    def counts(self) -> tuple[int, int]:
        e = w = 0
        for diags in self.data.values():
            for d in diags:
                if d.get("severity", 1) == 1:
                    e += 1
                elif d.get("severity") == 2:
                    w += 1
        return e, w

    def _act(self, it, _col=0):
        d = it.data(0, Qt.UserRole)
        if d:
            self.open_location.emit(*d)


# ================================================================ busca em arquivos
class SearchWorker(QThread):
    hit = Signal(str, int, int, str)
    done = Signal(int, int)

    def __init__(self, root: Path, pattern: str, case: bool, regex: bool, include: str):
        super().__init__()
        self.root, self.pattern, self.case, self.regex, self.include = root, pattern, case, regex, include
        self.cancel = False

    def run(self):
        flags = 0 if self.case else re.I
        try:
            rx = re.compile(self.pattern if self.regex else re.escape(self.pattern), flags)
        except re.error:
            self.done.emit(0, 0)
            return
        globs = [g.strip() for g in self.include.split(",") if g.strip()]
        nfiles = nhits = 0
        for f in walk_files(self.root):
            if self.cancel or nhits > 5000:
                break
            if globs and not any(fnmatch.fnmatch(f.name, g) for g in globs):
                continue
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            found = False
            for i, line in enumerate(text.splitlines()):
                m = rx.search(line)
                if m:
                    found = True
                    nhits += 1
                    self.hit.emit(str(f), i, m.start(), line.strip()[:200])
            nfiles += found
        self.done.emit(nfiles, nhits)


class SearchPanel(QWidget):
    open_location = Signal(str, int, int)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        lay.addWidget(label("BUSCAR NOS ARQUIVOS", "section", 3))
        self.q = QLineEdit()
        self.q.setPlaceholderText("texto ou regex  (Enter)")
        self.q.returnPressed.connect(self.search)
        lay.addWidget(self.q)
        self.inc = QLineEdit()
        self.inc.setPlaceholderText("arquivos: *.py, *.ts  (opcional)")
        self.inc.returnPressed.connect(self.search)
        lay.addWidget(self.inc)
        row = QHBoxLayout()
        self.case = QCheckBox("Aa")
        self.case.setToolTip("Diferenciar maiusculas")
        self.rx = QCheckBox(".*")
        self.rx.setToolTip("Expressao regular")
        row.addWidget(self.case)
        row.addWidget(self.rx)
        row.addStretch()
        lay.addLayout(row)
        self.info = label("", "muted", 0.5, 12)
        lay.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFont(mono_font(12))
        self.tree.itemClicked.connect(self._open)
        lay.addWidget(self.tree, 1)
        self.root: Path | None = None
        self.worker: SearchWorker | None = None
        self.nodes: dict[str, QTreeWidgetItem] = {}

    def search(self):
        if not self.root or not self.q.text():
            return
        if self.worker and self.worker.isRunning():
            self.worker.cancel = True
            self.worker.wait(500)
        self.tree.clear()
        self.nodes.clear()
        self.info.setText("procurando...")
        self.worker = SearchWorker(self.root, self.q.text(), self.case.isChecked(), self.rx.isChecked(),
                                   self.inc.text())
        self.worker.hit.connect(self._hit)
        self.worker.done.connect(lambda nf, nh: self.info.setText(f"{nh} resultado(s) em {nf} arquivo(s)"))
        self.worker.start()

    def _hit(self, path, line, col, text):
        top = self.nodes.get(path)
        if top is None:
            rel = os.path.relpath(path, self.root) if self.root else path
            top = QTreeWidgetItem([rel])
            top.setIcon(0, lang_icon(languages.detect(path)))
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
            self.nodes[path] = top
        it = QTreeWidgetItem([f"{line + 1}:  {text}"])
        it.setData(0, Qt.UserRole, (path, line, col))
        top.addChild(it)

    def _open(self, it, _c):
        d = it.data(0, Qt.UserRole)
        if d:
            self.open_location.emit(*d)


# ================================================================ abrir rapido / paleta
class Picker(QDialog):
    """Lista com filtro difuso: usada pelo Ctrl+P (arquivos) e Ctrl+Shift+P (comandos)."""

    def __init__(self, parent, placeholder: str, items: list[tuple[str, str, object]], icon_fn=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet("QDialog { background: #070708; border: 1px solid #e3121f; }")
        self.resize(640, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.q = QLineEdit()
        self.q.setPlaceholderText(placeholder)
        self.q.textChanged.connect(self.filter)
        self.q.installEventFilter(self)
        lay.addWidget(self.q)
        self.list = QListWidget()
        self.list.itemActivated.connect(self.accept_item)
        lay.addWidget(self.list, 1)
        self.items = items
        self.icon_fn = icon_fn
        self.result = None
        self.filter("")
        pr = parent.geometry()
        self.move(parent.mapToGlobal(pr.topLeft()).x() + (pr.width() - self.width()) // 2,
                  parent.mapToGlobal(pr.topLeft()).y() + 60)

    @staticmethod
    def score(q: str, s: str) -> int:
        if not q:
            return 1
        ql, sl = q.lower(), s.lower()
        if ql in sl:
            return 1000 - sl.index(ql) - len(sl) // 10
        i = 0
        for ch in sl:
            if i < len(ql) and ch == ql[i]:
                i += 1
        return 100 - len(sl) // 10 if i == len(ql) else 0

    def filter(self, q: str):
        self.list.clear()
        scored = sorted(((self.score(q, t + " " + sub), t, sub, data) for t, sub, data in self.items),
                        key=lambda x: -x[0])
        for sc, t, sub, data in scored[:300]:
            if sc <= 0:
                continue
            it = QListWidgetItem(f"{t}    {sub}" if sub else t)
            it.setData(Qt.UserRole, data)
            if self.icon_fn:
                it.setIcon(self.icon_fn(t))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, e):
        if obj is self.q and e.type() == e.Type.KeyPress:
            if e.key() in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
                return True
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self.list.currentItem():
                    self.accept_item(self.list.currentItem())
                return True
        return False

    def accept_item(self, it):
        self.result = it.data(Qt.UserRole)
        self.accept()


# ================================================================ barra de busca no editor
class FindBar(QWidget):
    def __init__(self, get_editor):
        super().__init__()
        self.get_editor = get_editor
        self.setObjectName("findbar")
        self.setStyleSheet("QWidget#findbar { background: #070708; border-bottom: 1px solid #3a0a0f; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)
        r1 = QHBoxLayout()
        self.find = QLineEdit()
        self.find.setPlaceholderText("buscar")
        self.find.textChanged.connect(self.update_hits)
        self.find.returnPressed.connect(lambda: self.step(True))
        r1.addWidget(self.find, 1)
        self.case = QCheckBox("Aa")
        self.word = QCheckBox("ab")
        self.word.setToolTip("Palavra inteira")
        self.rx = QCheckBox(".*")
        for cb in (self.case, self.word, self.rx):
            cb.toggled.connect(self.update_hits)
            r1.addWidget(cb)
        self.count = label("", "muted", 0.5, 12)
        self.count.setMinimumWidth(80)
        r1.addWidget(self.count)
        r1.addWidget(button("↑", "ghost", lambda: self.step(False)))
        r1.addWidget(button("↓", "ghost", lambda: self.step(True)))
        r1.addWidget(button("✕", "ghost", self.close_bar))
        lay.addLayout(r1)
        self.rrow = QWidget()
        r2 = QHBoxLayout(self.rrow)
        r2.setContentsMargins(0, 0, 0, 0)
        self.repl = QLineEdit()
        self.repl.setPlaceholderText("substituir por")
        r2.addWidget(self.repl, 1)
        r2.addWidget(button("SUBSTITUIR", "ghost", self.replace_one))
        r2.addWidget(button("TODOS", "ghost", self.replace_all))
        lay.addWidget(self.rrow)
        self.hide()

    def open(self, replace: bool):
        ed = self.get_editor()
        self.rrow.setVisible(replace)
        self.show()
        if ed and ed.textCursor().hasSelection() and " " not in ed.textCursor().selectedText():
            self.find.setText(ed.textCursor().selectedText())
        self.find.setFocus()
        self.find.selectAll()
        self.update_hits()

    def opts(self):
        return self.case.isChecked(), self.rx.isChecked(), self.word.isChecked()

    def update_hits(self):
        ed = self.get_editor()
        if not ed or not self.isVisible():
            return
        case, rx, word = self.opts()
        n = ed.find_all(self.find.text(), case, rx, word)
        self.count.setText(f"{n} resultado(s)" if self.find.text() else "")

    def step(self, fwd: bool):
        ed = self.get_editor()
        if ed:
            ed.find_step(fwd)

    def replace_one(self):
        ed = self.get_editor()
        if ed:
            case, rx, word = self.opts()
            ed.replace_current(self.find.text(), self.repl.text(), case, rx, word)

    def replace_all(self):
        ed = self.get_editor()
        if ed:
            case, rx, word = self.opts()
            n = ed.replace_all(self.find.text(), self.repl.text(), case, rx, word)
            self.count.setText(f"{n} substituido(s)")

    def close_bar(self):
        ed = self.get_editor()
        if ed:
            ed.search_hits = []
            ed.update_extra()
            ed.setFocus()
        self.hide()
