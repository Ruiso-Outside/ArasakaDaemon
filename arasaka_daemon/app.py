"""
ARASAKA DAEMON // IDE (janela principal).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QDir, QFileSystemWatcher, QModelIndex, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFileSystemModel, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                               QTabWidget, QToolButton, QToolTip, QTreeView, QVBoxLayout, QWidget)

from . import analysis, languages
from . import fx
from .editor import CodeEditor
from .ide import IntelMixin
from .intel import DebugPanel, LocationsPanel, ProfilerPanel, StructurePanel
from .kit import (FONTS, CutFrame, HudHeader, button, label, load_fonts, logo_pixmap, spaced, stylesheet)
from .lsp import LspManager, from_uri, to_uri
from .panels import (FindBar, IconProvider, OutputPanel, Picker, ProblemsPanel, SearchPanel, Terminal, lang_icon,
                     mono_font, walk_files)

APP_ID = "arasaka-daemon"
APP_NAME = "ARASAKA DAEMON"
VERSION = "2.0.0"
ASSETS = Path(__file__).resolve().parent / "assets"


def config_dir() -> Path:
    if os.environ.get("ARASAKA_DAEMON_HOME"):
        return Path(os.environ["ARASAKA_DAEMON_HOME"]) / "config"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_ID
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID


DEFAULTS = {"font_size": 13, "tab_size": 4, "auto_close": True, "autocomplete": True, "trim_whitespace": True,
            "final_newline": True, "autosave": False, "lsp": True, "run_overrides": {}, "recent": [],
            "session": {}, "inlay_hints": True, "usage_counts": True, "flow_analysis": True, "git_gutter": True,
            "templates": {}}

EXTRA_QSS = """
QMenuBar { background: #030304; border-bottom: 1px solid #1a0507; padding: 2px 6px; }
QMenuBar::item { padding: 6px 12px; background: transparent; color: #8c8c96; }
QMenuBar::item:selected { color: #ffffff; background: rgba(227,18,31,0.18); }
QFrame#activity { background: #030304; border-right: 1px solid #1a0507; }
QToolButton#act { background: transparent; border: none; border-left: 3px solid transparent; color: #55555e;
  font-size: 20px; padding: 10px 0; }
QToolButton#act:hover { color: #ffffff; }
QToolButton#act:checked { color: #ffffff; border-left: 3px solid #e3121f; background: rgba(227,18,31,0.10); }
QFrame#side { background: #050506; border-right: 1px solid #16161a; }
QTreeView, QTreeWidget { background: #050506; border: none; outline: none; }
QTreeView::item, QTreeWidget::item { padding: 3px 2px; border: none; }
QTreeView::item:hover, QTreeWidget::item:hover { background: rgba(227,18,31,0.10); }
QTreeView::item:selected, QTreeWidget::item:selected { background: rgba(227,18,31,0.28); color: #ffffff; }
QTabWidget::pane { border: none; background: #0a0a0c; }
QTabBar { background: #050506; }
QTabBar::tab { background: #050506; color: #8c8c96; padding: 8px 14px; border: none;
  border-right: 1px solid #111114; border-top: 2px solid transparent; }
QTabBar::tab:selected { background: #0a0a0c; color: #ffffff; border-top: 2px solid #e3121f; }
QTabBar::tab:hover { color: #ffffff; }
QTabWidget#bottom QTabBar::tab { padding: 6px 14px; font-weight: 700; }
QStatusBar { background: #8e0b14; color: #ffffff; }
QStatusBar QLabel { color: #ffffff; padding: 0 10px; font-weight: 700; }
QStatusBar::item { border: none; }
QSpinBox { background: #050506; border: 1px solid #2a2a31; padding: 6px 8px; }
QPushButton::menu-indicator { image: none; width: 0; }
QHeaderView { background: #050506; border: none; }
QHeaderView::section { background: #070708; color: #8c8c96; border: none; border-right: 1px solid #16161a;
  border-bottom: 1px solid #2a0a0d; padding: 4px 8px; font-weight: 700; }
QTableWidget, QTableView { background: #050506; gridline-color: #16161a; border: 1px solid #16161a; }
QTableCornerButton::section { background: #070708; border: none; }
QListWidget { background: #050506; border: none; outline: none; }
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: rgba(227,18,31,0.28); color: #ffffff; }
"""


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = config_dir() / "settings.json"
        try:
            self.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self, indent=2, ensure_ascii=False), encoding="utf-8")


def git_branch(root: Path | None) -> str:
    p = root
    while p and p != p.parent:
        head = p / ".git" / "HEAD"
        if head.is_file():
            t = head.read_text(errors="ignore").strip()
            return t.split("/")[-1] if t.startswith("ref:") else t[:7]
        p = p.parent
    return ""


# ================================================================ paginas em abas
class WelcomePage(QScrollArea):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(60, 40, 60, 40)
        lay.setSpacing(14)
        top = QHBoxLayout()
        lg = QLabel()
        lg.setPixmap(logo_pixmap(120))
        top.addWidget(lg)
        col = QVBoxLayout()
        col.addStretch()
        t = QLabel("ARASAKA")
        t.setFont(QFont(FONTS["brand"], 40))
        spaced(t, 10, 48, family=FONTS["brand"])
        col.addWidget(t)
        col.addWidget(label("DAEMON  //  AMBIENTE DE DESENVOLVIMENTO", "red", 5, 14, True))
        col.addWidget(label(f"v{VERSION}  ·  {len(languages.LANGS)} linguagens  ·  LSP  ·  terminal integrado",
                            "muted", 1, 13))
        col.addStretch()
        top.addLayout(col)
        top.addStretch()
        lay.addLayout(top)
        lay.addSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("ABRIR PASTA", "primary", win.open_folder_dialog))
        row.addWidget(button("ABRIR ARQUIVO", None, win.open_file_dialog))
        row.addWidget(button("NOVO ARQUIVO", None, win.new_file))
        row.addWidget(button("LINGUAGENS", "ghost", win.show_languages))
        row.addStretch()
        lay.addLayout(row)
        cols = QHBoxLayout()
        cols.setSpacing(16)
        rec = CutFrame(cut=12)
        rl = QVBoxLayout(rec)
        rl.setContentsMargins(20, 16, 20, 16)
        rl.addWidget(label("PROJETOS RECENTES", "section", 3))
        self.recent_box = QVBoxLayout()
        rl.addLayout(self.recent_box)
        rl.addStretch()
        cols.addWidget(rec, 1)
        keys = CutFrame(cut=12)
        kl = QGridLayout(keys)
        kl.setContentsMargins(20, 16, 20, 16)
        kl.addWidget(label("ATALHOS", "section", 3), 0, 0, 1, 2)
        shortcuts = [("Shift Shift", "Search Everywhere"), ("Alt+Enter", "acoes de contexto / intencoes"),
                     ("Ctrl+P", "abrir arquivo do projeto"), ("Ctrl+Shift+P", "paleta de comandos"),
                     ("F5 / Shift+F9", "executar / depurar"), ("Ctrl+Espaco", "autocompletar"),
                     ("F12 / Ctrl+clique", "ir para definicao"), ("Shift+F12", "encontrar usos"),
                     ("Ctrl+Alt+H", "hierarquia de chamadas"), ("F2", "renomear simbolo"),
                     ("Ctrl+Alt+M / V / C", "extrair metodo / variavel / constante"),
                     ("Ctrl+F6", "alterar assinatura"), ("Ctrl+F12", "estrutura do arquivo"),
                     ("Ctrl+Shift+T", "ir para o teste"), ("Alt+Shift+H", "historico local"),
                     ("Alt+Esq / Dir", "voltar / avancar"), ("Tab", "expandir live template"),
                     ("Ctrl+`", "terminal")]
        for i, (k, d) in enumerate(shortcuts, 1):
            kk = label(k, "red", 1, 13, True)
            kk.setFont(mono_font(13))
            kl.addWidget(kk, i, 0)
            kl.addWidget(label(d, "muted", 0.5, 13), i, 1)
        cols.addWidget(keys, 1)
        lay.addLayout(cols)
        lay.addStretch()
        self.setWidget(inner)
        self.win = win
        self.refresh()

    def refresh(self):
        while self.recent_box.count():
            it = self.recent_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rec = [r for r in self.win.settings.get("recent", []) if Path(r).is_dir()][:8]
        if not rec:
            self.recent_box.addWidget(label("nenhum ainda", "dim", 0.5))
        for r in rec:
            b = button(f"{Path(r).name}   ·   {r}", "ghost", lambda p=r: self.win.open_folder(Path(p)))
            b.setStyleSheet("text-align: left;")
            self.recent_box.addWidget(b)


class LanguagesPage(QScrollArea):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.inner.setObjectName("page")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(40, 26, 40, 26)
        self.lay.setSpacing(10)
        self.setWidget(self.inner)
        self.build()

    def build(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                QWidget().setLayout(it.layout())
        self.lay.addWidget(HudHeader("LINGUAGENS", "Runtimes e servidores de linguagem (LSP) instalados",
                                     "DAEMON://LANG"))
        row = QHBoxLayout()
        row.addWidget(label("Os botoes INSTALAR executam o comando no TERMINAL integrado. O LSP traz autocompletar, "
                            "erros em tempo real, documentacao e ir para definicao.", "muted", 0.3, wrap=True), 1)
        row.addWidget(button("REVERIFICAR", "ghost", self.build))
        self.lay.addLayout(row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for c, h in enumerate(["", "LINGUAGEM", "EXECUCAO", "LSP (INTELIGENCIA)", "EXTENSOES"]):
            grid.addWidget(label(h, "section", 2, 12), 0, c)
        for r, lang in enumerate(languages.LANGS, 1):
            ic = QLabel()
            ic.setPixmap(lang_icon(lang).pixmap(28, 28))
            grid.addWidget(ic, r, 0)
            grid.addWidget(label(lang.name.upper(), None, 1.5, 13, True), r, 1)
            # runtime
            if lang.runtime:
                found = lang.runtime_found()
                if found:
                    grid.addWidget(label("■ " + Path(found).name, "muted", 0.5, 12), r, 2)
                elif lang.runtime_install:
                    b = button("INSTALAR", None, lambda c=lang.runtime_install: self.win.install(c),
                               lang.runtime_install)
                    grid.addWidget(b, r, 2)
                else:
                    grid.addWidget(label("nao encontrado", "dim", 0.5, 12), r, 2)
            else:
                grid.addWidget(label("—", "dim", 0, 12), r, 2)
            # lsp
            if lang.servers:
                srv, cmd = lang.server()
                if srv:
                    grid.addWidget(label("■ " + (srv.name or cmd[0]), "muted", 0.5, 12), r, 3)
                else:
                    s0 = lang.servers[0]
                    if s0.install.startswith("http") or " " not in s0.install:
                        b = button("COMO INSTALAR", "ghost", lambda u=s0.install: QDesktopServices.openUrl(
                            QUrl(u.split()[-1])) if u.startswith("http") else self.win.toast(u), s0.install)
                    else:
                        b = button("INSTALAR " + (s0.name or s0.cmd[0]).upper(), None,
                                   lambda c=s0.install: self.win.install(c), s0.install)
                    grid.addWidget(b, r, 3)
            else:
                grid.addWidget(label("so realce de sintaxe", "dim", 0.5, 12), r, 3)
            grid.addWidget(label(" ".join(lang.exts[:5]), "dim", 0.3, 12), r, 4)
        self.lay.addLayout(grid)
        self.lay.addStretch()


class SettingsPage(QScrollArea):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        s = win.settings
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(40, 26, 40, 26)
        lay.setSpacing(12)
        lay.addWidget(HudHeader("CONFIGURACOES", "Editor, execucao e servidores de linguagem", f"BUILD://{VERSION}"))
        box = CutFrame(cut=12)
        form = QFormLayout(box)
        form.setContentsMargins(22, 18, 22, 18)
        form.setSpacing(12)
        fs = QSpinBox()
        fs.setRange(8, 32)
        fs.setValue(int(s["font_size"]))
        fs.valueChanged.connect(lambda v: self._set("font_size", v, True))
        form.addRow(label("TAMANHO DA FONTE", "muted", 2, bold=True), fs)
        ts = QSpinBox()
        ts.setRange(2, 8)
        ts.setValue(int(s["tab_size"]))
        ts.valueChanged.connect(lambda v: self._set("tab_size", v))
        form.addRow(label("TAB (ESPACOS)", "muted", 2, bold=True), ts)
        for key, text in [("autocomplete", "Autocompletar enquanto digita"),
                          ("auto_close", "Fechar parenteses, colchetes e aspas automaticamente"),
                          ("trim_whitespace", "Remover espacos no fim das linhas ao salvar"),
                          ("final_newline", "Garantir linha em branco no fim do arquivo"),
                          ("autosave", "Salvar automaticamente ao trocar de aba / janela"),
                          ("lsp", "Ativar servidores de linguagem (LSP)"),
                          ("inlay_hints", "Inlay hints: tipos inferidos e nomes de parametros no meio da linha"),
                          ("usage_counts", "Contadores de uso ao lado de funcoes e classes"),
                          ("flow_analysis", "Analise de fluxo de dados propria (Python): None, codigo morto, recursos"),
                          ("git_gutter", "Marcadores do git e blame na lateral")]:
            cb = QCheckBox(text)
            cb.setChecked(bool(s[key]))
            cb.toggled.connect(lambda v, k=key: self._set(k, v))
            form.addRow("", cb)
        lay.addWidget(box)
        lay.addWidget(label("COMANDOS DE EXECUCAO (F5)", "section", 3))
        lay.addWidget(label("Variaveis: {file} {dir} {stem} {root}. Deixe vazio para usar o padrao.", "dim", 0.3))
        rb = CutFrame(cut=12)
        rf = QFormLayout(rb)
        rf.setContentsMargins(22, 18, 22, 18)
        rf.setSpacing(8)
        for lang in languages.LANGS:
            if not lang.run_command():
                continue
            e = QLineEdit(s["run_overrides"].get(lang.id, ""))
            e.setPlaceholderText(lang.run_command())
            e.setFont(mono_font(12))
            e.editingFinished.connect(lambda le=e, lid=lang.id: self._run(lid, le.text()))
            rf.addRow(label(lang.name.upper(), "muted", 1.5, 12, True), e)
        lay.addWidget(rb)
        lay.addStretch()
        self.setWidget(inner)

    def _set(self, k, v, refont=False):
        self.win.settings[k] = v
        self.win.settings.save()
        for ed in self.win.editors():
            ed.settings = self.win.settings
            if refont:
                ed.set_font_size(int(v))
        if k == "lsp":
            self.win.lsp.disabled = not v

    def _run(self, lid, text):
        ov = dict(self.win.settings["run_overrides"])
        if text.strip():
            ov[lid] = text.strip()
        else:
            ov.pop(lid, None)
        self.win.settings["run_overrides"] = ov
        self.win.settings.save()


# ================================================================ janela principal
class MainWindow(IntelMixin, QMainWindow):
    def __init__(self, open_paths: list[str]):
        super().__init__()
        self.settings = Settings()
        self.root: Path | None = None
        self.lsp = LspManager()
        self.lsp.disabled = not self.settings["lsp"]
        self.lsp_state: dict[str, str] = {}
        self._saving: dict[str, float] = {}
        self.untitled_n = 0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ASSETS / "arasaka-daemon.svg")))
        self.resize(1440, 900)

        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # barra de atividades
        act = QFrame()
        act.setObjectName("activity")
        act.setFixedWidth(52)
        al = QVBoxLayout(act)
        al.setContentsMargins(0, 8, 0, 8)
        al.setSpacing(2)
        lg = QLabel()
        lg.setPixmap(logo_pixmap(30))
        lg.setAlignment(Qt.AlignCenter)
        al.addWidget(lg)
        al.addSpacing(10)
        self.act_btns = {}
        for key, glyph, tip in [("explorer", "▤", "Explorador (Ctrl+Shift+E)"), ("search", "⌕", "Buscar (Ctrl+Shift+F)"),
                                ("structure", "≣", "Estrutura do arquivo (Ctrl+F12)"),
                                ("langs", "{ }", "Linguagens"), ("run", "▶", "Executar (F5)"),
                                ("debug", "⊛", "Depurar (Shift+F9)")]:
            b = QToolButton()
            b.setObjectName("act")
            b.setText(glyph)
            b.setToolTip(tip)
            b.setCheckable(key in ("explorer", "search", "structure"))
            b.setFixedSize(52, 48)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.activity(k))
            al.addWidget(b)
            self.act_btns[key] = b
        al.addStretch()
        cfg = QToolButton()
        cfg.setObjectName("act")
        cfg.setText("⚙")
        cfg.setToolTip("Configuracoes (Ctrl+,)")
        cfg.setFixedSize(52, 48)
        cfg.clicked.connect(self.show_settings)
        al.addWidget(cfg)
        h.addWidget(act)

        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setHandleWidth(1)
        # barra lateral
        self.side = QStackedWidget()
        self.side.setObjectName("side")
        self.side.setMinimumWidth(200)
        exp = QWidget()
        el = QVBoxLayout(exp)
        el.setContentsMargins(0, 8, 0, 0)
        el.setSpacing(4)
        eh = QHBoxLayout()
        eh.setContentsMargins(12, 0, 6, 0)
        self.exp_title = label("EXPLORADOR", "section", 3)
        eh.addWidget(self.exp_title, 1)
        for glyph, tip, fn in [("+", "Novo arquivo", lambda: self.new_in_tree(False)),
                               ("▣", "Nova pasta", lambda: self.new_in_tree(True)),
                               ("⟳", "Atualizar", self.refresh_tree), ("⊟", "Recolher", lambda: self.tree.collapseAll())]:
            b = button(glyph, "ghost", fn, tip)
            b.setFixedWidth(30)
            eh.addWidget(b)
        el.addLayout(eh)
        self.fsmodel = QFileSystemModel(self)
        self.fsmodel.setIconProvider(IconProvider())
        self.fsmodel.setReadOnly(False)
        self.fsmodel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.Hidden)
        self.tree = QTreeView()
        self.tree.setModel(self.fsmodel)
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.activated.connect(self.tree_open)
        self.tree.doubleClicked.connect(self.tree_open)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.no_folder = QWidget()
        nl = QVBoxLayout(self.no_folder)
        nl.addWidget(label("Nenhuma pasta aberta.", "muted", 0.5))
        nl.addWidget(button("ABRIR PASTA", "primary", self.open_folder_dialog))
        nl.addStretch()
        el.addWidget(self.no_folder)
        el.addWidget(self.tree, 1)
        self.side.addWidget(exp)
        self.search = SearchPanel()
        self.search.open_location.connect(self.open_location)
        self.side.addWidget(self.search)
        self.structure = StructurePanel()
        self.structure.open_location.connect(self.open_location)
        self.side.addWidget(self.structure)
        self.hsplit.addWidget(self.side)

        # editor + painel inferior
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setHandleWidth(1)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.findbar = FindBar(self.editor)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        cl.addWidget(self.findbar)
        cl.addWidget(self.tabs, 1)
        self.vsplit.addWidget(center)

        self.bottom = QTabWidget()
        self.bottom.setObjectName("bottom")
        self.bottom.setDocumentMode(True)
        self.terminal = Terminal()
        out_wrap = QWidget()
        ol = QVBoxLayout(out_wrap)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)
        self.output = OutputPanel()
        ol.addWidget(self.output, 1)
        orow = QHBoxLayout()
        orow.setContentsMargins(8, 4, 8, 4)
        self.stdin = QLineEdit()
        self.stdin.setFont(mono_font(13))
        self.stdin.setPlaceholderText("entrada do programa (stdin) + Enter")
        self.stdin.returnPressed.connect(lambda: (self.output.write_input(self.stdin.text()), self.stdin.clear()))
        orow.addWidget(self.stdin, 1)
        orow.addWidget(button("■ PARAR", "ghost", self.output.stop))
        ol.addLayout(orow)
        self.problems = ProblemsPanel()
        self.problems.open_location.connect(self.open_location)
        self.lsplog = OutputPanel()
        self.refs = LocationsPanel()
        self.refs.open_location.connect(self.open_location)
        self.debug_panel = DebugPanel()
        self.debug_panel.command.connect(self.debug_cmd)
        self.debug_panel.open_location.connect(lambda p, l, c: self.open_file(Path(p), l, c))
        self.debug_panel.watches_changed.connect(
            lambda ws: self.debug and self.debug.send({"cmd": "watches", "list": ws}))
        self.profiler = ProfilerPanel()
        self.profiler.open_location.connect(self.open_location)
        self.bottom.addTab(self.terminal, "TERMINAL")
        self.bottom.addTab(out_wrap, "SAIDA")
        self.bottom.addTab(self.problems, "PROBLEMAS")
        self.bottom.addTab(self.lsplog, "LSP")
        self.bottom.addTab(self.refs, "REFERENCIAS")
        self.bottom.addTab(self.debug_panel, "DEPURAR")
        self.bottom.addTab(self.profiler, "PROFILER")
        self.vsplit.addWidget(self.bottom)
        self.vsplit.setStretchFactor(0, 4)
        self.vsplit.setStretchFactor(1, 1)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setStretchFactor(1, 1)
        h.addWidget(self.hsplit, 1)
        self.setCentralWidget(root)
        self.hsplit.setSizes([270, 1100])
        self.vsplit.setSizes([640, 220])

        # barra de status
        sb = self.statusBar()
        self.st_branch = QLabel("")
        self.st_problems = QLabel("■ 0  ▲ 0")
        self.st_pos = QLabel("")
        self.st_indent = QLabel("")
        self.st_enc = QLabel("")
        self.st_lang = QPushButton("")
        self.st_lang.setFlat(True)
        self.st_lang.setStyleSheet("QPushButton { color: #ffffff; border: none; padding: 0 10px; font-weight: 700;"
                                   " background: transparent; } QPushButton:hover { background: rgba(0,0,0,0.25); }")
        self.st_lang.clicked.connect(self.pick_language)
        self.st_lsp = QLabel("")
        sb.addWidget(self.st_branch)
        sb.addWidget(self.st_problems)
        for w in (self.st_pos, self.st_indent, self.st_enc, self.st_lang, self.st_lsp):
            sb.addPermanentWidget(w)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.file_changed_on_disk)
        self.lsp.diagnostics.connect(self.on_diagnostics)
        self.lsp.log.connect(lambda t: self.lsplog.append_color(t + "\n", "#8c8c96"))
        self.lsp.status.connect(self.on_lsp_status)

        self.setup_intel()
        self.build_menus()
        self.welcome = WelcomePage(self)
        self.tabs.addTab(self.welcome, QIcon(logo_pixmap(16)), "BEM-VINDO")
        self.activity("explorer")
        self.restore_session(open_paths)

    # ------------------------------------------------------------ menus
    def build_menus(self):
        mb = self.menuBar()
        self.actions_list: list[QAction] = []

        def add(menu, text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(lambda _=False, s=slot: s())
            menu.addAction(a)
            self.actions_list.append(a)
            return a

        m = mb.addMenu("ARQUIVO")
        add(m, "Novo arquivo", self.new_file, "Ctrl+N")
        add(m, "Abrir arquivo...", self.open_file_dialog, "Ctrl+O")
        add(m, "Abrir pasta...", self.open_folder_dialog, "Ctrl+Shift+O")
        self.recent_menu = m.addMenu("Pastas recentes")
        self.recent_menu.aboutToShow.connect(self.fill_recent)
        m.addSeparator()
        add(m, "Salvar", self.save_current, "Ctrl+S")
        add(m, "Salvar como...", lambda: self.save_current(True), "Ctrl+Shift+S")
        add(m, "Salvar tudo", self.save_all, "Ctrl+Alt+S")
        m.addSeparator()
        add(m, "Fechar aba", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        add(m, "Fechar pasta", self.close_folder)
        add(m, "Sair", self.close, "Ctrl+Q")
        m = mb.addMenu("EDITAR")
        add(m, "Buscar", lambda: self.findbar.open(False), "Ctrl+F")
        add(m, "Substituir", lambda: self.findbar.open(True), "Ctrl+H")
        add(m, "Buscar nos arquivos", lambda: self.activity("search", force=True), "Ctrl+Shift+F")
        m.addSeparator()
        add(m, "Ir para linha...", self.goto_line, "Ctrl+G")
        add(m, "Ir para definicao", self.goto_definition, "F12")
        add(m, "Formatar documento", self.format_document, "Shift+Alt+F")
        self.intel_menus(add, mb)
        m = mb.addMenu("VER")
        add(m, "Paleta de comandos", self.command_palette, "Ctrl+Shift+P")
        add(m, "Abrir arquivo do projeto", self.quick_open, "Ctrl+P")
        add(m, "Explorador", lambda: self.activity("explorer", force=True), "Ctrl+Shift+E")
        add(m, "Mostrar/ocultar painel", self.toggle_bottom, "Ctrl+J")
        add(m, "Terminal", lambda: self.show_bottom(0, focus=True), "Ctrl+`")
        add(m, "Problemas", lambda: self.show_bottom(2), "Ctrl+Shift+M")
        m.addSeparator()
        add(m, "Aumentar fonte", lambda: self.zoom(1), "Ctrl+=")
        add(m, "Diminuir fonte", lambda: self.zoom(-1), "Ctrl+-")
        m.addSeparator()
        add(m, "Linguagens", self.show_languages)
        add(m, "Configuracoes", self.show_settings, "Ctrl+,")
        self.intel_view_menu(add, m)
        m = mb.addMenu("EXECUTAR")
        add(m, "Executar arquivo", self.run_current, "F5")
        add(m, "Executar no terminal", lambda: self.run_current(in_terminal=True), "Ctrl+F5")
        add(m, "Parar", self.output.stop, "Shift+F5")
        self.intel_run_menu(add, m)
        m.addSeparator()
        add(m, "Reiniciar servidores de linguagem", self.restart_lsp)
        m = mb.addMenu("AJUDA")
        add(m, "Bem-vindo", self.show_welcome)
        add(m, "Sobre", lambda: QMessageBox.about(self, APP_NAME, f"{APP_NAME} v{VERSION}\n\nIDE com tema Arasaka "
                                                  "para Linux e Windows. Realce para "
                                                  f"{len(languages.LANGS)} linguagens e LSP.\n\nArasaka e marca da "
                                                  "CD PROJEKT RED; projeto pessoal de fa."))

    def fill_recent(self):
        self.recent_menu.clear()
        for r in self.settings.get("recent", [])[:10]:
            self.recent_menu.addAction(r, lambda p=r: self.open_folder(Path(p)))

    # ------------------------------------------------------------ util
    def editor(self) -> CodeEditor | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditor) else None

    def editors(self) -> list[CodeEditor]:
        return [self.tabs.widget(i) for i in range(self.tabs.count()) if isinstance(self.tabs.widget(i), CodeEditor)]

    def toast(self, text: str):
        self.statusBar().showMessage("  " + text, 4000)

    def activity(self, key: str, force: bool = False):
        if key == "langs":
            return self.show_languages()
        if key == "run":
            return self.run_current()
        if key == "debug":
            return self.start_debug()
        idx = {"explorer": 0, "search": 1, "structure": 2}[key]
        visible = self.side.isVisible() and self.side.currentIndex() == idx
        if visible and not force:
            self.side.hide()
            self.act_btns[key].setChecked(False)
            return
        self.side.show()
        self.side.setCurrentIndex(idx)
        for k in ("explorer", "search", "structure"):
            self.act_btns[k].setChecked(k == key)
        if key == "structure":
            self.schedule_intel()
            self.structure.q.setFocus()
        if key == "search":
            ed = self.editor()
            if ed and ed.textCursor().hasSelection():
                self.search.q.setText(ed.textCursor().selectedText())
            self.search.q.setFocus()
            self.search.q.selectAll()

    def toggle_bottom(self):
        self.bottom.setVisible(not self.bottom.isVisible())

    def show_bottom(self, idx: int, focus=False):
        self.bottom.show()
        self.bottom.setCurrentIndex(idx)
        if focus and idx == 0:
            self.terminal.inp.setFocus()

    def zoom(self, d: int):
        ed = self.editor()
        if ed:
            ed.zoom(d)

    def page_tab(self, attr: str, cls, title: str):
        w = getattr(self, attr, None)
        if w is None or self.tabs.indexOf(w) < 0:
            w = cls(self)
            setattr(self, attr, w)
            self.tabs.addTab(w, title)
        self.tabs.setCurrentWidget(w)
        return w

    def show_languages(self):
        w = self.page_tab("lang_page", LanguagesPage, "LINGUAGENS")
        w.build()

    def show_settings(self):
        self.page_tab("settings_page", SettingsPage, "CONFIGURACOES")

    def show_welcome(self):
        if self.tabs.indexOf(self.welcome) < 0:
            self.tabs.addTab(self.welcome, QIcon(logo_pixmap(16)), "BEM-VINDO")
        self.welcome.refresh()
        self.tabs.setCurrentWidget(self.welcome)

    def install(self, cmd: str):
        if sys.platform != "win32":
            cmd = cmd.replace("sudo ", "pkexec ")
        self.show_bottom(0)
        self.terminal.run(cmd)
        self.toast("Instalando no terminal... depois clique em REVERIFICAR")

    # ------------------------------------------------------------ pastas
    def open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Abrir pasta", str(self.root or Path.home()))
        if d:
            self.open_folder(Path(d))

    def open_folder(self, path: Path):
        path = Path(path).resolve()
        if not path.is_dir():
            return
        self.root = path
        self.fsmodel.setRootPath(str(path))
        self.tree.setRootIndex(self.fsmodel.index(str(path)))
        self.no_folder.hide()
        self.tree.show()
        self.exp_title.setText(path.name.upper())
        self.search.root = path
        rec = [str(path)] + [r for r in self.settings.get("recent", []) if r != str(path)]
        self.settings["recent"] = rec[:12]
        self.settings.save()
        self.terminal.start(path)
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self.st_branch.setText(("⎇ " + git_branch(path)) if git_branch(path) else "")
        self.welcome.refresh()
        self.build_index()

    def close_folder(self):
        self.root = None
        self.tree.hide()
        self.no_folder.show()
        self.exp_title.setText("EXPLORADOR")
        self.setWindowTitle(APP_NAME)

    def refresh_tree(self):
        if self.root:
            self.fsmodel.setRootPath("")
            self.fsmodel.setRootPath(str(self.root))
            self.tree.setRootIndex(self.fsmodel.index(str(self.root)))

    def tree_open(self, idx: QModelIndex):
        p = Path(self.fsmodel.filePath(idx))
        if p.is_file():
            self.open_file(p)

    def tree_selected_dir(self) -> Path | None:
        idx = self.tree.currentIndex()
        if idx.isValid():
            p = Path(self.fsmodel.filePath(idx))
            return p if p.is_dir() else p.parent
        return self.root

    def new_in_tree(self, folder: bool):
        base = self.tree_selected_dir()
        if not base:
            return self.new_file()
        name, ok = QInputDialog.getText(self, "Nova pasta" if folder else "Novo arquivo", "Nome:")
        if not ok or not name.strip():
            return
        p = base / name.strip()
        try:
            if folder:
                p.mkdir(parents=True, exist_ok=False)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch(exist_ok=False)
                self.open_file(p)
        except OSError as e:
            QMessageBox.warning(self, "Erro", str(e))

    def tree_menu(self, pos):
        idx = self.tree.indexAt(pos)
        p = Path(self.fsmodel.filePath(idx)) if idx.isValid() else self.root
        if not p:
            return
        m = QMenu(self)
        if p.is_file():
            m.addAction("Abrir", lambda: self.open_file(p))
            if languages.detect(p).run_command():
                m.addAction("Executar", lambda: (self.open_file(p), self.run_current()))
            m.addSeparator()
        m.addAction("Novo arquivo", lambda: self.new_in_tree(False))
        m.addAction("Nova pasta", lambda: self.new_in_tree(True))
        m.addSeparator()
        m.addAction("Renomear", lambda: self.rename(p))
        if p.is_file():
            m.addAction("Exclusao segura (procura referencias)...", lambda: self.safe_delete_file(p))
            m.addAction("Historico local", lambda: (self.open_file(p), self.file_history()))
        m.addAction("Excluir (lixeira)", lambda: self.delete_path(p))
        m.addSeparator()
        m.addAction("Copiar caminho", lambda: QApplication.clipboard().setText(str(p)))
        m.addAction("Abrir no gerenciador de arquivos",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p if p.is_dir() else p.parent))))
        m.addAction("Abrir terminal aqui", lambda: (self.show_bottom(0), self.terminal.run(
            f'cd "{p if p.is_dir() else p.parent}"')))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def rename(self, p: Path):
        name, ok = QInputDialog.getText(self, "Renomear", "Novo nome:", text=p.name)
        if ok and name.strip() and name != p.name:
            new = p.with_name(name.strip())
            try:
                p.rename(new)
            except OSError as e:
                QMessageBox.warning(self, "Erro", str(e))
                return
            for ed in self.editors():
                if ed.path and ed.path == p:
                    ed.path = new
                    self.update_tab(ed)

    def delete_path(self, p: Path):
        if QMessageBox.question(self, "Excluir", f"Mover para a lixeira?\n{p}") != QMessageBox.Yes:
            return
        self._trash(p)

    # ------------------------------------------------------------ arquivos
    def open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Abrir arquivo", str(self.root or Path.home()))
        for f in files:
            self.open_file(Path(f))

    def new_file(self):
        self.untitled_n += 1
        ed = CodeEditor(None, self.settings)
        ed.untitled_name = f"sem-titulo-{self.untitled_n}"
        self.add_editor(ed)

    def open_file(self, path: Path, line: int | None = None, col: int = 0) -> CodeEditor | None:
        path = Path(path).resolve()
        for ed in self.editors():
            if ed.path and ed.path.resolve() == path:
                self.tabs.setCurrentWidget(ed)
                if line is not None:
                    ed.goto(line, col)
                return ed
        if not path.is_file():
            return None
        try:
            if path.stat().st_size > 20_000_000:
                QMessageBox.warning(self, "Arquivo grande", "Arquivo maior que 20 MB: abrir nao e suportado.")
                return None
            with open(path, "rb") as f:
                if b"\0" in f.read(8000):
                    QMessageBox.information(self, "Binario", f"{path.name} parece ser um arquivo binario.")
                    return None
            ed = CodeEditor(path, self.settings)
        except OSError as e:
            QMessageBox.warning(self, "Erro", str(e))
            return None
        self.add_editor(ed)
        self.watcher.addPath(str(path))
        self.lsp_open(ed)
        if line is not None:
            ed.goto(line, col)
        return ed

    def add_editor(self, ed: CodeEditor):
        i = self.tabs.addTab(ed, lang_icon(ed.lang), ed.title())
        self.tabs.setTabToolTip(i, str(ed.path or ed.title()))
        self.tabs.setCurrentIndex(i)
        ed.document().modificationChanged.connect(lambda _m, e=ed: self.update_tab(e))
        ed.cursor_moved.connect(self.update_status)
        ed.text_changed_debounced.connect(lambda e=ed: self.lsp_change(e))
        ed.completion_requested.connect(lambda ln, col, trig, e=ed: self.complete(e, ln, col, trig))
        ed.hover_requested.connect(lambda ln, col, gp, e=ed: self.hover(e, ln, col, gp))
        ed.definition_requested.connect(lambda ln, col, e=ed: self.definition(e, ln, col))
        self.intel_attach(ed)
        ed.setFocus()
        self.update_status()

    def update_tab(self, ed: CodeEditor):
        i = self.tabs.indexOf(ed)
        if i >= 0:
            self.tabs.setTabText(i, ("● " if ed.document().isModified() else "") + ed.title())
            self.tabs.setTabIcon(i, lang_icon(ed.lang))
            self.tabs.setTabToolTip(i, str(ed.path or ed.title()))

    def tab_changed(self, _i):
        if self.settings["autosave"]:
            self.save_all(quiet=True)
        self.findbar.update_hits()
        self.update_status()
        if hasattr(self, "history"):
            self.schedule_intel()

    def save_editor(self, ed: CodeEditor, as_new=False) -> bool:
        if ed.path is None or as_new:
            start = str((self.root or Path.home()) / (ed.path.name if ed.path else ed.title()))
            p, _ = QFileDialog.getSaveFileName(self, "Salvar como", start)
            if not p:
                return False
            ed.save(Path(p))
            self.watcher.addPath(p)
            self.lsp_open(ed)
        else:
            self._saving[str(ed.path)] = time.time()
            try:
                ed.save()
            except OSError as e:
                QMessageBox.warning(self, "Erro ao salvar", str(e))
                return False
        self.update_tab(ed)
        c = self.lsp_client(ed)
        if c:
            c.did_save(ed.path, ed.toPlainText())
        self.snapshot(ed, "salvo")
        self.reindex_file(ed.path, ed.toPlainText())
        self.refresh_git(ed)
        self.schedule_intel(ed)
        self.toast(f"salvo: {ed.path}")
        return True

    def save_current(self, as_new=False):
        ed = self.editor()
        if ed:
            self.save_editor(ed, as_new)

    def save_all(self, quiet=False):
        for ed in self.editors():
            if ed.document().isModified() and (ed.path or not quiet):
                self.save_editor(ed)

    def close_tab(self, i: int):
        w = self.tabs.widget(i)
        if w is None:
            return
        if isinstance(w, CodeEditor):
            if w.document().isModified():
                r = QMessageBox.question(self, "Salvar?", f"Salvar alteracoes em {w.title()}?",
                                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
                if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save_editor(w)):
                    return
            c = self.lsp_client(w)
            if c and w.path:
                c.did_close(w.path)
            if w.path:
                self.watcher.removePath(str(w.path))
                self.problems.set_file(str(w.path), [])
                self.local_diags.pop(str(w.path), None)
            if w is self.debug_editor:
                self.debug_editor = None
        self.tabs.removeTab(i)
        if isinstance(w, CodeEditor):
            w.deleteLater()

    def file_changed_on_disk(self, path: str):
        if time.time() - self._saving.get(path, 0) < 2:
            return
        for ed in self.editors():
            if ed.path and str(ed.path) == path:
                if not Path(path).exists():
                    return
                if not ed.document().isModified():
                    self.snapshot(ed, "antes de recarregar do disco")
                    ed.reload()
                    self.lsp_change(ed)
                    self.toast(f"recarregado: {ed.path.name}")
                else:
                    self.toast(f"{ed.path.name} mudou no disco (voce tem alteracoes nao salvas)")
        if Path(path).exists() and path not in self.watcher.files():
            self.watcher.addPath(path)

    def open_location(self, path: str, line: int, col: int):
        self.jump(path, line, col)

    def goto_line(self):
        ed = self.editor()
        if not ed:
            return
        n, ok = QInputDialog.getInt(self, "Ir para linha", f"Linha (1 - {ed.blockCount()}):",
                                    ed.textCursor().blockNumber() + 1, 1, ed.blockCount())
        if ok:
            ed.goto(n - 1)

    def pick_language(self):
        ed = self.editor()
        if not ed:
            return
        items = [(l.name, " ".join(l.exts[:3]), l.id) for l in languages.LANGS + [languages.PLAIN]]
        p = Picker(self, "Linguagem do arquivo", items)
        if p.exec() and p.result:
            lang = languages.BY_ID.get(p.result, languages.PLAIN)
            ed.set_language(lang)
            self.update_tab(ed)
            self.update_status()
            self.lsp_open(ed)

    # ------------------------------------------------------------ paleta / abrir rapido
    def quick_open(self):
        if not self.root:
            return self.open_file_dialog()
        files = []
        for f in walk_files(self.root, 20000):
            rel = os.path.relpath(f, self.root)
            files.append((f.name, os.path.dirname(rel), str(f)))
        p = Picker(self, "Buscar arquivo pelo nome...", files, lambda n: lang_icon(languages.detect(n)))
        if p.exec() and p.result:
            self.open_file(Path(p.result))

    def command_palette(self):
        items = [(a.text(), a.shortcut().toString(QKeySequence.NativeText), a) for a in self.actions_list]
        p = Picker(self, "Comando...", items)
        if p.exec() and p.result:
            p.result.trigger()

    # ------------------------------------------------------------ status
    def update_status(self, *_):
        ed = self.editor()
        if not ed:
            for w in (self.st_pos, self.st_indent, self.st_enc, self.st_lsp):
                w.setText("")
            self.st_lang.setText("")
            return
        ln, col = ed.line_col()
        sel = len(ed.textCursor().selectedText())
        self.st_pos.setText(f"Ln {ln + 1}, Col {col + 1}" + (f"  ({sel} sel.)" if sel else ""))
        self.st_indent.setText("Tabs" if ed.indent_unit == "\t" else f"Espacos: {len(ed.indent_unit)}")
        self.st_enc.setText(f"{ed.encoding.upper().replace('-SIG', ' BOM')}  {'CRLF' if ed.newline == chr(13) + chr(10) else 'LF'}")
        self.st_lang.setText(ed.lang.name)
        st = self.lsp_state.get(ed.lang.id, "")
        self.st_lsp.setText({"ready": "◆ LSP", "starting": "◇ LSP...", "missing": "◇ sem LSP",
                             "error": "✕ LSP", "stopped": "◇ LSP parado"}.get(st, ""))
        self.st_lsp.setToolTip("Servidor de linguagem: " + (st or "nenhum"))

    # ------------------------------------------------------------ LSP
    def project_root_for(self, path: Path) -> Path:
        if self.root and str(path).startswith(str(self.root)):
            return self.root
        markers = (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
                   "CMakeLists.txt", "compile_commands.json", "composer.json", "Gemfile")
        p = path.parent
        while p != p.parent:
            if any((p / m).exists() for m in markers) or list(p.glob("*.csproj")) or list(p.glob("*.sln")):
                return p
            p = p.parent
        return path.parent

    def lsp_client(self, ed: CodeEditor):
        if not ed.path or self.lsp.disabled:
            return None
        return self.lsp.client_for(ed.lang, self.project_root_for(ed.path))

    def lsp_open(self, ed: CodeEditor):
        c = self.lsp_client(ed)
        if c:
            c.did_open(ed.path, ed.toPlainText(), ed.version)
        self.update_status()

    def lsp_change(self, ed: CodeEditor):
        c = self.lsp_client(ed)
        if c:
            c.did_change(ed.path, ed.toPlainText(), ed.version)

    def on_lsp_status(self, lid: str, st: str):
        self.lsp_state[lid] = st
        self.update_status()

    def on_diagnostics(self, uri: str, diags: list):
        path = from_uri(uri).resolve()
        self.lsp_diags[str(path)] = diags
        matched = False
        for ed in self.editors():
            if ed.path and ed.path.resolve() == path:
                self.merge_diagnostics(ed)
                matched = True
        if not matched:
            self.problems.set_file(str(path), diags)
        e, w = self.problems.counts()
        self.st_problems.setText(f"■ {e}  ▲ {w}")

    def complete(self, ed: CodeEditor, ln: int, col: int, trig: str):
        c = self.lsp_client(ed)
        if not c or not c.ready:
            ed.show_completions([])
            return
        c.did_change(ed.path, ed.toPlainText(), ed.version)
        ver = ed.version

        def done(items):
            if ed.version == ver and ed.line_col() == (ln, col):
                ed.show_completions(items)
        c.completion(ed.path, ln, col, trig, done)

    def hover(self, ed: CodeEditor, ln: int, col: int, gp):
        c = self.lsp_client(ed)
        if not c or not c.ready:
            return

        def done(text):
            if text:
                QToolTip.showText(gp, text[:1500], ed)
        c.hover(ed.path, ln, col, done)

    def definition(self, ed: CodeEditor, ln: int, col: int):
        c = self.lsp_client(ed)
        if not c:
            self.toast("Ir para definicao precisa de um servidor de linguagem (aba LINGUAGENS)")
            return

        def done(loc):
            if loc:
                self.jump(loc[0], loc[1], loc[2])
            else:
                self.toast("Definicao nao encontrada")
        c.definition(ed.path, ln, col, done)

    def goto_definition(self):
        ed = self.editor()
        if ed:
            ln, col = ed.line_col()
            self.definition(ed, ln, col)

    def format_document(self):
        ed = self.editor()
        c = self.lsp_client(ed) if ed else None
        if not c:
            self.toast("Formatar precisa de um servidor de linguagem (aba LINGUAGENS)")
            return
        c.did_change(ed.path, ed.toPlainText(), ed.version)
        c.formatting(ed.path, len(ed.indent_unit) if ed.indent_unit != "\t" else 4, ed.indent_unit != "\t",
                     lambda edits: edits and ed.apply_edits(edits) or self.toast(
                         "formatado" if edits else "nada a formatar"))

    def restart_lsp(self):
        self.lsp.restart()
        self.lsp_state.clear()
        for ed in self.editors():
            self.lsp_open(ed)
        self.toast("servidores de linguagem reiniciados")

    # ------------------------------------------------------------ executar
    def run_current(self, in_terminal: bool = False):
        ed = self.editor()
        if not ed:
            return self.toast("Abra um arquivo para executar")
        if ed.lang.id == "http":
            return self.run_http(ed)
        if ed.document().isModified() or ed.path is None:
            if not self.save_editor(ed):
                return
        self.snapshot(ed, "executado")
        tmpl = self.settings["run_overrides"].get(ed.lang.id) or ed.lang.run_command()
        venv = analysis.python_project_venv(self.root) if ed.lang.id == "python" else None
        if venv and not self.settings["run_overrides"].get("python"):
            tmpl = re.sub(r"^\S+", lambda _m: f'"{venv}"', tmpl, count=1)
        if not tmpl:
            return self.toast(f"Sem comando de execucao para {ed.lang.name} (configure em CONFIGURACOES)")
        f = ed.path
        cmd = (tmpl.replace("{file}", str(f)).replace("{dir}", str(f.parent)).replace("{stem}", f.stem)
               .replace("{root}", str(self.root or f.parent)))
        cwd = f.parent if ed.lang.id != "csharp" else self.project_root_for(f)
        if in_terminal:
            self.show_bottom(0)
            self.terminal.run(f'cd "{cwd}"')
            self.terminal.run(cmd)
            return
        self.show_bottom(1)
        self.output.run(languages.shell_argv(cmd), cwd, f"{ed.lang.name.upper()}  //  {f.name}")
        self.stdin.setFocus()

    # ------------------------------------------------------------ sessao
    def restore_session(self, open_paths: list[str]):
        sess = self.settings.get("session") or {}
        folder = next((p for p in open_paths if Path(p).is_dir()), None)
        files = [p for p in open_paths if Path(p).is_file()]
        if folder:
            self.open_folder(Path(folder))
        elif not files and sess.get("root") and Path(sess["root"]).is_dir():
            self.open_folder(Path(sess["root"]))
            for f in sess.get("files", []):
                if Path(f).is_file():
                    self.open_file(Path(f))
            cur = sess.get("current")
            if cur:
                self.open_file(Path(cur))
        elif files and not folder:
            self.open_folder(Path(files[0]).parent)
        for f in files:
            self.open_file(Path(f))
        if not self.root:
            self.close_folder()

    def closeEvent(self, e):
        dirty = [ed for ed in self.editors() if ed.document().isModified()]
        if dirty:
            r = QMessageBox.question(self, "Alteracoes nao salvas",
                                     f"{len(dirty)} arquivo(s) com alteracoes. Salvar antes de sair?",
                                     QMessageBox.SaveAll | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                e.ignore()
                return
            if r == QMessageBox.SaveAll:
                for ed in dirty:
                    if not self.save_editor(ed):
                        e.ignore()
                        return
        cur = self.editor()
        self.settings["session"] = {"root": str(self.root) if self.root else "",
                                    "files": [str(ed.path) for ed in self.editors() if ed.path],
                                    "current": str(cur.path) if cur and cur.path else ""}
        self.settings.save()
        self.stop_debug()
        self.lsp.stop_all()
        self.terminal.shutdown()
        self.output.stop()
        e.accept()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)


def main(argv: list[str] | None = None):
    argv = list(sys.argv if argv is None else argv)
    QApplication.setApplicationName(APP_ID)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(APP_ID)
    app = QApplication(argv)
    load_fonts()
    app.setStyleSheet(stylesheet() + EXTRA_QSS)
    app.setWindowIcon(QIcon(str(ASSETS / "arasaka-daemon.svg")))
    paths = [a for a in argv[1:] if not a.startswith("--")]
    win = MainWindow(paths)
    # visual Cyberpunk (CRT, glitch, inicialização, barra de status); sem a tela de inicialização nas prévias
    fx.install(win, name="ARASAKA DAEMON", icon=ASSETS / "arasaka-daemon.svg", boot=not any(a.startswith("--screenshot=") for a in argv))
    win.show()
    app.applicationStateChanged.connect(
        lambda st: st != Qt.ApplicationActive and win.settings["autosave"] and win.save_all(quiet=True))
    shot = next((a.split("=", 1)[1] for a in argv if a.startswith("--screenshot=")), None)
    if shot:
        delay = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--delay=")), "3000"))
        QTimer.singleShot(delay, lambda: (win.grab().save(shot), app.quit()))
    return app.exec()
