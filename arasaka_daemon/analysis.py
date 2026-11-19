"""
ARASAKA DAEMON // analise semantica propria.

Funciona sem servidor de linguagem e complementa o LSP:
  - Python: AST em tempo real (modulo ast) para inlay hints (tipos inferidos e
    nomes de parametros) e analise de fluxo de dados (condicoes sempre
    verdadeiras/falsas, codigo inalcancavel, uso de None, recursos sem fechar,
    variaveis nao usadas).
  - Todas as linguagens: indice de definicoes do projeto (funcoes, classes e
    heranca) por expressoes regulares, usado no Search Everywhere, na hierarquia
    de tipos e na hierarquia de chamadas quando o servidor nao oferece.
  - Utilidades: divisao de argumentos, funcao que envolve uma linha, arquivo de
    teste correspondente, extracao de variavel.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path


# ================================================================ Python: AST
def _diag(line, col, end_line, end_col, msg, sev=2, code=""):
    return {"range": {"start": {"line": line, "character": col}, "end": {"line": end_line, "character": end_col}},
            "severity": sev, "message": msg, "source": "daemon", "code": code}


def _node_diag(n, msg, sev=2, code=""):
    return _diag(n.lineno - 1, n.col_offset, (getattr(n, "end_lineno", None) or n.lineno) - 1,
                 getattr(n, "end_col_offset", None) or n.col_offset + 1, msg, sev, code)


def _const_value(n):
    """Valor constante de uma expressao, ou um sentinela se nao for constante."""
    try:
        v = ast.literal_eval(n)
        return v
    except Exception:
        pass
    if isinstance(n, ast.Compare) and len(n.ops) == 1:
        a, b = n.left, n.comparators[0]
        if isinstance(a, ast.Name) and isinstance(b, ast.Name) and a.id == b.id and \
                isinstance(n.ops[0], (ast.Eq, ast.Is, ast.LtE, ast.GtE)):
            return True
        if isinstance(a, ast.Name) and isinstance(b, ast.Name) and a.id == b.id and \
                isinstance(n.ops[0], (ast.NotEq, ast.IsNot, ast.Lt, ast.Gt)):
            return False
        try:
            la, lb = ast.literal_eval(a), ast.literal_eval(b)
            op = n.ops[0]
            return {ast.Eq: la == lb, ast.NotEq: la != lb, ast.Lt: la < lb, ast.Gt: la > lb,
                    ast.LtE: la <= lb, ast.GtE: la >= lb}.get(type(op), _NOPE)
        except Exception:
            return _NOPE
    if isinstance(n, ast.BoolOp):
        vals = [_const_value(v) for v in n.values]
        if isinstance(n.op, ast.And) and any(v is not _NOPE and not v for v in vals):
            return False
        if isinstance(n.op, ast.Or) and any(v is not _NOPE and v for v in vals):
            return True
        if all(v is not _NOPE for v in vals):
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        v = _const_value(n.operand)
        return _NOPE if v is _NOPE else not v
    return _NOPE


_NOPE = object()
_TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _infer_type(n, classes: set[str], funcs: dict) -> str:
    if isinstance(n, ast.Constant):
        return "None" if n.value is None else type(n.value).__name__
    if isinstance(n, ast.JoinedStr):
        return "str"
    if isinstance(n, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(n, (ast.Dict, ast.DictComp)):
        return "dict"
    if isinstance(n, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(n, ast.Tuple):
        return "tuple"
    if isinstance(n, ast.GeneratorExp):
        return "generator"
    if isinstance(n, ast.Lambda):
        return "function"
    if isinstance(n, ast.Compare) or (isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)):
        return "bool"
    if isinstance(n, ast.BinOp):
        a, b = _infer_type(n.left, classes, funcs), _infer_type(n.right, classes, funcs)
        if isinstance(n.op, ast.Div) and a in ("int", "float") and b in ("int", "float"):
            return "float"
        if a == b and a:
            return a
        if {a, b} == {"int", "float"}:
            return "float"
        return ""
    if isinstance(n, ast.Call):
        f = n.func
        name = f.id if isinstance(f, ast.Name) else ""
        builtin = {"int": "int", "float": "float", "str": "str", "list": "list", "dict": "dict", "set": "set",
                   "tuple": "tuple", "bool": "bool", "len": "int", "sorted": "list", "open": "TextIO",
                   "range": "range", "enumerate": "enumerate", "zip": "zip", "repr": "str", "input": "str",
                   "abs": "int|float", "round": "int", "bytes": "bytes", "frozenset": "frozenset"}
        if name in builtin:
            return builtin[name]
        if name in classes or (name[:1].isupper() and name not in funcs):
            return name
        if name in funcs and funcs[name]:
            return funcs[name]
        if isinstance(f, ast.Attribute):
            if f.attr in ("split", "splitlines", "readlines", "keys", "values", "items"):
                return "list" if f.attr in ("split", "splitlines", "readlines") else ""
            if f.attr in ("join", "strip", "lower", "upper", "replace", "format", "read", "decode", "title"):
                return "str"
    return ""


class _PyAnalyzer(ast.NodeVisitor):
    def __init__(self, tree: ast.AST):
        self.diags: list[dict] = []
        self.hints: list[dict] = []
        self.classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        self.funcs: dict[str, str] = {}
        self.signatures: dict[str, list[str]] = {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ret = ast.unparse(n.returns) if n.returns is not None else ""
                self.funcs.setdefault(n.name, ret)
                params = [a.arg for a in n.args.posonlyargs + n.args.args]
                self.signatures.setdefault(n.name, params)
            elif isinstance(n, ast.ClassDef):
                for b in n.body:
                    if isinstance(b, ast.FunctionDef) and b.name == "__init__":
                        self.signatures.setdefault(n.name, [a.arg for a in b.args.args][1:])

    # ---------------------------------------------------- fluxo
    def check_body(self, body: list):
        for i, st in enumerate(body):
            if isinstance(st, _TERMINAL) and i + 1 < len(body):
                nxt = body[i + 1]
                self.diags.append(_node_diag(nxt, "Codigo inalcancavel: vem depois de "
                                             f"'{type(st).__name__.lower()}'", 2, "unreachable"))
                break

    def generic_visit(self, node):
        for field in ("body", "orelse", "finalbody"):
            b = getattr(node, field, None)
            if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
                self.check_body(b)
        super().generic_visit(node)

    def visit_If(self, n: ast.If):
        v = _const_value(n.test)
        if v is not _NOPE and not (isinstance(n.test, ast.Constant) and n.test.value in (True, 1)
                                   and not n.orelse):
            self.diags.append(_node_diag(n.test, f"Condicao sempre {'verdadeira' if v else 'falsa'}", 2,
                                         "constant-condition"))
        self.generic_visit(n)

    def visit_While(self, n: ast.While):
        v = _const_value(n.test)
        if v is not _NOPE and not v:
            self.diags.append(_node_diag(n.test, "Condicao do while sempre falsa: o laco nunca executa", 2,
                                         "constant-condition"))
        elif v is not _NOPE and v and not any(isinstance(x, (ast.Break, ast.Return, ast.Raise))
                                               for x in ast.walk(n)):
            self.diags.append(_node_diag(n.test, "Laco infinito: a condicao e sempre verdadeira e nao ha break, "
                                         "return nem raise", 2, "infinite-loop"))
        self.generic_visit(n)

    def visit_Assert(self, n: ast.Assert):
        if isinstance(n.test, ast.Tuple) and n.test.elts:
            self.diags.append(_node_diag(n.test, "assert com tupla e sempre verdadeiro", 2, "constant-condition"))
        self.generic_visit(n)

    def visit_Compare(self, n: ast.Compare):
        for op, right in zip(n.ops, n.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
                self.diags.append(_node_diag(n, "Compare com None usando 'is' / 'is not'", 3, "none-compare"))
        self.generic_visit(n)

    def visit_FunctionDef(self, n):
        self._scope(n)
        self.generic_visit(n)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scope(self, fn):
        """Variaveis nao usadas, uso de variavel que pode ser None, open() sem with."""
        assigned: dict[str, ast.AST] = {}
        used: set[str] = set()
        nonlocal_names: set[str] = set()
        maybe_none: dict[str, int] = {}
        for node in ast.walk(fn):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                nonlocal_names.update(node.names)
            if node is not fn and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name):
                        used.add(sub.id)
        for st in ast.walk(fn):
            if isinstance(st, ast.Name):
                if isinstance(st.ctx, ast.Store):
                    assigned.setdefault(st.id, st)
                else:
                    used.add(st.id)
        for name, node in assigned.items():
            if name not in used and not name.startswith("_") and name not in nonlocal_names:
                self.diags.append(_node_diag(node, f"Variavel '{name}' recebe valor mas nunca e usada", 3,
                                             "unused-variable"))
        # None -> uso de atributo sem checagem, na mesma sequencia de instrucoes
        self._none_flow(fn.body, maybe_none)
        # open() fora de with e sem close()
        closes = {n.func.value.id for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "close"
                  and isinstance(n.func.value, ast.Name)}
        for st in ast.walk(fn):
            if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and \
                    isinstance(st.value.func, ast.Name) and st.value.func.id == "open":
                tgt = st.targets[0]
                if isinstance(tgt, ast.Name) and tgt.id not in closes:
                    self.diags.append(_node_diag(st.value, f"Arquivo aberto em '{tgt.id}' nunca e fechado: "
                                                 "use 'with open(...) as ...'", 2, "resource-leak"))

    def _none_flow(self, body: list, state: dict):
        for st in body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                name = st.targets[0].id
                v = st.value
                is_none = isinstance(v, ast.Constant) and v.value is None
                is_get = isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and \
                    v.func.attr in ("get", "match", "search", "fullmatch") and not (
                        v.func.attr == "get" and len(v.args) > 1)
                if is_none or is_get:
                    state[name] = "None" if is_none else f"{v.func.attr}()"
                else:
                    state.pop(name, None)
                self._check_none_use(st.value, state)
                continue
            if isinstance(st, (ast.If, ast.While, ast.Assert, ast.Try, ast.With, ast.For)):
                test = getattr(st, "test", None)
                names = {n.id for n in ast.walk(test) if isinstance(n, ast.Name)} if test is not None else set()
                for n in list(state):
                    if n in names or isinstance(st, (ast.Try, ast.With, ast.For)):
                        state.pop(n, None)
                if test is not None:
                    self._check_none_use(test, {})
                continue
            if isinstance(st, ast.stmt):
                self._check_none_use(st, state)
                # qualquer reatribuicao limpa o estado
                for n in ast.walk(st):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        state.pop(n.id, None)

    def _check_none_use(self, node, state):
        if not state:
            return
        for n in ast.walk(node):
            if isinstance(n, (ast.Attribute, ast.Subscript)) and isinstance(n.value, ast.Name) and \
                    n.value.id in state:
                origin = state.pop(n.value.id)
                what = "e None" if origin == "None" else f"pode ser None (veio de {origin})"
                self.diags.append(_node_diag(n, f"'{n.value.id}' {what} aqui: possivel erro de NoneType", 2,
                                             "maybe-none"))
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in state:
                origin = state.pop(n.func.id)
                self.diags.append(_node_diag(n, f"'{n.func.id}' pode ser None e esta sendo chamado", 2,
                                             "maybe-none"))

    # ---------------------------------------------------- inlay hints
    def collect_hints(self, tree):
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                t = _infer_type(n.value, self.classes, self.funcs)
                if t and t != "None":
                    tg = n.targets[0]
                    self.hints.append({"line": tg.lineno - 1, "col": tg.end_col_offset, "label": f": {t}",
                                       "kind": 1})
            elif isinstance(n, ast.Call):
                f = n.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                params = self.signatures.get(name)
                if not params:
                    continue
                if isinstance(f, ast.Attribute) and params and params[0] in ("self", "cls"):
                    params = params[1:]
                for arg, pname in zip(n.args, params):
                    if isinstance(arg, ast.Starred):
                        break
                    if isinstance(arg, ast.Name) and arg.id == pname:
                        continue
                    self.hints.append({"line": arg.lineno - 1, "col": arg.col_offset, "label": f"{pname}:",
                                       "kind": 2})


def analyze_python(text: str) -> tuple[list[dict], list[dict]]:
    """Retorna (diagnosticos, inlay hints) do codigo Python. Erros de sintaxe viram diagnostico."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        line = max(0, (e.lineno or 1) - 1)
        col = max(0, (e.offset or 1) - 1)
        return [_diag(line, col, line, col + 1, f"Erro de sintaxe: {e.msg}", 1, "syntax")], []
    except (ValueError, RecursionError):
        return [], []
    a = _PyAnalyzer(tree)
    try:
        a.visit(tree)
    except Exception:  # noqa: BLE001 - a analise nunca pode derrubar o editor
        pass
    try:
        a.collect_hints(tree)
    except Exception:  # noqa: BLE001
        pass
    # remove duplicatas
    seen, diags = set(), []
    for d in a.diags:
        k = (d["range"]["start"]["line"], d["range"]["start"]["character"], d["code"])
        if k not in seen:
            seen.add(k)
            diags.append(d)
    return diags, a.hints


