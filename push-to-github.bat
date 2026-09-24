@echo off
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------------
rem  Pure ASCII on purpose: Chinese characters inside a .bat file break
rem  cmd.exe when the console code page is not UTF-8. The Chinese guide is
rem  read from next-steps.zh.txt by PowerShell instead.
rem ---------------------------------------------------------------------

set "REPOURL=%~1"
if not "%REPOURL%"=="" goto :haveurl

echo.
echo ============================================================
echo   First create an EMPTY repository on GitHub:
echo.
echo     1. Open  https://github.com/new
echo     2. Name: energy-rss        Visibility: Public
echo     3. Do NOT tick "Add a README file"
echo     4. Click Create repository, then copy the URL it shows
echo ============================================================
echo.
set /p "REPOURL=Paste the repository URL here, then press Enter: "

:haveurl
if "%REPOURL%"=="" goto :nourl

where git >nul 2>nul
if errorlevel 1 goto :nogit

echo.
echo [prep] trust this folder, so git stops complaining about ownership
set "SAFEDIR=%~dp0"
set "SAFEDIR=%SAFEDIR:~0,-1%"
set "SAFEDIR=%SAFEDIR:\=/%"
git config --global --add safe.directory "%SAFEDIR%" >nul 2>nul

echo.
echo [1/6] git init
if exist ".git" (
  echo       already a git repository, skipping
) else (
  git init -b main
)
if not exist ".git" goto :fail

echo [2/6] make sure git knows who you are
git config user.name >nul 2>nul
if errorlevel 1 git config user.name "energy-rss"
git config user.email >nul 2>nul
if errorlevel 1 git config user.email "energy-rss@users.noreply.github.com"

echo [3/6] git add .
git add .
if errorlevel 1 goto :fail

echo [4/6] git commit
git commit -m "init energy-rss feeds"
if errorlevel 1 echo       nothing new to commit

echo [5/6] set origin to %REPOURL%
git remote remove origin >nul 2>nul
git remote add origin "%REPOURL%"
if errorlevel 1 goto :fail
git branch -M main

echo [6/6] git push -u origin main
echo.
git push -u origin main
if errorlevel 1 goto :pushfail

echo.
echo PUSH OK
call :guide
pause
exit /b 0

:guide
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath 'next-steps.zh.txt' -Encoding UTF8 | ForEach-Object { Write-Host $_ }"
if errorlevel 1 echo (Could not display next-steps.zh.txt. Open it in Notepad instead.)
goto :eof

:nourl
echo.
echo [ERROR] No repository URL was given, so there is nothing to do.
pause
exit /b 1

:nogit
echo.
echo [ERROR] git was not found on this computer.
echo         Install Git for Windows first: https://git-scm.com/download/win
pause
exit /b 1

:fail
echo.
echo [ERROR] A git step failed. Read the messages above.
pause
exit /b 1

:pushfail
echo.
echo [ERROR] Push failed. Usual causes:
echo         - the URL is wrong, or the repository does not exist yet
echo         - you closed the GitHub login window without signing in
echo         - the remote repository already has commits
echo           fix: git pull --rebase origin main    then run this again
echo.
echo         You can also copy the exact git commands from README.md
echo         and run them by hand in this folder.
pause
exit /b 1
