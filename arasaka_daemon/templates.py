"""
ARASAKA DAEMON // live templates (snippets dinamicos).

Digite a abreviacao e aperte Tab. Campos: ${1:padrao}, $1, $0 (posicao final).
Campos com o mesmo numero sao espelhados. Variaveis de contexto:
  $FILE$  $STEM$  $CLASS$ (nome do arquivo em PascalCase)  $DATE$  $TIME$
  $SELECTION$ (texto selecionado)  $CLIPBOARD$
Templates do usuario: chave "templates" em settings.json, por linguagem
(ou "*" para todas), por exemplo {"python": {"pdb": "breakpoint()$0"}}.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

DEFAULT: dict[str, dict[str, str]] = {
    "python": {
        "main": 'def main():\n    ${1:pass}\n\n\nif __name__ == "__main__":\n    main()\n',
        "def": "def ${1:nome}(${2}):\n    ${0:pass}",
        "class": "class ${1:$CLASS$}:\n    def __init__(self${2}):\n        ${0:pass}",
        "dc": "@dataclass\nclass ${1:$CLASS$}:\n    ${2:campo}: ${3:int}$0",
        "for": "for ${1:item} in ${2:itens}:\n    ${0:pass}",
        "fori": "for ${1:i} in range(${2:n}):\n    ${0:pass}",
        "enum": "for ${1:i}, ${2:item} in enumerate(${3:itens}):\n    ${0:pass}",
        "while": "while ${1:True}:\n    ${0:pass}",
        "if": "if ${1:condicao}:\n    ${0:pass}",
        "ifn": "if ${1:x} is None:\n    ${0:pass}",
        "try": "try:\n    ${1:pass}\nexcept ${2:Exception} as ${3:e}:\n    ${0:raise}",
        "with": "with open(${1:caminho}, encoding=\"utf-8\") as ${2:f}:\n    ${0:dados = $2.read()}",
        "lc": "[${1:x} for $1 in ${2:itens}${3: if $1}]$0",
        "dcomp": "{${1:k}: ${2:v} for $1, $2 in ${3:itens}.items()}$0",
        "prop": "@property\ndef ${1:nome}(self):\n    return self._$1$0",
        "test": "def test_${1:caso}():\n    ${0:assert True}",
        "pr": "print(f\"$SELECTION${1:valor} = {$SELECTION${1}}\")$0",
        "log": "logging.getLogger(__name__).${1:info}(\"${2:mensagem}\")$0",
        "imp": "import ${1:modulo}$0",
        "fro": "from ${1:modulo} import ${2:nome}$0",
    },
    "javascript": {
        "fn": "function ${1:nome}(${2}) {\n  ${0}\n}",
        "afn": "const ${1:nome} = (${2}) => {\n  ${0}\n};",
        "cl": "console.log(${1:$SELECTION$});$0",
        "for": "for (let ${1:i} = 0; $1 < ${2:arr}.length; $1++) {\n  ${0}\n}",
        "fof": "for (const ${1:item} of ${2:itens}) {\n  ${0}\n}",
        "if": "if (${1:condicao}) {\n  ${0}\n}",
        "try": "try {\n  ${1}\n} catch (${2:err}) {\n  ${0:console.error($2);}\n}",
        "class": "class ${1:$CLASS$} {\n  constructor(${2}) {\n    ${0}\n  }\n}",
        "imp": "import ${2:{ ${3:nome} \\}} from '${1:modulo}';$0",
        "desc": "describe('${1:$STEM$}', () => {\n  it('${2:funciona}', () => {\n    ${0:expect(true).toBe(true);}\n  });\n});",
        "fetch": "const ${1:res} = await fetch(${2:url});\nconst ${3:dados} = await $1.json();$0",
    },
    "go": {
        "main": "package main\n\nimport \"fmt\"\n\nfunc main() {\n\t${0:fmt.Println(\"ARASAKA\")}\n}\n",
        "fn": "func ${1:nome}(${2}) ${3:error} {\n\t${0}\n}",
        "iferr": "if err != nil {\n\t${0:return err}\n}",
        "for": "for ${1:i} := 0; $1 < ${2:n}; $1++ {\n\t${0}\n}",
        "forr": "for ${1:_}, ${2:v} := range ${3:itens} {\n\t${0}\n}",
        "st": "type ${1:Nome} struct {\n\t${0}\n}",
        "pf": "fmt.Printf(\"${1:%v}\\n\", ${2:valor})$0",
    },
    "rust": {
        "main": "fn main() {\n    ${0:println!(\"ARASAKA\");}\n}\n",
        "fn": "fn ${1:nome}(${2}) -> ${3:()} {\n    ${0}\n}",
        "st": "#[derive(Debug, Clone)]\nstruct ${1:Nome} {\n    ${0}\n}",
        "impl": "impl ${1:Nome} {\n    pub fn new(${2}) -> Self {\n        ${0:Self {  \\}}\n    }\n}",
        "for": "for ${1:item} in ${2:itens} {\n    ${0}\n}",
        "pl": "println!(\"{:?}\", ${1:valor});$0",
        "test": "#[test]\nfn ${1:caso}() {\n    ${0:assert!(true);}\n}",
    },
    "java": {
        "main": "public static void main(String[] args) {\n    ${0}\n}",
        "psvm": "public static void main(String[] args) {\n    ${0}\n}",
        "sout": "System.out.println(${1:$SELECTION$});$0",
        "fori": "for (int ${1:i} = 0; $1 < ${2:n}; $1++) {\n    ${0}\n}",
        "fore": "for (${1:var} ${2:item} : ${3:itens}) {\n    ${0}\n}",
        "class": "public class ${1:$CLASS$} {\n    ${0}\n}",
        "try": "try {\n    ${1}\n} catch (${2:Exception} ${3:e}) {\n    ${0:throw new RuntimeException($3);}\n}",
        "test": "@Test\nvoid ${1:caso}() {\n    ${0:assertTrue(true);}\n}",
    },
    "c": {
        "main": "#include <stdio.h>\n\nint main(void) {\n    ${0:printf(\"ARASAKA\\n\");}\n    return 0;\n}\n",
        "for": "for (int ${1:i} = 0; $1 < ${2:n}; $1++) {\n    ${0}\n}",
        "pf": "printf(\"${1:%d}\\n\", ${2:valor});$0",
        "inc": "#include <${1:stdio.h}>$0",
        "st": "typedef struct {\n    ${0}\n} ${1:Nome};",
    },
    "cpp": {
        "main": "#include <iostream>\n\nint main() {\n    ${0:std::cout << \"ARASAKA\" << std::endl;}\n    return 0;\n}\n",
        "for": "for (int ${1:i} = 0; $1 < ${2:n}; ++$1) {\n    ${0}\n}",
        "forr": "for (auto& ${1:item} : ${2:itens}) {\n    ${0}\n}",
        "cout": "std::cout << ${1:valor} << std::endl;$0",
        "class": "class ${1:$CLASS$} {\npublic:\n    $1();\n    ~$1();\n${0}\n};",
    },
    "csharp": {
        "cw": "Console.WriteLine(${1:$SELECTION$});$0",
        "prop": "public ${1:int} ${2:Nome} { get; set; }$0",
        "for": "for (int ${1:i} = 0; $1 < ${2:n}; $1++)\n{\n    ${0}\n}",
        "fore": "foreach (var ${1:item} in ${2:itens})\n{\n    ${0}\n}",
        "class": "public class ${1:$CLASS$}\n{\n    ${0}\n}",
    },
    "html": {
        "html5": "<!DOCTYPE html>\n<html lang=\"${1:pt-BR}\">\n<head>\n  <meta charset=\"UTF-8\">\n  <meta name=\"viewport\" "
                 "content=\"width=device-width, initial-scale=1.0\">\n  <title>${2:$STEM$}</title>\n</head>\n<body>\n"
                 "  ${0}\n</body>\n</html>\n",
        "div": "<div class=\"${1}\">${0}</div>",
        "a": "<a href=\"${1:#}\">${0:link}</a>",
        "script": "<script src=\"${1:app.js}\"></script>$0",
        "link": "<link rel=\"stylesheet\" href=\"${1:style.css}\">$0",
    },
    "http": {
        "get": "GET ${1:{{host}}}/${2:recurso}\nAccept: application/json\n$0",
        "post": "POST ${1:{{host}}}/${2:recurso}\nContent-Type: application/json\n\n{\n  \"${3:campo}\": \"${4:valor}\"\n}\n$0",
        "var": "@${1:host} = ${2:http://localhost:8000}\n$0",
        "sep": "\n###\n$0",
    },
    "shellscript": {
        "sh": "#!/usr/bin/env bash\nset -euo pipefail\n\n${0}",
        "if": "if [[ ${1:condicao} ]]; then\n  ${0}\nfi",
        "for": "for ${1:f} in ${2:*}; do\n  ${0:echo \"\\$$1\"}\ndone",
        "fn": "${1:nome}() {\n  ${0}\n}",
    },
    "*": {
        "todo": "TODO($DATE$): ${0}",
        "date": "$DATE$$0",
    },
}
DEFAULT["typescript"] = dict(DEFAULT["javascript"], **{
    "int": "interface ${1:Nome} {\n  ${2:campo}: ${3:string};\n}$0",
    "type": "type ${1:Nome} = ${0};",
    "fn": "function ${1:nome}(${2}): ${3:void} {\n  ${0}\n}",
})


def all_for(lang_id: str, user: dict | None = None) -> dict[str, str]:
    out = dict(DEFAULT.get("*", {}))
    out.update(DEFAULT.get(lang_id, {}))
    for k in ("*", lang_id):
        out.update((user or {}).get(k, {}))
    return out


_FIELD = re.compile(r"\$\{(\d+)(?::((?:[^{}\\]|\\.|\{\{[^{}]*\}\}|\{[^{}]*\})*))?\}|\$(\d+)")


def expand(body: str, indent: str, unit: str, ctx: dict) -> tuple[str, list[tuple[int, int, int]]]:
    """Expande o template. Retorna (texto, [(numero, inicio, fim)]) com posicoes relativas ao inicio."""
    stem = Path(ctx.get("file", "arquivo")).stem
    now = _dt.datetime.now()
    rep = {"$FILE$": Path(ctx.get("file", "")).name, "$STEM$": stem,
           "$CLASS$": "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s.]+", stem) if p) or "Nome",
           "$DATE$": now.strftime("%Y-%m-%d"), "$TIME$": now.strftime("%H:%M"),
           "$SELECTION$": ctx.get("selection", ""), "$CLIPBOARD$": ctx.get("clipboard", "")}
    for k, v in rep.items():
        body = body.replace(k, v)
    # indentacao: linhas seguintes recebem a indentacao da linha atual; 4 espacos / \t viram a unidade do editor
    lines = body.split("\n")
    fixed = [lines[0]]
    for ln in lines[1:]:
        m = re.match(r"^((?:    |\t)*)", ln)
        lvl = len(m.group(1).replace("\t", "    ")) // 4 if m else 0
        fixed.append(indent + unit * lvl + ln[len(m.group(1)) if m else 0:] if ln else ln)
    body = "\n".join(fixed)
    out, fields, i = "", [], 0
    defaults: dict[int, str] = {}
    for m in _FIELD.finditer(body):
        n = int(m.group(1) or m.group(3))
        if m.group(1) and m.group(2) is not None:
            defaults.setdefault(n, m.group(2))
    for m in _FIELD.finditer(body):
        out += body[i:m.start()].replace("\\}", "}").replace("\\$", "$")
        n = int(m.group(1) or m.group(3))
        val = m.group(2) if m.group(1) and m.group(2) is not None else defaults.get(n, "")
        # campos aninhados como ${3: if $1}: substitui referencias simples pelo padrao
        val = re.sub(r"\$(\d+)", lambda mm: defaults.get(int(mm.group(1)), ""), val.replace("\\}", "}"))
        start = len(out)
        out += val
        fields.append((n, start, len(out)))
        i = m.end()
    out += body[i:].replace("\\}", "}").replace("\\$", "$")
    return out, fields
