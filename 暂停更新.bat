@echo off
REM 文件简介：停止自动更新——建一个 PAUSE 标记文件，run_daily.bat 看到它就直接退出。
chcp 65001 >nul
cd /d "%~dp0"
echo paused > "%~dp0PAUSE"
echo.
echo 已暂停每日更新，今晚 21:00 不会自动跑。
echo 恢复请双击「恢复更新.bat」
echo.
pause