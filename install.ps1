# ============================================================
#   ARASAKA DAEMON // instalador Windows
#   Uso:  clique duas vezes em install.bat
#         (ou: powershell -ExecutionPolicy Bypass -File install.ps1 [-SemLsp] [-SemMenuContexto])
# ============================================================
param([switch]$SemLsp, [switch]$SemMenuContexto)
$ErrorActionPreference = 'Stop'
$App  = 'arasaka-daemon'
$Dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $env:LOCALAPPDATA $App
$Bin  = Join-Path $Data 'bin'

function Step($t) { Write-Host ""; Write-Host "[$script:n] $t" -ForegroundColor Red; $script:n++ }
function Ok($t)   { Write-Host "     ■ $t" -ForegroundColor Gray }
function Warn($t) { Write-Host "     !! $t" -ForegroundColor Yellow }
$script:n = 1

Write-Host ""
Write-Host "   A R A S A K A   D A E M O N" -ForegroundColor Red
Write-Host "   IDE para Linux e Windows" -ForegroundColor DarkGray

if (-not (Test-Path (Join-Path $Dir 'arasaka_daemon\app.py'))) { throw "Arquivos do app nao encontrados em $Dir" }

Step "Python"
$py = $null
foreach ($c in @('py', 'python', 'python3')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $py = $cmd.Source; break }
}
if (-not $py) {
    Warn "Python nao encontrado. Instalando com winget..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $py = (Get-Command py -ErrorAction SilentlyContinue).Source
    if (-not $py) { throw "Instale o Python 3.9+ (python.org) e rode de novo." }
}
$ver = & $py -c "import sys; print('%d.%d' % sys.version_info[:2])"
Ok "Python $ver ($py)"

Step "Ambiente Python (PySide6 / Qt 6)"
New-Item -ItemType Directory -Force -Path $Data, $Bin | Out-Null
$vpy = Join-Path $Data 'venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) { & $py -m venv (Join-Path $Data 'venv') }
& $vpy -m pip install -q --upgrade pip 2>$null | Out-Null
Write-Host "     › baixando PySide6 (~120 MB na primeira vez)..."
& $vpy -m pip install -q --upgrade "PySide6-Essentials>=6.5"
if ($LASTEXITCODE -ne 0) { throw "falha ao instalar PySide6" }
Ok ("PySide6 " + (& $vpy -c "import PySide6; print(PySide6.__version__)"))

if (-not $SemLsp) {
    Step "Servidor de linguagem do Python (pylsp)"
    if (Get-Command pylsp -ErrorAction SilentlyContinue) { Ok "pylsp ja disponivel" }
    else {
        & $vpy -m pip install -q "python-lsp-server[pyflakes]"
        if ($LASTEXITCODE -eq 0) {
            Set-Content -Encoding ASCII -Path (Join-Path $Bin 'pylsp.cmd') -Value "@echo off`r`n`"$Data\venv\Scripts\pylsp.exe`" %*"
            Ok "pylsp instalado"
        } else { Warn "falhou: instale depois pela aba LINGUAGENS" }
    }
}

Step "Arquivos do app"
$appDir = Join-Path $Data 'app'
if (Test-Path $appDir) { Remove-Item -Recurse -Force $appDir }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Copy-Item -Recurse (Join-Path $Dir 'arasaka_daemon') $appDir
Get-ChildItem -Recurse -Directory -Filter '__pycache__' $appDir | Remove-Item -Recurse -Force
$pyw = Join-Path $Data 'venv\Scripts\pythonw.exe'
# lancador: acha o pacote e poe a pasta bin (pylsp.cmd) no PATH, de qualquer diretorio
$launch = Join-Path $Data 'launch.pyw'
Set-Content -Encoding UTF8 -Path $launch -Value @"
import os, sys
sys.path.insert(0, r"$appDir")
os.environ["PATH"] = r"$Bin" + os.pathsep + os.environ.get("PATH", "")
from arasaka_daemon.__main__ import main
sys.exit(main())
"@
Set-Content -Encoding ASCII -Path (Join-Path $Bin "$App.cmd") -Value "@echo off`r`nstart `"`" `"$pyw`" `"$launch`" %*"

# icone .ico gerado a partir do SVG
$ico = Join-Path $Data "$App.ico"
& $vpy -c "import sys; from PySide6.QtGui import QGuiApplication, QIcon; a=QGuiApplication(sys.argv); QIcon(sys.argv[1]).pixmap(256,256).save(sys.argv[2])" (Join-Path $appDir 'arasaka_daemon\assets\arasaka-daemon.svg') $ico 2>$null

# PATH do usuario
$up = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ($up -split ';' | Where-Object { $_ -eq $Bin })) {
    [Environment]::SetEnvironmentVariable('Path', ($up.TrimEnd(';') + ';' + $Bin), 'User')
    Ok "comando 'arasaka-daemon' adicionado ao PATH (abra um novo terminal)"
}

# atalhos
$ws = New-Object -ComObject WScript.Shell
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Arasaka Daemon.lnk'
$desk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Arasaka Daemon.lnk'
foreach ($lnk in @($menu, $desk)) {
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = $pyw
    $s.Arguments = "`"$launch`""
    $s.WorkingDirectory = $env:USERPROFILE
    if (Test-Path $ico) { $s.IconLocation = $ico }
    $s.Description = 'Arasaka Daemon - IDE'
    $s.Save()
}
Ok "atalhos no Menu Iniciar e na Area de Trabalho"

if (-not $SemMenuContexto) {
    $cmdline = "`"$pyw`" `"$launch`" `"%V`""
    foreach ($key in @('HKCU:\Software\Classes\Directory\shell\ArasakaDaemon',
                       'HKCU:\Software\Classes\Directory\Background\shell\ArasakaDaemon')) {
        New-Item -Force -Path "$key\command" | Out-Null
        Set-ItemProperty -Path $key -Name '(default)' -Value 'Abrir no Arasaka Daemon'
        if (Test-Path $ico) { Set-ItemProperty -Path $key -Name 'Icon' -Value $ico }
        Set-ItemProperty -Path "$key\command" -Name '(default)' -Value $cmdline
    }
    Ok "menu de contexto 'Abrir no Arasaka Daemon' nas pastas"
}

Write-Host ""
Write-Host " ■ INSTALACAO CONCLUIDA" -ForegroundColor Red
Write-Host "   Abra 'Arasaka Daemon' no Menu Iniciar. Na aba LINGUAGENS instale as outras linguagens."
Write-Host ""
