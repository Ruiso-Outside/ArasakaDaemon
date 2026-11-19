"""
ARASAKA DAEMON // recursos de IDE avancada (mixin da janela principal).

  1. Inteligencia semantica: analise propria (AST) + LSP, inlay hints,
     contadores de uso, estrutura do arquivo.
  2. Refatoracao: renomear, alterar assinatura, extrair variavel / constante /
     metodo, exclusao segura (simbolo e arquivo), code actions do servidor.
  3. Navegacao: Search Everywhere (Shift Shift), usos, implementacao,
     definicao do tipo, hierarquia de chamadas e de tipos, ir para o teste,
     voltar/avancar, historico local.
  4. Depuracao (Python): breakpoints condicionais, logpoints, passo a passo,
     valores inline, avaliar expressao, observar; profiler de CPU e memoria.
  5. Ecossistema: git (marcadores, blame, diff com HEAD, conflitos), cliente
     HTTP (.http), ambiente virtual do projeto.
  6. Intention actions (Alt+Enter) e live templates.
"""
from __future__ import annotations

import ast
import collections
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QDialog, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QVBoxLayout)

from . import analysis, debugger, languages, tools
from .history import LocalHistory, data_dir, unified
from .intel import (ChangeSignatureDialog, HistoryDialog, SearchEverywhere, UsagesDialog)
from .lsp import SYMBOL_KIND, from_uri
from .panels import Picker, lang_icon, walk_files

IDENT = re.compile(r"[A-Za-z_$][\w$]*")
USAGE_KINDS = {5, 6, 9, 10, 11, 12, 23, 26}


# ================================================================ threads auxiliares
class IndexWorker(QThread):
    """Indice de definicoes + contagem de identificadores por arquivo (Search Everywhere, hierarquias, usos)."""
    ready = Signal(object, object)

    def __init__(self, root: Path):
        super().__init__()
        self.root = root

    def run(self):
        defs, words = [], {}
        for f in walk_files(self.root, 25000):
            if f.suffix.lower() not in analysis.SOURCE_EXTS:
                continue
            try:
                if f.stat().st_size > 1_500_000:
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            defs += analysis.scan_definitions(f, text)
            words[str(f)] = collections.Counter(IDENT.findall(text))
        self.ready.emit(defs, words)


class ShiftShift(QObject):
    """Detecta Shift pressionado duas vezes seguidas (Search Everywhere)."""

    def __init__(self, cb):
        super().__init__()
        self.cb = cb
        self.last = 0.0
        self.clean = True

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.KeyPress:
            if e.key() != Qt.Key_Shift:
                self.clean = False
                self.last = 0.0
            elif not e.isAutoRepeat():
                self.clean = True
        elif t == QEvent.KeyRelease and e.key() == Qt.Key_Shift and not e.isAutoRepeat() and self.clean:
            now = time.time()
            if now - self.last < 0.4:
                self.last = 0.0
                QTimer.singleShot(0, self.cb)
            else:
                self.last = now
        return False


def _offset_to_lc(text: str, off: int) -> tuple[int, int]:
    line = text.count("\n", 0, off)
    col = off - (text.rfind("\n", 0, off) + 1)
    return line, col


def _lc_to_offset(text: str, line: int, col: int) -> int:
    pos = 0
    for _ in range(line):
        nl = text.find("\n", pos)
        if nl < 0:
            return len(text)
        pos = nl + 1
    return min(len(text), pos + col)


