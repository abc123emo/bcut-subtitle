@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   bcut_subtitle - Windows exe 打包脚本
echo ============================================
echo.

echo [1/4] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+ 并勾选 "Add python.exe to PATH"
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

echo.
echo [2/4] 安装 PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败，请检查网络
    pause
    exit /b 1
)

echo.
echo [3/4] 打包 GUI 版（无控制台，双击用）...
python -m PyInstaller --clean --noconfirm --onefile --windowed --icon app.ico --name bcut_subtitle bcut_subtitle.py
if errorlevel 1 (
    echo [错误] GUI 版打包失败
    pause
    exit /b 1
)

echo.
echo [4/4] 打包 CLI 版（带控制台，命令行用）...
python -m PyInstaller --clean --noconfirm --onefile --icon app.ico --name bcut_subtitle_cli bcut_subtitle.py
if errorlevel 1 (
    echo [错误] CLI 版打包失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   GUI 版: dist\bcut_subtitle.exe   （双击打开图形界面）
echo   CLI 版: dist\bcut_subtitle_cli.exe（命令行/拖拽批量）
echo.
echo   提示: 如需识别"视频"文件，请把 ffmpeg.exe
echo         放到 dist\ 目录下（与 exe 同级）。
echo         音频(mp3/wav/m4a/flac/aac)无需 ffmpeg。
echo ============================================
pause
