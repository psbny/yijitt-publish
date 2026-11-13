# tarot-pipeline

把一批 YouTube 塔罗/占星频道的更新，自动整理成**内容平台**后台的文章：下字幕 → 判类型 → 提时间戳 → 提交 AI 翻译成正文 → 配封面 → 定时发布。

一句话：**每天 21:00 自动跑一轮，第二天按时间表把文章排出去，再把结果报到 IM。**

## 它每天做什么

```
21:00 任务计划
  └─ run_daily.bat
       ├─ 有 PAUSE 文件？有就跳过
       ├─ 确保代理在跑（clash，7890）
       ├─ tarot-pipeline run --all
       │    阶段1  扫频道（RSS → 频道页 → /streams 兜底），落在窗口内的视频进候选
       │    阶段2  拿详情/章节/字幕，判类型，挑第 3 秒或章节里的截图，算费用
       │    阶段3  把 .srt 提交给平台 AI（扣能量币），拿到 task_id
       │    阶段4  等 AI 出稿（默认 25 分钟超时）
       │    阶段5  封面/价格/频道/定时发布（排到第二天）
       └─ tarot-pipeline report --push   生成日报并推IM 机器人
```

三类内容的价格与排期不同：**能量 0.29**（短、无时间戳、不截图）、**选组 0.59**（≤3 个选项时间戳、要截图）、**全星座 0.79**（12 星座时间戳、不截图）。具体规则全在 `rules.yaml` 与 `RULES.md`。

## 快速开始

```bat
cd /d <项目根>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.venv\Scripts\python.exe -m pip install --no-build-isolation -e .

copy config.example.yaml config.yaml
REM 然后改 config.yaml 里这四项：blogger_docx / cover_dir / clash_exe / clash_home
```

装完就有 `tarot-pipeline` 命令（也可以 `python -m tarot_pipeline`，不依赖安装）。

```bat
tarot-pipeline --help
tarot-pipeline run --dry-run --limit 3        REM 先干跑，不提交不花钱
tarot-pipeline report --print                 REM 看最近一轮的日报
```

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `tarot-pipeline run` | 全量扫描 + 处理，默认 **dry-run**（只打印，不提交） |
| `tarot-pipeline run --all` | 扫描+提交+等 AI+发布，**会扣能量币** |
| `tarot-pipeline run --commit` | 只提交，不排期（第二天再 `--publish-only`） |
| `tarot-pipeline run --publish-only` | 只把已提交的任务等出稿并排期 |
| `tarot-pipeline run --video <id>` | 只跑一条视频（调试用） |
| `tarot-pipeline run --blogger 麦肯齐` | 只跑某个博主 |
| `tarot-pipeline run --window-start "2026-11-01 00:00" --window-end "2026-11-08 23:59"` | 自定义回补窗口，补漏用 |
| `tarot-pipeline report --print` | 只打印日报，不推送 |
| `tarot-pipeline report --push` | 生成日报并推送到 `config.yaml` 里配的通道 |
| `tarot-pipeline adopt-orphans --hours 6 --date 2026-11-09` | 把最近 6 小时生成的裸草稿补封面/价格/排期 |
| `tarot-pipeline portcheck 7890` | 端口探测（开着 exit 0） |
| `tarot-pipeline ensure-proxy` | 确保 clash 在跑（就绪 exit 0） |

> ⚠️ `--all` **隐含 `--commit`**。只想看看会做什么，请单独用 `--dry-run`，不要加 `--all`。

## 目录结构

```
src/tarot_pipeline/
  cli.py            命令行入口（子命令分发）
  pipeline.py       主流程：五阶段、判定、状态机
  report.py         日报：解析 logs/daily.log + run-*.json，渲染/推送
  paths.py          所有"东西放哪儿"的唯一出处（支持 TAROT_HOME）
  feeds.py          频道发现：RSS → 频道页 → /streams 兜底
  youtube.py        yt-dlp 封装（详情/章节/字幕/截图/客户端切换）
  core.py           规则判定：类型、时长、星座、付费解读、Shorts
  chapterai.py      章节名 AI 正名（只认星座名，不生成时间戳）
  bloggers.py       读 jb.docx 的博主名单
  profiles.py       每个博主的历史画像（记忆票）
  rank.py           多视频博主按"最想点开"排序（带缓存）
  schedule.py       排期：价格、时段、发布日
  publish.py        后台写入：正文/封面/频道/定时，标题纠重
  backend.py         后台 API 客户端
  shots.py          选组截图（下片段 + 截帧）
  translate.py      标题清洗（默认不翻，交平台；可用谷歌直译）
  proxyctl.py       clash 起停 + 系统代理开关
  rules.py          rules.yaml 读取
  tools/            portcheck / ensure-proxy（给 bat 用）
scripts/            一次性/运维脚本（探针、导 cookie），不属于主流程
tests/              离线测试，不碰网络
```

