"""
ARASAKA DAEMON // ponto de entrada.

  arasaka-daemon                 abre a IDE (restaura a ultima sessao)
  arasaka-daemon PASTA           abre a pasta como projeto
  arasaka-daemon ARQUIVO...      abre arquivos
"""
import sys


def main() -> int:
    if sys.argv[1:2] in (["--version"], ["-v"]):
        from .app import APP_NAME, VERSION
        print(f"{APP_NAME} {VERSION}")
        return 0
    from .app import main as gui
    return gui(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
