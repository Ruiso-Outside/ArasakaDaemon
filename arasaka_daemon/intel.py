"""
ARASAKA DAEMON // paineis de inteligencia e ferramentas:
estrutura (arvore de simbolos), referencias e hierarquias, Search Everywhere,
historico local, profiler, depurador, alterar assinatura e exclusao segura.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import languages
from .history import ago, unified
from .kit import button, label
from .lsp import SYMBOL_GLYPH, SYMBOL_KIND
from .panels import lang_icon, mono_font

KIND_COLOR = {5: "#ff9e64", 6: "#7fd1ff", 12: "#7fd1ff", 9: "#7fd1ff", 11: "#c3a6ff", 10: "#ffd08a",
              13: "#d8d8de", 14: "#ff5d6a", 8: "#9fd8b0", 7: "#9fd8b0", 23: "#ff9e64", 2: "#e3121f"}


def _sym_text(s: dict) -> str:
    g = SYMBOL_GLYPH.get(s.get("kind", 0), "·")
    return f"{g}  {s['name']}"


# ================================================================ estrutura do arquivo
class StructurePanel(QWidget):
    open_location = Signal(str, int, int)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        lay.addWidget(label("ESTRUTURA", "section", 3))
        self.q = QLineEdit()
        self.q.setPlaceholderText("filtrar simbolos")
        self.q.textChanged.connect(self.rebuild)
        lay.addWidget(self.q)
        self.info = label("", "dim", 0.5, 12)
        lay.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFont(mono_font(12))
        self.tree.itemClicked.connect(self._open)
        self.tree.itemActivated.connect(self._open)
        lay.addWidget(self.tree, 1)
        self.path = ""
        self.syms: list[dict] = []

    def set_symbols(self, path: str, syms: list[dict], source: str):
        self.path, self.syms = path, syms
        n = sum(1 for _ in self._walk(syms))
        self.info.setText(f"{Path(path).name}  ·  {n} simbolo(s)  ·  {source}" if path else "")
        self.rebuild()

    def _walk(self, syms):
        for s in syms:
            yield s
            yield from self._walk(s.get("children", []))

    def rebuild(self, *_):
        self.tree.clear()
        q = self.q.text().lower()

        def add(parent, items):
            for s in items:
                kids = s.get("children", [])
                match = not q or q in s["name"].lower()
                if not match and not any(q in c["name"].lower() for c in self._walk(kids)):
                    continue
                it = QTreeWidgetItem([_sym_text(s) + (f"   {s['detail'][:40]}" if s.get("detail") else "")])
                it.setForeground(0, QColor(KIND_COLOR.get(s.get("kind"), "#c9c9cf")))
                it.setToolTip(0, f"{SYMBOL_KIND.get(s.get('kind'), 'simbolo')}  ·  linha {s['line'] + 1}")
                it.setData(0, Qt.UserRole, (self.path, s["line"], s.get("col", 0)))
                if parent is None:
                    self.tree.addTopLevelItem(it)
                else:
                    parent.addChild(it)
                add(it, kids)
                it.setExpanded(True)
        add(None, self.syms)

    def _open(self, it, _c=0):
        d = it.data(0, Qt.UserRole)
        if d:
            self.open_location.emit(*d)


# ================================================================ referencias / hierarquias
class LocationsPanel(QWidget):
    """Lista de locais agrupados por arquivo, ou arvore de hierarquia carregada sob demanda."""
    open_location = Signal(str, int, int)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 4, 10, 4)
        self.title = label("", "red", 1, 12, True)
        bar.addWidget(self.title, 1)
        self.flip = button("⇄ INVERTER", "ghost", self._flip)
        self.flip.hide()
        bar.addWidget(self.flip)
        lay.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFont(mono_font(12))
        self.tree.itemClicked.connect(self._open)
        self.tree.itemActivated.connect(self._open)
        self.tree.itemExpanded.connect(self._expand)
        lay.addWidget(self.tree, 1)
        self.expand_fn = None
        self.flip_fn = None
        self.root: Path | None = None

    def _rel(self, path) -> str:
        try:
            return os.path.relpath(str(path), str(self.root)) if self.root else str(path)
        except ValueError:
            return str(path)

    def show_locations(self, title: str, locs: list[tuple]):
        """locs: [(path, line, col, preview)]"""
        self.tree.clear()
        self.expand_fn = None
        self.flip.hide()
        self.title.setText(f"{title}   ·   {len(locs)} resultado(s)")
        groups: dict[str, QTreeWidgetItem] = {}
        for path, line, col, preview in locs:
            top = groups.get(str(path))
            if top is None:
                top = QTreeWidgetItem([self._rel(path)])
                top.setIcon(0, lang_icon(languages.detect(str(path))))
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
                groups[str(path)] = top
            it = QTreeWidgetItem([f"{line + 1}:  {preview.strip()[:180]}"])
            it.setData(0, Qt.UserRole, (str(path), line, col))
            top.addChild(it)
        for top in groups.values():
            top.setText(0, f"{top.text(0)}   {top.childCount()}")

    def show_hierarchy(self, title: str, roots: list[dict], expand_fn, flip_fn=None):
        """roots: [{text, path, line, col, payload}] ; expand_fn(payload, cb(lista de nos))."""
        self.tree.clear()
        self.title.setText(title)
        self.expand_fn = expand_fn
        self.flip_fn = flip_fn
        self.flip.setVisible(flip_fn is not None)
        for r in roots:
            it = self._node(r)
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
        if not roots:
            self.tree.addTopLevelItem(QTreeWidgetItem(["(nada encontrado)"]))

    def _node(self, n: dict) -> QTreeWidgetItem:
        it = QTreeWidgetItem([n["text"] + (f"    {self._rel(n['path'])}:{n['line'] + 1}" if n.get("path") else "")])
        if n.get("path"):
            it.setIcon(0, lang_icon(languages.detect(str(n["path"]))))
            it.setData(0, Qt.UserRole, (str(n["path"]), n["line"], n.get("col", 0)))
        it.setData(0, Qt.UserRole + 1, n.get("payload"))
        it.setData(0, Qt.UserRole + 2, False)
        if n.get("payload") is not None and n.get("depth", 0) < 12:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        return it

    def _expand(self, it: QTreeWidgetItem):
        if not self.expand_fn or it.data(0, Qt.UserRole + 2):
            return
        it.setData(0, Qt.UserRole + 2, True)
        payload = it.data(0, Qt.UserRole + 1)
        if payload is None:
            return
        loading = QTreeWidgetItem(["carregando..."])
        it.addChild(loading)

        def done(nodes):
            try:
                it.removeChild(loading)
            except RuntimeError:
                return
            for n in nodes:
                it.addChild(self._node(n))
            if not nodes:
                it.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicator)
        self.expand_fn(payload, done)

    def _flip(self):
        if self.flip_fn:
            self.flip_fn()

    def _open(self, it, _c=0):
        d = it.data(0, Qt.UserRole)
        if d:
            self.open_location.emit(*d)


# ================================================================ Search Everywhere
class SearchEverywhere(QDialog):
    """Shift Shift: arquivos, simbolos, acoes da IDE e configuracoes num unico campo."""
    CATS = [("all", "TUDO"), ("file", "ARQUIVOS"), ("symbol", "SIMBOLOS"), ("action", "ACOES"),
            ("setting", "CONFIGURACOES")]

    def __init__(self, parent, providers: dict, async_symbols=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet("QDialog { background: #070708; border: 1px solid #e3121f; }"
                           "QPushButton#cat { padding: 5px 12px; border: none; color: #8c8c96; background: transparent;}"
                           "QPushButton#cat:checked { color: #ffffff; border-bottom: 2px solid #e3121f; }")
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.cat_btns = {}
        for key, text in self.CATS:
            b = QPushButton(text)
            b.setObjectName("cat")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_cat(k))
            row.addWidget(b)
            self.cat_btns[key] = b
        row.addStretch()
        row.addWidget(label("Tab: categoria  ·  Shift Shift", "dim", 0.5, 11))
        lay.addLayout(row)
        self.q = QLineEdit()
        self.q.setPlaceholderText("buscar em tudo: arquivos, classes, funcoes, acoes, configuracoes...")
        self.q.textChanged.connect(lambda _t: self._timer.start())
        self.q.installEventFilter(self)
        lay.addWidget(self.q)
        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.itemActivated.connect(self.accept_item)
        lay.addWidget(self.list, 1)
        self.providers = providers
        self.async_symbols = async_symbols
        self.cat = "all"
        self.result = None
        self.extra: list[tuple] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        self.cat_btns["all"].setChecked(True)
        pr = parent.geometry()
        self.move(parent.mapToGlobal(pr.topLeft()).x() + (pr.width() - self.width()) // 2,
                  parent.mapToGlobal(pr.topLeft()).y() + 50)
        self.refresh()

    def set_cat(self, key: str):
        self.cat = key
        for k, b in self.cat_btns.items():
            b.setChecked(k == key)
        self.refresh()
        self.q.setFocus()

    @staticmethod
    def score(q: str, s: str) -> int:
        from .panels import Picker
        return Picker.score(q, s)

    def refresh(self):
        q = self.q.text().strip()
        rows = []
        for cat, fn in self.providers.items():
            if self.cat not in ("all", cat):
                continue
            for title, sub, data, icon in fn(q):
                st = self.score(q, title)
                ss = 150 if q and q.lower() in sub.lower() else 0     # caminho / tipo: so trecho exato
                if q and st <= 0 and ss == 0:
                    continue
                sc = st * 3 + ss
                rows.append((sc + {"symbol": 30, "file": 20, "action": 10}.get(cat, 0), cat, title, sub, data, icon))
        for cat, title, sub, data, icon in self.extra:
            if self.cat in ("all", cat) and (not q or self.score(q, title) > 0):
                rows.append((self.score(q, title) * 3 + 25, cat, title, sub, data, icon))
        rows.sort(key=lambda r: -r[0])
        self.list.clear()
        label_cat = dict(self.CATS)
        seen = set()
        for _sc, cat, title, sub, data, icon in rows[:250]:
            loc = data[1] if isinstance(data, tuple) and data and data[0] == "loc" else None
            key = (cat, title, loc[0], loc[1]) if loc else (cat, title, sub)
            if key in seen:
                continue
            seen.add(key)
            it = QListWidgetItem(f"{title}    {sub}" if sub else title)
            it.setData(Qt.UserRole, (cat, data))
            it.setToolTip(label_cat.get(cat, cat))
            if icon is not None:
                it.setIcon(icon)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        if self.async_symbols and q and len(q) >= 2 and self.cat in ("all", "symbol"):
            self.async_symbols(q, self._async_done)

    def _async_done(self, q: str, items: list[tuple]):
        if q != self.q.text().strip():
            return
        self.extra = [("symbol",) + tuple(i) for i in items]
        cur = self.list.currentRow()
        self.refresh_no_async()
        self.list.setCurrentRow(max(0, cur))

    def refresh_no_async(self):
        a = self.async_symbols
        self.async_symbols = None
        try:
            self.refresh()
        finally:
            self.async_symbols = a

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
            if e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                keys = [k for k, _ in self.CATS]
                i = keys.index(self.cat) + (1 if e.key() == Qt.Key_Tab else -1)
                self.set_cat(keys[i % len(keys)])
                return True
        return False

    def accept_item(self, it):
        self.result = it.data(Qt.UserRole)
        self.accept()


# ================================================================ historico local
class HistoryDialog(QDialog):
    def __init__(self, parent, history, files: list[Path], current_text: dict, on_restore, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 680)
        self.history, self.current_text, self.on_restore = history, current_text, on_restore
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(label(title.upper(), "section", 3))
        lay.addWidget(label("Fotos automaticas: ao salvar, executar, recarregar, excluir, refatorar e a cada poucos "
                            "minutos de edicao. Independente do git.", "dim", 0.3, 12, wrap=True))
        sp = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFont(mono_font(12))
        self.tree.currentItemChanged.connect(self._show)
        sp.addWidget(self.tree)
        self.diff = QPlainTextEdit()
        self.diff.setObjectName("console")
        self.diff.setReadOnly(True)
        self.diff.setFont(mono_font(12))
        self.diff.setLineWrapMode(QPlainTextEdit.NoWrap)
        sp.addWidget(self.diff)
        sp.setSizes([360, 740])
        lay.addWidget(sp, 1)
        row = QHBoxLayout()
        self.info = label("", "muted", 0.5, 12)
        row.addWidget(self.info, 1)
        self.btn_restore = button("RESTAURAR ESTA VERSAO", "primary", self._restore)
        row.addWidget(self.btn_restore)
        row.addWidget(button("FECHAR", "ghost", self.reject))
        lay.addLayout(row)
        for f, n, last in files:
            exists = Path(f).exists()
            top = QTreeWidgetItem([f"{Path(f).name}   {n}" + ("" if exists else "   [EXCLUIDO]")])
            top.setToolTip(0, str(f))
            top.setIcon(0, lang_icon(languages.detect(str(f))))
            if not exists:
                top.setForeground(0, QColor("#ff5d6a"))
            self.tree.addTopLevelItem(top)
            for snap in history.list(Path(f)):
                it = QTreeWidgetItem([f"{time.strftime('%d/%m %H:%M:%S', time.localtime(snap['time']))}  "
                                      f"{snap.get('label', '')}  ({ago(snap['time'])})"])
                it.setData(0, Qt.UserRole, (str(f), snap))
                top.addChild(it)
            if len(files) == 1:
                top.setExpanded(True)
                if top.childCount():
                    self.tree.setCurrentItem(top.child(0))

    def _current(self, path: str) -> str:
        if path in self.current_text:
            return self.current_text[path]
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _show(self, it, _prev=None):
        self.diff.clear()
        d = it.data(0, Qt.UserRole) if it else None
        self.btn_restore.setEnabled(bool(d))
        if not d:
            return
        path, snap = d
        old = self.history.read(snap)
        cur = self._current(path)
        text = unified(cur, old, "atual", f"foto {time.strftime('%H:%M:%S', time.localtime(snap['time']))}")
        if not text:
            text = "(identico a versao atual)\n\n" + old
        self.info.setText(f"{snap.get('lines', '?')} linhas  ·  {snap.get('label', '')}  ·  {ago(snap['time'])}")
        c = self.diff.textCursor()
        for ln in text.splitlines(True):
            f = QTextCharFormat()
            f.setForeground(QColor("#64c88c") if ln.startswith("+") and not ln.startswith("+++") else
                            QColor("#ff5d6a") if ln.startswith("-") and not ln.startswith("---") else
                            QColor("#7fd1ff") if ln.startswith("@@") else QColor("#c9c9cf"))
            c.insertText(ln, f)
        self.diff.moveCursor(QTextCursor.Start)

    def _restore(self):
        it = self.tree.currentItem()
        d = it.data(0, Qt.UserRole) if it else None
        if d:
            path, snap = d
            self.on_restore(Path(path), self.history.read(snap))
            self.accept()


# ================================================================ profiler
class ProfilerPanel(QWidget):
    open_location = Signal(str, int, int)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.summary = label("Rode EXECUTAR > Executar com profiler (Ctrl+Alt+F5).", "muted", 0.5, 12)
        self.summary.setContentsMargins(10, 6, 10, 6)
        lay.addWidget(self.summary)
        sp = QSplitter(Qt.Horizontal)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["FUNCAO", "LOCAL", "CHAMADAS", "PROPRIO (s)", "ACUMULADO (s)", "%"])
        self.table.setRootIsDecorated(False)
        self.table.setFont(mono_font(12))
        self.table.setSortingEnabled(True)
        self.table.itemActivated.connect(self._open)
        self.table.itemDoubleClicked.connect(self._open)
        sp.addWidget(self.table)
        self.mem = QTreeWidget()
        self.mem.setHeaderLabels(["MEMORIA ALOCADA (linha)", "KB", "BLOCOS"])
        self.mem.setRootIsDecorated(False)
        self.mem.setFont(mono_font(12))
        self.mem.itemDoubleClicked.connect(self._open)
        sp.addWidget(self.mem)
        sp.setSizes([800, 360])
        lay.addWidget(sp, 1)

    def show_python(self, data: dict, root: Path | None):
        def mb(b):
            return f"{b / 1048576:.1f} MB"
        self.summary.setText(f"TEMPO {data.get('wall', 0):.3f}s  ·  CPU {data.get('cpu', 0):.3f}s  ·  PICO DE MEMORIA "
                             f"(Python) {mb(data.get('peak', 0))}  ·  RSS {mb(data.get('rss', 0))}  ·  THREADS "
                             f"{data.get('threads', 1)}" + (f"  ·  ERRO {data['error']}" if data.get("error") else ""))
        self.table.clear()
        self.table.setSortingEnabled(False)
        total = max(1e-9, data.get("wall", 0))
        rows = [r for r in data.get("rows", []) if not self._noise(r["file"], r["func"]) and
                (self._is_user(r["file"], root) or r["cumtime"] >= total * 0.01)]
        for r in sorted(rows, key=lambda r: -r["cumtime"])[:200]:
            loc = f"{self._short(r['file'], root)}:{r['line']}"
            it = _NumItem([r["func"], loc, str(r["calls"]), f"{r['tottime']:.4f}", f"{r['cumtime']:.4f}",
                           f"{100 * r['cumtime'] / total:.1f}"])
            if self._is_user(r["file"], root):
                it.setForeground(0, QColor("#ffffff"))
            else:
                for c in range(6):
                    it.setForeground(c, QColor("#6a6a74"))
            it.setData(0, Qt.UserRole, (r["file"], max(0, r["line"] - 1), 0))
            self.table.addTopLevelItem(it)
        for c in range(6):
            self.table.resizeColumnToContents(c)
        self.table.setSortingEnabled(True)
        self.table.sortItems(4, Qt.DescendingOrder)
        self.mem.clear()
        mem = [m for m in data.get("mem", []) if not self._noise(m["file"], "")]
        for m in sorted(mem, key=lambda m: (not self._is_user(m["file"], root), -m["size"])):
            it = _NumItem([f"{self._short(m['file'], root)}:{m['line']}", f"{m['size'] / 1024:.1f}", str(m["count"])])
            it.setData(0, Qt.UserRole, (m["file"], max(0, m["line"] - 1), 0))
            self.mem.addTopLevelItem(it)
        self.mem.resizeColumnToContents(0)

    def show_generic(self, data: dict, title: str):
        self.table.clear()
        self.mem.clear()
        self.summary.setText(f"{title}  ·  TEMPO {data.get('wall', 0):.3f}s  ·  CPU {data.get('cpu', 0):.3f}s "
                             f"(usuario {data.get('user', 0):.3f}s, sistema {data.get('sys', 0):.3f}s)  ·  MEMORIA "
                             f"MAXIMA {data.get('rss', 0) / 1048576:.1f} MB  ·  CODIGO {data.get('code')}")

    @staticmethod
    def _noise(f: str, func: str) -> bool:
        f = str(f)
        return (f.startswith("<frozen") or f == "~" or Path(f).name in ("profile_runner.py", "runpy.py", "cProfile.py",
                                                                        "tracemalloc.py", "pkgutil.py")
                or func in ("<built-in method builtins.exec>", "<method 'disable' of '_lsprof.Profiler' objects>"))

    @staticmethod
    def _is_user(f: str, root) -> bool:
        return bool(root) and str(f).startswith(str(root)) and "site-packages" not in str(f)

    @staticmethod
    def _short(f: str, root) -> str:
        if root and str(f).startswith(str(root)):
            return os.path.relpath(f, root)
        return Path(f).name if f and not f.startswith("~") else f

    def _open(self, it, _c=0):
        d = it.data(0, Qt.UserRole)
        if d and Path(d[0]).is_file():
            self.open_location.emit(*d)


class _NumItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        try:
            return float(self.text(col)) < float(other.text(col))
        except ValueError:
            return self.text(col) < other.text(col)


# ================================================================ depurador
class DebugPanel(QWidget):
    command = Signal(dict)
    open_location = Signal(str, int, int)
    watches_changed = Signal(list)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        self.state = label("parado", "muted", 1, 12, True)
        bar.addWidget(self.state)
        bar.addStretch()
        self.btns = {}
        for key, text, tip in [("continue", "▶ CONTINUAR", "F9"), ("pause", "⏸ PAUSAR", ""),
                               ("next", "↷ PULAR", "F8 (step over)"), ("step", "↘ ENTRAR", "F7 (step into)"),
                               ("out", "↗ SAIR", "Shift+F8 (step out)"), ("quit", "■ PARAR", "Ctrl+F2")]:
            b = button(text, "ghost", lambda k=key: self.command.emit({"cmd": k}), tip)
            bar.addWidget(b)
            self.btns[key] = b
        lay.addLayout(bar)
        sp = QSplitter(Qt.Horizontal)
        self.stack = QListWidget()
        self.stack.setFont(mono_font(12))
        self.stack.currentRowChanged.connect(self._frame)
        sp.addWidget(self._titled("PILHA DE CHAMADAS", self.stack))
        self.vars = QTreeWidget()
        self.vars.setHeaderLabels(["VARIAVEL", "VALOR", "TIPO"])
        self.vars.setFont(mono_font(12))
        self.vars.itemExpanded.connect(self._expand)
        sp.addWidget(self._titled("VARIAVEIS", self.vars))
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        self.watch = QTreeWidget()
        self.watch.setHeaderLabels(["OBSERVAR", "VALOR"])
        self.watch.setFont(mono_font(12))
        self.watch.setRootIsDecorated(False)
        self.watch.itemDoubleClicked.connect(self._remove_watch)
        wrow = QHBoxLayout()
        self.watch_in = QLineEdit()
        self.watch_in.setPlaceholderText("+ expressao para observar")
        self.watch_in.returnPressed.connect(self._add_watch)
        wrow.addWidget(self.watch_in)
        rl.addWidget(label("  EXPRESSOES OBSERVADAS (duplo clique remove)", "section", 2, 11))
        rl.addWidget(self.watch, 1)
        rl.addLayout(wrow)
        rl.addWidget(label("  AVALIAR EXPRESSAO (no contexto pausado)", "section", 2, 11))
        self.console = QPlainTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setFont(mono_font(12))
        rl.addWidget(self.console, 1)
        self.eval_in = QLineEdit()
        self.eval_in.setFont(mono_font(12))
        self.eval_in.setPlaceholderText("expressao ou instrucao Python + Enter  (ex.: len(itens), x = 10)")
        self.eval_in.returnPressed.connect(self._eval)
        rl.addWidget(self.eval_in)
        sp.addWidget(right)
        sp.setSizes([260, 460, 420])
        lay.addWidget(sp, 1)
        self.watches: list[str] = []
        self.pending: dict[int, QTreeWidgetItem] = {}
        self.next_id = 1
        self.frames: list[dict] = []
        self._loading_frame = False
        self.set_running(False, active=False)

    @staticmethod
    def _titled(title, w):
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(2)
        l.addWidget(label("  " + title, "section", 2, 11))
        l.addWidget(w, 1)
        return box

    def set_running(self, running: bool, active: bool = True):
        self.state.setText(("EXECUTANDO" if running else "PAUSADO") if active else "SEM SESSAO")
        for k, b in self.btns.items():
            b.setEnabled(active and (k in ("pause", "quit") if running else k != "pause"))
        self.eval_in.setEnabled(active and not running)

    def show_stop(self, ev: dict):
        self.set_running(False)
        self.frames = ev.get("stack", [])
        self._loading_frame = True
        self.stack.clear()
        for f in self.frames:
            self.stack.addItem(f"{f['func']}    {Path(f['file']).name}:{f['line'] + 1}")
        self.stack.setCurrentRow(ev.get("frame", 0))
        self._loading_frame = False
        if ev.get("exception"):
            self.state.setText("EXCECAO: " + ev["exception"][:80])
            self.log(f"!! {ev['exception']}\n", "#ff5d6a")
        self.vars.clear()
        for v in ev.get("vars", []):
            self.vars.addTopLevelItem(self._var_item(v, v["name"]))
        for c in range(3):
            self.vars.resizeColumnToContents(c)
        self.watch.clear()
        for w in ev.get("watches", []):
            it = QTreeWidgetItem([w["expr"], w["value"]])
            if not w.get("ok", True):
                it.setForeground(1, QColor("#ff5d6a"))
            self.watch.addTopLevelItem(it)

    def _var_item(self, v: dict, path: str | None) -> QTreeWidgetItem:
        it = QTreeWidgetItem([v["name"], v["value"], v.get("type", "")])
        it.setForeground(0, QColor("#7fd1ff"))
        it.setData(0, Qt.UserRole, path)
        if v.get("expandable") and path:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        return it

    def _expand(self, it):
        path = it.data(0, Qt.UserRole)
        if not path or it.childCount():
            return
        i = self.next_id
        self.next_id += 1
        self.pending[i] = it
        self.command.emit({"cmd": "children", "expr": path, "id": i})

    def show_children(self, ev: dict):
        it = self.pending.pop(ev.get("id"), None)
        if it is None:
            return
        for v in ev.get("items", []):
            try:
                it.addChild(self._var_item(v, v.get("path")))
            except RuntimeError:
                return

    def _frame(self, row: int):
        if self._loading_frame or row < 0 or row >= len(self.frames):
            return
        f = self.frames[row]
        self.open_location.emit(f["file"], f["line"], 0)
        self.command.emit({"cmd": "frame", "index": row})

    def _add_watch(self):
        t = self.watch_in.text().strip()
        if t:
            self.watches.append(t)
            self.watch_in.clear()
            self.watches_changed.emit(list(self.watches))

    def _remove_watch(self, it, _c):
        t = it.text(0)
        if t in self.watches:
            self.watches.remove(t)
            self.watches_changed.emit(list(self.watches))

    def _eval(self):
        t = self.eval_in.text().strip()
        if t:
            self.log(f">>> {t}\n", "#ececf0")
            self.command.emit({"cmd": "eval", "expr": t})
            self.eval_in.clear()

    def show_eval(self, ev: dict):
        self.log(f"{ev.get('value', '')}" + (f"   ({ev['type']})" if ev.get("type") else "") + "\n",
                 "#9fd8b0" if ev.get("ok") else "#ff5d6a")

    def log(self, text: str, color="#c9c9cf"):
        c = self.console.textCursor()
        c.movePosition(QTextCursor.End)
        f = QTextCharFormat()
        f.setForeground(QColor(color))
        c.insertText(text, f)
        self.console.setTextCursor(c)
        self.console.ensureCursorVisible()


# ================================================================ alterar assinatura
class ChangeSignatureDialog(QDialog):
    def __init__(self, parent, name: str, params: list[str], n_calls: int):
        super().__init__(parent)
        self.setWindowTitle("Alterar assinatura")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(label("ALTERAR ASSINATURA", "section", 3))
        lay.addWidget(label(f"{name}  ·  {n_calls} chamada(s) no projeto serao atualizadas. Parametros novos recebem o "
                            "valor padrao nas chamadas.", "muted", 0.3, 12, wrap=True))
        row = QHBoxLayout()
        row.addWidget(label("NOME", "muted", 2, 12, True))
        self.name = QLineEdit(name)
        self.name.textChanged.connect(self._preview)
        row.addWidget(self.name, 1)
        lay.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["PARAMETRO (como na definicao)", "VALOR NAS CHAMADAS (novos)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setFont(mono_font(12))
        self.table.itemChanged.connect(self._preview)
        lay.addWidget(self.table, 1)
        for i, p in enumerate(params):
            self._add_row(p, "", i)
        btns = QHBoxLayout()
        btns.addWidget(button("+ ADICIONAR", "ghost", lambda: self._add_row("novo", "None", None)))
        btns.addWidget(button("− REMOVER", "ghost", self._remove))
        btns.addWidget(button("↑", "ghost", lambda: self._move(-1)))
        btns.addWidget(button("↓", "ghost", lambda: self._move(1)))
        btns.addStretch()
        lay.addLayout(btns)
        self.preview = label("", "red", 0.5, 13)
        self.preview.setFont(mono_font(13))
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)
        ok = QHBoxLayout()
        ok.addStretch()
        ok.addWidget(button("CANCELAR", "ghost", self.reject))
        ok.addWidget(button("REFATORAR", "primary", self.accept))
        lay.addLayout(ok)
        self._preview()

    def _add_row(self, text, default, orig):
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        a = QTableWidgetItem(text)
        a.setData(Qt.UserRole, orig)
        b = QTableWidgetItem(default)
        if orig is not None:
            b.setFlags(b.flags() & ~Qt.ItemIsEditable)
            b.setText("(existente)")
            b.setForeground(QColor("#55555e"))
        self.table.setItem(r, 0, a)
        self.table.setItem(r, 1, b)
        self.table.blockSignals(False)
        self._preview()

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._preview()

    def _move(self, d):
        r = self.table.currentRow()
        t = r + d
        if r < 0 or not (0 <= t < self.table.rowCount()):
            return
        self.table.blockSignals(True)
        for c in range(2):
            a, b = self.table.takeItem(r, c), self.table.takeItem(t, c)
            self.table.setItem(r, c, b)
            self.table.setItem(t, c, a)
        self.table.blockSignals(False)
        self.table.setCurrentCell(t, 0)
        self._preview()

    def params(self) -> list[tuple[int | None, str, str]]:
        out = []
        for r in range(self.table.rowCount()):
            a, b = self.table.item(r, 0), self.table.item(r, 1)
            if a and a.text().strip():
                orig = a.data(Qt.UserRole)
                out.append((orig, a.text().strip(), "" if orig is not None else (b.text().strip() if b else "")))
        return out

    def _preview(self, *_):
        self.preview.setText(f"{self.name.text()}({', '.join(p[1] for p in self.params())})")


# ================================================================ exclusao segura
class UsagesDialog(QDialog):
    def __init__(self, parent, title: str, intro: str, hits: list[tuple], root: Path | None, confirm: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(label(title.upper(), "section", 3))
        lay.addWidget(label(intro, "muted", 0.3, 12, wrap=True))
        self.panel = LocationsPanel()
        self.panel.root = root
        self.panel.show_locations("USOS ENCONTRADOS", hits)
        lay.addWidget(self.panel, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("CANCELAR", "primary", self.reject))
        row.addWidget(button(confirm, "ghost", self.accept))
        lay.addLayout(row)
