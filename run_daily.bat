@echo off
REM 文件简介：每天 21:00 由 Windows 任务计划调用的入口——确保代理就绪，跑 tarot-pipeline run --all，最后推日报。
REM 2026-11-07 四处修：
REM  ①判断/启动代理不再用 netstat|findstr 管道（那天它卡死，整晚没跑），改为 tools\ensure_proxy.py；
REM  ②python 必须走绝对路径——PATH 里的 python 只是 .cmd 垫片，不带 call 调 .cmd 时 bat 不返回，后面步骤全丢；
REM  ③解释器改指项目内 .venv（Agent 环境 公共运行库没有 requests/yt-dlp，被它坑过一次全员 0 候选）；
REM  ④起 clash 交给 ensure_proxy.py（DETACHED_PROCESS + 轮询端口），比自己 start /min 稳。
chcp 65001 >nul
cd /d "%~dp0"
set PYEXE=%~dp0.venv\Scripts\python.exe
REM src 先上 PYTHONPATH：即使哪天忘了 pip install -e .，-m tarot_pipeline 也能跑
set PYTHONPATH=%~dp0src
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=%~dp0logs\daily.log

echo [%date% %time%] ===== 任务启动 ===== >> "%LOG%"

if exist "%~dp0PAUSE" (
  echo [%date% %time%] 检测到 PAUSE 文件，跳过本次更新 >> "%LOG%"
  exit /b 0
)

if not exist "%PYEXE%" (
  echo [%date% %time%] 找不到 %PYEXE%，先建 .venv 再跑 >> "%LOG%"
  exit /b 3
)

"%PYEXE%" -m tarot_pipeline ensure-proxy >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] 代理没起来，放弃本次更新 >> "%LOG%"
  exit /b 2
)

echo [%date% %time%] ===== 开始每日更新 ===== >> "%LOG%"
"%PYEXE%" -m tarot_pipeline run --all >> "%LOG%" 2>&1
set RC=%errorlevel%
REM 跑完渲染日报并按 config.yaml 的 report.targets 推送IM（没配通道就只写文件）
"%PYEXE%" -m tarot_pipeline report --push >> "%LOG%" 2>&1
set RCR=%errorlevel%
REM 本地 git 记一笔（有改动才提交；不联网、不推送）
"%PYEXE%" "%~dp0scripts\git_snapshot.py" >> "%LOG%" 2>&1
echo [%date% %time%] ===== 结束 主流程退出码=%RC% 日报退出码=%RCR% ===== >> "%LOG%"
