"""
ARASAKA DAEMON // ferramentas de ecossistema.

  - git: conteudo do HEAD, marcadores de linha alterada, blame por linha,
    blocos de conflito de merge (<<<<<<< ======= >>>>>>>).
  - cliente HTTP: arquivos .http / .rest (estilo JetBrains / VS Code REST
    Client) com variaveis @nome = valor e {{nome}}.
  - profiler: roda Python com cProfile + tracemalloc, e qualquer outro programa
    medindo CPU e memoria maxima.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PySide6.QtCore import QThread, Signal


# ================================================================ git
def _git(args: list[str], cwd: Path, timeout=8) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def git_root(path: Path) -> Path | None:
    p = Path(path).resolve()
    for d in [p] + list(p.parents):
        if (d / ".git").exists():
            return d
    return None


def git_head_text(path: Path) -> str | None:
    root = git_root(path.parent)
    if not root:
        return None
    rel = os.path.relpath(path.resolve(), root).replace(os.sep, "/")
    return _git(["show", f"HEAD:{rel}"], root)


def line_changes(head: str | None, current: str) -> dict[int, str]:
    """{linha: 'add' | 'mod' | 'del'} comparando o buffer com o HEAD."""
    if head is None:
        return {}
    a = head.replace("\r\n", "\n").splitlines()
    b = current.splitlines()
    out: dict[int, str] = {}
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            for j in range(j1, j2):
                out[j] = "add"
        elif tag == "replace":
            for j in range(j1, j2):
                out[j] = "mod"
        elif tag == "delete":
            out[max(0, j1 - 1) if j1 >= len(b) else j1] = out.get(j1, "del")
    return out


def blame(path: Path) -> dict[int, dict]:
    """{linha: {hash, author, time, summary}} do arquivo salvo."""
    root = git_root(path.parent)
    if not root:
        return {}
    out = _git(["blame", "--porcelain", "--", str(path.resolve())], root, timeout=15)
    if not out:
        return {}
    res, commits, cur, line_no = {}, {}, None, 0
    for ln in out.splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", ln)
        if m:
            cur = commits.setdefault(m.group(1), {"hash": m.group(1)})
            line_no = int(m.group(2)) - 1
            continue
        if cur is None:
            continue
        if ln.startswith("author "):
            cur["author"] = ln[7:]
        elif ln.startswith("author-time "):
            cur["time"] = int(ln[12:])
        elif ln.startswith("summary "):
            cur["summary"] = ln[8:]
        elif ln.startswith("\t"):
            res[line_no] = cur
    return res


def conflict_blocks(text: str) -> list[dict]:
    """Blocos de conflito: [{start, mid, base, end}] (numeros de linha)."""
    out, cur = [], None
    for i, ln in enumerate(text.splitlines()):
        if ln.startswith("<<<<<<<"):
            cur = {"start": i, "base": None, "mid": None, "end": None, "ours": ln[7:].strip()}
        elif cur and ln.startswith("|||||||"):
            cur["base"] = i
        elif cur and ln.startswith("=======") and cur["mid"] is None:
            cur["mid"] = i
        elif cur and ln.startswith(">>>>>>>") and cur["mid"] is not None:
            cur["end"] = i
            cur["theirs"] = ln[7:].strip()
            out.append(cur)
            cur = None
    return out


def resolve_conflict(lines: list[str], blk: dict, choice: str) -> list[str]:
    ours_end = blk["base"] if blk["base"] is not None else blk["mid"]
    ours = lines[blk["start"] + 1:ours_end]
    theirs = lines[blk["mid"] + 1:blk["end"]]
    keep = {"ours": ours, "theirs": theirs, "both": ours + theirs, "none": []}[choice]
    return lines[:blk["start"]] + keep + lines[blk["end"] + 1:]


# ================================================================ cliente HTTP
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def parse_http(text: str, line: int) -> tuple[dict | None, dict]:
    """Acha a requisicao que contem a linha (separadas por ###). Retorna (requisicao, variaveis)."""
    vars_: dict[str, str] = {}
    for ln in text.splitlines():
        m = re.match(r"^\s*@([\w.-]+)\s*=\s*(.*?)\s*$", ln)
        if m:
            vars_[m.group(1)] = m.group(2)
    lines = text.splitlines()
    # limites do bloco
    start = 0
    for i in range(min(line, len(lines) - 1), -1, -1):
        if lines[i].startswith("###"):
            start = i + 1
            break
    end = len(lines)
    for i in range(line + 1 if line < len(lines) and not lines[line].startswith("###") else line + 1, len(lines)):
        if lines[i].startswith("###"):
            end = i
            break
    block = lines[start:end]

    def sub(s: str) -> str:
        def rep(m):
            k = m.group(1).strip()
            if k.startswith("$env."):
                return os.environ.get(k[5:], "")
            if k == "$timestamp":
                return str(int(time.time()))
            if k == "$uuid":
                return str(uuid.uuid4())
            return vars_.get(k, m.group(0))
        for _ in range(3):
            s = re.sub(r"\{\{\s*([^}]+?)\s*\}\}", rep, s)
        return s

    req = None
    body: list[str] = []
    in_body = False
    for ln in block:
        if req is None:
            if not ln.strip() or ln.lstrip().startswith(("#", "//")) or re.match(r"^\s*@[\w.-]+\s*=", ln):
                continue
            m = re.match(r"^\s*(?:(" + "|".join(HTTP_METHODS) + r")\s+)?(\S+)(?:\s+HTTP/[\d.]+)?\s*$", ln)
            if not m:
                continue
            req = {"method": m.group(1) or "GET", "url": sub(m.group(2)), "headers": {}}
            continue
        if not in_body:
            if not ln.strip():
                in_body = True
                continue
            if ln.lstrip().startswith(("#", "//")):
                continue
            h = re.match(r"^\s*([\w-]+)\s*:\s*(.*)$", ln)
            if h:
                req["headers"][h.group(1)] = sub(h.group(2))
                continue
            if ln.lstrip().startswith(("?", "&")):
                req["url"] += sub(ln.strip())
                continue
        else:
            body.append(ln)
    if req is not None:
        b = "\n".join(body).strip()
        if b.startswith("< "):       # corpo de arquivo:  < ./dados.json
            req["body_file"] = b[2:].strip()
            b = ""
        req["body"] = sub(b)
    return req, vars_


class HttpWorker(QThread):
    done = Signal(dict)

    def __init__(self, req: dict, base_dir: Path):
        super().__init__()
        self.req, self.base_dir = req, base_dir

    def run(self):
        # urllib e importado no topo: importar dentro da thread trava com o hook de import do PySide
        r = self.req
        data = None
        if r.get("body_file"):
            try:
                data = (self.base_dir / r["body_file"]).read_bytes()
            except OSError as e:
                self.done.emit({"error": f"arquivo do corpo: {e}"})
                return
        elif r.get("body"):
            data = r["body"].encode("utf-8")
        url = r["url"]
        if not re.match(r"^\w+://", url):
            url = "http://" + url
        rq = urllib.request.Request(url, data=data, method=r["method"], headers=r["headers"])
        if data and "Content-Type" not in r["headers"] and "content-type" not in r["headers"]:
            if r.get("body", "").lstrip()[:1] in ("{", "["):
                rq.add_header("Content-Type", "application/json")
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(rq, timeout=60)
            status, reason, headers, raw = resp.status, resp.reason, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as e:
            status, reason, headers, raw = e.code, e.reason, dict(e.headers.items()), e.read()
        except Exception as e:  # noqa: BLE001
            self.done.emit({"error": str(e), "url": url, "method": r["method"]})
            return
        dt = time.time() - t0
        ctype = headers.get("Content-Type", headers.get("content-type", ""))
        text = raw.decode("utf-8", errors="replace")
        if "json" in ctype or text.lstrip()[:1] in ("{", "["):
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        self.done.emit({"status": status, "reason": reason, "headers": headers, "body": text, "time": dt,
                        "size": len(raw), "url": url, "method": r["method"]})


# ================================================================ profiler
PY_PROFILE_RUNNER = r'''
import cProfile, pstats, sys, os, json, time, tracemalloc, runpy, io
out, target = sys.argv[1], sys.argv[2]
sys.argv = sys.argv[2:]
sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
tracemalloc.start()
pr = cProfile.Profile()
t0 = time.perf_counter()
err = None
try:
    pr.runcall(runpy.run_path, target, run_name="__main__")
except SystemExit:
    pass
except BaseException as e:
    import traceback; traceback.print_exc(); err = repr(e)
wall = time.perf_counter() - t0
cur, peak = tracemalloc.get_traced_memory()
snap = tracemalloc.take_snapshot()
tracemalloc.stop()
st = pstats.Stats(pr)
rows = []
for (f, ln, fn), (cc, nc, tt, ct, callers) in st.stats.items():
    rows.append({"file": f, "line": ln, "func": fn, "calls": nc, "tottime": tt, "cumtime": ct})
rows.sort(key=lambda r: -r["cumtime"])
mem = []
for s in snap.statistics("lineno")[:25]:
    fr = s.traceback[0]
    mem.append({"file": fr.filename, "line": fr.lineno, "size": s.size, "count": s.count})
try:
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
except Exception:
    rss = 0
try:
    import threading
    threads = threading.active_count()
except Exception:
    threads = 1
json.dump({"wall": wall, "peak": peak, "rss": rss, "rows": rows[:300], "mem": mem, "error": err,
           "cpu": time.process_time(), "threads": threads}, open(out, "w"))
'''

GENERIC_RUNNER = r'''
import subprocess, sys, json, time, os
out = sys.argv[1]
t0 = time.perf_counter()
p = subprocess.Popen(sys.argv[2:] if len(sys.argv) > 3 else sys.argv[2], shell=len(sys.argv) == 3)
code = p.wait()
wall = time.perf_counter() - t0
info = {"wall": wall, "code": code}
try:
    import resource
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    info.update(cpu=ru.ru_utime + ru.ru_stime, user=ru.ru_utime, sys=ru.ru_stime,
                rss=ru.ru_maxrss * (1 if sys.platform == "darwin" else 1024))
except Exception:
    pass
json.dump(info, open(out, "w"))
sys.exit(code)
'''