# ================================================================ indice de definicoes (todas as linguagens)
DEF_PATTERNS = [
    # (regex, grupo do nome, grupo das bases, tipo LSP)
    (re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\("), 1, None, 12),
    (re.compile(r"^\s*class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:"), 1, 2, 5),
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\("), 1, None, 12),
    (re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?(?:public\s+|private\s+|protected\s+|internal\s+|static\s+|"
                r"final\s+|sealed\s+|open\s+|data\s+|partial\s+)*(?:class|interface|struct|enum|record|trait|object)"
                r"\s+(\w+)(?:<[^>{]*>)?\s*(?:(?:extends|:|implements|<)\s*([\w<>,.\s]+?))?\s*(?:\{|$|where)"), 1, 2, 5),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"), 1, None,
     12),
    (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\("), 1, None, 12),
    (re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)"), 1, None, 12),
    (re.compile(r"^\s*impl(?:<[^>]*>)?\s+(\w+)\s+for\s+(\w+)"), 2, 1, 23),
    (re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|override|virtual|abstract|async|"
                r"synchronized|extern|inline)\s+)+[\w<>\[\],.?]+(?:\s*<[^>]*>)?\s+(\w+)\s*\([^;]*$"), 1, None, 6),
    (re.compile(r"^\s+[\w<>\[\],.?]+\s+(\w+)\s*\([^;=]*\)\s*(?:throws\s+[\w,.\s]+)?\{\s*$"), 1, None, 6),
    (re.compile(r"^\s*(?:fun|def|sub|proc)\s+(?:[\w.]+\.)?(\w+)"), 1, None, 12),
    (re.compile(r"^\s*(?:local\s+)?function\s+([\w.:]+)"), 1, None, 12),
    (re.compile(r"^[A-Za-z_][\w\s\*&:<>,]*?\b(\w+)\s*\([^;]*\)\s*\{?\s*$"), 1, None, 12),
]
_KEYWORDS_NOT_NAMES = {"if", "for", "while", "switch", "return", "catch", "else", "elif", "new", "sizeof", "with"}
SOURCE_EXTS = {".py", ".pyw", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".kts", ".cs", ".go",
               ".rs", ".c", ".h", ".cpp", ".cc", ".hpp", ".cxx", ".php", ".rb", ".swift", ".dart", ".lua", ".scala",
               ".vue", ".svelte"}


def scan_definitions(path: Path, text: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines()):
        if len(line) > 400 or not line.strip() or line.lstrip().startswith(("//", "#", "*", "/*", "--")):
            continue
        for rx, ng, bg, kind in DEF_PATTERNS:
            m = rx.match(line)
            if m:
                name = m.group(ng)
                if not name or name in _KEYWORDS_NOT_NAMES:
                    continue
                bases = []
                if bg and m.group(bg):
                    bases = [b.strip().split("<")[0].split("(")[0].split(".")[-1]
                             for b in re.split(r"[,\s]+(?:implements\s+)?", m.group(bg)) if b.strip()]
                    bases = [b for b in bases if b and b not in ("object", "implements", "extends", "metaclass")
                             and "=" not in b]
                out.append({"name": name, "kind": kind, "path": path, "line": i, "col": m.start(ng),
                            "bases": bases, "indent": len(line) - len(line.lstrip())})
                break
    return out


def build_index(files) -> list[dict]:
    idx = []
    for f in files:
        if f.suffix.lower() not in SOURCE_EXTS:
            continue
        try:
            if f.stat().st_size > 1_500_000:
                continue
            idx += scan_definitions(f, f.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return idx


def enclosing_definition(lines: list[str], line: int) -> tuple[str, int] | None:
    """Funcao/metodo que contem a linha (por indentacao + padroes de definicao)."""
    if not (0 <= line < len(lines)):
        return None
    cur = lines[line]
    cur_ind = len(cur) - len(cur.lstrip()) if cur.strip() else 10 ** 6
    for i in range(line, -1, -1):
        t = lines[i]
        if not t.strip():
            continue
        ind = len(t) - len(t.lstrip())
        if ind > cur_ind and i != line:
            continue
        for rx, ng, _bg, kind in DEF_PATTERNS:
            m = rx.match(t)
            if m and m.group(ng) not in _KEYWORDS_NOT_NAMES and kind in (6, 12) and (ind < cur_ind or i == line):
                return m.group(ng), i
        cur_ind = min(cur_ind, ind)
    return None


# ================================================================ utilidades de texto
def split_args(s: str) -> list[str]:
    """Divide 'a, f(b, c), [d, e]' respeitando parenteses, colchetes, chaves e strings."""
    out, depth, cur, quote, esc = [], 0, "", "", False
    for ch in s:
        if quote:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in "([{<" and not (ch == "<" and depth == 0 and not re.search(r"\w$", cur)):
            depth += 1
        elif ch in ")]}>" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def matching_paren(text: str, open_idx: int) -> int:
    depth, quote, esc = 0, "", False
    for i in range(open_idx, len(text)):
        ch = text[i]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def test_candidates(path: Path, root: Path | None) -> list[Path]:
    """Arquivo de teste <-> codigo, nas convencoes mais comuns de cada linguagem."""
    stem, ext, d = path.stem, path.suffix, path.parent
    is_test = bool(re.match(r"^test_|_test$|\.test$|\.spec$|Tests?$|_spec$", stem) or stem.startswith("test_"))
    names = []
    if is_test:
        base = re.sub(r"^test_|_test$|\.test$|\.spec$|Tests?$|_spec$", "", stem)
        names = [base + ext]
    else:
        names = [f"test_{stem}{ext}", f"{stem}_test{ext}", f"{stem}.test{ext}", f"{stem}.spec{ext}",
                 f"{stem}Test{ext}", f"{stem}Tests{ext}", f"{stem}_spec{ext}"]
    found, seen = [], set()
    search_roots = [d, d.parent]
    if root:
        search_roots.append(root)
    for r in search_roots:
        for n in names:
            for cand in (r / n, r / "tests" / n, r / "test" / n, r / "__tests__" / n, r / "spec" / n):
                if cand.is_file() and cand not in seen:
                    seen.add(cand)
                    found.append(cand)
    if not found and root:
        from .panels import walk_files
        for f in walk_files(root, 40000):
            if f.name in names and f not in seen:
                seen.add(f)
                found.append(f)
    return found


def default_test_path(path: Path, root: Path | None) -> Path:
    stem, ext = path.stem, path.suffix
    name = {".py": f"test_{stem}.py", ".go": f"{stem}_test.go", ".java": f"{stem}Test.java",
            ".kt": f"{stem}Test.kt", ".cs": f"{stem}Tests.cs", ".rb": f"{stem}_spec.rb",
            ".rs": f"{stem}_test.rs"}.get(ext, f"{stem}.test{ext}")
    if ext == ".py" and root and (root / "tests").is_dir():
        return root / "tests" / name
    return path.parent / name


def test_template(path: Path, target: Path) -> str:
    stem = path.stem
    ext = path.suffix
    if ext == ".py":
        return f"import pytest\n\nimport {stem}\n\n\ndef test_{stem}():\n    assert True\n"
    if ext in (".js", ".ts", ".jsx", ".tsx", ".mjs"):
        return (f"import {{ describe, it, expect }} from 'vitest';\n\ndescribe('{stem}', () => {{\n"
                f"  it('funciona', () => {{\n    expect(true).toBe(true);\n  }});\n}});\n")
    if ext == ".go":
        return f"package main\n\nimport \"testing\"\n\nfunc Test{stem.title()}(t *testing.T) {{\n}}\n"
    if ext == ".java":
        return (f"import org.junit.jupiter.api.Test;\nimport static org.junit.jupiter.api.Assertions.*;\n\n"
                f"class {target.stem} {{\n    @Test\n    void funciona() {{\n        assertTrue(true);\n    }}\n}}\n")
    return ""


DECL = {"python": "{n} = {e}", "javascript": "const {n} = {e};", "typescript": "const {n} = {e};",
        "go": "{n} := {e}", "rust": "let {n} = {e};", "java": "var {n} = {e};", "csharp": "var {n} = {e};",
        "cpp": "auto {n} = {e};", "c": "__auto_type {n} = {e};", "kotlin": "val {n} = {e}",
        "swift": "let {n} = {e}", "dart": "final {n} = {e};", "php": "${n} = {e};", "ruby": "{n} = {e}",
        "lua": "local {n} = {e}", "shellscript": "{n}={e}", "powershell": "${n} = {e}", "scala": "val {n} = {e}"}
CONST_DECL = {"python": "{n} = {e}", "javascript": "const {n} = {e};", "typescript": "const {n} = {e};",
              "go": "const {n} = {e}", "rust": "const {n}: _ = {e};", "java": "static final var {n} = {e};",
              "csharp": "const var {n} = {e};", "cpp": "constexpr auto {n} = {e};", "c": "#define {n} ({e})",
              "kotlin": "const val {n} = {e}", "php": "const {n} = {e};", "ruby": "{n} = {e}"}


def suggest_name(expr: str) -> str:
    m = re.search(r"(\w+)\s*\([^()]*\)\s*$", expr)
    if m:
        n = re.sub(r"^(get|fetch|load|read|compute|calc|make|build|create)_?", "", m.group(1))
        n = n[:1].lower() + n[1:] if n else "valor"
        return re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower() if "_" in m.group(1) else n
    m = re.search(r"\.(\w+)\s*$", expr)
    if m:
        return m.group(1)
    if re.match(r"^\s*[\"']", expr):
        return "texto"
    if re.match(r"^\s*[\d.]+\s*$", expr):
        return "numero"
    return "valor"


def word_at(text: str, col: int) -> tuple[str, int]:
    for m in re.finditer(r"[A-Za-z_$][\w$]*", text):
        if m.start() <= col <= m.end():
            return m.group(0), m.start()
    return "", col


def python_project_venv(root: Path | None) -> Path | None:
    if not root:
        return None
    for d in (".venv", "venv", "env", ".env"):
        p = root / d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if p.exists():
            return p
    return None
