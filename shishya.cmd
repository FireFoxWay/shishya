@echo off
rem Shishya, in a terminal. Windows has no shebang, so this is the launcher:
rem put this folder on PATH and "shishya" works from any prompt.
setlocal
set PYTHONUTF8=1
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0shishya" %*
) else (
  python "%~dp0shishya" %*
)
exit /b %errorlevel%
