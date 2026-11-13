@echo off
REM 文件简介：恢复自动更新——删掉 PAUSE 标记；删完要手动跑一次 run_daily.bat 才会立刻补更。
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0PAUSE" del "%~dp0PAUSE"
echo.
echo 已恢复每日更新，下一次 21:00 会自动跑。
echo.
pause