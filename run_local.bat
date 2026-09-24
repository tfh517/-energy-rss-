@echo off
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------------
rem  This file is deliberately pure ASCII. Chinese text inside a .bat file
rem  breaks cmd.exe when the console code page is not UTF-8, so all Chinese
rem  messages live in Python and in the .txt / .md files instead.
rem ---------------------------------------------------------------------

set "PYEXE="
call :trypy py -3
call :trypy "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :trypy "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :trypy "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
call :trypy "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
call :trypy "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
call :trypy "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not defined PYEXE goto :nopython

echo Interpreter: %PYEXE%
echo.
%PYEXE% build.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo Done. Generated files are in the docs\ folder.
if not "%RC%"=="0" echo Some sources failed. Read the log above.
echo.
pause
exit /b %RC%

:trypy
if defined PYEXE goto :eof
%~1 %2 --version >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%*"
goto :eof

:nopython
echo [ERROR] No usable Python found on this computer.
echo.
echo   Checked:  py -3  and  %%LOCALAPPDATA%%\Programs\Python\Python3xx\
echo.
echo   Fix: install Python 3.10 or newer from
echo        https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup.
echo.
echo   Your existing installs (if any) live under:
echo        %LOCALAPPDATA%\Programs\Python\
echo.
echo   If Python is already installed there but still not detected,
echo   run this once in a normal Command Prompt:
echo        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -m ensurepip
echo.
pause
exit /b 1