class IntelMixin:
    # ============================================================ configuracao
    def setup_intel(self):
        self.history = LocalHistory()
        self.lsp_diags: dict[str, list] = {}
        self.local_diags: dict[str, list] = {}
        self.def_index: list[dict] = []
        self.word_counts: dict[str, collections.Counter] = {}
        self.head_cache: dict[str, str | None] = {}
        self.nav_back: list[tuple] = []
        self.nav_fwd: list[tuple] = []
        self.debug: debugger.DebugSession | None = None
        self.debug_editor = None
        self._index_worker = None
        self._http_worker = None
        self._intel_timer = QTimer(self)
        self._intel_timer.setSingleShot(True)
        self._intel_timer.setInterval(250)
        self._intel_timer.timeout.connect(self.refresh_intel)
        self._snap_timer = QTimer(self)
        self._snap_timer.setInterval(120_000)
        self._snap_timer.timeout.connect(lambda: self.snapshot_all("edicao"))
        self._snap_timer.start()
        self.lsp.apply_edit.connect(lambda edit: self.apply_workspace_edit(edit, "acao do servidor"))
        self._shift = ShiftShift(self.search_everywhere)
        QApplication.instance().installEventFilter(self._shift)

    def intel_menus(self, add, mb):
        """Recebe a funcao add(menu, texto, slot, atalho) da janela."""
        m = mb.addMenu("REFATORAR")
        add(m, "Acoes de contexto / intencoes", self.intention_actions, "Alt+Return")
        m.addSeparator()
        add(m, "Renomear simbolo...", self.rename_symbol, "F2")
        add(m, "Alterar assinatura...", self.change_signature, "Ctrl+F6")
        add(m, "Extrair variavel...", self.extract_variable, "Ctrl+Alt+V")
        add(m, "Extrair constante...", self.extract_constant, "Ctrl+Alt+C")
        add(m, "Extrair metodo / funcao...", self.extract_method, "Ctrl+Alt+M")
        add(m, "Exclusao segura do simbolo", self.safe_delete_symbol, "Alt+Delete")
        m.addSeparator()
        add(m, "Organizar imports", lambda: self.run_code_action_kind("source.organizeImports"), "Ctrl+Alt+O")
        m = mb.addMenu("NAVEGAR")
        add(m, "Search Everywhere (Shift Shift)", self.search_everywhere, "Ctrl+Shift+A")
        add(m, "Estrutura do arquivo", lambda: self.activity("structure", force=True), "Ctrl+F12")
        m.addSeparator()
        add(m, "Encontrar usos (referencias)", self.find_usages, "Shift+F12")
        add(m, "Ir para implementacao", self.goto_implementation, "Ctrl+Alt+B")
        add(m, "Ir para definicao do tipo", self.goto_type_definition, "Ctrl+Shift+B")
        add(m, "Hierarquia de chamadas", self.call_hierarchy, "Ctrl+Alt+H")
        add(m, "Hierarquia de tipos", self.type_hierarchy, "Ctrl+Alt+U")
        add(m, "Ir para o teste / codigo", self.goto_test, "Ctrl+Shift+T")
        m.addSeparator()
        add(m, "Voltar", self.nav_go_back, "Alt+Left")
        add(m, "Avancar", self.nav_go_forward, "Alt+Right")
        m.addSeparator()
        add(m, "Historico local do arquivo", self.file_history, "Alt+Shift+H")
        add(m, "Historico local do projeto (inclui excluidos)", self.project_history)
        m = mb.addMenu("GIT")
        add(m, "Mostrar / ocultar blame", self.toggle_blame, "Ctrl+Alt+A")
        add(m, "Comparar com HEAD", self.diff_with_head, "Ctrl+Alt+D")
        add(m, "Reverter arquivo para HEAD", self.revert_to_head)
        m.addSeparator()
        add(m, "Conflito: aceitar o atual (ours)", lambda: self.resolve_conflict("ours"))
        add(m, "Conflito: aceitar o recebido (theirs)", lambda: self.resolve_conflict("theirs"))
        add(m, "Conflito: aceitar os dois", lambda: self.resolve_conflict("both"))
        add(m, "Proximo conflito", self.next_conflict, "Ctrl+Alt+N")
        return m

    def intel_run_menu(self, add, m):
        m.addSeparator()
        add(m, "Depurar arquivo (Python)", self.start_debug, "Shift+F9")
        add(m, "Alternar breakpoint", lambda: self.editor() and self.editor().toggle_breakpoint(), "Ctrl+F8")
        add(m, "Continuar", lambda: self.debug_cmd({"cmd": "continue"}), "F9")
        add(m, "Pular (step over)", lambda: self.debug_cmd({"cmd": "next"}), "F8")
        add(m, "Entrar (step into)", lambda: self.debug_cmd({"cmd": "step"}), "F7")
        add(m, "Sair (step out)", lambda: self.debug_cmd({"cmd": "out"}), "Shift+F8")
        add(m, "Parar depuracao", lambda: self.debug_cmd({"cmd": "quit"}), "Ctrl+F2")
        add(m, "Avaliar expressao...", self.evaluate_dialog, "Alt+F8")
        m.addSeparator()
        add(m, "Executar com profiler (CPU e memoria)", self.run_profiler, "Ctrl+Alt+F5")

    def intel_view_menu(self, add, m):
        m.addSeparator()
        for key, text in [("inlay_hints", "Inlay hints (tipos e parametros)"), ("usage_counts", "Contadores de uso"),
                          ("flow_analysis", "Analise de fluxo de dados (Python)"), ("git_gutter", "Marcadores do git")]:
            a = add(m, text, lambda k=key: self.toggle_setting(k))
            a.setCheckable(True)
            a.setChecked(bool(self.settings.get(key, True)))
            setattr(self, f"act_{key}", a)

    def toggle_setting(self, key: str):
        self.settings[key] = not self.settings.get(key, True)
        self.settings.save()
        a = getattr(self, f"act_{key}", None)
        if a:
            a.setChecked(self.settings[key])
        for ed in self.editors():
            if key == "inlay_hints" and not self.settings[key]:
                ed.set_inlay_hints([])
            if key == "usage_counts" and not self.settings[key]:
                ed.set_eol("usages", {})
            if key == "git_gutter" and not self.settings[key]:
                ed.git_changes = {}
                ed.gutter.update()
            if key == "flow_analysis" and not self.settings[key]:
                self.local_diags.pop(str(ed.path), None)
                self.merge_diagnostics(ed)
        self.schedule_intel()
        self.toast(f"{key}: {'ligado' if self.settings[key] else 'desligado'}")

    # ============================================================ editor: ganchos
    def intel_attach(self, ed):
        ed.templates_user = self.settings.get("templates", {})
        ed.text_changed_debounced.connect(lambda e=ed: self.schedule_intel(e))
        ed.viewport_scrolled.connect(lambda e=ed: self.schedule_intel(e, hints_only=True))
        ed.breakpoints_changed.connect(self.push_breakpoints)
        ed.context_menu.connect(lambda m, ln, col, e=ed: self.editor_menu(e, m, ln, col))
        ed.cursor_moved.connect(lambda *_a, e=ed: self._blame_line(e))
        if ed.path:
            try:
                self.history.snapshot(ed.path, ed.toPlainText(), "aberto")
            except OSError:
                pass
            QTimer.singleShot(50, lambda e=ed: self.refresh_git(e))
        self.schedule_intel(ed)

    def editor_menu(self, ed, m: QMenu, ln: int, col: int):
        for text, fn, sc in [("Acoes de contexto...", self.intention_actions, "Alt+Enter"),
                             ("Renomear simbolo...", self.rename_symbol, "F2"),
                             ("Encontrar usos", self.find_usages, "Shift+F12"),
                             ("Ir para definicao", self.goto_definition, "F12"),
                             ("Ir para implementacao", self.goto_implementation, "Ctrl+Alt+B"),
                             ("Hierarquia de chamadas", self.call_hierarchy, "Ctrl+Alt+H")]:
            a = m.addAction(f"{text}\t{sc}", fn)
        r = m.addMenu("Refatorar")
        r.addAction("Extrair variavel\tCtrl+Alt+V", self.extract_variable)
        r.addAction("Extrair constante\tCtrl+Alt+C", self.extract_constant)
        r.addAction("Extrair metodo\tCtrl+Alt+M", self.extract_method)
        r.addAction("Alterar assinatura\tCtrl+F6", self.change_signature)
        r.addAction("Exclusao segura\tAlt+Delete", self.safe_delete_symbol)
        m.addSeparator()
        m.addAction("Alternar breakpoint\tCtrl+F8", lambda: ed.toggle_breakpoint(ln))
        m.addAction("Historico local\tAlt+Shift+H", self.file_history)
        m.addAction("Comparar com HEAD\tCtrl+Alt+D", self.diff_with_head)
        del a

    def schedule_intel(self, ed=None, hints_only=False):
        self._intel_hints_only = hints_only and not self._intel_timer.isActive()
        self._intel_timer.start()

    # ============================================================ inteligencia por arquivo
    def refresh_intel(self):
        ed = self.editor()
        if not ed:
            return
        hints_only = getattr(self, "_intel_hints_only", False)
        self._intel_hints_only = False
        text = ed.toPlainText()
        if not hints_only:
            if ed.lang.id == "python" and self.settings.get("flow_analysis", True) and len(text) < 400_000:
                diags, hints = analysis.analyze_python(text)
                ed._local_hints = hints
                self.local_diags[str(ed.path or id(ed))] = diags
                self.merge_diagnostics(ed)
            ed.conflicts = tools.conflict_blocks(text) if "<<<<<<<" in text else []
            if ed.conflicts:
                ed.update_extra()
            if self.settings.get("git_gutter", True) and ed.path:
                key = str(ed.path)
                if key in self.head_cache:
                    ed.git_changes = tools.line_changes(self.head_cache[key], text)
                    ed.gutter.update()
            self.refresh_symbols(ed)
        self.refresh_hints(ed)

    def merge_diagnostics(self, ed):
        key = str(ed.path) if ed.path else str(id(ed))
        lsp = self.lsp_diags.get(key, [])
        local = self.local_diags.get(key, [])
        # o que o servidor ja aponta na mesma posicao nao se repete
        lsp_pos = {(d["range"]["start"]["line"], d["range"]["start"]["character"]) for d in lsp}
        merged = lsp + [d for d in local if (d["range"]["start"]["line"], d["range"]["start"]["character"])
                        not in lsp_pos]
        ed.set_diagnostics(merged)
        if ed.path:
            self.problems.set_file(str(ed.path), merged)
        e, w = self.problems.counts()
        self.st_problems.setText(f"■ {e}  ▲ {w}")

    def refresh_hints(self, ed):
        if not self.settings.get("inlay_hints", True):
            return
        c = self.lsp_client(ed)
        if c and c.ready and c.has("inlayHintProvider"):
            first, last = ed.visible_lines()
            ver = ed.version

            def done(hints):
                if ed.version == ver:
                    ed.set_inlay_hints(hints)
            c.did_change(ed.path, ed.toPlainText(), ed.version)
            c.inlay_hints(ed.path, max(0, first - 5), last + 5, done)
        else:
            ed.set_inlay_hints(getattr(ed, "_local_hints", []))

    def refresh_symbols(self, ed):
        c = self.lsp_client(ed)

        def show(syms, source):
            if self.editor() is not ed:
                return
            syms = self._prune_locals(syms)
            ed._symbols = syms
            self.structure.set_symbols(str(ed.path or ed.title()), syms, source)
            self.refresh_usages(ed, syms)
        if c and c.ready and c.has("documentSymbolProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)
            c.document_symbols(ed.path, lambda s: show(s, "LSP"))
        else:
            show(self.local_symbols(ed), "analise propria")

    @staticmethod
    def _prune_locals(syms: list[dict], in_func: bool = False) -> list[dict]:
        """Esconde variaveis locais de funcoes na estrutura (ficam so classes, funcoes, campos e globais)."""
        out = []
        for s in syms or []:
            if in_func and s.get("kind") in (13, 14):
                continue
            s = dict(s, children=IntelMixin._prune_locals(s.get("children", []), s.get("kind") in (6, 9, 12)))
            out.append(s)
        return out

    def local_symbols(self, ed) -> list[dict]:
        flat = analysis.scan_definitions(ed.path or Path(ed.title()), ed.toPlainText())
        lines = ed.toPlainText().splitlines()
        roots, stack = [], []
        for d in flat:
            s = {"name": d["name"], "kind": d["kind"], "detail": ", ".join(d["bases"]) if d["bases"] else "",
                 "line": d["line"], "col": d["col"], "end": self._block_end(lines, d["line"]), "children": [],
                 "indent": d["indent"]}
            while stack and stack[-1]["indent"] >= s["indent"]:
                stack.pop()
            if stack and s["kind"] == 12 and stack[-1]["kind"] in (5, 23):
                s["kind"] = 6
            (stack[-1]["children"] if stack else roots).append(s)
            stack.append(s)
        return roots

    @staticmethod
    def _block_end(lines: list[str], start: int) -> int:
        """Ultima linha do bloco que comeca em start (indentacao ou chaves)."""
        if start >= len(lines):
            return start
        head = lines[start]
        ind = len(head) - len(head.lstrip())
        if "{" in head or (start + 1 < len(lines) and lines[start + 1].strip() == "{"):
            depth = 0
            for i in range(start, len(lines)):
                depth += lines[i].count("{") - lines[i].count("}")
                if depth <= 0 and i > start or (depth == 0 and "}" in lines[i] and i >= start and "{" in head
                                                 and lines[i].count("{") <= lines[i].count("}") and i > start):
                    return i
            return len(lines) - 1
        end = start
        for i in range(start + 1, len(lines)):
            t = lines[i]
            if not t.strip():
                continue
            if len(t) - len(t.lstrip()) <= ind:
                break
            end = i
        return end

    def refresh_usages(self, ed, syms):
        if not self.settings.get("usage_counts", True) or not self.word_counts:
            ed.set_eol("usages", {})
            return
        own = collections.Counter(IDENT.findall(ed.toPlainText()))
        key = str(ed.path) if ed.path else ""
        defs = collections.Counter(d["name"] for d in self.def_index)
        data = {}

        def walk(items):
            for s in items:
                if s.get("kind") in USAGE_KINDS and not s["name"].startswith("__"):
                    total = own[s["name"]] + sum(c[s["name"]] for p, c in self.word_counts.items() if p != key)
                    n = max(0, total - max(1, defs.get(s["name"], 1)))
                    data[s["line"]] = f"{n} uso" + ("" if n == 1 else "s")
                walk(s.get("children", []))
        walk(syms)
        ed.set_eol("usages", data)

    # ============================================================ indice do projeto
    def build_index(self):
        if not self.root:
            return
        if self._index_worker and self._index_worker.isRunning():
            self._index_worker.requestInterruption()
        w = IndexWorker(self.root)
        w.ready.connect(self._index_ready)
        self._index_worker = w
        w.start()

    def _index_ready(self, defs, words):
        self.def_index, self.word_counts = defs, words
        self.schedule_intel()

    def reindex_file(self, path: Path, text: str):
        if path.suffix.lower() not in analysis.SOURCE_EXTS:
            return
        self.def_index = [d for d in self.def_index if d["path"] != path] + analysis.scan_definitions(path, text)
        self.word_counts[str(path)] = collections.Counter(IDENT.findall(text))

    # ============================================================ git
    def refresh_git(self, ed):
        if not ed.path or not self.settings.get("git_gutter", True):
            return
        key = str(ed.path)
        self.head_cache[key] = tools.git_head_text(ed.path)
        ed.git_changes = tools.line_changes(self.head_cache[key], ed.toPlainText())
        ed.blame = tools.blame(ed.path) if self.head_cache[key] is not None else {}
        data = {}
        for ln, info in ed.blame.items():
            if info.get("hash", "").startswith("0000000"):
                continue
            from .history import ago
            data[ln] = f"{info.get('author', '')}, {ago(info.get('time', 0))} · {info.get('summary', '')[:60]}"
        ed._blame_eol = data
        self._blame_line(ed)
        ed.gutter.update()

    def _blame_line(self, ed):
        data = getattr(ed, "_blame_eol", None)
        if data:
            ln = ed.textCursor().blockNumber()
            ed.set_eol("blame", {ln: data[ln]} if ln in data and not ed.document().isModified() else {})

    def toggle_blame(self):
        ed = self.editor()
        if ed:
            if not ed.blame:
                self.refresh_git(ed)
            if not ed.blame:
                return self.toast("Arquivo fora de um repositorio git (ou ainda nao commitado)")
            ed.toggle_blame()

    def diff_with_head(self):
        ed = self.editor()
        if not ed or not ed.path:
            return
        head = tools.git_head_text(ed.path)
        if head is None:
            return self.toast("Sem versao no HEAD (arquivo novo ou fora do git)")
        self.show_text_dialog(f"Diff com HEAD — {ed.path.name}",
                              unified(head, ed.toPlainText(), "HEAD", "atual") or "(sem alteracoes)", diff=True)

    def revert_to_head(self):
        ed = self.editor()
        if not ed or not ed.path:
            return
        head = tools.git_head_text(ed.path)
        if head is None:
            return self.toast("Sem versao no HEAD")
        if QMessageBox.question(self, "Reverter", f"Descartar as alteracoes de {ed.path.name} desde o ultimo commit?"
                                "\n(Fica uma foto no historico local.)") != QMessageBox.Yes:
            return
        self.history.snapshot(ed.path, ed.toPlainText(), "antes de reverter para HEAD")
        self.replace_editor_text(ed, head)

    def show_text_dialog(self, title: str, text: str, diff=False):
        d = QDialog(self)
        d.setWindowTitle(title)
        d.resize(1000, 640)
        lay = QVBoxLayout(d)
        v = QPlainTextEdit()
        v.setObjectName("console")
        v.setReadOnly(True)
        v.setLineWrapMode(QPlainTextEdit.NoWrap)
        from .panels import mono_font
        v.setFont(mono_font(12))
        c = v.textCursor()
        for ln in text.splitlines(True):
            f = QTextCharFormat()
            if diff:
                f.setForeground(QColor("#64c88c") if ln.startswith("+") and not ln.startswith("+++") else
                                QColor("#ff5d6a") if ln.startswith("-") and not ln.startswith("---") else
                                QColor("#7fd1ff") if ln.startswith("@@") else QColor("#c9c9cf"))
            c.insertText(ln, f)
        v.moveCursor(QTextCursor.Start)
        lay.addWidget(v)
        d.exec()

    def _conflict_here(self, ed):
        ln = ed.textCursor().blockNumber()
        for b in tools.conflict_blocks(ed.toPlainText()):
            if b["start"] <= ln <= b["end"]:
                return b
        return None

    def resolve_conflict(self, choice: str):
        ed = self.editor()
        if not ed:
            return
        b = self._conflict_here(ed)
        if not b:
            return self.toast("Coloque o cursor dentro de um bloco <<<<<<< ... >>>>>>>")
        lines = ed.toPlainText().split("\n")
        new = tools.resolve_conflict(lines, b, choice)
        cur = QTextCursor(ed.document())
        cur.beginEditBlock()
        a = ed.cursor_at(b["start"], 0)
        e = ed.cursor_at(b["end"], 0)
        e.movePosition(QTextCursor.EndOfBlock)
        a.setPosition(e.position(), QTextCursor.KeepAnchor)
        keep = new[b["start"]:len(new) - (len(lines) - b["end"] - 1)]
        a.insertText("\n".join(keep))
        cur.endEditBlock()
        left = tools.conflict_blocks(ed.toPlainText())
        self.toast(f"conflito resolvido · restam {len(left)}")
        self.schedule_intel(ed)

    def next_conflict(self):
        ed = self.editor()
        if not ed:
            return
        ln = ed.textCursor().blockNumber()
        blocks = tools.conflict_blocks(ed.toPlainText())
        if not blocks:
            return self.toast("Nenhum conflito neste arquivo")
        nxt = next((b for b in blocks if b["start"] > ln), blocks[0])
        self.nav_push()
        ed.goto(nxt["start"])

    # ============================================================ historico local
    def snapshot(self, ed, label: str):
        if ed and ed.path:
            try:
                self.history.snapshot(ed.path, ed.toPlainText(), label)
            except OSError:
                pass

    def snapshot_all(self, label: str):
        for ed in self.editors():
            if ed.path and ed.document().isModified():
                self.snapshot(ed, label)

    def file_history(self):
        ed = self.editor()
        if not ed or not ed.path:
            return self.toast("Abra um arquivo salvo para ver o historico local")
        self.snapshot(ed, "ao abrir o historico")
        snaps = self.history.list(ed.path)
        HistoryDialog(self, self.history, [(ed.path, len(snaps), snaps[0]["time"] if snaps else 0)],
                      {str(ed.path): ed.toPlainText()}, self.restore_version,
                      f"Historico local — {ed.path.name}").exec()

    def project_history(self):
        self.snapshot_all("ao abrir o historico")
        files = self.history.all_files(self.root)
        if not files:
            return self.toast("Historico local vazio")
        cur = {str(ed.path): ed.toPlainText() for ed in self.editors() if ed.path}
        HistoryDialog(self, self.history, files, cur, self.restore_version,
                      "Historico local do projeto").exec()

    def restore_version(self, path: Path, text: str):
        ed = next((e for e in self.editors() if e.path and e.path.resolve() == path.resolve()), None)
        if ed is None and path.exists():
            ed = self.open_file(path)
        if ed is not None:
            self.snapshot(ed, "antes de restaurar")
            self.replace_editor_text(ed, text)
            self.toast(f"versao restaurada em {path.name} (Ctrl+Z desfaz; salve para gravar)")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.open_file(path)
        self.toast(f"arquivo recuperado: {path}")

    @staticmethod
    def replace_editor_text(ed, text: str):
        c = QTextCursor(ed.document())
        c.beginEditBlock()
        c.select(QTextCursor.Document)
        c.insertText(text)
        c.endEditBlock()

    # ============================================================ navegacao
    def nav_push(self):
        ed = self.editor()
        if ed and ed.path:
            ln, col = ed.line_col()
            loc = (str(ed.path), ln, col)
            if not self.nav_back or self.nav_back[-1] != loc:
                self.nav_back.append(loc)
                self.nav_back = self.nav_back[-100:]
            self.nav_fwd.clear()

    def nav_go_back(self):
        self._nav(self.nav_back, self.nav_fwd)

    def nav_go_forward(self):
        self._nav(self.nav_fwd, self.nav_back)

    def _nav(self, src, dst):
        if not src:
            return self.toast("sem historico de navegacao")
        ed = self.editor()
        if ed and ed.path:
            ln, col = ed.line_col()
            dst.append((str(ed.path), ln, col))
        p, ln, col = src.pop()
        self.open_file(Path(p), ln, col)

    def jump(self, path, line, col=0):
        self.nav_push()
        self.open_file(Path(path), line, col)

    def _word(self, ed=None):
        ed = ed or self.editor()
        if not ed:
            return "", 0, 0
        ln, col = ed.line_col()
        w, start = analysis.word_at(ed.textCursor().block().text(), col)
        return w, ln, start

    def _preview(self, path: Path, line: int) -> str:
        ed = next((e for e in self.editors() if e.path and e.path.resolve() == Path(path).resolve()), None)
        if ed:
            b = ed.document().findBlockByNumber(line)
            return b.text() if b.isValid() else ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, t in enumerate(f):
                    if i == line:
                        return t.rstrip("\n")
        except OSError:
            pass
        return ""

    def show_refs(self, title: str, locs: list[tuple]):
        self.refs.root = self.root
        self.refs.show_locations(title, [(p, l, c, self._preview(p, l)) for p, l, c, *_ in locs])
        self.show_bottom(self.bottom.indexOf(self.refs))

    def find_usages(self):
        ed = self.editor()
        name, ln, col = self._word(ed)
        if not name:
            return self.toast("Coloque o cursor sobre um simbolo")
        c = self.lsp_client(ed)
        if c and c.ready and c.has("referencesProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)

            def done(locs):
                if locs:
                    self.show_refs(f"USOS DE '{name}'  (LSP)", locs)
                else:
                    self.show_refs(f"USOS DE '{name}'  (busca textual)", self.text_usages(name))
            c.references(ed.path, ln, col, done)
        else:
            self.show_refs(f"USOS DE '{name}'  (busca textual)", self.text_usages(name))

    def text_usages(self, name: str, include_all_files=False) -> list[tuple]:
        """Ocorrencias da palavra inteira no projeto (codigo, strings, comentarios, configuracoes)."""
        rx = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
        out = []
        open_text = {str(e.path): e.toPlainText() for e in self.editors() if e.path}
        files = list(walk_files(self.root, 30000)) if self.root else [Path(p) for p in open_text]
        for f in files:
            if str(f) in open_text:
                text = open_text[str(f)]
            else:
                try:
                    if f.stat().st_size > 2_000_000:
                        continue
                    text = f.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
            if name not in text:
                continue
            for i, line in enumerate(text.splitlines()):
                for m in rx.finditer(line):
                    out.append((f, i, m.start()))
                    if len(out) > 3000:
                        return out
        return out

    def _locs_request(self, method: str, title: str, fallback=None):
        ed = self.editor()
        if not ed:
            return
        name, ln, col = self._word(ed)
        c = self.lsp_client(ed)
        if c and c.ready:
            c.did_change(ed.path, ed.toPlainText(), ed.version)

            def done(locs):
                if len(locs) == 1:
                    self.jump(locs[0][0], locs[0][1], locs[0][2])
                elif locs:
                    self.show_refs(title, locs)
                elif fallback:
                    fallback(name)
                else:
                    self.toast(f"{title.lower()}: nada encontrado")
            c.locations_request(method, ed.path, ln, col, done)
        elif fallback:
            fallback(name)
        else:
            self.toast(f"{title} precisa de um servidor de linguagem")

    def goto_implementation(self):
        def fb(name):
            ed = self.editor()
            here = (str(ed.path), ed.line_col()[0]) if ed and ed.path else None
            subs = {d["name"] for d in self.def_index if name in d["bases"]}
            locs = [(d["path"], d["line"], d["col"]) for d in self.def_index
                    if (d["name"] == name or d["name"] in subs) and (str(d["path"]), d["line"]) != here]
            if len(locs) == 1:
                self.jump(*locs[0])
            elif locs:
                self.show_refs(f"IMPLEMENTACOES DE '{name}'  (indice)", locs)
            else:
                self.toast("Nenhuma implementacao encontrada")
        self._locs_request("textDocument/implementation", "IMPLEMENTACOES", fb)

    def goto_type_definition(self):
        self._locs_request("textDocument/typeDefinition", "DEFINICAO DO TIPO")

    def goto_test(self):
        ed = self.editor()
        if not ed or not ed.path:
            return
        cands = analysis.test_candidates(ed.path, self.root)
        if len(cands) == 1:
            return self.jump(cands[0], 0)
        if cands:
            p = Picker(self, "Arquivo correspondente...", [(c.name, str(c.parent), str(c)) for c in cands],
                       lambda n: lang_icon(languages.detect(n)))
            if p.exec() and p.result:
                self.jump(Path(p.result), 0)
            return
        target = analysis.default_test_path(ed.path, self.root)
        if QMessageBox.question(self, "Criar teste", f"Nenhum teste para {ed.path.name}.\nCriar {target}?") \
                == QMessageBox.Yes:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(analysis.test_template(ed.path, target), encoding="utf-8")
            self.jump(target, 0)

    # ============================================================ hierarquias
    def call_hierarchy(self, outgoing: bool = False):
        ed = self.editor()
        name, ln, col = self._word(ed)
        if not name:
            return self.toast("Coloque o cursor sobre uma funcao")
        c = self.lsp_client(ed)
        title = f"{'CHAMADAS FEITAS POR' if outgoing else 'QUEM CHAMA'} '{name}'"
        flip = lambda: self.call_hierarchy(not outgoing)  # noqa: E731
        if c and c.ready and c.has("callHierarchyProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)
            method = "callHierarchy/outgoingCalls" if outgoing else "callHierarchy/incomingCalls"

            def node(item, depth=0):
                r = item.get("selectionRange") or item.get("range")
                return {"text": f"{item.get('name', '?')}  {item.get('detail', '')}", "path": from_uri(item["uri"]),
                        "line": r["start"]["line"], "col": r["start"]["character"], "payload": (item, depth)}

            def expand(payload, cb):
                item, depth = payload
                c.hierarchy_step(item, method, lambda res: cb([dict(node(i), depth=depth + 1) for i, _r in res]))

            c.prepare_call_hierarchy(ed.path, ln, col, lambda items: self._show_hier(
                title + "  (LSP)", [node(i) for i in items], expand, flip))
            return
        # sem servidor: busca textual + funcao que envolve cada chamada
        defs = [d for d in self.def_index if d["name"] == name] or \
            [{"name": name, "path": ed.path, "line": ln, "col": col}]
        root = {"text": name, "path": defs[0]["path"], "line": defs[0]["line"], "col": defs[0]["col"],
                "payload": (name, defs[0]["path"], defs[0]["line"], 0)}
        self._show_hier(title + "  (analise propria)", [root],
                        self._outgoing_text if outgoing else self._incoming_text, flip)

    def _show_hier(self, title, roots, expand, flip):
        self.refs.root = self.root
        self.refs.show_hierarchy(title, roots, expand, flip)
        self.show_bottom(self.bottom.indexOf(self.refs))
        for i in range(self.refs.tree.topLevelItemCount()):
            self.refs.tree.topLevelItem(i).setExpanded(False)
            self.refs.tree.topLevelItem(i).setExpanded(True)

    def _lines_of(self, path: Path) -> list[str]:
        ed = next((e for e in self.editors() if e.path and e.path.resolve() == Path(path).resolve()), None)
        if ed:
            return ed.toPlainText().splitlines()
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def _incoming_text(self, payload, cb):
        name, dpath, dline, depth = payload
        rx = re.compile(rf"(?<![\w$.]){re.escape(name)}\s*\(|\.{re.escape(name)}\s*\(")
        callers: dict[tuple, dict] = {}
        for f, ln, col in self.text_usages(name):
            lines = self._lines_of(f)
            if ln >= len(lines) or not rx.search(lines[ln]):
                continue
            if str(f) == str(dpath) and ln == dline:
                continue
            enc = analysis.enclosing_definition(lines, ln)
            cname, cline = enc if enc else ("<modulo>", 0)
            if enc and enc[1] == ln:
                continue
            key = (str(f), cname, cline)
            n = callers.setdefault(key, {"text": f"{cname}", "path": f, "line": ln, "col": col, "count": 0,
                                         "payload": (cname, f, cline, depth + 1) if enc else None, "depth": depth + 1})
            n["count"] += 1
        out = []
        for n in callers.values():
            if n["count"] > 1:
                n["text"] += f"  ({n['count']} chamadas)"
            out.append(n)
        cb(sorted(out, key=lambda n: (str(n["path"]), n["line"])))

    def _outgoing_text(self, payload, cb):
        name, dpath, dline, depth = payload
        lines = self._lines_of(dpath)
        end = self._block_end(lines, dline)
        names = {d["name"]: d for d in self.def_index}
        seen, out = set(), []
        for i in range(dline + 1, end + 1):
            for m in re.finditer(r"(?<![\w$])([A-Za-z_]\w*)\s*\(", lines[i] if i < len(lines) else ""):
                n = m.group(1)
                if n in seen or n == name or n not in names:
                    continue
                seen.add(n)
                d = names[n]
                out.append({"text": n, "path": d["path"], "line": d["line"], "col": d["col"],
                            "payload": (n, d["path"], d["line"], depth + 1), "depth": depth + 1})
        cb(out)

    def type_hierarchy(self, sub: bool = True):
        ed = self.editor()
        name, ln, col = self._word(ed)
        if not name:
            return self.toast("Coloque o cursor sobre uma classe / tipo")
        title = f"{'SUBTIPOS' if sub else 'SUPERTIPOS'} DE '{name}'"
        flip = lambda: self.type_hierarchy(not sub)  # noqa: E731
        c = self.lsp_client(ed)
        if c and c.ready and c.has("typeHierarchyProvider"):
            method = "typeHierarchy/subtypes" if sub else "typeHierarchy/supertypes"

            def node(item, depth=0):
                r = item.get("selectionRange") or item.get("range")
                return {"text": item.get("name", "?"), "path": from_uri(item["uri"]), "line": r["start"]["line"],
                        "col": r["start"]["character"], "payload": (item, depth)}

            def expand(payload, cb):
                item, depth = payload
                c.hierarchy_step(item, method, lambda res: cb([dict(node(i), depth=depth + 1) for i, _r in res]))
            c.prepare_call_hierarchy(ed.path, ln, col, lambda items: self._show_hier(
                title + "  (LSP)", [node(i) for i in items], expand, flip), kind="type")
            return
        by_name: dict[str, list] = collections.defaultdict(list)
        for d in self.def_index:
            if d["kind"] in (5, 23, 11):
                by_name[d["name"]].append(d)

        def expand_index(payload, cb):
            n, depth = payload
            if sub:
                kids = [d for d in self.def_index if n in d["bases"]]
            else:
                bases = {b for d in by_name.get(n, []) for b in d["bases"]}
                kids = [by_name[b][0] if by_name.get(b) else {"name": b, "path": None, "line": 0, "col": 0}
                        for b in sorted(bases)]
            cb([{"text": k["name"] + ("" if k.get("path") else "  (externo)"), "path": k.get("path"),
                 "line": k["line"], "col": k["col"], "payload": (k["name"], depth + 1) if k.get("path") else None,
                 "depth": depth + 1} for k in kids])
        d0 = by_name.get(name, [{"path": ed.path, "line": ln, "col": col}])[0]
        self._show_hier(title + "  (indice do projeto)", [{"text": name, "path": d0["path"], "line": d0["line"],
                                                           "col": d0["col"], "payload": (name, 0)}], expand_index,
                        flip)

    # ============================================================ Search Everywhere
    def search_everywhere(self):
        if isinstance(QApplication.activeModalWidget(), QDialog) or QApplication.activePopupWidget():
            return
        files = []
        if self.root:
            for f in walk_files(self.root, 20000):
                files.append((f.name, os.path.relpath(f.parent, self.root), ("file", str(f)),
                              lang_icon(languages.detect(f.name))))
        else:
            files = [(e.path.name, str(e.path.parent), ("file", str(e.path)), lang_icon(e.lang))
                     for e in self.editors() if e.path]

        def p_files(q):
            return files if q or len(files) < 400 else files[:400]

        def p_symbols(q):
            out = []
            ed = self.editor()

            def walk(items, path):
                for s in items:
                    out.append((s["name"], f"{SYMBOL_KIND.get(s.get('kind'), '')}  ·  {Path(path).name}:"
                                f"{s['line'] + 1}", ("loc", (str(path), s["line"], s.get("col", 0))), None))
                    walk(s.get("children", []), path)
            if ed and getattr(ed, "_symbols", None):
                walk(ed._symbols, ed.path or ed.title())
            if q:
                for d in self.def_index:
                    rel = os.path.relpath(d["path"], self.root) if self.root else str(d["path"])
                    out.append((d["name"], f"{SYMBOL_KIND.get(d['kind'], '')}  ·  {rel}:{d['line'] + 1}",
                                ("loc", (str(d["path"]), d["line"], d["col"])), None))
            return out

        def p_actions(q):
            return [(a.text(), a.shortcut().toString(QKeySequence.NativeText), ("action", a), None)
                    for a in self.actions_list if a.text()]

        settings_items = [
            ("Tamanho da fonte", "font_size"), ("Tab (espacos)", "tab_size"),
            ("Autocompletar enquanto digita", "autocomplete"), ("Fechar pares automaticamente", "auto_close"),
            ("Remover espacos no fim ao salvar", "trim_whitespace"), ("Linha final no arquivo", "final_newline"),
            ("Salvar automaticamente", "autosave"), ("Servidores de linguagem (LSP)", "lsp"),
            ("Inlay hints", "inlay_hints"), ("Contadores de uso", "usage_counts"),
            ("Analise de fluxo (Python)", "flow_analysis"), ("Marcadores do git", "git_gutter"),
            ("Comandos de execucao (F5)", "run_overrides"), ("Live templates", "templates")]

        def p_settings(q):
            out = []
            for text, key in settings_items:
                v = self.settings.get(key)
                state = ("ligado" if v else "desligado") if isinstance(v, bool) else str(v)[:30] \
                    if not isinstance(v, dict) else "editar"
                out.append((text, f"configuracao  ·  {state}", ("setting", key), None))
            return out

        def async_syms(q, cb):
            ed = self.editor()
            c = self.lsp_client(ed) if ed else None
            if not (c and c.ready and c.has("workspaceSymbolProvider")):
                return

            def done(res):
                cb(q, [(s["name"], f"{SYMBOL_KIND.get(s['kind'], '')}  ·  {s['path'].name}:{s['line'] + 1}  (LSP)",
                        ("loc", (str(s["path"]), s["line"], s["col"])), None) for s in res[:200]])
            c.workspace_symbols(q, done)

        dlg = SearchEverywhere(self, {"file": p_files, "symbol": p_symbols, "action": p_actions,
                                      "setting": p_settings}, async_syms)
        if not dlg.exec() or not dlg.result:
            return
        cat, data = dlg.result
        kind, val = data
        if kind == "file":
            self.nav_push()
            self.open_file(Path(val))
        elif kind == "loc":
            self.jump(*val)
        elif kind == "action":
            val.trigger()
        elif kind == "setting":
            if isinstance(self.settings.get(val), bool):
                if hasattr(self, f"act_{val}"):
                    self.toggle_setting(val)
                else:
                    self.settings[val] = not self.settings[val]
                    self.settings.save()
                    self.toast(f"{val}: {'ligado' if self.settings[val] else 'desligado'}")
            elif val == "templates":
                self.open_file(self.settings.path)
            else:
                self.show_settings()

    # ============================================================ edicoes no projeto
    def apply_workspace_edit(self, edit: dict, label: str) -> tuple[int, int]:
        """Aplica um WorkspaceEdit do LSP. Arquivos abertos mudam no editor (Ctrl+Z desfaz); os outros, no disco."""
        per_file: dict[str, list] = collections.defaultdict(list)
        ops = []
        for uri, edits in (edit.get("changes") or {}).items():
            per_file[str(from_uri(uri))] += edits
        for dc in edit.get("documentChanges") or []:
            if "textDocument" in dc:
                per_file[str(from_uri(dc["textDocument"]["uri"]))] += dc.get("edits", [])
            else:
                ops.append(dc)
        n_edits = 0
        for path, edits in per_file.items():
            n_edits += len(edits)
            self.apply_text_edits(Path(path), edits, label)
        for op in ops:
            try:
                if op.get("kind") == "create":
                    p = from_uri(op["uri"])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.touch(exist_ok=True)
                elif op.get("kind") == "rename":
                    a, b = from_uri(op["oldUri"]), from_uri(op["newUri"])
                    self.history.snapshot(a, a.read_text(encoding="utf-8", errors="replace"), "antes de renomear")
                    a.rename(b)
                    for ed in self.editors():
                        if ed.path and ed.path.resolve() == a.resolve():
                            ed.path = b
                            self.update_tab(ed)
                elif op.get("kind") == "delete":
                    p = from_uri(op["uri"])
                    if p.is_file():
                        self.history.snapshot(p, p.read_text(encoding="utf-8", errors="replace"), "antes de excluir")
                    from PySide6.QtCore import QFile
                    QFile.moveToTrash(str(p))
            except OSError as e:
                self.toast(f"erro: {e}")
        return n_edits, len(per_file)

    def apply_text_edits(self, path: Path, edits: list[dict], label: str):
        ed = next((e for e in self.editors() if e.path and e.path.resolve() == path.resolve()), None)
        if ed is not None:
            self.snapshot(ed, f"antes de {label}")
            ed.apply_edits(edits)
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        self.history.snapshot(path, text, f"antes de {label}")
        for e in sorted(edits, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
                        reverse=True):
            r = e["range"]
            a = _lc_to_offset(text, r["start"]["line"], r["start"]["character"])
            b = _lc_to_offset(text, r["end"]["line"], r["end"]["character"])
            text = text[:a] + e["newText"] + text[b:]
        self._saving[str(path)] = time.time()
        path.write_text(text, encoding="utf-8")
        self.reindex_file(path, text)

    # ============================================================ renomear
    def rename_symbol(self):
        ed = self.editor()
        name, ln, col = self._word(ed)
        if not name:
            return self.toast("Coloque o cursor sobre um simbolo")
        new, ok = QInputDialog.getText(self, "Renomear simbolo", f"Novo nome para '{name}':", text=name)
        new = new.strip()
        if not ok or not new or new == name:
            return
        if not IDENT.fullmatch(new):
            return self.toast("Nome invalido")
        c = self.lsp_client(ed)
        if c and c.ready and c.has("renameProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)

            def done(edit):
                if not edit:
                    return self.rename_textual(ed, name, new)
                n, nf = self.apply_workspace_edit(edit, f"renomear {name}")
                self.toast(f"'{name}' → '{new}': {n} ocorrencia(s) em {nf} arquivo(s)")

            def prepared(res):
                if res is None:
                    return self.toast("Este simbolo nao pode ser renomeado aqui")
                c.rename(ed.path, ln, col, new, done)
            c.prepare_rename(ed.path, ln, col, prepared)
        else:
            self.rename_textual(ed, name, new)

    def rename_textual(self, ed, name: str, new: str):
        hits = self.text_usages(name)
        if not hits:
            return
        files = {str(f) for f, _l, _c in hits}
        scope = "arquivo"
        if len(files) > 1:
            r = QMessageBox.question(self, "Renomear (sem servidor de linguagem)",
                                     f"Sem LSP, a renomeacao e textual (palavra inteira).\n'{name}' aparece em "
                                     f"{len(hits)} lugar(es) de {len(files)} arquivo(s).\n\nSim: renomear no projeto "
                                     "todo\nNao: so neste arquivo", QMessageBox.Yes | QMessageBox.No |
                                     QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            scope = "projeto" if r == QMessageBox.Yes else "arquivo"
        per: dict[str, list] = collections.defaultdict(list)
        for f, ln, col in hits:
            if scope == "arquivo" and ed.path and Path(f).resolve() != ed.path.resolve():
                continue
            per[str(f)].append({"range": {"start": {"line": ln, "character": col},
                                          "end": {"line": ln, "character": col + len(name)}}, "newText": new})
        for f, edits in per.items():
            self.apply_text_edits(Path(f), edits, f"renomear {name}")
        self.toast(f"'{name}' → '{new}': {sum(len(v) for v in per.values())} ocorrencia(s) (textual)")

    # ============================================================ intencoes (Alt+Enter)
    def intention_actions(self):
        ed = self.editor()
        if not ed:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 14px; }")
        ln, col = ed.line_col()
        cur = ed.textCursor()
        rng = self._cursor_range(ed)
        here_diags = [d for d in ed.diagnostics if d["range"]["start"]["line"] <= ln <= d["range"]["end"]["line"]]
        # conflitos
        if self._conflict_here(ed):
            for text, ch in [("Aceitar o atual (ours)", "ours"), ("Aceitar o recebido (theirs)", "theirs"),
                             ("Aceitar os dois", "both"), ("Descartar os dois", "none")]:
                menu.addAction("⚑ Conflito: " + text, lambda c=ch: self.resolve_conflict(c))
            menu.addSeparator()
        # correcoes proprias
        for a in self.builtin_intentions(ed, ln, here_diags):
            menu.addAction(a[0], a[1])
        if cur.hasSelection():
            menu.addAction("Extrair variavel", self.extract_variable)
            menu.addAction("Extrair constante", self.extract_constant)
            menu.addAction("Extrair metodo / funcao", self.extract_method)
        name = self._word(ed)[0]
        if name:
            menu.addAction(f"Renomear '{name}'", self.rename_symbol)
            menu.addAction(f"Encontrar usos de '{name}'", self.find_usages)
            if re.match(rf"^\s*(?:async\s+)?(?:def|function|func|fn|fun)\s+{re.escape(name)}\b|"
                        rf"\b{re.escape(name)}\s*\(", cur.block().text()):
                menu.addAction("Alterar assinatura", self.change_signature)
        if ed.path:
            menu.addAction("Ir para o teste / criar teste", self.goto_test)
        holder = menu.addAction("buscando acoes do servidor...")
        holder.setEnabled(False)
        c = self.lsp_client(ed)
        if c and c.ready and c.has("codeActionProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)

            def done(actions):
                try:
                    holder.setVisible(False)
                except RuntimeError:
                    return
                if not actions:
                    return
                first = menu.actions()[0] if menu.actions() else None
                sep = menu.insertSeparator(first) if first else None
                for act in actions:
                    title = act.get("title", "?")
                    kind = act.get("kind", "")
                    icon = "✚" if kind.startswith("quickfix") else "⟲" if kind.startswith("refactor") else "◆"
                    qa = QAction(f"{icon} {title}", menu)
                    qa.triggered.connect(lambda _=False, a=act: self.run_code_action(a))
                    menu.insertAction(sep, qa)
                menu.adjustSize()
            c.code_actions(ed.path, rng, here_diags, done)
        else:
            holder.setText("(sem servidor de linguagem: so acoes da IDE)")
        r = ed.cursorRect()
        menu.exec(ed.viewport().mapToGlobal(r.bottomLeft()))

    @staticmethod
    def _cursor_range(ed) -> dict:
        c = ed.textCursor()
        a = QTextCursor(c)
        a.setPosition(c.selectionStart())
        b = QTextCursor(c)
        b.setPosition(c.selectionEnd())
        return {"start": {"line": a.blockNumber(), "character": a.positionInBlock()},
                "end": {"line": b.blockNumber(), "character": b.positionInBlock()}}

    def run_code_action(self, action: dict):
        c = self.lsp_client(self.editor())
        if not c:
            return
        if "command" in action and isinstance(action["command"], str):     # Command puro
            return c.execute_command(action)

        def go(a):
            if a.get("edit"):
                self.apply_workspace_edit(a["edit"], a.get("title", "acao"))
            if isinstance(a.get("command"), dict):
                c.execute_command(a["command"])
            self.toast(a.get("title", ""))
        c.resolve_code_action(action, go)

    def run_code_action_kind(self, kind: str):
        ed = self.editor()
        c = self.lsp_client(ed) if ed else None
        if not (c and c.ready and c.has("codeActionProvider")):
            return self.toast("Precisa de um servidor de linguagem com code actions")
        c.did_change(ed.path, ed.toPlainText(), ed.version)
        full = {"start": {"line": 0, "character": 0}, "end": {"line": ed.blockCount(), "character": 0}}

        def done(actions):
            acts = [a for a in actions if a.get("kind", "").startswith(kind)]
            if acts:
                self.run_code_action(acts[0])
            else:
                self.toast("O servidor nao ofereceu essa acao")
        c.code_actions(ed.path, full, [], done, only=[kind])

    def builtin_intentions(self, ed, ln: int, diags: list) -> list[tuple]:
        out = []
        text = ed.toPlainText()
        lines = text.split("\n")
        line = lines[ln] if ln < len(lines) else ""
        for d in diags:
            code, msg = d.get("code"), d.get("message", "")
            if code == "none-compare":
                out.append(("✚ Usar 'is None' / 'is not None'", lambda l=ln: self._fix_none_compare(ed, l)))
            elif code == "unreachable":
                out.append(("✚ Remover codigo inalcancavel", lambda dd=d: self._delete_range(ed, dd["range"],
                                                                                          whole=True)))
            elif code == "unused-variable":
                m = re.search(r"'(\w+)'", msg)
                if m:
                    out.append((f"✚ Renomear '{m.group(1)}' para '_'", lambda n=m.group(1): self._rename_line(
                        ed, ln, n, "_")))
            m = re.search(r"undefined name '(\w+)'|\"(\w+)\" is not defined|name '(\w+)' is not defined", msg)
            if m and ed.lang.id == "python":
                mod = next(g for g in m.groups() if g)
                if mod in getattr(sys, "stdlib_module_names", ()):
                    out.append((f"✚ Adicionar 'import {mod}'", lambda mm=mod: self._add_import(ed, f"import {mm}")))
                else:
                    found = [d for d in self.def_index if d["name"] == mod and d["path"].suffix == ".py"]
                    for dd in found[:3]:
                        if self.root and dd["path"] != ed.path:
                            modpath = os.path.relpath(dd["path"].with_suffix(""), self.root).replace(os.sep, ".")
                            out.append((f"✚ Adicionar 'from {modpath} import {mod}'",
                                        lambda s=f"from {modpath} import {mod}": self._add_import(ed, s)))
        if ed.lang.id == "python":
            lc = self._list_comp_candidate(lines, ln)
            if lc:
                out.append(("⟲ Converter laco em list comprehension", lambda r=lc: self._apply_list_comp(ed, r)))
            if re.match(r"^\s*class\s+\w+", line):
                out.append(("⟲ Gerar construtor (__init__) a partir dos atributos", lambda: self._gen_init(ed, ln)))
                out.append(("⟲ Gerar __repr__", lambda: self._gen_repr(ed, ln)))
            m = re.match(r"^(\s*)if\s+(.+):\s*$", line)
            if m and ln + 3 < len(lines):
                tern = self._ternary_candidate(lines, ln)
                if tern:
                    out.append(("⟲ Converter if/else em expressao condicional", lambda r=tern: self._apply_lines(
                        ed, r[0], r[1], r[2])))
        if ed.lang.id in ("javascript", "typescript"):
            m = re.match(r"^(\s*)for\s*\(\s*(?:let|var|const)\s+(\w+)\s*=\s*0\s*;\s*\2\s*<\s*([\w.]+)\.length\s*;", line)
            if m:
                out.append(("⟲ Converter em for...of", lambda mm=m: self._js_for_of(ed, ln, mm)))
            m = re.search(r"\bvar\s+", line)
            if m:
                out.append(("⟲ Trocar 'var' por 'let'", lambda: self._apply_lines(ed, ln, ln, [re.sub(
                    r"\bvar\s+", "let ", line, count=1)])))
        if ed.lang.id in ("javascript", "typescript", "python") and re.search(r"(['\"]).*\+.*\1|\+\s*['\"]", line):
            out.append(("⟲ Converter concatenacao em template string / f-string",
                        lambda: self._to_template_string(ed, ln)))
        return out

    # ---------------------------------------------------- implementacao das intencoes
    def _apply_lines(self, ed, a: int, b: int, new_lines: list[str]):
        self.snapshot(ed, "antes de intencao")
        ca = ed.cursor_at(a, 0)
        cb = ed.cursor_at(b, 0)
        cb.movePosition(QTextCursor.EndOfBlock)
        ca.setPosition(cb.position(), QTextCursor.KeepAnchor)
        ca.insertText("\n".join(new_lines))

    def _fix_none_compare(self, ed, ln: int):
        t = ed.document().findBlockByNumber(ln).text()
        t2 = re.sub(r"!=\s*None\b", "is not None", re.sub(r"==\s*None\b", "is None", t))
        self._apply_lines(ed, ln, ln, [t2])

    def _rename_line(self, ed, ln, old, new):
        t = ed.document().findBlockByNumber(ln).text()
        self._apply_lines(ed, ln, ln, [re.sub(rf"\b{re.escape(old)}\b", new, t, count=1)])

    def _delete_range(self, ed, r: dict, whole=False):
        self.snapshot(ed, "antes de remover")
        a = ed.cursor_at(r["start"]["line"], 0 if whole else r["start"]["character"])
        b = ed.cursor_at(r["end"]["line"], r["end"]["character"])
        if whole:
            b.movePosition(QTextCursor.EndOfBlock)
            b.movePosition(QTextCursor.Right)
        a.setPosition(b.position(), QTextCursor.KeepAnchor)
        a.removeSelectedText()

    def _add_import(self, ed, stmt: str):
        lines = ed.toPlainText().split("\n")
        idx = 0
        i = 0
        if lines and lines[0].startswith("#!"):
            i = 1
        # pula docstring do modulo
        if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
            q = lines[i].lstrip()[:3]
            if lines[i].count(q) >= 2:
                i += 1
            else:
                i += 1
                while i < len(lines) and q not in lines[i]:
                    i += 1
                i += 1
        idx = i
        for j in range(i, len(lines)):
            if re.match(r"^(import|from)\s+\w", lines[j]):
                idx = j + 1
            elif lines[j].strip() and not lines[j].startswith("#") and idx > i:
                break
        c = ed.cursor_at(idx, 0)
        c.insertText(stmt + "\n")
        self.toast(stmt)

    @staticmethod
    def _list_comp_candidate(lines, ln):
        """x = []  /  for a in b:  /  [if c:]  x.append(e)   ->   x = [e for a in b if c]"""
        for start in (ln, ln - 1, ln - 2):
            if start < 0 or start + 2 >= len(lines):
                continue
            m0 = re.match(r"^(\s*)(\w+)\s*=\s*\[\]\s*$", lines[start])
            m1 = re.match(r"^(\s*)for\s+(.+?)\s+in\s+(.+):\s*$", lines[start + 1])
            if not (m0 and m1 and m0.group(1) == m1.group(1)):
                continue
            ind, var = m0.group(1), m0.group(2)
            m2 = re.match(rf"^\s+{re.escape(var)}\.append\((.+)\)\s*$", lines[start + 2])
            cond = ""
            end = start + 2
            if not m2:
                mi = re.match(r"^\s+if\s+(.+):\s*$", lines[start + 2])
                if mi and start + 3 < len(lines):
                    m2 = re.match(rf"^\s+{re.escape(var)}\.append\((.+)\)\s*$", lines[start + 3])
                    cond = f" if {mi.group(1)}"
                    end = start + 3
            if not m2:
                continue
            nxt = lines[end + 1] if end + 1 < len(lines) else ""
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) > len(ind):
                continue
            new = f"{ind}{var} = [{m2.group(1)} for {m1.group(2)} in {m1.group(3)}{cond}]"
            return start, end, [new]
        return None

    def _apply_list_comp(self, ed, r):
        self._apply_lines(ed, r[0], r[1], r[2])

    @staticmethod
    def _ternary_candidate(lines, ln):
        m = re.match(r"^(\s*)if\s+(.+):\s*$", lines[ln])
        a = re.match(r"^\s+(\w+)\s*=\s*(.+)$", lines[ln + 1])
        e = re.match(r"^(\s*)else:\s*$", lines[ln + 2])
        b = re.match(r"^\s+(\w+)\s*=\s*(.+)$", lines[ln + 3])
        if m and a and e and b and a.group(1) == b.group(1) and e.group(1) == m.group(1):
            return ln, ln + 3, [f"{m.group(1)}{a.group(1)} = {a.group(2)} if {m.group(2)} else {b.group(2)}"]
        return None

    def _js_for_of(self, ed, ln, m):
        lines = ed.toPlainText().split("\n")
        i, arr = m.group(2), m.group(3)
        end = self._block_end(lines, ln)
        item = re.sub(r"s$", "", arr.split(".")[-1]) or "item"
        if item == arr.split(".")[-1]:
            item = "item"
        body = [re.sub(rf"\b{re.escape(arr)}\[\s*{i}\s*\]", item, l) for l in lines[ln + 1:end + 1]]
        if any(re.search(rf"\b{i}\b", l) for l in body):
            return self.toast(f"O indice '{i}' e usado no corpo: conversao nao e segura")
        head = re.sub(r"for\s*\(.*\)\s*\{", f"for (const {item} of {arr}) {{", lines[ln])
        self._apply_lines(ed, ln, end, [head] + body)

    def _to_template_string(self, ed, ln):
        t = ed.document().findBlockByNumber(ln).text()
        m = re.search(r"((?:(['\"])(?:[^'\"\\]|\\.)*\2|[\w.()\[\]]+)(?:\s*\+\s*(?:(['\"])(?:[^'\"\\]|\\.)*\3|"
                      r"[\w.()\[\]]+))+)", t)
        if not m or "+" not in m.group(1):
            return self.toast("Nada para converter nesta linha")
        parts = [p.strip() for p in re.split(r"\s*\+\s*(?=(?:[^'\"]*['\"][^'\"]*['\"])*[^'\"]*$)", m.group(1))]
        py = ed.lang.id == "python"
        out = ""
        for p in parts:
            if p[:1] in "'\"" and p[-1:] == p[:1]:
                out += p[1:-1].replace("{", "{{").replace("}", "}}") if py else p[1:-1].replace("`", "\\`")
            else:
                inner = re.sub(r"^str\((.*)\)$", r"\1", p) if py else p
                out += "{" + inner + "}" if py else "${" + inner + "}"
        new = (f'f"{out}"' if py else f"`{out}`")
        self._apply_lines(ed, ln, ln, [t[:m.start(1)] + new + t[m.end(1):]])

    def _class_attrs(self, ed, ln) -> tuple[list[str], int, str]:
        lines = ed.toPlainText().split("\n")
        end = self._block_end(lines, ln)
        body = "\n".join(lines[ln:end + 1])
        attrs = []
        for a in re.findall(r"self\.(\w+)\s*(?:=|\.|\[|\))", body):
            if a not in attrs and not a.startswith("__"):
                attrs.append(a)
        for a in re.findall(r"^\s+(\w+)\s*:\s*[\w\[\], .|]+(?:\s*=.*)?$", body, re.M):
            if a not in attrs:
                attrs.append(a)
        ind = re.match(r"\s*", lines[ln]).group(0) + ed.indent_unit
        return attrs, end, ind

    def _gen_init(self, ed, ln):
        attrs, end, ind = self._class_attrs(ed, ln)
        lines = ed.toPlainText().split("\n")
        if any(re.match(r"^\s*def\s+__init__", l) for l in lines[ln:end + 1]):
            return self.toast("A classe ja tem __init__")
        u = ed.indent_unit
        new = [f"{ind}def __init__(self{''.join(', ' + a.lstrip('_') for a in attrs)}):"]
        new += [f"{ind}{u}self.{a} = {a.lstrip('_')}" for a in attrs] or [f"{ind}{u}pass"]
        c = ed.cursor_at(ln, 0)
        c.movePosition(QTextCursor.EndOfBlock)
        doc_end = ln
        if ln + 1 < len(lines) and lines[ln + 1].strip().startswith(('"""', "'''")):
            q = lines[ln + 1].strip()[:3]
            doc_end = ln + 1
            if lines[ln + 1].strip().count(q) < 2:
                while doc_end + 1 < len(lines) and q not in lines[doc_end + 1]:
                    doc_end += 1
                doc_end += 1
            c = ed.cursor_at(doc_end, 0)
            c.movePosition(QTextCursor.EndOfBlock)
        self.snapshot(ed, "antes de gerar __init__")
        pass_only = doc_end + 1 <= end and lines[doc_end + 1].strip() == "pass" and doc_end + 1 == end
        if pass_only:
            self._apply_lines(ed, end, end, new)
        else:
            c.insertText("\n" + "\n".join(new) + ("\n" if end > doc_end else ""))

    def _gen_repr(self, ed, ln):
        attrs, end, ind = self._class_attrs(ed, ln)
        name = re.match(r"^\s*class\s+(\w+)", ed.document().findBlockByNumber(ln).text()).group(1)
        u = ed.indent_unit
        fields = ", ".join(f"{a}={{self.{a}!r}}" for a in attrs)
        c = ed.cursor_at(end, 0)
        c.movePosition(QTextCursor.EndOfBlock)
        self.snapshot(ed, "antes de gerar __repr__")
        c.insertText(f"\n\n{ind}def __repr__(self):\n{ind}{u}return f\"{name}({fields})\"")

    # ============================================================ extracoes
    def _selection_expr(self, ed) -> tuple[str, QTextCursor] | None:
        c = ed.textCursor()
        if not c.hasSelection():
            # sem selecao: expressao sob o cursor ate o fim da chamada / palavra
            line = c.block().text()
            col = c.positionInBlock()
            m = None
            for mm in re.finditer(r"[\w.]+(?:\([^()]*\))?", line):
                if mm.start() <= col <= mm.end():
                    m = mm
            if not m:
                return None
            c.setPosition(c.block().position() + m.start())
            c.setPosition(c.block().position() + m.end(), QTextCursor.KeepAnchor)
        t = c.selectedText()
        if " " in t:
            return None
        return t.strip(), c

    def extract_variable(self):
        ed = self.editor()
        if not ed:
            return
        r = self._selection_expr(ed)
        if not r or not r[0]:
            return self.toast("Selecione uma expressao (em uma linha)")
        expr, c = r
        tmpl = analysis.DECL.get(ed.lang.id)
        if not tmpl:
            return self.toast(f"Extrair variavel nao suportado em {ed.lang.name}")
        name, ok = QInputDialog.getText(self, "Extrair variavel", f"Nome para  {expr[:60]}", text=analysis.suggest_name(expr))
        if not ok or not IDENT.fullmatch(name.strip()):
            return
        name = name.strip()
        # todas as ocorrencias identicas no mesmo bloco
        lines = ed.toPlainText().split("\n")
        ln = c.blockNumber()
        stmt_line = ln
        while stmt_line > 0 and lines[stmt_line - 1].rstrip().endswith(("\\", ",", "(", "+", "&&", "||")):
            stmt_line -= 1
        ind = re.match(r"\s*", lines[stmt_line]).group(0)
        self.snapshot(ed, "antes de extrair variavel")
        doc = ed.document()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        c.insertText(name)
        ins = ed.cursor_at(stmt_line, 0)
        ins.insertText(ind + tmpl.format(n=name, e=expr) + "\n")
        edit.endEditBlock()
        self.toast(f"variavel '{name}' extraida")

    def extract_constant(self):
        ed = self.editor()
        if not ed:
            return
        r = self._selection_expr(ed)
        if not r or not r[0]:
            return self.toast("Selecione um valor (numero, texto...)")
        expr, c = r
        tmpl = analysis.CONST_DECL.get(ed.lang.id)
        if not tmpl:
            return self.toast(f"Extrair constante nao suportado em {ed.lang.name}")
        sug = re.sub(r"\W+", "_", analysis.suggest_name(expr)).upper().strip("_") or "VALOR"
        name, ok = QInputDialog.getText(self, "Extrair constante", f"Nome da constante para  {expr[:60]}", text=sug)
        if not ok or not IDENT.fullmatch(name.strip()):
            return
        name = name.strip()
        text = ed.toPlainText()
        n = len(re.findall(re.escape(expr), text))
        replace_all = n > 1 and QMessageBox.question(
            self, "Extrair constante", f"Substituir todas as {n} ocorrencias de {expr[:40]}?") == QMessageBox.Yes
        self.snapshot(ed, "antes de extrair constante")
        lines = text.split("\n")
        idx = 0
        for i, l in enumerate(lines[:400]):
            if re.match(r"^(import|from|#include|using|package|use|require|const .* = require)\b", l) or \
                    (i == idx and (l.startswith(("#!", '"""', "//", "#")) or not l.strip())):
                idx = i + 1
        cur = QTextCursor(ed.document())
        cur.beginEditBlock()
        if replace_all:
            for h in reversed(list(re.finditer(re.escape(expr), text))):
                a = QTextCursor(ed.document())
                a.setPosition(h.start())
                a.setPosition(h.end(), QTextCursor.KeepAnchor)
                a.insertText(name)
        else:
            c.insertText(name)
        ins = ed.cursor_at(idx, 0)
        ins.insertText(("\n" if idx and lines[idx - 1].strip() else "") + tmpl.format(n=name, e=expr) + "\n\n")
        cur.endEditBlock()
        self.toast(f"constante {name} extraida")

    def extract_method(self):
        ed = self.editor()
        if not ed:
            return
        c = ed.textCursor()
        if not c.hasSelection():
            return self.toast("Selecione as linhas que vao virar metodo / funcao")
        lsp = self.lsp_client(ed)
        if lsp and lsp.ready and lsp.has("codeActionProvider") and ed.lang.id != "python":
            lsp.did_change(ed.path, ed.toPlainText(), ed.version)

            def done(actions):
                ext = [a for a in actions if "extract" in a.get("kind", "") and re.search(
                    r"method|function|metodo|funcao", a.get("title", ""), re.I)]
                if ext:
                    return self.run_code_action(ext[0])
                self.toast("O servidor nao ofereceu 'extrair metodo' para esta selecao")
            lsp.code_actions(ed.path, self._cursor_range(ed), [], done, only=["refactor.extract"])
            return
        if ed.lang.id != "python":
            return self.toast("Extrair metodo: Python pela IDE; outras linguagens pelo servidor de linguagem (LSP)")
        self._extract_python_method(ed)

    def _extract_python_method(self, ed):
        text = ed.toPlainText()
        lines = text.split("\n")
        c = ed.textCursor()
        a = ed.document().findBlock(c.selectionStart()).blockNumber()
        b_cur = QTextCursor(c)
        b_cur.setPosition(c.selectionEnd())
        b = b_cur.blockNumber() - (1 if b_cur.positionInBlock() == 0 and b_cur.blockNumber() > a else 0)
        sel = lines[a:b + 1]
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self.toast("Corrija os erros de sintaxe antes de extrair")
        func = None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno - 1 < a and n.end_lineno - 1 >= b:
                if func is None or n.lineno > func.lineno:
                    func = n
        import textwrap
        block = textwrap.dedent("\n".join(sel))
        try:
            sel_tree = ast.parse(block)
        except SyntaxError:
            return self.toast("A selecao precisa ser um conjunto completo de instrucoes")
        if any(isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom)) for n in ast.walk(sel_tree)):
            return self.toast("A selecao contem return/yield: extracao automatica nao e segura")
        stored, loaded = [], []
        for n in ast.walk(sel_tree):
            if isinstance(n, ast.Name):
                (stored if isinstance(n.ctx, ast.Store) else loaded).append(n.id)
        before, after = set(), set()
        scope_nodes = ast.walk(func) if func else ast.walk(tree)
        for n in scope_nodes:
            if isinstance(n, ast.Name) and hasattr(n, "lineno"):
                if n.lineno - 1 < a and isinstance(n.ctx, ast.Store):
                    before.add(n.id)
                elif n.lineno - 1 > b and isinstance(n.ctx, ast.Load):
                    after.add(n.id)
            if isinstance(n, ast.arg) and func is not None:
                before.add(n.arg)
        params = []
        for nme in loaded:
            if nme in before and nme not in params and nme != "self":
                params.append(nme)
        returns = []
        for nme in stored:
            if nme in after and nme not in returns:
                returns.append(nme)
        is_method = bool(func and func.args.args and func.args.args[0].arg in ("self", "cls")
                         and ("self" in loaded or "cls" in loaded))
        name, ok = QInputDialog.getText(self, "Extrair metodo", f"Parametros: ({', '.join(params) or '—'})   "
                                        f"retorno: {', '.join(returns) or '—'}\n\nNome:", text="nova_funcao")
        if not ok or not IDENT.fullmatch(name.strip()):
            return
        name = name.strip()
        u = ed.indent_unit
        def_ind = " " * func.col_offset if func else ""
        sig = ", ".join((["self"] if is_method else []) + params)
        body = [def_ind + u + l if l.strip() else "" for l in block.rstrip("\n").split("\n")]
        if returns:
            body.append(f"{def_ind}{u}return {', '.join(returns)}")
        blank = 1 if def_ind else 2          # PEP 8: 2 linhas entre funcoes de modulo, 1 entre metodos
        new_def = [""] * (blank + 1) + [f"{def_ind}def {name}({sig}):"] + body
        sel_ind = re.match(r"\s*", sel[0]).group(0)
        call = f"{'self.' if is_method else ''}{name}({', '.join(params)})"
        call_line = f"{sel_ind}{', '.join(returns)} = {call}" if returns else f"{sel_ind}{call}"
        self.snapshot(ed, "antes de extrair metodo")
        cur = QTextCursor(ed.document())
        cur.beginEditBlock()
        insert_after = (func.end_lineno - 1) if func else b
        if func and func.col_offset > 0 and is_method:
            insert_after = func.end_lineno - 1
        ins = ed.cursor_at(insert_after, 0)
        ins.movePosition(QTextCursor.EndOfBlock)
        ins.insertText("\n".join(new_def))
        self._apply_lines(ed, a, b, [call_line])
        cur.endEditBlock()
        self.toast(f"{'metodo' if is_method else 'funcao'} {name}({sig}) extraido(a)")

    # ============================================================ alterar assinatura
    def change_signature(self):
        ed = self.editor()
        name, ln, col = self._word(ed)
        if not name:
            return self.toast("Coloque o cursor no nome da funcao")
        c = self.lsp_client(ed)

        def with_def(path: Path, dline: int, dcol: int):
            lines = self._lines_of(path)
            text = "\n".join(lines)
            off = _lc_to_offset(text, dline, dcol)
            m = re.compile(rf"\b{re.escape(name)}\s*\(").search(text, max(0, off - len(name) - 2))
            if not m or text.count("\n", off, m.start()) > 1:
                return self.toast("Definicao da funcao nao encontrada")
            open_idx = m.end() - 1
            close = analysis.matching_paren(text, open_idx)
            if close < 0:
                return self.toast("Parenteses da definicao nao fecham")
            params = analysis.split_args(text[open_idx + 1:close])
            self._collect_calls(ed, name, path, dline, lambda calls: self._signature_dialog(
                name, path, open_idx, close, params, calls))

        if c and c.ready and c.has("definitionProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)
            c.definition(ed.path, ln, col, lambda loc: with_def(*loc) if loc else with_def(ed.path, ln, col))
        else:
            d = next((d for d in self.def_index if d["name"] == name), None)
            if re.match(rf"^\s*(?:async\s+)?(?:def|function|func|fn|fun)\s+{re.escape(name)}\b",
                        ed.textCursor().block().text()) or d is None:
                with_def(ed.path, ln, col)
            else:
                with_def(d["path"], d["line"], d["col"])

    def _collect_calls(self, ed, name, dpath, dline, cb):
        c = self.lsp_client(ed)
        rx = re.compile(rf"(?<![\w$]){re.escape(name)}\s*\(")

        def finish(locs):
            calls = []
            for p, l, col, *_ in locs:
                if Path(p).resolve() == Path(dpath).resolve() and l == dline:
                    continue
                line = self._preview(p, l)
                if rx.search(line[col:col + len(name) + 40] if col < len(line) else ""):
                    calls.append((Path(p), l, col))
            cb(calls)
        if c and c.ready and c.has("referencesProvider"):
            ln, col = ed.line_col()
            w, start = analysis.word_at(ed.textCursor().block().text(), col)
            c.references(ed.path, ln, start, lambda locs: finish(locs or self.text_usages(name)))
        else:
            finish(self.text_usages(name))

    def _signature_dialog(self, name, dpath, open_idx, close, params, calls):
        dlg = ChangeSignatureDialog(self, name, params, len(calls))
        if not dlg.exec():
            return
        new_params = dlg.params()
        new_name = dlg.name.text().strip() or name
        is_method = bool(params) and re.match(r"^\*?\s*(self|cls)\b", params[0] or "")
        offset = 1 if is_method else 0

        def pname(p: str) -> str:
            m = re.match(r"^\**\s*(\w+)", p)
            return m.group(1) if m else p

        old_names = [pname(p) for p in params]
        per_file: dict[str, list] = collections.defaultdict(list)
        # chamadas
        for path, l, col in calls:
            lines = self._lines_of(path)
            text = "\n".join(lines)
            off = _lc_to_offset(text, l, col)
            m = re.compile(rf"{re.escape(name)}\s*\(").match(text, off)
            if not m:
                continue
            o = m.end() - 1
            cl = analysis.matching_paren(text, o)
            if cl < 0:
                continue
            args = analysis.split_args(text[o + 1:cl])
            pos = [a for a in args if not re.match(r"^\w+\s*=(?!=)", a) and not a.startswith("*")]
            kw = {re.match(r"^(\w+)", a).group(1): a for a in args if re.match(r"^\w+\s*=(?!=)", a)}
            star = [a for a in args if a.startswith("*")]
            out, must_kw = [], False
            for orig, ptext, default in new_params:
                if orig is not None and orig < offset:
                    continue
                pn = pname(ptext)
                if orig is not None:
                    i = orig - offset
                    on = old_names[orig]
                    if i < len(pos):
                        out.append(f"{pn}={pos[i]}" if must_kw else pos[i])
                    elif on in kw:
                        out.append(kw.pop(on) if pn == on else f"{pn}={kw.pop(on).split('=', 1)[1].strip()}")
                        must_kw = True
                    else:
                        must_kw = True
                else:
                    if default:
                        out.append(f"{pn}={default}" if must_kw else default)
                    else:
                        must_kw = True
            removed = {old_names[i] for i in range(len(params)) if i not in {p[0] for p in new_params}}
            out += [v for k, v in kw.items() if k not in removed] + star
            s_l, s_c = _offset_to_lc(text, off)
            e_l, e_c = _offset_to_lc(text, cl + 1)
            per_file[str(path)].append({"range": {"start": {"line": s_l, "character": s_c},
                                                  "end": {"line": e_l, "character": e_c}},
                                        "newText": f"{new_name}({', '.join(out)})"})
        # definicao
        dtext = "\n".join(self._lines_of(dpath))
        nm = dtext.rfind(name, 0, open_idx)
        s_l, s_c = _offset_to_lc(dtext, nm)
        e_l, e_c = _offset_to_lc(dtext, close + 1)
        per_file[str(dpath)].append({"range": {"start": {"line": s_l, "character": s_c},
                                               "end": {"line": e_l, "character": e_c}},
                                     "newText": f"{new_name}({', '.join(p[1] for p in new_params)})"})
        for f, edits in per_file.items():
            self.apply_text_edits(Path(f), edits, f"alterar assinatura de {name}")
        self.toast(f"assinatura alterada: {len(calls)} chamada(s) em {len(per_file)} arquivo(s)")

    # ============================================================ exclusao segura
    def safe_delete_symbol(self):
        ed = self.editor()
        name, ln, col = self._word(ed)
        if not name:
            return self.toast("Coloque o cursor no nome do simbolo (na definicao)")
        syms = getattr(ed, "_symbols", None) or self.local_symbols(ed)
        target = None

        def walk(items):
            nonlocal target
            for s in items:
                if s["name"] == name and s["line"] == ln:
                    target = s
                walk(s.get("children", []))
        walk(syms)
        if not target:
            return self.toast("Use na linha da definicao (def / class / function...)")
        lines = ed.toPlainText().split("\n")
        end = target.get("end", ln)
        if end <= ln:
            end = self._block_end(lines, ln)
        # decorators logo acima
        start = ln
        while start > 0 and lines[start - 1].lstrip().startswith("@"):
            start -= 1

        def decide(hits):
            hits = [(p, l, c) for p, l, c in hits
                    if not (ed.path and Path(p).resolve() == ed.path.resolve() and start <= l <= end)]
            if hits:
                dlg = UsagesDialog(self, "Exclusao segura", f"'{name}' ainda e referenciado em {len(hits)} lugar(es) "
                                   "(codigo, strings, comentarios ou configuracoes). Excluir pode quebrar o sistema.",
                                   [(p, l, c, self._preview(p, l)) for p, l, c in hits], self.root,
                                   "EXCLUIR MESMO ASSIM")
                if not dlg.exec():
                    return
            self.snapshot(ed, f"antes de excluir {name}")
            a = ed.cursor_at(start, 0)
            b = ed.cursor_at(end, 0)
            b.movePosition(QTextCursor.EndOfBlock)
            if b.block().next().isValid():
                b.movePosition(QTextCursor.Right)
            nxt = b.block()
            while nxt.isValid() and not nxt.text().strip() and nxt.next().isValid() and \
                    not nxt.next().text().strip():
                b.movePosition(QTextCursor.NextBlock)
                nxt = b.block()
            a.setPosition(b.position(), QTextCursor.KeepAnchor)
            a.removeSelectedText()
            self.toast(f"'{name}' excluido ({end - start + 1} linha(s)) · historico local tem a copia")

        hits = self.text_usages(name)
        c = self.lsp_client(ed)
        if c and c.ready and c.has("referencesProvider"):
            c.did_change(ed.path, ed.toPlainText(), ed.version)

            def done(locs):
                merged = {(str(p), l, cc) for p, l, cc in hits}
                merged |= {(str(p), l, cc) for p, l, cc, *_ in locs}
                decide([(Path(p), l, cc) for p, l, cc in sorted(merged)])
            c.references(ed.path, ln, col, done)
        else:
            decide(hits)

    def safe_delete_file(self, p: Path):
        """Antes de apagar um arquivo, procura referencias a ele (imports, strings, configs)."""
        if p.is_dir():
            return self.delete_path(p)
        stem, name = p.stem, p.name
        rx_names = [name]
        if len(stem) >= 3 and stem not in ("index", "main", "__init__", "test", "utils", "app"):
            rx_names.append(stem)
        hits = []
        for n in rx_names:
            for f, l, c in self.text_usages(n):
                if Path(f).resolve() != p.resolve() and (str(f), l) not in {(str(h[0]), h[1]) for h in hits}:
                    hits.append((f, l, c))
        if hits:
            dlg = UsagesDialog(self, "Exclusao segura", f"{name} e mencionado em {len(hits)} lugar(es) do projeto "
                               "(imports, caminhos em strings, comentarios ou configuracoes).",
                               [(f, l, c, self._preview(f, l)) for f, l, c in hits], self.root,
                               "MOVER PARA A LIXEIRA MESMO ASSIM")
            if not dlg.exec():
                return
        elif QMessageBox.question(self, "Exclusao segura", f"Nenhuma referencia a {name} encontrada.\n"
                                  f"Mover para a lixeira?\n{p}") != QMessageBox.Yes:
            return
        self._trash(p)

    def _trash(self, p: Path):
        try:
            if p.is_file():
                self.history.snapshot(p, p.read_text(encoding="utf-8", errors="replace"), "antes de excluir")
        except OSError:
            pass
        from PySide6.QtCore import QFile
        if not QFile.moveToTrash(str(p)):
            QMessageBox.warning(self, "Erro", "Nao foi possivel mover para a lixeira.")
        else:
            self.toast(f"{p.name} na lixeira · copia no historico local do projeto")

    # ============================================================ depurador
    def start_debug(self):
        ed = self.editor()
        if not ed:
            return self.toast("Abra um arquivo Python para depurar")
        if ed.lang.id != "python":
            return self.toast("O depurador integrado suporta Python nesta versao")
        if ed.document().isModified() or ed.path is None:
            if not self.save_editor(ed):
                return
        self.stop_debug()
        self.snapshot(ed, "depurado")
        sess = debugger.DebugSession(self)
        self.debug = sess
        sess.stopped.connect(self.on_debug_stop)
        sess.running.connect(self.on_debug_running)
        sess.exited.connect(self.on_debug_exit)
        sess.eval_result.connect(self.debug_panel.show_eval)
        sess.children.connect(self.debug_panel.show_children)
        self.push_breakpoints()
        if self.debug_panel.watches:
            sess.send({"cmd": "watches", "list": self.debug_panel.watches})
        root = self.root or ed.path.parent
        runner = debugger.runner_path(data_dir())
        argv = [debugger.interpreter(self.root), "-u", str(runner), str(ed.path)]
        self.debug_panel.console.clear()
        self.debug_panel.log(f"■ depurando {ed.path.name}  ·  {argv[0]}\n", "#ff2e40")
        self.debug_panel.set_running(True)
        self.output.run(argv, ed.path.parent, f"DEPURAR  //  {ed.path.name}",
                        debugger.debug_env(sess.port, root))
        self.show_bottom(self.bottom.indexOf(self.debug_panel))

    def push_breakpoints(self):
        if not self.debug:
            return
        bps = []
        for ed in self.editors():
            if ed.path and ed.lang.id == "python":
                for b in ed.breakpoints:
                    if b.get("enabled", True):
                        bps.append({"file": str(ed.path.resolve()), "line": ed.bp_line(b), "cond": b.get("cond", ""),
                                    "log": b.get("log", "")})
        self.debug.set_breakpoints(bps)

    def debug_cmd(self, cmd: dict):
        if not self.debug:
            if cmd.get("cmd") == "continue":
                return self.start_debug()
            return self.toast("Nenhuma sessao de depuracao (Shift+F9 inicia)")
        if cmd.get("cmd") == "quit":
            self.debug.send(cmd)
            QTimer.singleShot(400, self.stop_debug)
            return
        if cmd.get("cmd") in ("next", "step", "out", "continue", "eval", "children", "frame") and \
                not self.debug.paused:
            return
        self.debug.send(cmd)

    def stop_debug(self):
        if self.debug:
            self.debug.close()
            self.debug.deleteLater()
            self.debug = None
        if self.output.running() and "DEPURAR" in self.output.toPlainText()[:200]:
            self.output.stop()
        self.clear_debug_marks()
        self.debug_panel.set_running(False, active=False)

    def clear_debug_marks(self):
        for ed in self.editors():
            if ed.debug_line >= 0:
                ed.set_debug_line(-1)
            ed.set_eol("debug", {})

    def on_debug_stop(self, ev: dict):
        self.clear_debug_marks()
        self.debug_panel.show_stop(ev)
        frame = ev.get("stack", [{}])[ev.get("frame", 0)] if ev.get("stack") else {"file": ev["file"],
                                                                                   "line": ev["line"]}
        ed = self.open_file(Path(frame["file"]), frame["line"])
        if not ed:
            return
        ed.set_debug_line(frame["line"])
        self.debug_editor = ed
        # valores inline: variaveis do frame nas linhas da funcao ate a linha atual
        values = {v["name"]: v["value"] for v in ev.get("vars", [])}
        lines = ed.toPlainText().split("\n")
        enc = analysis.enclosing_definition(lines, frame["line"])
        start = enc[1] if enc else max(0, frame["line"] - 40)
        data = {}
        for i in range(start, min(frame["line"], len(lines) - 1) + 1):
            names = []
            for m in IDENT.finditer(lines[i]):
                n = m.group(0)
                if n in values and n not in names:
                    names.append(n)
            if names:
                data[i] = "   ".join(f"{n} = {values[n][:60]}" for n in names[:5])
        ed.set_eol("debug", data)
        self.show_bottom(self.bottom.indexOf(self.debug_panel))
        self.raise_()
        self.activateWindow()

    def on_debug_running(self):
        self.clear_debug_marks()
        self.debug_panel.set_running(True)

    def on_debug_exit(self, code: int):
        self.clear_debug_marks()
        self.debug_panel.log(f"■ sessao encerrada · codigo {code}\n", "#ececf0" if code == 0 else "#ff5d6a")
        self.debug_panel.set_running(False, active=False)
        if self.debug:
            self.debug.deleteLater()
            self.debug = None

    def evaluate_dialog(self):
        if not self.debug or not self.debug.paused:
            return self.toast("Avaliar expressao funciona com o programa pausado no depurador")
        ed = self.editor()
        sel = ed.textCursor().selectedText() if ed else ""
        t, ok = QInputDialog.getText(self, "Avaliar expressao", "Expressao (no contexto pausado):", text=sel)
        if ok and t.strip():
            self.show_bottom(self.bottom.indexOf(self.debug_panel))
            self.debug_panel.log(f">>> {t}\n", "#ececf0")
            self.debug.send({"cmd": "eval", "expr": t})

    # ============================================================ profiler
    def run_profiler(self):
        ed = self.editor()
        if not ed:
            return self.toast("Abra um arquivo para medir")
        if ed.document().isModified() or ed.path is None:
            if not self.save_editor(ed):
                return
        out = Path(tempfile.gettempdir()) / f"arasaka-prof-{os.getpid()}.json"
        out.unlink(missing_ok=True)
        base = data_dir()
        base.mkdir(parents=True, exist_ok=True)
        if ed.lang.id == "python":
            runner = base / "profile_runner.py"
            runner.write_text(tools.PY_PROFILE_RUNNER, encoding="utf-8")
            argv = [debugger.interpreter(self.root), "-u", str(runner), str(out), str(ed.path)]
            title = f"PROFILER  //  {ed.path.name}"
            kind = "python"
        else:
            tmpl = self.settings["run_overrides"].get(ed.lang.id) or ed.lang.run_command()
            if not tmpl:
                return self.toast(f"Sem comando de execucao para {ed.lang.name}")
            f = ed.path
            cmd = (tmpl.replace("{file}", str(f)).replace("{dir}", str(f.parent)).replace("{stem}", f.stem)
                   .replace("{root}", str(self.root or f.parent)))
            runner = base / "measure_runner.py"
            runner.write_text(tools.GENERIC_RUNNER, encoding="utf-8")
            argv = [sys.executable, str(runner), str(out), cmd]
            title = f"PROFILER  //  {ed.path.name}"
            kind = "generic"

        def finished(_code):
            try:
                self.output.finished.disconnect(finished)
            except (RuntimeError, TypeError):
                pass
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return self.toast("O profiler nao gerou resultado (veja a SAIDA)")
            if kind == "python":
                self.profiler.show_python(data, self.root or ed.path.parent)
            else:
                self.profiler.show_generic(data, ed.path.name)
            self.show_bottom(self.bottom.indexOf(self.profiler))
        self.output.finished.connect(finished)
        self.show_bottom(1)
        self.output.run(argv, ed.path.parent, title)

    # ============================================================ cliente HTTP
    def run_http(self, ed):
        req, _vars = tools.parse_http(ed.toPlainText(), ed.textCursor().blockNumber())
        if not req:
            return self.toast("Nenhuma requisicao aqui (formato: GET https://... / cabecalhos / linha vazia / corpo)")
        self.show_bottom(1)
        self.output.clear()
        self.output.append_color(f"■ HTTP  //  {req['method']} {req['url']}\n", "#ff2e40")
        for k, v in req["headers"].items():
            self.output.append_color(f"{k}: {v}\n", "#55555e")
        if req.get("body"):
            self.output.append_color(req["body"][:2000] + "\n", "#55555e")
        self.output.append_color("\n... enviando\n", "#8c8c96")
        w = tools.HttpWorker(req, ed.path.parent if ed.path else Path.cwd())
        w.done.connect(self._http_done)
        self._http_worker = w
        w.start()

    def _http_done(self, r: dict):
        o = self.output
        if r.get("error"):
            o.append_color(f"!! {r['error']}\n", "#ff2e40")
            return
        st = r["status"]
        col = "#64c88c" if st < 300 else "#ffb347" if st < 400 else "#ff2e40"
        o.append_color(f"\nHTTP {st} {r['reason']}   ·   {r['time'] * 1000:.0f} ms   ·   {r['size']} bytes\n", col)
        for k, v in r["headers"].items():
            o.append_color(f"{k}: ", "#7fd1ff")
            o.append_color(f"{v}\n", "#8c8c96")
        o.append_color("\n" + r["body"][:200000] + "\n", "#d8d8de")
