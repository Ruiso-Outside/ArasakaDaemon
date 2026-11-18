"""
ARASAKA DAEMON // cliente LSP (Language Server Protocol).

Um servidor por (linguagem, pasta do projeto), conversando por stdio com
mensagens JSON-RPC. Suporta: sincronizacao de documentos, diagnosticos,
autocompletar, hover, ir para definicao e formatacao.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from .languages import Language


def to_uri(path: Path) -> str:
    return Path(path).resolve().as_uri()


def from_uri(uri: str) -> Path:
    p = unquote(urlparse(uri).path)
    if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
        p = p[1:]
    return Path(p)


def find_tsserver(cmd: list[str]) -> Path | None:
    """Acha o tsserver.js (pacote 'typescript') perto do typescript-language-server ou no npm global."""
    cands = []
    for part in cmd:
        p = Path(part)
        if "typescript-language-server" in p.name:
            for parent in list(p.parents)[:5]:
                cands.append(parent / "typescript" / "lib")
                cands.append(parent / "node_modules" / "typescript" / "lib")
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(Path(appdata) / "npm" / "node_modules" / "typescript" / "lib")
    for base in ("/usr/lib/node_modules", "/usr/local/lib/node_modules",
                 str(Path.home() / ".npm-global/lib/node_modules"), str(Path.home() / ".local/lib/node_modules")):
        cands.append(Path(base) / "typescript" / "lib")
    for c in cands:
        if (c / "tsserver.js").exists():
            return c
    return None


def ts_native(cmd: list[str]) -> bool:
    """True se o 'tsc' encontrado e o TypeScript 7+ (com --lsp)."""
    import subprocess
    try:
        out = subprocess.run([*cmd[:-2], "--version"], capture_output=True, text=True, timeout=8).stdout
        return int(out.split()[-1].split(".")[0]) >= 7
    except Exception:
        return False


class LspClient(QObject):
    diagnostics = Signal(str, list)        # uri, lista
    log = Signal(str)
    state = Signal(str)                    # starting | ready | stopped | error

    def __init__(self, lang: Language, cmd: list[str], root: Path, server_name: str):
        super().__init__()
        self.lang, self.cmd, self.root, self.name = lang, cmd, Path(root), server_name
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(self.root))
        env = QProcessEnvironment.systemEnvironment()
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.readyReadStandardError.connect(self._stderr)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.buf = b""
        self.next_id = 1
        self.pending: dict[int, object] = {}
        self.ready = False
        self.queue: list[dict] = []
        self.open_docs: set[str] = set()
        self.caps: dict = {}
        self.triggers: list[str] = []

    # ------------------------------------------------------------ ciclo de vida
    def start(self):
        self.state.emit("starting")
        self.proc.start(self.cmd[0], self.cmd[1:])
        params = {
            "processId": os.getpid(),
            "clientInfo": {"name": "Arasaka Daemon", "version": "1.0"},
            "rootUri": to_uri(self.root),
            "rootPath": str(self.root),
            "workspaceFolders": [{"uri": to_uri(self.root), "name": self.root.name}],
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": False},
                    "completion": {"completionItem": {"snippetSupport": False, "documentationFormat": ["plaintext"],
                                                      "insertReplaceSupport": False},
                                   "contextSupport": True},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "definition": {"linkSupport": False},
                    "formatting": {},
                    "publishDiagnostics": {"relatedInformation": False},
                    "diagnostic": {"dynamicRegistration": False, "relatedDocumentSupport": False},
                    "signatureHelp": {},
                },
                "workspace": {"workspaceFolders": True, "configuration": True},
                "window": {"workDoneProgress": False},
            },
            "initializationOptions": self._init_options(),
        }
        self._send_now({"jsonrpc": "2.0", "id": self._id(), "method": "initialize", "params": params},
                       self._initialized)

    def _init_options(self) -> dict:
        if self.lang.id in ("typescript", "javascript"):
            ts = find_tsserver(self.cmd)
            if ts:
                return {"tsserver": {"path": str(ts)}}
        return {}

    def _initialized(self, result):
        if result is None:
            self.ready = False
            self.state.emit("error")
            self.log.emit(f"[{self.name}] falhou ao iniciar (veja a mensagem acima)")
            return
        self.caps = (result or {}).get("capabilities", {})
        cp = self.caps.get("completionProvider") or {}
        self.triggers = cp.get("triggerCharacters") or []
        self.ready = True
        self._write({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        for msg in self.queue:
            self._write(msg)
        self.queue.clear()
        self.state.emit("ready")
        self.log.emit(f"[{self.name}] pronto ({self.root})")
        for uri in getattr(self, "_pull_later", set()):
            self.pull_diagnostics(uri)
        self._pull_later = set()

    def stop(self):
        if self.proc.state() != QProcess.NotRunning:
            try:
                self._write({"jsonrpc": "2.0", "id": self._id(), "method": "shutdown", "params": None})
                self._write({"jsonrpc": "2.0", "method": "exit", "params": None})
            except Exception:
                pass
            if not self.proc.waitForFinished(800):
                self.proc.kill()

    def _error(self, *_):
        try:
            self.state.emit("error")
        except RuntimeError:
            pass

    def _finished(self, *_):
        self.ready = False
        self.state.emit("stopped")

    # ------------------------------------------------------------ transporte
    def _id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i

    def _write(self, msg: dict):
        data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        self.proc.write(b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data)

    def _send_now(self, msg: dict, cb=None):
        if cb is not None and "id" in msg:
            self.pending[msg["id"]] = cb
        self._write(msg)

    def _send(self, msg: dict, cb=None):
        if cb is not None and "id" in msg:
            self.pending[msg["id"]] = cb
        if self.ready:
            self._write(msg)
        else:
            self.queue.append(msg)

    def request(self, method: str, params: dict, cb):
        self._send({"jsonrpc": "2.0", "id": self._id(), "method": method, "params": params}, cb)

    def notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _stderr(self):
        txt = bytes(self.proc.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if txt:
            self.log.emit(f"[{self.name}] {txt[:400]}")

    def _read(self):
        self.buf += bytes(self.proc.readAllStandardOutput())
        while True:
            sep = self.buf.find(b"\r\n\r\n")
            if sep < 0:
                return
            header = self.buf[:sep].decode("ascii", errors="ignore")
            length = None
            for line in header.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
            if length is None:
                self.buf = self.buf[sep + 4:]
                continue
            if len(self.buf) < sep + 4 + length:
                return
            body = self.buf[sep + 4:sep + 4 + length]
            self.buf = self.buf[sep + 4 + length:]
            try:
                self._handle(json.loads(body.decode("utf-8")))
            except Exception as e:  # noqa: BLE001
                self.log.emit(f"[{self.name}] erro ao ler mensagem: {e}")

    def _handle(self, msg: dict):
        if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
            cb = self.pending.pop(msg["id"], None)
            if "error" in msg:
                err = msg["error"]
                if err.get("code") not in (-32800,):     # cancelado
                    self.log.emit(f"[{self.name}] {err.get('message', err)}")
                if cb:
                    cb(None)
            elif cb:
                cb(msg.get("result"))
            return
        method = msg.get("method", "")
        if "id" in msg:   # requisicao do servidor
            result = None
            if method == "workspace/configuration":
                result = [None] * len(msg.get("params", {}).get("items", []))
            elif method == "workspace/workspaceFolders":
                result = [{"uri": to_uri(self.root), "name": self.root.name}]
            self._write({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            return
        if method == "textDocument/publishDiagnostics":
            p = msg.get("params", {})
            self.diagnostics.emit(p.get("uri", ""), p.get("diagnostics", []))
        elif method in ("window/logMessage", "window/showMessage"):
            m = msg.get("params", {})
            if m.get("type", 4) <= 2:
                self.log.emit(f"[{self.name}] {m.get('message', '')[:400]}")

    # ------------------------------------------------------------ documentos
    def did_open(self, path: Path, text: str, version: int):
        uri = to_uri(path)
        if uri in self.open_docs:
            return
        self.open_docs.add(uri)
        self.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": self.lang.id,
                                                              "version": version, "text": text}})
        self.pull_diagnostics(uri)

    def did_change(self, path: Path, text: str, version: int):
        uri = to_uri(path)
        if uri not in self.open_docs:
            return self.did_open(path, text, version)
        self.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": version},
                                               "contentChanges": [{"text": text}]})
        self.pull_diagnostics(uri)

    def pull_diagnostics(self, uri: str):
        """Modelo 'pull' (LSP 3.17): o cliente pede os diagnosticos (ex.: TypeScript 7)."""
        if not self.ready:
            self._pull_later = getattr(self, "_pull_later", set()) | {uri}
            return
        if not self.caps.get("diagnosticProvider"):
            return

        def done(res):
            if isinstance(res, dict) and res.get("kind") == "full":
                self.diagnostics.emit(uri, res.get("items", []))
        self.request("textDocument/diagnostic", {"textDocument": {"uri": uri}}, done)

    def did_save(self, path: Path, text: str):
        self.notify("textDocument/didSave", {"textDocument": {"uri": to_uri(path)}, "text": text})

    def did_close(self, path: Path):
        uri = to_uri(path)
        if uri in self.open_docs:
            self.open_docs.discard(uri)
            self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})

    # ------------------------------------------------------------ recursos
    @staticmethod
    def _pos(path, line, col):
        return {"textDocument": {"uri": to_uri(path)}, "position": {"line": line, "character": col}}

    def completion(self, path, line, col, trigger: str, cb):
        params = self._pos(path, line, col)
        params["context"] = ({"triggerKind": 2, "triggerCharacter": trigger} if trigger and trigger in self.triggers
                             else {"triggerKind": 1})

        def done(res):
            items = res.get("items", []) if isinstance(res, dict) else (res or [])
            out = []
            for it in items:
                ins = it.get("insertText") or it.get("label", "")
                te = it.get("textEdit")
                if isinstance(te, dict) and te.get("newText"):
                    ins = te["newText"]
                out.append({"label": it.get("label", "").strip(), "insert": ins, "kind": it.get("kind"),
                            "detail": (it.get("detail") or "").strip(), "sort": it.get("sortText") or it.get("label")})
            out.sort(key=lambda x: x["sort"])
            cb(out)
        self.request("textDocument/completion", params, done)

    def hover(self, path, line, col, cb):
        def done(res):
            if not res:
                return cb("")
            c = res.get("contents")
            if isinstance(c, dict):
                text = c.get("value", "")
            elif isinstance(c, list):
                text = "\n".join(x.get("value", "") if isinstance(x, dict) else str(x) for x in c)
            else:
                text = str(c or "")
            cb(text.replace("```", "").strip())
        self.request("textDocument/hover", self._pos(path, line, col), done)

    def definition(self, path, line, col, cb):
        def done(res):
            if not res:
                return cb(None)
            loc = res[0] if isinstance(res, list) and res else res
            if not isinstance(loc, dict):
                return cb(None)
            uri = loc.get("uri") or loc.get("targetUri")
            rng = loc.get("range") or loc.get("targetSelectionRange") or loc.get("targetRange")
            cb((from_uri(uri), rng["start"]["line"], rng["start"]["character"]) if uri and rng else None)
        self.request("textDocument/definition", self._pos(path, line, col), done)

    def formatting(self, path, tab_size: int, spaces: bool, cb):
        self.request("textDocument/formatting", {"textDocument": {"uri": to_uri(path)},
                                                 "options": {"tabSize": tab_size, "insertSpaces": spaces}},
                     lambda res: cb(res or []))


class LspManager(QObject):
    """Cria/reaproveita clientes por linguagem + raiz do projeto."""
    diagnostics = Signal(str, list)
    log = Signal(str)
    status = Signal(str, str)              # languageId, estado

    def __init__(self):
        super().__init__()
        self.clients: dict[tuple, LspClient] = {}
        self.disabled = False
        self.missing_warned: set[str] = set()

    def client_for(self, lang: Language, root: Path) -> LspClient | None:
        if self.disabled or not lang.servers:
            return None
        key = (lang.id, str(root))
        c = self.clients.get(key)
        if c and c.proc.state() != QProcess.NotRunning:
            return c
        server, cmd = lang.server()
        if server and lang.id in ("typescript", "javascript") and server.cmd[0] == "typescript-language-server"                 and find_tsserver(cmd) is None:
            # TypeScript 7 (nativo) nao tem tsserver.js: usa o LSP embutido no tsc
            alt = next((s for s in lang.servers if s.cmd[0] == "tsc"), None)
            alt_cmd = alt.resolve() if alt else None
            if alt_cmd and ts_native(alt_cmd):
                server, cmd = alt, alt_cmd
        if not server:
            if lang.id not in self.missing_warned:
                self.missing_warned.add(lang.id)
                self.log.emit(f"[LSP] nenhum servidor para {lang.name}. Instale: {lang.servers[0].install}")
                self.status.emit(lang.id, "missing")
            return None
        c = LspClient(lang, cmd, root, server.name or cmd[0])
        c.diagnostics.connect(self.diagnostics.emit)
        c.log.connect(self.log.emit)
        c.state.connect(lambda st, lid=lang.id: self.status.emit(lid, st))
        self.clients[key] = c
        self.log.emit(f"[LSP] iniciando {c.name} para {lang.name}: {' '.join(cmd)}")
        c.start()
        return c

    def stop_all(self):
        for c in self.clients.values():
            c.stop()
        self.clients.clear()

    def restart(self):
        self.stop_all()
        self.missing_warned.clear()
