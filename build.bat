@echo off
cd /d "%~dp0"
set TEMP=%CD%\.tmp
set TMP=%TEMP%
if not exist .tmp mkdir .tmp
if not exist assets\app.ico .venv\Scripts\python.exe -m tools.make_icon
.venv\Scripts\python.exe -m PyInstaller --noconfirm package.spec
if errorlevel 1 exit /b 1
copy /y README.md dist\WeChatFileManager\README.md >nul
copy /y LICENSE dist\WeChatFileManager\LICENSE >nul
echo Build complete: dist\WeChatFileManager\WeChatFileManager.exe
