@echo off
rem ARASAKA DAEMON // instalador Windows (duplo clique)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
