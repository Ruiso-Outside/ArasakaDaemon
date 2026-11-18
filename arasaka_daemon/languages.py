"""
ARASAKA DAEMON // registro de linguagens.

Cada linguagem define: extensoes, regras de realce, comentarios, como
executar o arquivo atual, quais servidores LSP usar e como instala-los.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

WIN = sys.platform == "win32"


@dataclass
class LspServer:
    cmd: list[str]                 # comando; o primeiro item e procurado no PATH
    install: str                   # comando para instalar (mostrado e executado no terminal)
    name: str = ""

    def resolve(self) -> list[str] | None:
        exe = shutil.which(self.cmd[0])
        if not exe:
            return None
        if WIN and exe.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/c", exe, *self.cmd[1:]]
        return [exe, *self.cmd[1:]]


@dataclass
class Language:
    id: str                        # languageId do LSP
    name: str
    exts: tuple
    color: str
    abbr: str
    keywords: str = ""
    types: str = ""
    builtins: str = ""
    constants: str = "true false null"
    line_comment: str = ""
    block_comment: tuple = ()
    quotes: str = "\"'"
    triple_quotes: bool = False
    backtick: bool = False
    decorators: bool = False       # @decorator / @Annotation
    preprocessor: bool = False     # #include
    variables: str = ""            # prefixo de variavel ($ em PHP/shell)
    case_insensitive: bool = False
    markup: bool = False           # HTML/XML
    run: str = ""                  # modelo do comando de execucao
    run_win: str = ""              # variante Windows (se diferente)
    runtime: list = field(default_factory=list)   # executaveis que indicam o runtime instalado
    runtime_install: str = ""
    servers: list = field(default_factory=list)   # [LspServer]
    filenames: tuple = ()          # nomes exatos (Makefile, Dockerfile...)

    def run_command(self) -> str:
        return (self.run_win if WIN and self.run_win else self.run)

    def server(self) -> tuple[LspServer, list[str]] | tuple[None, None]:
        for s in self.servers:
            cmd = s.resolve()
            if cmd:
                return s, cmd
        return None, None

    def runtime_found(self) -> str:
        for r in self.runtime:
            p = shutil.which(r)
            if p:
                return p
        return ""


PY = "python" if WIN else "python3"
EXE = ".exe" if WIN else ""
OUT = '"{dir}/{stem}' + EXE + '"'

C_KW = ("auto break case const continue default do else enum extern for goto if inline register restrict return "
        "sizeof static struct switch typedef union volatile while")
C_TY = ("void char short int long float double signed unsigned bool size_t int8_t int16_t int32_t int64_t uint8_t "
        "uint16_t uint32_t uint64_t FILE")

LANGS: list[Language] = [
    Language("python", "Python", (".py", ".pyw", ".pyi"), "#3572A5", "PY",
             "and as assert async await break class continue def del elif else except finally for from global if "
             "import in is lambda nonlocal not or pass raise return try while with yield match case",
             "int float str bool list dict set tuple bytes object type complex frozenset bytearray",
             "print len range open input enumerate zip map filter sorted reversed sum min max abs any all isinstance "
             "hasattr getattr setattr super property staticmethod classmethod iter next repr format round id hash "
             "self cls __init__ __name__ __main__",
             "True False None", "#", (), "\"'", True, decorators=True,
             run=f'{PY} -u "{{file}}"', runtime=[PY, "python", "py"],
             runtime_install="sudo apt install python3" if not WIN else "winget install Python.Python.3.12",
             servers=[LspServer(["pylsp"], f"{PY} -m pip install -U python-lsp-server", "pylsp"),
                      LspServer(["pyright-langserver", "--stdio"], "npm install -g pyright", "pyright")]),
    Language("javascript", "JavaScript", (".js", ".mjs", ".cjs", ".jsx"), "#f1e05a", "JS",
             "break case catch class const continue debugger default delete do else export extends finally for "
             "from function if import in instanceof let new of return static super switch this throw try typeof "
             "var void while with yield async await get set",
             "Array Object String Number Boolean Map Set Promise Date RegExp Error Symbol BigInt JSON Math",
             "console window document require module exports process globalThis setTimeout setInterval fetch",
             "true false null undefined NaN Infinity", "//", ("/*", "*/"), "\"'", backtick=True,
             run='node "{file}"', runtime=["node"],
             runtime_install="sudo apt install nodejs npm" if not WIN else "winget install OpenJS.NodeJS.LTS",
             servers=[LspServer(["typescript-language-server", "--stdio"],
                                "npm install -g typescript typescript-language-server", "tsserver"),
                      LspServer(["tsc", "--lsp", "--stdio"], "npm install -g typescript", "tsc (TS 7)")]),
    Language("typescript", "TypeScript", (".ts", ".tsx", ".mts", ".cts"), "#3178c6", "TS",
             "break case catch class const continue debugger default delete do else export extends finally for "
             "from function if import in instanceof let new of return static super switch this throw try typeof "
             "var void while yield async await get set interface type enum implements namespace declare abstract "
             "public private protected readonly as keyof infer is satisfies",
             "string number boolean any unknown never void object Array Record Partial Promise Map Set",
             "console window document require process", "true false null undefined", "//", ("/*", "*/"), "\"'",
             backtick=True, decorators=True, run='npx --yes tsx "{file}"', runtime=["node"],
             runtime_install="npm install -g tsx",
             servers=[LspServer(["typescript-language-server", "--stdio"],
                                "npm install -g typescript typescript-language-server", "tsserver"),
                      LspServer(["tsc", "--lsp", "--stdio"], "npm install -g typescript", "tsc (TS 7)")]),
    Language("java", "Java", (".java",), "#b07219", "JV",
             "abstract assert break case catch class continue default do else enum extends final finally for if "
             "implements import instanceof interface native new package private protected public return static "
             "strictfp super switch synchronized this throw throws transient try volatile while var record yield",
             "boolean byte char short int long float double void String Integer Long Double Object List Map "
             "ArrayList HashMap Optional",
             "System out println", "true false null", "//", ("/*", "*/"), "\"'", decorators=True,
             run='java "{file}"', runtime=["java"],
             runtime_install="sudo apt install default-jdk" if not WIN else "winget install EclipseAdoptium.Temurin.21.JDK",
             servers=[LspServer(["jdtls"], "Baixe o Eclipse JDT LS: https://github.com/eclipse-jdtls/eclipse.jdt.ls",
                                "jdtls")]),
    Language("c", "C", (".c", ".h"), "#555555", "C", C_KW, C_TY, "printf scanf malloc free memcpy strlen NULL",
             "true false NULL", "//", ("/*", "*/"), "\"'", preprocessor=True,
             run=f'gcc -Wall -g "{{file}}" -o {OUT} && {OUT}', runtime=["gcc", "clang"],
             runtime_install="sudo apt install build-essential" if not WIN else "winget install BrechtSanders.WinLibs.POSIX.UCRT",
             servers=[LspServer(["clangd"], "sudo apt install clangd" if not WIN else "winget install LLVM.LLVM",
                                "clangd")]),
    Language("cpp", "C++", (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ino"), "#f34b7d", "C++",
             C_KW + " alignas alignof catch class constexpr consteval decltype delete explicit export friend "
                    "mutable namespace new noexcept operator private protected public template this throw try "
                    "typename using virtual override final co_await co_return concept requires",
             C_TY + " auto string vector map unordered_map set unique_ptr shared_ptr optional std",
             "cout cin endl cerr printf make_unique make_shared move", "true false nullptr NULL", "//",
             ("/*", "*/"), "\"'", preprocessor=True,
             run=f'g++ -std=c++20 -Wall -g "{{file}}" -o {OUT} && {OUT}', runtime=["g++", "clang++"],
             runtime_install="sudo apt install build-essential" if not WIN else "winget install BrechtSanders.WinLibs.POSIX.UCRT",
             servers=[LspServer(["clangd"], "sudo apt install clangd" if not WIN else "winget install LLVM.LLVM",
                                "clangd")]),
    Language("csharp", "C#", (".cs", ".csx"), "#178600", "C#",
             "abstract as base break case catch checked class const continue default delegate do else enum event "
             "explicit extern finally fixed for foreach goto if implicit in interface internal is lock namespace "
             "new operator out override params private protected public readonly ref return sealed sizeof "
             "stackalloc static struct switch this throw try typeof unchecked unsafe using virtual volatile while "
             "async await var record init get set yield where",
             "bool byte char decimal double float int long object sbyte short string uint ulong ushort void "
             "List Dictionary Task", "Console WriteLine Math", "true false null", "//", ("/*", "*/"), "\"'",
             decorators=False, run='dotnet run', runtime=["dotnet"],
             runtime_install="sudo apt install dotnet-sdk-8.0" if not WIN else "winget install Microsoft.DotNet.SDK.8",
             servers=[LspServer(["csharp-ls"], "dotnet tool install --global csharp-ls", "csharp-ls")]),
    Language("go", "Go", (".go",), "#00ADD8", "GO",
             "break case chan const continue default defer else fallthrough for func go goto if import interface "
             "map package range return select struct switch type var",
             "bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 rune string uint "
             "uint8 uint16 uint32 uint64 uintptr any",
             "append cap close copy delete len make new panic print println recover fmt", "true false nil iota",
             "//", ("/*", "*/"), "\"'", backtick=True, run='go run "{file}"', runtime=["go"],
             runtime_install="sudo apt install golang" if not WIN else "winget install GoLang.Go",
             servers=[LspServer(["gopls"], "go install golang.org/x/tools/gopls@latest", "gopls")]),
    Language("rust", "Rust", (".rs",), "#dea584", "RS",
             "as async await break const continue crate dyn else enum extern fn for if impl in let loop match mod "
             "move mut pub ref return self Self static struct super trait type unsafe use where while",
             "i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64 bool char str String Vec Option Result "
             "Box Rc Arc HashMap", "println print format vec panic assert assert_eq Some None Ok Err",
             "true false", "//", ("/*", "*/"), "\"", decorators=False,
             run=f'rustc -g "{{file}}" -o {OUT} && {OUT}', runtime=["rustc", "cargo"],
             runtime_install="curl https://sh.rustup.rs -sSf | sh" if not WIN else "winget install Rustlang.Rustup",
             servers=[LspServer(["rust-analyzer"], "rustup component add rust-analyzer", "rust-analyzer")]),
    Language("php", "PHP", (".php", ".phtml"), "#4F5D95", "PHP",
             "abstract and as break callable case catch class clone const continue declare default do echo else "
             "elseif empty enddeclare endfor endforeach endif endswitch endwhile extends final finally fn for "
             "foreach function global goto if implements include include_once instanceof insteadof interface isset "
             "list match namespace new or print private protected public readonly require require_once return "
             "static switch throw trait try unset use var while xor yield",
             "int float string bool array object mixed void", "strlen count array_map json_encode var_dump",
             "true false null TRUE FALSE NULL", "//", ("/*", "*/"), "\"'", variables="$",
             run='php "{file}"', runtime=["php"],
             runtime_install="sudo apt install php-cli" if not WIN else "winget install PHP.PHP.8.3",
             servers=[LspServer(["intelephense", "--stdio"], "npm install -g intelephense", "intelephense")]),
    Language("ruby", "Ruby", (".rb", ".rake", ".gemspec"), "#701516", "RB",
             "alias and begin break case class def defined? do else elsif end ensure for if in module next not or "
             "redo rescue retry return self super then undef unless until when while yield require attr_accessor",
             "Array Hash String Integer Float Symbol", "puts print p gets", "true false nil", "#", ("=begin", "=end"),
             "\"'", run='ruby "{file}"', runtime=["ruby"],
             runtime_install="sudo apt install ruby-full" if not WIN else "winget install RubyInstallerTeam.Ruby.3.2",
             servers=[LspServer(["solargraph", "stdio"], "gem install solargraph", "solargraph")]),
    Language("kotlin", "Kotlin", (".kt", ".kts"), "#A97BFF", "KT",
             "as break class continue do else for fun if in interface is null object package return super this "
             "throw try typealias typeof val var when while by catch constructor init companion data sealed "
             "override open private public internal protected lateinit suspend import",
             "Int Long Double Float Boolean String Char Unit Any List Map Set Array", "println print listOf mapOf",
             "true false null", "//", ("/*", "*/"), "\"'", triple_quotes=True, decorators=True,
             run=f'kotlinc "{{file}}" -include-runtime -d "{{dir}}/{{stem}}.jar" && java -jar "{{dir}}/{{stem}}.jar"',
             runtime=["kotlinc"], runtime_install="sdk install kotlin",
             servers=[LspServer(["kotlin-language-server"], "https://github.com/fwcd/kotlin-language-server", "kls")]),
    Language("swift", "Swift", (".swift",), "#F05138", "SW",
             "associatedtype class deinit enum extension fileprivate func import init inout internal let open "
             "operator private protocol public rethrows static struct subscript typealias var break case continue "
             "default defer do else fallthrough for guard if in repeat return switch where while as catch is "
             "throw throws try async await",
             "Int Double Float Bool String Character Array Dictionary Set Optional", "print", "true false nil",
             "//", ("/*", "*/"), "\"", triple_quotes=True, decorators=True, run='swift "{file}"', runtime=["swift"],
             servers=[LspServer(["sourcekit-lsp"], "Vem com o Swift toolchain", "sourcekit-lsp")]),
    Language("dart", "Dart", (".dart",), "#00B4AB", "DT",
             "abstract as assert async await break case catch class const continue default do else enum export "
             "extends external factory final finally for get if implements import in is late library mixin new "
             "operator part required rethrow return set static super switch this throw try typedef var while with "
             "yield", "int double num String bool List Map Set Future Stream void dynamic", "print",
             "true false null", "//", ("/*", "*/"), "\"'", triple_quotes=True, decorators=True,
             run='dart run "{file}"', runtime=["dart"], runtime_install="https://dart.dev/get-dart",
             servers=[LspServer(["dart", "language-server"], "Vem com o Dart SDK", "dart")]),
    Language("lua", "Lua", (".lua",), "#000080", "LUA",
             "and break do else elseif end for function goto if in local not or repeat return then until while",
             "", "print pairs ipairs require table string math tostring tonumber type pcall error setmetatable",
             "true false nil", "--", ("--[[", "]]"), "\"'", run='lua "{file}"', runtime=["lua", "lua5.4", "luajit"],
             runtime_install="sudo apt install lua5.4" if not WIN else "winget install DEVCOM.Lua",
             servers=[LspServer(["lua-language-server"], "sudo snap install lua-language-server --classic"
                                if not WIN else "winget install LuaLS.lua-language-server", "lua-ls")]),
    Language("shellscript", "Shell", (".sh", ".bash", ".zsh"), "#89e051", "SH",
             "if then else elif fi case esac for while until do done in function select time return break continue "
             "local export readonly declare unset shift source exit",
             "", "echo printf read cd ls grep sed awk cat test set eval exec trap", "true false", "#", (), "\"'",
             variables="$", run='bash "{file}"', run_win='bash "{file}"', runtime=["bash"],
             servers=[LspServer(["bash-language-server", "start"], "npm install -g bash-language-server", "bashls")],
             filenames=(".bashrc", ".zshrc", ".profile")),
    Language("powershell", "PowerShell", (".ps1", ".psm1", ".psd1"), "#012456", "PS",
             "begin break catch class continue data define do dynamicparam else elseif end enum exit filter "
             "finally for foreach from function hidden if in param process return static switch throw trap try "
             "until using var while", "", "Write-Host Write-Output Get-ChildItem Set-Location Get-Content",
             "$true $false $null", "#", ("<#", "#>"), "\"'", variables="$", case_insensitive=True,
             run='pwsh -NoProfile -File "{file}"', run_win='powershell -NoProfile -ExecutionPolicy Bypass -File "{file}"',
             runtime=["pwsh", "powershell"]),
    Language("bat", "Batch", (".bat", ".cmd"), "#C1F12E", "BAT",
             "if else for in do goto call exit set echo rem not exist defined errorlevel setlocal endlocal pause",
             "", "", "", "rem ", (), "\"", variables="%", case_insensitive=True, run='"{file}"', runtime=["cmd"]),
    Language("sql", "SQL", (".sql",), "#e38c00", "SQL",
             "select from where insert into values update set delete create table drop alter add column primary "
             "key foreign references index view join inner left right outer on group by order having limit offset "
             "union all distinct as and or not null is in like between exists case when then else end begin "
             "commit rollback transaction default unique check constraint", "int integer varchar text char date "
             "timestamp boolean float double decimal serial bigint", "count sum avg min max coalesce now",
             "true false null", "--", ("/*", "*/"), "'\"", case_insensitive=True),
    Language("html", "HTML", (".html", ".htm", ".xhtml", ".vue", ".svelte"), "#e34c26", "HTM", markup=True,
             line_comment="", block_comment=("<!--", "-->"), quotes="\"'",
             run='', servers=[LspServer(["vscode-html-language-server", "--stdio"],
                                        "npm install -g vscode-langservers-extracted", "html-ls")]),
    Language("xml", "XML", (".xml", ".svg", ".xaml", ".csproj", ".plist", ".ui"), "#0060ac", "XML", markup=True,
             block_comment=("<!--", "-->"), quotes="\"'"),
    Language("css", "CSS", (".css", ".scss", ".sass", ".less"), "#563d7c", "CSS",
             "important media import keyframes font-face supports root hover active focus before after nth-child",
             "", "rgb rgba hsl var calc url linear-gradient", "", "", ("/*", "*/"), "\"'",
             servers=[LspServer(["vscode-css-language-server", "--stdio"],
                                "npm install -g vscode-langservers-extracted", "css-ls")]),
    Language("json", "JSON", (".json", ".jsonc", ".code-workspace"), "#cbcb41", "{}",
             "", "", "", "true false null", "//", ("/*", "*/"), "\"",
             servers=[LspServer(["vscode-json-language-server", "--stdio"],
                                "npm install -g vscode-langservers-extracted", "json-ls")]),
    Language("yaml", "YAML", (".yml", ".yaml"), "#cb171e", "YML", "", "", "",
             "true false null yes no on off", "#", (), "\"'",
             servers=[LspServer(["yaml-language-server", "--stdio"], "npm install -g yaml-language-server", "yaml")]),
    Language("toml", "TOML", (".toml", ".ini", ".cfg", ".conf", ".editorconfig", ".desktop"), "#9c4221", "TML",
             "", "", "", "true false", "#", (), "\"'"),
    Language("markdown", "Markdown", (".md", ".markdown", ".mdx"), "#083fa1", "MD", line_comment="",
             quotes="", constants=""),
    Language("makefile", "Makefile", (".mk", ".mak"), "#427819", "MK",
             "ifeq ifneq ifdef ifndef else endif include define endef export", "", "", "", "#", (), "\"'",
             variables="$", run='make -C "{dir}"', runtime=["make"], filenames=("Makefile", "makefile", "GNUmakefile")),
    Language("dockerfile", "Dockerfile", (".dockerfile",), "#384d54", "DKR",
             "FROM RUN CMD LABEL EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD STOPSIGNAL "
             "HEALTHCHECK SHELL AS", "", "", "", "#", (), "\"'", variables="$", case_insensitive=True,
             filenames=("Dockerfile", "Containerfile")),
]

PLAIN = Language("plaintext", "Texto", (".txt", ".log"), "#8c8c96", "TXT", constants="", quotes="")

BY_ID = {lang.id: lang for lang in LANGS}


def detect(path: str | Path) -> Language:
    p = Path(path)
    name = p.name
    for lang in LANGS:
        if name in lang.filenames:
            return lang
    ext = p.suffix.lower()
    for lang in LANGS:
        if ext in lang.exts:
            return lang
    return PLAIN


def run_command(lang: Language, file: Path, root: Path | None) -> str:
    tmpl = lang.run_command()
    if not tmpl:
        return ""
    f = Path(file)
    return (tmpl.replace("{file}", str(f)).replace("{dir}", str(f.parent)).replace("{stem}", f.stem)
            .replace("{root}", str(root or f.parent)))


def shell_argv(command: str) -> list[str]:
    if WIN:
        return ["cmd", "/d", "/s", "/c", command]
    return ["bash", "-lc", command]


def interactive_shell() -> list[str]:
    if WIN:
        ps = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [ps, "-NoLogo", "-NoProfile", "-Command", "-"]
    return [os.environ.get("SHELL", "/bin/bash") if Path(os.environ.get("SHELL", "")).name in ("bash", "zsh")
            else "/bin/bash", "-s"]