运行时目录：`data/`（cookie、缓存、画像）、`logs/`（daily.log、run-*.json、日报）、`work/`（临时字幕、截图）、`封面/`（封面截图）。

## 状态文件

`state.json` 是"去重 + 重试"的全部记忆：

- `videos`：已处理过的视频（提交/发布/重复/失败），下次不再当候选。
- `pending`：已提交但还没出稿的任务（task_id、标题、费用）。
- `waiting`：**留着以后重试**的条目，`status` 有五种：
  | status | 含义 | 多久后放弃 |
  | --- | --- | --- |
  | `no_subs` | 这条视频没有字幕（以后可能补） | 20 天 |
  | `hold` | 全星座章节/时间戳不齐 | 3 天 |
  | `live_future` | 直播预告/首映，还没开始 | 到 `expect_at` 才试 |
  | `live_gone` | 直播结束了但还取不到回放 | 3 天 |
  | `live_wait` | 之前在直播中，等回放 | 20 天 |

## 每天自动跑

Windows 任务计划里那条 **内容自动发布每日更新**，21:00 调 `run_daily.bat`：

- 只在存在 `PAUSE` 文件时跳过（双击 `暂停更新.bat` / `恢复更新.bat` 切换）。
- 日志写在 `logs\daily.log`，每次以 `===== 任务启动` 开头、`===== 结束` 收尾。
- 跑完自动推日报；日报也会存成 `logs\report-latest.txt`。
- `run_daily.bat` 里 python 必须走绝对路径（PATH 里的 `python` 只是个 `.cmd` 垫片，不带 `call` 调用会让 bat 不返回）。

## 排错先看三处

1. `logs\daily.log` 最后一段——这次的阶段日志和报错都在里面。
2. `logs\run-*.json`——每条候选的 `status` / `reason`（`skip`、`no_subs`、`error`、`hold`…）。
3. `tarot-pipeline report --print`——把上面两样汇总成人话。

常见原因：代理没起来（整轮会判"窗口内无新视频"）、cookie 过期（日志出现 `Sign in to confirm you're not a bot`）、yt-dlp 版本旧（`pip install -U yt-dlp`）、平台 AI 额度不足（会退款并自动 `PAUSE`）。

## 安全

`config.yaml`（含IM 机器人 webhook）、`cookies.json`、`state.json`、`data/`、`logs/`、`封面/` 都**不进仓库**（见 `.gitignore`）。要分享配置，用 `config.example.yaml`。

## 开跑前自检（cookie）

每天开跑、开始扫描之前，会先用 `config.yaml` 里 `preflight.cookie_video_ids` 列的视频探一次详情（约 5–10 秒）：

- 能拿到详情 → 正常，继续跑
- 报 `Sign in to confirm your age / you're not a bot` → 说明 YouTube cookie 失效，**推一条IM 机器人提醒**，然后照常继续
- 报网络错误或视频被删 → 不报警（避免狼来了）

cookie 失效只能人工修：在 waimian 的 Chrome 里重新登录 YouTube，再跑 `scripts\export_cookies.py`。

## 本地版本记录（git）

项目是个本地 git 仓库（没有远端，代码不出本机）。每天跑完会由 `scripts\git_snapshot.py` 自动提交一次，提交信息形如 `每日运行 2026-11-11 22:06（2 个文件）`。

```bash
git log --oneline -10        # 看最近改了哪些
git diff HEAD~1              # 看上次改了什么
git checkout -- src/tarot_pipeline/report.py   # 撤销某个文件的改动
git reset --hard HEAD~1      # 整体回滚到上一次提交（慎用）
```

`config.yaml` / `state.json` / `cookies.json` / `data/` / `logs/` / `封面/` 都在 `.gitignore` 里，不会被提交。

## 更细的规则

运营规则、踩过的坑、为什么这么判，全在 `RULES.md`（很长，按主题分节）。改动前先看对应小节，别只看代码。
