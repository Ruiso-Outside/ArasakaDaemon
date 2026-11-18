# ARASAKA DAEMON // desinstalador Windows
# powershell -ExecutionPolicy Bypass -File uninstall.ps1
$App  = 'arasaka-daemon'
$Data = Join-Path $env:LOCALAPPDATA $App
$Bin  = Join-Path $Data 'bin'
foreach ($l in @((Join-Path ([Environment]::GetFolderPath('Programs')) 'Arasaka Daemon.lnk'),
                 (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Arasaka Daemon.lnk'))) {
    if (Test-Path $l) { Remove-Item -Force $l }
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'HKCU:\Software\Classes\Directory\shell\ArasakaDaemon',
    'HKCU:\Software\Classes\Directory\Background\shell\ArasakaDaemon'
$up = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', (($up -split ';' | Where-Object { $_ -and $_ -ne $Bin }) -join ';'), 'User')
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Data
Write-Host " ■ ARASAKA DAEMON REMOVIDO (configuracoes em %APPDATA%\arasaka-daemon foram mantidas)" -ForegroundColor Red
