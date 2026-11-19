"""
ARASAKA DAEMON // realce de sintaxe.

Um unico realcador generico, configurado pelo registro de linguagens.
Regras simples (palavras-chave, tipos, numeros, funcoes) por regex e um
scanner proprio para strings e comentarios, que acompanha o estado entre
linhas (comentarios de bloco, strings triplas, template strings).
"""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from .languages import Language

THEME = {
    "text": "#d8d8de",
    "keyword": "#ff2e40",
    "type": "#ff9e64",
    "builtin": "#8fc1c4",
    "constant": "#ff6b9c",
    "number": "#ffb86b",
    "string": "#9fd8b0",
    "escape": "#ffd08a",
    "comment": "#5f5f6b",
    "function": "#f4f4f8",
    "decorator": "#c879ff",
    "preproc": "#c879ff",
    "variable": "#ffd08a",
    "operator": "#ff5d6a",
    "tag": "#ff2e40",
    "attr": "#ffb347",
    "heading": "#ff2e40",
    "bold": "#f4f4f8",
    "link": "#8fc1c4",
    "code": "#9fd8b0",
    "key": "#ff9e64",
}


def fmt(color: str, bold=False, italic=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


F = {
    "keyword": fmt(THEME["keyword"], bold=True),
    "type": fmt(THEME["type"]),
    "builtin": fmt(THEME["builtin"]),
    "constant": fmt(THEME["constant"]),
    "number": fmt(THEME["number"]),
    "string": fmt(THEME["string"]),
    "escape": fmt(THEME["escape"]),
    "comment": fmt(THEME["comment"], italic=True),
    "function": fmt(THEME["function"], bold=True),
    "decorator": fmt(THEME["decorator"]),
    "preproc": fmt(THEME["preproc"]),
    "variable": fmt(THEME["variable"]),
    "operator": fmt(THEME["operator"]),
    "tag": fmt(THEME["tag"], bold=True),
    "attr": fmt(THEME["attr"]),
    "heading": fmt(THEME["heading"], bold=True),
    "bold": fmt(THEME["bold"], bold=True),
    "italic": fmt(THEME["text"], italic=True),
    "link": fmt(THEME["link"]),
    "code": fmt(THEME["code"]),
    "key": fmt(THEME["key"]),
}

# estados entre linhas
NORMAL, BLOCK_COMMENT, TRIPLE_DQ, TRIPLE_SQ, BACKTICK, FENCE = 0, 1, 2, 3, 4, 5

MAX_HIGHLIGHT_CHARS = 1_500_000


def _words(s: str, ci: bool) -> re.Pattern | None:
    ws = [w for w in s.split() if w]
    if not ws:
        return None
    alt = "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True))
    return re.compile(rf"(?<![\w$#@-])(?:{alt})(?![\w-])" if any("-" in w for w in ws) else
                      rf"(?<![\w$#@])(?:{alt})(?!\w)", re.I if ci else 0)


def build_rules(lang: Language) -> list[tuple[re.Pattern, str, int]]:
    rules: list[tuple[re.Pattern, str, int]] = []
    L = lang
    ci = L.case_insensitive
    if L.id == "markdown":
        rules = [
            (re.compile(r"^\s{0,3}#{1,6}\s.*$"), "heading", 0),
            (re.compile(r"\*\*[^*]+\*\*|__[^_]+__"), "bold", 0),
            (re.compile(r"(?<![*\w])\*[^*\s][^*]*\*(?!\*)|(?<![_\w])_[^_\s][^_]*_(?!_)"), "italic", 0),
            (re.compile(r"`[^`]+`"), "code", 0),
            (re.compile(r"!?\[[^\]]*\]\([^)]*\)"), "link", 0),
            (re.compile(r"^\s*(?:[-*+]|\d+\.)\s"), "keyword", 0),
            (re.compile(r"^\s*>.*$"), "comment", 0),
        ]
        return rules
    if L.markup:
        rules = [
            (re.compile(r"</?[\w:.-]+|/?>"), "tag", 0),
            (re.compile(r"\s([\w:@.#-]+)(?==)"), "attr", 1),
            (re.compile(r"&[#\w]+;"), "escape", 0),
            (re.compile(r"<!DOCTYPE[^>]*>|<\?[^?]*\?>", re.I), "preproc", 0),
        ]
        return rules
    num = re.compile(r"(?<![\w.])(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|"
                     r"\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)[a-zA-Z]{0,3}(?!\w)")
    if L.id in ("css",):
        rules += [(re.compile(r"#[0-9a-fA-F]{3,8}\b"), "number", 0),
                       (re.compile(r"(?<![\w-])-?\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg|fr)?"), "number", 0),
                       (re.compile(r"([\w-]+)(?=\s*:[^:])"), "key", 1),
                       (re.compile(r"[.#][\w-]+|::?[\w-]+"), "function", 0),
                       (re.compile(r"@[\w-]+"), "keyword", 0)]
    elif L.id == "json":
        rules += [(num, "number", 0), (re.compile(r'"(?:[^"\\]|\\.)*"(?=\s*:)'), "key", 0)]
    elif L.id == "yaml":
        rules += [(num, "number", 0), (re.compile(r"^(\s*-?\s*)([\w./-]+)(?=\s*:)"), "key", 2),
                       (re.compile(r"^\s*-\s"), "operator", 0), (re.compile(r"[&*][\w-]+"), "variable", 0),
                       (re.compile(r"^---$|^\.\.\.$"), "keyword", 0)]
    elif L.id == "toml":
        rules += [(num, "number", 0), (re.compile(r"^\s*\[\[?[^\]]+\]\]?"), "heading", 0),
                       (re.compile(r"^\s*([\w.\"-]+)(?=\s*=)"), "key", 1)]
    else:
        rules += [(num, "number", 0),
                       (re.compile(r"\b([A-Za-z_]\w*)(?=\s*\()"), "function", 1)]
        if L.id not in ("sql", "bat", "shellscript", "powershell", "makefile", "dockerfile"):
            rules.append((re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"), "constant", 0))
        if L.id in ("java", "csharp", "kotlin", "swift", "dart", "typescript", "cpp", "rust", "go", "php"):
            rules.append((re.compile(r"\b[A-Z][a-z0-9]\w*\b"), "type", 0))
    for words, kind in ((L.builtins, "builtin"), (L.types, "type"), (L.constants, "constant"),
                        (L.keywords, "keyword")):
        pat = _words(words, ci)
        if pat:
            rules.append((pat, kind, 0))
    if L.decorators:
        rules.append((re.compile(r"@[\w.]+"), "decorator", 0))
    if L.preprocessor:
        rules.append((re.compile(r"^\s*#\s*\w+"), "preproc", 0))
    if L.variables == "$":
        rules.append((re.compile(r"\$\{?[\w@#?*!-]+\}?"), "variable", 0))
    elif L.variables == "%":
        rules.append((re.compile(r"%[\w~]+%?|%%\w"), "variable", 0))
    if L.id == "rust":
        rules.append((re.compile(r"\b\w+!"), "decorator", 0))
        rules.append((re.compile(r"'[a-z_]\w*\b(?!')"), "decorator", 0))
    return rules


# ---------------------------------------------------------------- injecao de linguagem em strings
# SQL, JSON, HTML e regex escritos dentro de strings ganham o realce da linguagem de dentro.
_INJ_SQL = re.compile(r"^\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(TABLE|INDEX|VIEW)|DROP|ALTER|WITH)\b",
                      re.I)
_INJ_HTML = re.compile(r"^\s*<(!DOCTYPE|[a-zA-Z][\w-]*)[^>]*>")
_INJ_JSON = re.compile(r'^\s*[\[{]\s*("|\]|}|$)')
_INJ_REGEX_CALL = re.compile(r"(re\.\w+|RegExp|Pattern\.compile|Regex|regexp\.\w+|preg_\w+)\s*\(\s*[rbuf]*$")
_REGEX_RULES = [(re.compile(r"\\[dDwWsSbBnrtfv]|\\."), "escape", 0),
                (re.compile(r"\[\^?(?:\\.|[^\]])*\]"), "type", 0),
                (re.compile(r"\(\?(?:[:=!]|<[=!]|P?<\w+>)|[()|]"), "keyword", 0),
                (re.compile(r"[*+?]\??|\{\d+(,\d*)?\}\??"), "operator", 0),
                (re.compile(r"[\^$.]"), "builtin", 0)]
_INJ_CACHE: dict[str, list] = {}


def injected_rules(lang_id: str) -> list:
    if lang_id == "regex":
        return _REGEX_RULES
    if lang_id not in _INJ_CACHE:
        from .languages import BY_ID
        lg = BY_ID.get(lang_id)
        _INJ_CACHE[lang_id] = build_rules(lg) if lg else []
    return _INJ_CACHE[lang_id]


def detect_injection(before: str, content: str, prefix: str) -> str:
    if "r" in prefix.lower() and not content.startswith("<"):
        return "regex"
    if _INJ_REGEX_CALL.search(before):
        return "regex"
    if _INJ_SQL.match(content):
        return "sql"
    if _INJ_HTML.match(content):
        return "html"
    if _INJ_JSON.match(content) and ":" in content or content.strip() in ("{}", "[]"):
        return "json"
    return ""


class Highlighter(QSyntaxHighlighter):
    def __init__(self, doc, lang: Language):
        super().__init__(doc)
        self.lang = lang
        self.enabled = doc.characterCount() < MAX_HIGHLIGHT_CHARS
        self.rules = build_rules(lang)
        self.hints: dict[int, tuple[str, list[tuple[int, float]]]] = {}   # linha -> (texto, [(coluna, largura)])
        self.inject = lang.id not in ("sql", "json", "html", "xml", "markdown", "plaintext")

    # ------------------------------------------------------------------
    def highlightBlock(self, text: str):
        if self.enabled:
            for pat, kind, group in self.rules:
                for m in pat.finditer(text):
                    s, e = m.span(group)
                    if e > s:
                        self.setFormat(s, e - s, F[kind])
            if self.lang.id == "markdown":
                self._markdown_fence(text)
            else:
                self._scan(text)
        self._gaps(text)

    def _gaps(self, text: str):
        """Abre espaco visual (sem mudar o texto) para os inlay hints: espacamento extra no caractere anterior."""
        h = self.hints.get(self.currentBlock().blockNumber())
        if not h or h[0] != text:
            return
        for col, width in h[1]:
            if 0 < col <= len(text):
                f = QTextCharFormat(self.format(col - 1))
                f.setFontLetterSpacingType(QFont.AbsoluteSpacing)
                f.setFontLetterSpacing(width)
                self.setFormat(col - 1, 1, f)

    def _markdown_fence(self, text: str):
        prev = self.previousBlockState()
        inside = prev == FENCE
        if text.lstrip().startswith("```") or text.lstrip().startswith("~~~"):
            self.setFormat(0, len(text), F["preproc"])
            self.setCurrentBlockState(NORMAL if inside else FENCE)
            return
        if inside:
            self.setFormat(0, len(text), F["code"])
        self.setCurrentBlockState(FENCE if inside else NORMAL)

    def _scan(self, text: str):
        L = self.lang
        lc = L.line_comment
        bc = L.block_comment
        n = len(text)
        state = self.previousBlockState()
        if state < 0:
            state = NORMAL
        i = 0
        # continua construcoes de linhas anteriores
        if state != NORMAL:
            end_tok = {BLOCK_COMMENT: bc[1] if bc else "", TRIPLE_DQ: '"""', TRIPLE_SQ: "'''", BACKTICK: "`"}[state]
            kind = "comment" if state == BLOCK_COMMENT else "string"
            j = self._find_end(text, 0, end_tok, state != BLOCK_COMMENT)
            if j < 0:
                self.setFormat(0, n, F[kind])
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, j + len(end_tok), F[kind])
            i = j + len(end_tok)
            state = NORMAL
        quotes = L.quotes
        while i < n:
            c = text[i]
            if bc and text.startswith(bc[0], i) and (bc[0] != "=begin" or i == 0):
                j = self._find_end(text, i + len(bc[0]), bc[1], False)
                if j < 0:
                    self.setFormat(i, n - i, F["comment"])
                    self.setCurrentBlockState(BLOCK_COMMENT)
                    return
                self.setFormat(i, j + len(bc[1]) - i, F["comment"])
                i = j + len(bc[1])
                continue
            if lc and text.startswith(lc, i) if not L.case_insensitive else \
                    lc and text[i:i + len(lc)].lower() == lc:
                if lc == "#" and L.id in ("shellscript",) and i > 0 and text[i - 1] == "$":
                    i += 1
                    continue
                self.setFormat(i, n - i, F["comment"])
                break
            if L.triple_quotes and (text.startswith('"""', i) or text.startswith("'''", i)):
                tok = text[i:i + 3]
                j = self._find_end(text, i + 3, tok, True)
                if j < 0:
                    self.setFormat(i, n - i, F["string"])
                    self.setCurrentBlockState(TRIPLE_DQ if tok == '"""' else TRIPLE_SQ)
                    return
                self.setFormat(i, j + 3 - i, F["string"])
                i = j + 3
                continue
            if L.backtick and c == "`":
                j = self._find_end(text, i + 1, "`", True)
                if j < 0:
                    self.setFormat(i, n - i, F["string"])
                    self.setCurrentBlockState(BACKTICK)
                    return
                self.setFormat(i, j + 1 - i, F["string"])
                i = j + 1
                continue
            if c in quotes and quotes and L.markup and not text[:i].rstrip().endswith("="):
                i += 1          # em HTML/XML so ha strings em valores de atributo
                continue
            if c in quotes and quotes:
                # apostrofo em Rust (lifetime) / contracoes: so trata como string se fechar na linha
                j = self._find_end(text, i + 1, c, True)
                if j < 0:
                    if c == "'" and L.id in ("rust",):
                        i += 1
                        continue
                    self.setFormat(i, n - i, F["string"])
                    break
                self.setFormat(i, j + 1 - i, F["string"])
                inj = detect_injection(text[:i], text[i + 1:j], text[max(0, i - 2):i]) if self.inject else ""
                if inj:
                    self._inject(text, i + 1, j, inj)
                else:
                    for m in re.finditer(r"\\.", text[i:j + 1]):
                        self.setFormat(i + m.start(), 2, F["escape"])
                i = j + 1
                continue
            i += 1
        self.setCurrentBlockState(NORMAL)

    def _inject(self, text: str, start: int, end: int, lang_id: str):
        """Realca text[start:end] (conteudo da string) com as regras de outra linguagem."""
        seg = text[start:end]
        base = QTextCharFormat(F["string"])
        base.setBackground(QColor(255, 255, 255, 8))
        self.setFormat(start, end - start, base)
        for pat, kind, group in injected_rules(lang_id):
            for m in pat.finditer(seg):
                s, e = m.span(group)
                if e > s:
                    f = QTextCharFormat(F[kind])
                    f.setBackground(QColor(255, 255, 255, 8))
                    self.setFormat(start + s, e - s, f)

    @staticmethod
    def _find_end(text: str, start: int, tok: str, escapes: bool) -> int:
        i = start
        n = len(text)
        while i < n:
            if escapes and text[i] == "\\":
                i += 2
                continue
            if text.startswith(tok, i):
                return i
            i += 1
        return -1
