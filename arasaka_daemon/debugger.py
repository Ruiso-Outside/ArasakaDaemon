"""
ARASAKA DAEMON // depurador Python.

O programa roda com um "runner" (bdb, biblioteca padrao) que conversa com a
IDE por um socket local (JSON por linha). stdin/stdout do programa continuam
no painel SAIDA.

Recursos: breakpoints, breakpoints condicionais (x > 500), logpoints (registram
uma mensagem sem pausar), passo a passo (entrar / pular / sair), pausar,
pilha de chamadas, variaveis por frame, expressoes observadas (watches),
avaliar expressao no contexto pausado (Evaluate Expression) e valores inline
no editor.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

RUNNER = r'''
import bdb, json, os, queue, reprlib, runpy, socket, sys, threading, traceback

_port = int(os.environ.pop("ARASAKA_DBG_PORT"))
_root = os.path.realpath(os.environ.pop("ARASAKA_DBG_ROOT", os.getcwd()))
_sock = socket.create_connection(("127.0.0.1", _port))
_rf = _sock.makefile("rb")
_lock = threading.Lock()
_self = os.path.realpath(__file__)
_rep = reprlib.Repr()
_rep.maxstring, _rep.maxother, _rep.maxlist, _rep.maxdict, _rep.maxlevel = 120, 120, 12, 12, 3


def _send(o):
    data = (json.dumps(o, default=str) + "\n").encode("utf-8", "replace")
    with _lock:
        try:
            _sock.sendall(data)
        except OSError:
            pass


def _r(v):
    try:
        return _rep.repr(v)
    except Exception as e:
        return "<erro no repr: %s>" % e


def _type(v):
    return type(v).__name__


class Daemon(bdb.Bdb):
    def __init__(self):
        super().__init__()
        self.cmds = queue.Queue()
        self.watches = []
        self.target = None
        self.frames = []
        self.paused_frame = None
        self.started = False
        self.stop_on_entry = os.environ.pop("ARASAKA_DBG_ENTRY", "") == "1"

    def is_user(self, fn):
        if not fn or fn.startswith("<"):
            return False
        fn = os.path.realpath(fn)
        if fn == _self:
            return False
        if self.target and fn == self.target:
            return True
        if "site-packages" in fn or "dist-packages" in fn or fn.startswith(os.path.realpath(sys.base_prefix)):
            return False
        return fn.startswith(_root)

    def stop_here(self, frame):
        if not self.is_user(frame.f_code.co_filename):
            return False
        return super().stop_here(frame)

    def user_call(self, frame, args):
        pass

    def set_continue(self):
        # mantem o rastreamento ligado: breakpoints novos e "pausar" continuam funcionando
        self._set_stopinfo(self.botframe, None, -1)

    def user_line(self, frame):
        if not self.is_user(frame.f_code.co_filename):
            return
        if not self.started:
            self.started = True
            if not self.stop_on_entry and not self.break_here(frame):
                self.set_continue()
                return
        self.interaction(frame, "breakpoint" if self.break_here_quiet(frame) else "step")

    def break_here_quiet(self, frame):
        fn = self.canonic(frame.f_code.co_filename)
        return frame.f_lineno in self.breaks.get(fn, [])

    def user_return(self, frame, value):
        pass

    def user_exception(self, frame, exc_info):
        pass

    # ------------------------------------------------------------------
    def stack_of(self, frame):
        st, f = [], frame
        while f is not None:
            if self.is_user(f.f_code.co_filename):
                st.append(f)
            f = f.f_back
        return st

    def vars_of(self, frame):
        out = []
        for k, v in list(frame.f_locals.items())[:150]:
            if k.startswith("__") or type(v).__name__ in ("module", "function", "type", "builtin_function_or_method"):
                continue
            out.append({"name": k, "value": _r(v), "type": _type(v), "expandable": hasattr(v, "__dict__") or
                        isinstance(v, (list, tuple, dict, set))})
        return out

    def children(self, frame, expr):
        try:
            v = eval(expr, frame.f_globals, frame.f_locals)
        except Exception as e:
            return [{"name": "!", "value": repr(e), "type": "erro", "expandable": False}]
        items = []
        if isinstance(v, dict):
            items = [(repr(k), x, "[%r]" % (k,)) for k, x in list(v.items())[:100]]
        elif isinstance(v, (list, tuple)):
            items = [(str(i), x, "[%d]" % i) for i, x in enumerate(v[:100])]
        elif isinstance(v, set):
            items = [(str(i), x, None) for i, x in enumerate(list(v)[:100])]
        elif hasattr(v, "__dict__"):
            items = [(k, x, "." + k) for k, x in list(vars(v).items())[:100] if not k.startswith("__")]
        return [{"name": n, "value": _r(x), "type": _type(x), "path": (expr + p) if p else None,
                 "expandable": p is not None and (hasattr(x, "__dict__") or isinstance(x, (list, tuple, dict, set)))}
                for n, x, p in items]

    def evaluate(self, frame, expr):
        try:
            try:
                code = compile(expr, "<avaliar>", "eval")
                v = eval(code, frame.f_globals, frame.f_locals)
                return {"ok": True, "value": _r(v), "type": _type(v)}
            except SyntaxError:
                code = compile(expr, "<avaliar>", "exec")
                exec(code, frame.f_globals, frame.f_locals)
                try:
                    import ctypes
                    ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(frame), ctypes.c_int(0))
                except Exception:
                    pass
                return {"ok": True, "value": "(executado)", "type": ""}
        except Exception as e:
            return {"ok": False, "value": "%s: %s" % (type(e).__name__, e), "type": "erro"}

    def interaction(self, frame, reason, exc=None):
        self.frames = self.stack_of(frame)
        if not self.frames:
            self.frames = [frame]
        self.paused_frame = frame
        cur = 0

        def snapshot(idx):
            fr = self.frames[idx]
            return {"event": "stopped", "reason": reason, "exception": exc, "frame": idx,
                    "file": os.path.realpath(fr.f_code.co_filename), "line": fr.f_lineno - 1,
                    "stack": [{"file": os.path.realpath(f.f_code.co_filename), "line": f.f_lineno - 1,
                               "func": f.f_code.co_name} for f in self.frames],
                    "vars": self.vars_of(fr),
                    "globals": [x for x in self.vars_of_globals(fr)] if idx == len(self.frames) - 1 else [],
                    "watches": [dict(expr=w, **self.evaluate(fr, w)) for w in self.watches]}
        _send(snapshot(cur))
        while True:
            c = self.cmds.get()
            cmd = c.get("cmd")
            fr = self.frames[cur]
            if cmd == "continue":
                self.set_continue()
                break
            if cmd == "next":
                self.set_next(frame)
                break
            if cmd == "step":
                self.set_step()
                break
            if cmd == "out":
                self.set_return(frame)
                break
            if cmd == "quit":
                self.set_quit()
                break
            if cmd == "frame":
                cur = max(0, min(len(self.frames) - 1, int(c.get("index", 0))))
                _send(snapshot(cur))
            elif cmd == "eval":
                r = self.evaluate(fr, c.get("expr", ""))
                r.update(event="eval", expr=c.get("expr", ""), id=c.get("id"))
                _send(r)
            elif cmd == "children":
                _send({"event": "children", "id": c.get("id"), "items": self.children(fr, c.get("expr", ""))})
            elif cmd == "watches":
                self.watches = list(c.get("list", []))
                _send(snapshot(cur))
        self.paused_frame = None
        _send({"event": "running"})

    def vars_of_globals(self, fr):
        return []


D = Daemon()


def _apply(c):
    cmd = c.get("cmd")
    if cmd == "breaks":
        D.clear_all_breaks()
        for b in c.get("list", []):
            cond = b.get("cond") or None
            if b.get("log"):
                cond = ("__import__('builtins').print('[logpoint] ' + f%r, file=__import__('sys').stderr) and False"
                        % b["log"])
                if b.get("cond"):
                    cond = "(%s) and %s" % (b["cond"], cond)
            D.set_break(os.path.realpath(b["file"]), int(b["line"]) + 1, cond=cond)
        return True
    if cmd == "pause":
        D.set_step()
        return True
    if cmd == "watches" and D.paused_frame is None:
        D.watches = list(c.get("list", []))
        return True
    return False


def _reader():
    while True:
        line = _rf.readline()
        if not line:
            D.cmds.put({"cmd": "quit"})
            os._exit(0)
        try:
            c = json.loads(line.decode("utf-8"))
        except ValueError:
            continue
        if not _apply(c):
            D.cmds.put(c)


threading.Thread(target=_reader, daemon=True).start()
target = os.path.realpath(sys.argv[1])
D.target = target
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(target))
_send({"event": "ready", "pid": os.getpid()})
while True:
    c = D.cmds.get()
    if c.get("cmd") == "start":
        break
    if c.get("cmd") == "quit":
        sys.exit(0)
code = 0
try:
    D.runcall(runpy.run_path, target, run_name="__main__")
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else 0
except bdb.BdbQuit:
    code = 1
except BaseException as e:
    traceback.print_exc()
    tb = e.__traceback__
    last = None
    while tb is not None:
        if D.is_user(tb.tb_frame.f_code.co_filename):
            last = tb.tb_frame
        tb = tb.tb_next
    if last is not None:
        D.set_continue()
        sys.settrace(None)
        D.interaction(last, "exception", "%s: %s" % (type(e).__name__, e))
    code = 1
_send({"event": "exited", "code": code})
try:
    _sock.close()
except OSError:
    pass
sys.exit(code)
'''


def runner_path(base: Path) -> Path:
    p = base / "debug_runner.py"
    if not p.exists() or p.read_text(encoding="utf-8") != RUNNER:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(RUNNER, encoding="utf-8")
    return p


class DebugSession(QObject):
    """Servidor TCP local que recebe eventos do runner e envia comandos."""
    stopped = Signal(dict)
    running = Signal()
    exited = Signal(int)
    eval_result = Signal(dict)
    children = Signal(dict)
    connected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        self.server.listen(QHostAddress.LocalHost, 0)
        self.sock: QTcpSocket | None = None
        self.buf = b""
        self.pending: list[dict] = []
        self.paused = False
        self.last_stop: dict | None = None

    @property
    def port(self) -> int:
        return self.server.serverPort()

    def _accept(self):
        s = self.server.nextPendingConnection()
        if self.sock is not None:
            s.close()
            return
        self.sock = s
        s.readyRead.connect(self._read)
        s.disconnected.connect(self._gone)

    def _gone(self):
        if self.sock is not None:
            self.sock = None
            self.paused = False
            self.exited.emit(-1)

    def _read(self):
        self.buf += bytes(self.sock.readAll())
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            try:
                ev = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            kind = ev.get("event")
            if kind == "ready":
                for c in self.pending:
                    self.send(c)
                self.pending.clear()
                self.connected.emit()
                self.send({"cmd": "start"})
            elif kind == "stopped":
                self.paused = True
                self.last_stop = ev
                self.stopped.emit(ev)
            elif kind == "running":
                self.paused = False
                self.running.emit()
            elif kind == "eval":
                self.eval_result.emit(ev)
            elif kind == "children":
                self.children.emit(ev)
            elif kind == "exited":
                code = int(ev.get("code") or 0)
                s, self.sock = self.sock, None
                self.paused = False
                self.exited.emit(code)
                if s:
                    s.close()

    def send(self, cmd: dict):
        if self.sock is None:
            self.pending.append(cmd)
            return
        self.sock.write((json.dumps(cmd) + "\n").encode("utf-8"))

    def set_breakpoints(self, bps: list[dict]):
        self.send({"cmd": "breaks", "list": bps})

    def close(self):
        if self.sock is not None:
            try:
                self.sock.write(b'{"cmd": "quit"}\n')
                self.sock.flush()
            except RuntimeError:
                pass
        self.server.close()


def debug_env(port: int, root: Path) -> dict:
    return {"ARASAKA_DBG_PORT": str(port), "ARASAKA_DBG_ROOT": str(root), "PYTHONBREAKPOINT": "0"}


def interpreter(root: Path | None) -> str:
    from .analysis import python_project_venv
    import shutil
    import sys
    v = python_project_venv(root)
    if v:
        return str(v)
    return shutil.which("python3") or shutil.which("python") or sys.executable


__all__ = ["DebugSession", "runner_path", "debug_env", "interpreter", "RUNNER", "os"]
