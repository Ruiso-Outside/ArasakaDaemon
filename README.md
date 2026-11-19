# ARASAKA DAEMON

IDE de programação com tema Arasaka para **Linux e Windows**, com foco em suporte às linguagens
populares.

O suporte a linguagens tem duas camadas:

1. **Realce de sintaxe próprio** para 28 linguagens e formatos:

   | Grupo | Linguagens e formatos |
   |---|---|
   | Programação | Python, JavaScript, TypeScript, Java, C, C++, C#, Go, Rust, PHP, Ruby, Kotlin, Swift, Dart, Lua |
   | Scripts | Shell, PowerShell, Batch |
   | Web, dados e configuração | SQL, HTML, XML, CSS/SCSS, JSON, YAML, TOML/INI, Markdown, Makefile, Dockerfile |

2. **LSP (Language Server Protocol)**, o mesmo protocolo do VS Code. Com o servidor da linguagem
   instalado, você ganha:
   - autocompletar inteligente (`Ctrl+Espaço` ou automático ao digitar);
   - **erros e avisos em tempo real**, com sublinhado ondulado, marcador ao lado do número da linha e
     a aba PROBLEMAS;
   - documentação ao passar o mouse;
   - **ir para definição** (`F12` ou `Ctrl+clique`);
   - **formatar documento** (`Shift+Alt+F`).

   Servidores suportados (todos instaláveis pela aba **LINGUAGENS**):

   | Linguagem | Servidor |
   |---|---|
   | Python | pylsp ou pyright |
   | JavaScript / TypeScript | typescript-language-server, ou o LSP nativo do **TypeScript 7** |
   | C / C++ | clangd |
   | C# | csharp-ls |
   | Go | gopls |
   | Rust | rust-analyzer |
   | Java | jdtls |
   | PHP | intelephense |
   | Ruby | solargraph |
   | Lua | lua-language-server |
   | Bash | bash-language-server |
   | HTML / CSS / JSON | vscode-langservers-extracted |
   | YAML | yaml-language-server |
   | Kotlin | kotlin-language-server |
   | Dart | dart |
   | Swift | sourcekit-lsp |

## Recursos

