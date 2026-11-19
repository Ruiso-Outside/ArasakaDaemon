"""
ARASAKA DAEMON // historico local (independente do git).

A IDE guarda "fotos" de cada arquivo: ao salvar, ao executar, antes de
recarregar do disco, antes de excluir, antes de refatoracoes e a cada poucos
minutos de edicao. Mesmo sem commit, da para voltar ao estado exato de
10 minutos atras, ou recuperar um arquivo excluido.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import sys
import time
from pathlib import Path

KEEP_PER_FILE = 150
KEEP_DAYS = 30


def data_dir() -> Path:
    if os.environ.get("ARASAKA_DAEMON_HOME"):
        return Path(os.environ["ARASAKA_DAEMON_HOME"]) / "data"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "arasaka-daemon"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "arasaka-daemon"


class LocalHistory:
    def __init__(self, base: Path | None = None):
        self.base = (base or data_dir()) / "history"
        self.base.mkdir(parents=True, exist_ok=True)
        self._last: dict[str, str] = {}      # caminho -> hash do ultimo snapshot

    def _dir(self, path: Path) -> Path:
        return self.base / hashlib.sha1(str(Path(path).resolve()).encode()).hexdigest()[:20]

    def snapshot(self, path: Path, text: str, label: str) -> bool:
        """Guarda uma foto se o conteudo mudou desde a ultima. Retorna True se gravou."""
        path = Path(path).resolve()
        h = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
        key = str(path)
        d = self._dir(path)
        if self._last.get(key) is None:
            snaps = self.list(path)
            if snaps:
                self._last[key] = snaps[0]["hash"]
        if self._last.get(key) == h:
            return False
        d.mkdir(parents=True, exist_ok=True)
        ts = time.time()
        name = f"{int(ts * 1000)}"
        (d / f"{name}.txt").write_text(text, encoding="utf-8", errors="replace")
        (d / f"{name}.json").write_text(json.dumps({"path": key, "label": label, "time": ts, "hash": h,
                                                    "lines": text.count("\n") + 1}), encoding="utf-8")
        (d / "path.txt").write_text(key, encoding="utf-8")
        self._last[key] = h
        self._prune(d)
        return True

    def _prune(self, d: Path):
        metas = sorted(d.glob("*.json"), reverse=True)
        limit = time.time() - KEEP_DAYS * 86400
        for i, m in enumerate(metas):
            try:
                old = float(m.stem) / 1000 < limit
            except ValueError:
                continue
            if i >= KEEP_PER_FILE or (old and i >= 10):
                m.unlink(missing_ok=True)
                m.with_suffix(".txt").unlink(missing_ok=True)

    def list(self, path: Path) -> list[dict]:
        d = self._dir(path)
        out = []
        for m in sorted(d.glob("*.json"), reverse=True):
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            meta["file"] = str(m.with_suffix(".txt"))
            out.append(meta)
        return out

    def read(self, snap: dict) -> str:
        return Path(snap["file"]).read_text(encoding="utf-8", errors="replace")

    def all_files(self, under: Path | None = None) -> list[tuple[Path, int, float]]:
        """[(caminho, n de fotos, horario da ultima)] — inclui arquivos que ja foram excluidos."""
        out = []
        for d in self.base.iterdir() if self.base.exists() else []:
            pf = d / "path.txt"
            if not pf.exists():
                continue
            p = Path(pf.read_text(encoding="utf-8").strip())
            if under and not str(p).startswith(str(under)):
                continue
            metas = sorted(d.glob("*.json"))
            if metas:
                try:
                    last = float(metas[-1].stem) / 1000
                except ValueError:
                    last = 0
                out.append((p, len(metas), last))
        out.sort(key=lambda x: -x[2])
        return out


def ago(ts: float) -> str:
    dt = time.time() - ts
    if dt < 60:
        return "agora ha pouco"
    if dt < 3600:
        return f"ha {int(dt // 60)} min"
    if dt < 86400:
        return f"ha {int(dt // 3600)} h"
    return f"ha {int(dt // 86400)} dia(s)"


def unified(a: str, b: str, name_a: str, name_b: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), name_a, name_b, n=3))
