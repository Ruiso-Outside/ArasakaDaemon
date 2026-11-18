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