| Área | O que tem |
|---|---|
| **Editor** | Números de linha, linha atual, pares de colchetes, indentação automática, fechamento de `()[]{}""''`, `Ctrl+/` comenta, `Ctrl+D` duplica, `Alt+↑/↓` move linhas, `Ctrl+Shift+K` apaga a linha, `Home` inteligente, zoom com `Ctrl+roda do mouse` |
| **Projeto** | Explorador de arquivos (novo, renomear, lixeira, copiar caminho), `Ctrl+P` abre arquivo pelo nome, `Ctrl+Shift+F` busca em todos os arquivos (texto ou regex) |
| **Executar (`F5`)** | Roda o arquivo atual com o comando da linguagem (Python, Node, `tsx`, `go run`, gcc/g++, `rustc`, `java`, `dotnet run`, PHP, Ruby, Lua, Bash, PowerShell...). A saída aparece no painel SAÍDA, que também tem um campo para digitar entradas (`input()`, `scanf`...). Os comandos podem ser trocados em CONFIGURAÇÕES |
| **Terminal integrado** | bash no Linux, PowerShell no Windows (`` Ctrl+` ``) |
| **Outros** | Paleta de comandos (`Ctrl+Shift+P`), buscar e substituir (`Ctrl+F` / `Ctrl+H`), ir para linha (`Ctrl+G`), branch do git na barra de status, a sessão (pasta e abas) é restaurada ao abrir, recarrega arquivos alterados fora da IDE |

## Recursos de IDE avançada (v2)

Os recursos abaixo usam o servidor de linguagem (LSP) quando ele oferece, e a **análise própria** da IDE
quando não oferece. Por isso funcionam mesmo com servidores simples como o pylsp.

| Área | O que tem |
|---|---|
| **Inteligência semântica** | AST do Python em tempo real com **análise de fluxo de dados**: condição sempre verdadeira/falsa, laço infinito, código inalcançável, variável que pode chegar `None` (`dict.get`, `re.match`), arquivo aberto sem fechar, variável não usada. **Inlay hints** no meio da linha (tipos inferidos e nomes de parâmetros) sem alterar o texto. **Contadores de uso** ao lado de funções e classes |
| **Refatoração** | Renomear (`F2`, no projeto todo), **alterar assinatura** (`Ctrl+F6`: adiciona, remove e reordena parâmetros e atualiza todas as chamadas com valores padrão), extrair **variável** (`Ctrl+Alt+V`), **constante** (`Ctrl+Alt+C`) e **método** (`Ctrl+Alt+M`, descobre parâmetros e retorno), **exclusão segura** de símbolo (`Alt+Delete`) e de arquivo (procura referências em código, strings, comentários e configurações) |
| **Navegação** | **Search Everywhere** (`Shift` `Shift`): arquivos, classes, funções, ações e configurações. Encontrar usos (`Shift+F12`), ir para implementação (`Ctrl+Alt+B`) e definição do tipo (`Ctrl+Shift+B`), **hierarquia de chamadas** (`Ctrl+Alt+H`) e **de tipos** (`Ctrl+Alt+U`) com botão de inverter, ir para o teste correspondente (`Ctrl+Shift+T`, cria se não existir), voltar/avançar (`Alt+←/→`), estrutura do arquivo (`Ctrl+F12`) |
| **Histórico local** | Fotos automáticas ao abrir, salvar, executar, recarregar, excluir, refatorar e a cada 2 minutos de edição, independentes do git. Diff com a versão atual e restaurar (`Alt+Shift+H`). O histórico do projeto também recupera **arquivos excluídos** |
| **Depuração (Python)** | `Shift+F9` depura. Clique na lateral para breakpoint; botão direito para **condição** (`x > 500`) ou **logpoint** (registra `i={i}` sem pausar). Passo a passo (`F7`/`F8`/`Shift+F8`, `F9` continua), pilha, variáveis expansíveis, expressões observadas, **valores inline** no editor e **Avaliar expressão** no contexto pausado (`Alt+F8`), que pode até mudar variáveis |
| **Profiler** | `Ctrl+Alt+F5`: no Python, tempo por função (próprio e acumulado), pico de memória e linhas que mais alocam; nas outras linguagens, tempo, CPU e memória máxima do processo |
| **Git** | Marcadores de linha nova/alterada/removida na lateral, blame da linha atual no fim da linha e coluna de blame (`Ctrl+Alt+A`), diff com o HEAD (`Ctrl+Alt+D`), reverter para o HEAD, **conflitos de merge** realçados e resolvidos com um clique (aceitar atual, recebido ou os dois) |
| **Cliente HTTP** | Arquivos `.http` / `.rest`: `GET https://...`, cabeçalhos, corpo, `###` entre requisições e variáveis `@host = ...` / `{{host}}`. `F5` envia a requisição sob o cursor e mostra status, tempo, cabeçalhos e JSON formatado |
| **Intention actions** | `Alt+Enter`: ações do servidor (quick fixes, organizar imports, refatorações) e da IDE: `is None`, adicionar import, remover código morto, converter laço em list comprehension, if/else em expressão, `for` em `for...of`, concatenação em f-string/template string, gerar `__init__` e `__repr__`, resolver conflito |
| **Live templates** | Digite a abreviação e `Tab` (`main`, `fori`, `try`, `lc`, `class`, `iferr`, `psvm`, `html5`, `get`...). Campos navegáveis com `Tab`, espelhados, e variáveis `$CLASS$`, `$DATE$`, `$SELECTION$`. Templates próprios em `settings.json` (`"templates": {"python": {"pdb": "breakpoint()$0"}}`) |
| **Injeção de linguagem** | SQL, JSON, HTML e regex dentro de strings ganham o realce da linguagem de dentro |
| **Ambientes** | Python roda e depura com o `.venv` / `venv` do projeto, quando existir |

Ainda não tem: banco de dados embutido, Docker/SSH/WSL, merge de 3 vias em tela própria e depurador para
outras linguagens além de Python.

## Instalar

### Linux (Zorin, Ubuntu, Debian)

```bash
tar xzf ArasakaDaemon.tar.gz && cd ArasakaDaemon
```

```bash
./install.sh
```

### Windows 10/11

1. Extraia o `ArasakaDaemon.zip`.
2. Dê dois cliques em **`install.bat`**.

O instalador:
- instala o Python 3.12 pelo winget, se ainda não houver Python;
- cria os atalhos no Menu Iniciar e na Área de Trabalho;
- adiciona o comando `arasaka-daemon` ao PATH;
- adiciona **"Abrir no Arasaka Daemon"** no menu de botão direito das pastas.

### Nos dois sistemas

O instalador também instala o servidor do **Python** (pylsp). Para as outras linguagens, abra a aba
**LINGUAGENS** (`{ }` na barra lateral) e clique em INSTALAR. O comando roda no terminal integrado.

Para executar programas, a linguagem precisa estar instalada no computador (Python, Node, gcc, JDK
etc.). A aba LINGUAGENS mostra o que foi encontrado.

## Linha de comando

```bash
arasaka-daemon                 # restaura a ultima sessao
arasaka-daemon ~/meu-projeto   # abre a pasta
arasaka-daemon a.py b.ts       # abre arquivos
```

## Desinstalar

| Sistema | Comando |
|---|---|
| Linux | `./uninstall.sh` |
| Windows | `powershell -ExecutionPolicy Bypass -File uninstall.ps1` |

Nos dois casos as configurações são mantidas.

---

Arasaka é marca da CD PROJEKT RED, e a fonte cedge1 usa a licença FontStruct Non-Commercial. Este é
um projeto pessoal de fã, sem fins comerciais.
