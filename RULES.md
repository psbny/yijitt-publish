# 说明：代码布局变更（2026-11-09）

> 本文写于改造前，里面提到的 lib/xxx.py、pipeline.py、
eport.py、	ools/xxx.py
> 现在都在 src/tarot_pipeline/ 下（lib/ → 包内平铺，	ools/ → src/tarot_pipeline/tools/），
> 入口统一成命令 	arot-pipeline（
un / 
eport / dopt-orphans / portcheck / ensure-proxy）。
> 规则、数字、坑的内容没有变，只把怎么调用换成了新写法；看到 python pipeline.py ...
> 就等价于 	arot-pipeline run ...。项目结构与分层见 README.md / ARCHITECTURE.md。

# 运营规则（用户口述，已落地到代码）

> 这份文件是"用户到底要什么"的唯一权威来源。以后换会话、换人接手，先读这个，
> 再看 `README.md`（怎么跑）和代码注释（踩过的坑）。
> 规则来源：m00368 / m01172 / m02671 / m02740 / m02970 / m03475 / m03587 等。

> 本文只讲**规则和原因**。所有可调数字（价格、时段、时长上限、窗口小时、每博主条数、发布日偏移）都在 **`rules.yaml`**，改规则改那个文件，改完不用改代码。

## 1. 项目做什么

把 YouTube 上 80 多个星座/塔罗博主的更新，每天自动搬进内容平台后台：
下字幕 → 判类型 → 提时间戳 → 交给平台 AI 翻成中文文章 → 补封面/价格/频道/定时发布。

博主清单在 `C:\path\to\jb.docx`，每行格式 `【中文名】名字 https://www.youtube.com/@handle/...`。

## 2. 三类内容

| 类型 | 时长 | 时间戳 | 价格 | 封面 |
|---|---|---|---|---|
| 能量 | 短（≤30 分钟才更） | 简介/评论里一般没有 | ¥0.29 | 用屏幕快照目录里的现成图 |
| 选组 | 中等 | ≤3 个选项 | ¥0.59 | 先找屏幕快照目录，找不到才截图（见第 6 节） |
| 全星座 | 长（<4 小时才更） | 12 个星座 | ¥0.79 | 用屏幕快照目录里的现成图 |

**判断顺序**（`lib/core.py` 的 `classify`）：
1. 章节里有 `Opção 1 / Option 2 / 选项一 / Pile 1` 这类 → **选组**（硬证据，压过标题）
2. 标题有 `All Signs / 全星座` → 全星座
3. 标题有 `互动塔罗 / 选一组 / Pick a / 选一颗` → 选组
4. 章节命中 ≥10 个星座 → 全星座
5. 都不符合 → 能量
6. 还判不出，用记忆库 `data\profiles.json` 里该博主的历史主类型兜底

> 有时间戳不等于全星座——全星座要看标题有没有 "all sign" 字样（m03033 第 4 点）。
> 以前按"时间戳条数"判类型的老逻辑已废除（m03155 第 1 条）。

## 3. 时间窗口

每天更新**前一天 21:00 到当天 21:00** 这 24 小时内的视频（`lib/feeds.py` 的 `daily_window`）。
窗口是固定的 24 小时，不随开跑时刻滑动。拖过一整天再恢复，中间那天就永久漏掉了。

## 4. 每博主取几条

每个博主取前 3 条（`max_videos_per_channel: 3`）。
> 用户要的是"按标题精彩程度取前 3"（m02671 ①），**已实现**：窗口内新视频超过 3 条时调用 `rank.py` 的模型排序（m07729 起走 `llm.providers` 本机网关链）（`pipeline.py:125`，结果缓存在 `data\rank-cache.json`），不足 3 条就按原顺序。
不设总量上限（`max_videos_per_run: 999`）。

## 5. 排期

- 发布日一律是**次日**（今天 11/6 跑，排 11/7）
- 能量和选组：`08:05、09:05 … 23:05`，铺满一轮后从 `08:10、09:10 …` 再来一轮，每轮 +5 分钟
- 全星座：优先 `09:15、14:15、21:15`，用完接 `16:15、19:15`；全星座只用这 5 个点
- 已经占用的时段要避开（读后台文章列表算占用）

## 6. 选组截图（封面）

规则（m02970 + m03474）：

1. 章节里**明写**展示选项的时间（含"展示/显示/showing/display"）→ 截那个时间点
2. 没写 → 截**视频第 5 秒**
3. 两种本质是同一件事（东西还在桌上），只是有的展示很短必须靠时间戳定位

截图只存 `work\shots\`，开工前统一清理，**不动** 封面目录（原 `C:\path\to\封面`，2026-11-08 已随项目搬到 `<项目根>\封面`，m03475）。

## 7. 字幕来源

- 能量：绝大多数来自普通视频
- 选组：视频
- 全星座：少量视频，**大部分来自直播回放**（回放的字幕生成慢，取决于 YouTube）

## 8. 更新标准

- 能量超过 30 分钟不更；全星座超过 4 小时不更（数字在 `rules.yaml:21`，m04708 由 40 改成 30）
- 同一条只更一次（靠 `state.json` + 服务端 MD5 去重）
- 标题和章节都没信号时，默认按**能量**处理（`classify` 末尾 return TYPE_ENERGY）；不再有"判不出就跳过"的分支

## 9. 标题

- 格式：`【中文名】+（全星座/选组才有的）【类型】+ 中文标题`；能量类只有 `【中文名】+标题`
- 标题默认不翻，交平台（`translate.use_google` 可开谷歌直译；模型翻译走 `llm` 网关链，m07729 起 旧模型通道已下线）
- 如果 AI 翻译出来的标题开头又带了博主名（`[约瑟夫]...`），要剥掉再拼 `【中文名】`

## 10. 后台操作

每个视频在创作者中心操作一次，三个字段：

1. **标题**：翻译后的中文标题（自动生成）
2. **时间戳**：填在 `/subtitle/submit` 的"章节分段"框里，格式
   - 选组：`选项1 🪶 羽毛 — 00:03:00`
   - 全星座：`白羊座 — 00:02:11`（12 行）
   - 能量：留空
3. **字幕**：上传 srt 文件

## 11. 平台 AI 失败怎么处理

| 现象 | 性质 | 处理 |
|---|---|---|
| 400 `context deadline exceeded` | 假失败（任务其实建了） | 用 file_hash 反查 aitask 接上，不重复花钱 |
| 422 `文件已提交过` | 重复提交 | 接上已有任务 |
| 502 / 503 | 平台网关/数据库抖动 | 节流 + 退避重试（`submit_interval: 25` 秒，重试 3 次） |
| pending 卡死 25 分钟 | 钱照扣不退 | 记 `ai_incomplete`，**不暂停** |
| `处理失败 + 退款`（pay_status=3） | **平台额度不足** | **只有这一种要暂停更新**（m03277） |

暂停时：关代理、建 `PAUSE`、写 `ALERT.md`、桌面放 `已暂停-看这里.txt`。
恢复：确认额度到账 → 双击 `恢复更新.bat` → 手动跑一次 `run_daily.bat` 补。

## 12. 存储与清理（m03587）

- 中间文件全在 `work\`（字幕、截图、视频片段），**开工前整个清空**，不是跑完就删
- 日志保留 30 天（`log_keep_days`）
- **不能删**：`state.json`（去重）、`data\profiles.json`（记忆）、`cookies.json`（登录态）

## 13. 已知限制

- 后台**没有删除接口**，发错的文章只能作废（visibility=0 + published_on=0 + 标题加【作废】）
- 后台没建频道的博主，文章显示"未分类"，不影响发布（香奈儿、水瓶座、阿米莉亚等）
- `cookies.json` 会过期，重导方式：ego 浏览器登录后台 → `node fetch_cookie.mjs`
- YouTube 反爬：短时间请求量大会被挡（几十分钟自愈），所以有节流
- 截图依赖 `C:\tools\bin\ffmpeg.exe`（曾丢过一次，用 `imageio-ffmpeg` 恢复）

## 14. 运行环境依赖（缺一样就静默失败）

这一节不是操作步骤（步骤在 README），只记「依赖什么、缺了会怎样」。

| 依赖 | 位置 / 值 | 缺了会怎样 |
|---|---|---|
| clash.meta 便携版 | `C:\tools\clash\clash.exe` | 抓不到 YouTube，阶段1 直接 0 候选 |
| 可用的 clash 配置目录 | `C:\tools\clash\config`（原 `clash.meta\config.yaml` 有 7 处重复 key，起不来，所以另建了一份） | clash 启动即退出 |
| 代理端口 | `127.0.0.1:7890`（mixed） | 同上 |
| 系统代理开关 | `ProxyEnable` 必须与 clash 同步 | **关 clash 不归零 → 系统代理指向空端口，整机断网** |
| deno | `C:\tools\bin\deno.exe` | yt-dlp 解 YouTube 播放器 JS 挑战（n-sig）；缺了会报 `n challenge solving failed` + `Requested format is not available`，拿不到格式也就截不了选组图 |
| YouTube 登录 cookie | `data\yt-cookies.txt`（`tools_export_cookies.py` 从 waimian Chrome 导出） | 数据中心 IP 不登录会被 `Sign in to confirm you're not a bot` 挡；缺了会大面积取详情失败 |
| ffmpeg | `C:\tools\bin\ffmpeg.exe`（+ ffprobe） | 选组截图**静默返回空**，不报错（曾丢过一次，用 `imageio-ffmpeg` 恢复） |
| 本机网关 | `127.0.0.1:3425` 不走 7890 | 本机调用被塞进代理会超时（`llm.chat` 固定 `proxies=None`） |
| 平台登录态 | `cookies.json`（session_id 160 字符） | 提交全部 401/400 |

**起停责任划分**：

- **启动**：`run_daily.bat` 负责。`netstat` 查 7890 → `start /min ... -d clash.meta.auto` → `ping -n 11`（**不能用 `timeout`，任务计划无控制台会直接报错跳过**）→ 再查一次，起不来 `exit /b 2`
- **停止**：`pipeline.py` 负责。提交阶段一结束就 `proxyctl.stop()`（`proxy_auto_stop: true`），`main()` 的 `finally` 再兜底一次
- **避免破坏**：任何停 clash 的路径都必须同时把 `ProxyEnable` 归零

**已知的出口 IP 问题**：

- `youtube.com/feeds/videos.xml`（RSS）对当前出口 IP（62.210.124.132，法国节点）返回 404，**不是端点下线**——同一 URL 由第三方服务器抓取返回 200 且数据完整
- 现已降级：RSS → 频道 `/videos` 页面解析（`6d ago` / `3 hours ago`）→ flat 列表，三级兜底
- 代价：发布时间精度从「精确时间戳」降到「小时级」，判定窗口留 ±6 小时容差
- 换节点拿到不同出口 IP 后 RSS 可能自动恢复，代码会优先用 RSS

## 15. 取数策略（为什么这么抓，别改回去）

上一节记"缺什么会坏"，这一节记"为什么这样选"。**机制写在代码里，这里只记决策和理由**——
因为下面每一条都是踩过坑换来的，只看代码会觉得"多此一举"，删掉就会原样再坏一次。

| 决策 | 为什么 | 不要做什么 |
|---|---|---|
| 有登录 cookie 就用默认客户端 | 数据中心 IP 匿名访问会被 `Sign in to confirm you're not a bot` 挡，2026-11-06 实测 73 条候选**全被挡** | 别为了"少依赖"把 cookie 去掉退回匿名抓取 |
| 没有 cookie 才用 `player_client=android` | android 能绕过一部分 bot 校验，但它**不支持 cookie**；两者同时给会被 yt-dlp 直接跳过 android | 别把 android 当主力——它拿不到登录态，量一大就废 |
| 必须装 deno 并允许 `--remote-components ejs:github` | 拿不到格式就**截不了选组图**（选组截图要下视频片段），且格式缺失时字幕接口也更容易 429 | 别把 `--remote-components` 当可选优化删掉，也别禁 yt-dlp 联网下载挑战脚本 |
| 字幕 429 只退避、不并发猛冲 | 同一出口 IP 短时间请求多了就被限流；实测退避 45s/90s 后能恢复 | 别把重试改成"立刻重试"，也别靠加并发解决 |
| 频道扫描并发 **4**（原 6） | 6 路时扫到第 80 个频道就开始出现 bot 拦；降并发是最便宜的缓解 | 别为了快把并发调回 6 以上 |
| RSS → 页面解析 → flat 列表 三级兜底 | RSS 被出口 IP 挡（404），页面解析能拿到"6 天前"这种相对时间 | 别看到 RSS 404 就以为"YouTube 关了 RSS"而删掉整条链路 |
| cookie 从 CDP 导，不读磁盘库 | Chrome 运行中会锁 `Network\Cookies`，直接读报 `WinError 32` | 别写"先关浏览器再复制文件"的流程，用户浏览器一直开着 |
| 取详情失败不写进 `state.videos` | 这样下一轮会自动重试，漏一条不会变成永久遗漏 | 别把失败也标记成"已处理"，那等于永久漏更 |

**维护事件（不是故障）**：

- **cookie 过期**：症状是日志重新出现 `Sign in to confirm you're not a bot` 或大面积取详情失败。
  处理：确认 waimian 那个 Chrome 开着且 YouTube 还是登录状态，跑 `python tools_export_cookies.py`，无需改代码。
- **deno / ffmpeg 失踪**：这两个都在 `C:\tools\bin`，属于外部目录，可能被别的操作清掉。
  症状分别是"拿不到格式"和"选组封面静默为空"（后者**不报错**，只看日志看不出来）。

### 15.2 推理模型一律 max_tokens >= 4000

`rank.py` 和章节筛选调的是推理型模型（原先是 旧模型通道 k3 系列，m07729 起改成 `llm.providers` 本机网关链），它可能先写思考链再写正文。
思考链实测能到 2500 字，`max_tokens` 给小了会出现"finish_reason=length、正文为空"，
表现为 `[翻译降级]` 或 `[排序降级] 模型没给出可用序号：''`。

- 两个文件都设 `max_tokens: 4000`，**改小必炸**（m02865 在 translate 上踩过，m04196 在 rank 上重犯一次）。
- 排序只送前 12 条（`_CAP = 12`）：15 条要 34 秒，12 条 20 秒，尾部原顺序补回。

### 15.3 取详情要"快路径优先"

带 cookie 必须走 web 客户端 + deno 解 JS 挑战，**20 秒/条**；不带 cookie 的 android 只要 **7 秒/条**。
所以 `lib/youtube.py` 的 `_run_smart()` 先跑 android，只有报 `Sign in / not a bot / Requested format / 429`
才带 cookie 重试。2026-11-06 实测：详情 6.9 秒/条、字幕 14.7 秒、评论时间戳 13.5 秒。

### 15.4 一条视频只取一次详情

扫描阶段（阶段1）只用 RSS/页面给的**标题**做初筛，不调 yt-dlp；真实时长、类型、字幕都留给阶段2 的
`process_one` 一次拿到。之前两边各取一次，同一条视频白跑两遍 7 秒，81 个频道要 448 秒。
2026-11-06 改完实测：扫描 **56.9 秒**（448 → 57），单测 23 个用例 0 failed。

改动要点：`scan_one_channel` 的 window 分支建 `yt.Video(video_id, title, duration=None)` 的 stub，
并置 `res["prefiltered"]=True`；阶段1 末尾的过滤循环遇到该标记就跳过（否则 `duration=None` 会被当成
"时长 0/Shorts"全部丢掉——踩过一次，0 条候选）。

`lib/rank.py` 另加了缓存 `data/rank-cache.json`（key = 频道名 + 视频 id 集合），同一批视频只问一次模型：
实测 15.3 秒 → 0.00 秒。缓存文件可以随时删，删了只是重新问一次模型。

**排序只在"该博主窗口内新视频超过 3 条"时才调用**（`if len(ents) > per`），101 个频道里通常只有几个。
2026-11-06 那次 81 频道扫描里只调了 7 次。所以排序不是扫描慢的主因，别为了省它去改别的。

### 15.5 选组：截图 3 秒、丢掉"首页"、要凑满 3 个选项

m04326 用户实测两条反馈，已改：

1. **截图默认第 3 秒**（原来 5 秒）。5 秒有的视频已经切画面/开始讲话了。
   `lib/shots.py` 的 `DEFAULT_SECOND = 3`、`lib/youtube.py` 的 `grab_frame(sec=3.0)`。
   时间戳里写了展示时间仍按它给的（`pick_second()`）。
2. **选组章节先过滤开场、再截取 3 个**。原来顺序是"先拿 3 个再过滤"，结果
   `INICIO + OPCIÓN 1 + OPCIÓN 2` 把 `OPCIÓN 3` 挤掉了，发出去只有两个选项。
   现在 `clean_chapters` 先丢掉 `INICIO / Introdução / 首页 / 开场` 这类，再从真选项里取前 3 个。
   实测西语视频：`INICIO, OPCIÓN 1, OPCIÓN 2, OPCIÓN 3` → 剩下 `OPCIÓN 1/2/3`。
3. 后台"时间戳/章节"就是 `tarot.contents` 的 title 列表。开场一栏在后台显示为 `🏠 首页`，
   这就是用户说"第一个那个首页不用给"的那一栏——源头就是章节里带了 INICIO。

### 15.6 章节筛选交给模型（m04376）

开场名千奇百怪（`INICIO` / `首页` / `Intro` / `今天先说两句` / `订阅点赞`），用固定噪声名单永远补不完。
所以先跑 `core.clean_chapters` 拿一个规则结果，再让模型按"这段是不是真正的选项/星座"挑一遍
（`lib/chapterai.py` 的 `screen()`，走 `translate.chat()`）。模型失败/没给序号就用规则结果，不会中断。

实测 4 个场景全部正确、每次 2~3 秒：西语 `INICIO+3选项` → 3 个选项（丢 INICIO）、
无首页的 3 选项 → 3 个全留、带 4 条噪音的 7 条 → 只剩 3 个 Pile、
全星座 14 条（含 Intro/总结）→ 正好 12 星座。

### 15.7 记忆库只在"有章节但认不出"时兜底（m04376）

原来 `classify` 最后一步无条件套记忆，导致"Corazón 一般都发选组"把一条**没有任何时间戳的口播视频**
判成了选组（价格按 0.59、标题带【选组】、章节为空）。用户指出这条本来就是能量。

现在记忆只在 `chapters and len(chapters) >= 2` 时才生效：没有时间戳的视频一律按能量处理。
单测 `test_classify_no_chapters_ignores_memory` / `test_classify_uses_memory_only_with_chapters` 守着这条。

### 15.8 选组的标题信号词（m04410 用户补充）

后台老稿里选组标题的高频写法：`互动塔罗`、`互动占卜`、`选一组`、`选一颗/条/只`、`无时限互动塔罗`，
英文 `Pick a Pile / Pick a Crystal`，西语 `Tarot interactivo`、葡语 `Tarot interativo`。
`lib/core.py` 的 `PICK_PAT` 已含「互动占卜」，其余见该正则。

注意：**不要**把单独的 `interactivo / interactivo` 当信号词——Corazón 的纯口播视频标题里也带
`Tarot atemporal/interactivo`，加进去会把能量误判成选组（m04376 踩过）。
外语选组靠章节里的 `Opción 1 / Opção 2` 硬证据来判，比标题可靠。

## 16. 标题与类型：钱花在哪、错在哪（m04578 定案）

### 16.1 标题不要花 API 费，交给平台

实测 93 篇：我们提交的标题与最终 `meta.title` **没有一篇完全相同**，平台 100% 会改写（平均 +6.2 字，最多 +15 字，17 篇只增删 emoji）。
结论：**模型翻的标题只是"提示词"**，平台还会再润一遍。所以：

- 标题默认**不翻**，直接传原文（`translate.use_google` 打开才走谷歌 → 原文兜底）
- 原 `translate.use_外部模型` 已随 旧模型通道下线删除（m07729）
- 谷歌的 `sl` 必须是 **auto**——写死 `en` 会让西语/葡语标题整段漏翻（真实案例：`Tarot Interactivo: ¿Qué Piensa de Ti Ahora Mismo?` 漏成「互动：¿Qué Piensa de Ti Ahora Mismo？」）

### 16.2 `【博主】` 前缀必须由代码拼

用户 m04578 明确：**前缀是他自己在后台手加的，平台不会补**。
所以发布前一律过 `pipeline._ensure_title_tags(cn, vtype, title)`：缺【博主】补【博主】，选组缺【选组】、全星座缺【全星座】就插在博主标签后，已经齐了就一个字都不动。

### 16.3 类型判错只能接受，救不回来

`tarot.contents` 与正文 H1 **就是我们提交时"章节分段"的回显**，不是平台的判断结果：

| 文章 | 价格 | tarot.contents |
|---|---|---|
| 1080095999（选组） | 59 | 简介📘 / 选项 1️⃣ / 选项 2️⃣ |
| 1080096000（选组） | 59 | 首页 🏠 / 选项 1 / 选项 2 |
| 1080096002（能量） | 29 | `[]`（空），正文 H1 = 0 条 |

所以出稿后**无法反查真实类型**；类型判错只能改价格和前缀，正文结构会一直错。用户 m04578：**可以接受**。
推论：类型必须在**提交前**判准，别指望事后纠正。

### 16.4 章节筛选什么时候才调模型

`chapterai.screen()` 只在 **`vtype == pick` 且原始章节数 > 4** 时调用（脏列表，含开场/广告/结尾）。
其余情况一律用 `core.clean_chapters()` 的规则结果（先丢噪声名、再取前 3 个选项）。
**坑**：这段代码曾经把 `b["cn"]` / `full.title` 写进 `prepare()`（那两个变量在这个作用域里不存在），NameError 被 `except` 吞掉，导致模型筛选**从来没生效过**，日志里只有一行"章节筛选异常"。改完用 dry-run 确认日志不再出现该异常。

### 16.5 实测结论：标题**必须传**，传空会变成文件名（2026-11-06 实验，20 币）

用两条真实选组视频做对照（`YcEQVpVYOcI` 传谷歌粗译、`BzlCS16djN8` 传空标题）：

| 传什么 | 平台最终 `meta.title` | 结论 |
|---|---|---|
| 谷歌粗译 `关于此人与您的关系的真相🗝🔮♥️` | `关于此人与您的关系的真相 🗝🔮♥️✨` | 只补了空格和 emoji，**不加【博主】前缀** |
| 空字符串 | `文件名：BzlCS16djN8.clean.srt 📁` | **直接拿文件名当标题**，废稿 |

两条铁律：

1. **永远不要传空标题**——平台会退化成"文件名：xxx"，而我们的临时文件是按 video_id 命名的，等于把 `BzlCS16djN8.clean.srt` 当标题发出去。
2. 平台对粗译**几乎不动**（只补空格/emoji），所以粗译质量就是最终质量的下限；`【博主】` 前缀和 `【选组】/【全星座】` 标签**必须由 `_ensure_title_tags()` 补**，别指望平台。

顺带确认（第二次验证 §16.3）：空标题那条 `tarot.contents` 正好 2 条（=我们传的 2 个选项），粗译那条 3 条（=传的 3 个选项），**章节结构 100% 来自我们的输入**。

### 16.6 标题改回"直接传原文"：平台自己会翻（m04769，2026-11-06 实测）

起因：2026-11-06 首跑时谷歌翻译被 4 路并发打到限流（返回 HTML，报 `Expecting value: line 1 column 1 (char 0)`），
14+ 条标题降级成外语原文提交。我以为会露出外文，结果**平台把它们全翻成了中文**。

实测（拉 `list_tasks` 与 `list_all_posts` 逐条对比，剥掉 `【…】` 前缀后判有没有汉字）：

| 项目 | 数字 |
|---|---|
| 当天有效文章 | 73 篇 |
| 提交时标题正文是外语 | **35 条** |
| 平台翻成中文 | **35 条（100%）** |

样例：`【Miss Z】Mark My Words… Your Destination` → `记住我的话……你的目的地就是 📍`；
`【Edgar】$22.22 PER QUESTION` → `每题 $22.22 💰😍`；
`【伊娃博士】Przekazy od Przewodników`（波兰语）→ `来自引导者的讯息 ✨📨`；
`【OM】¿QUÉ HAY EN SU MENTE?`（西语）→ `他/她在想什么？`。

所以定案：**标题默认传清洗后的原文，不自己翻**——少一道会坏的工序。

配置（`config.yaml` → `translate`）：

| 键 | 默认 | 含义 |
|---|---|---|
| `use_google` | `false` | 打开就用谷歌粗译（带重试），失败退回原文 |
| ~~`use_外部模型`~~ | 已删除 | m07729 起 旧模型通道下线，模型相关统一走 `llm.providers` |
| `google_retries` | `3` | 谷歌请求次数（4 路并发就限流，所以必须重试） |
| `google_backoff` | `2.0` | 秒；第 n 次重试等 `backoff × n` |

两个开关都关 = 传原文。`_ensure_title_tags()` 照旧补 `【博主】` 和 `【选组】/【全星座】`，
所以"原文"指的是**博主名之后的那段标题正文**。

## 17. 没字幕 / 直播还没开播：进 waiting，下次开跑自动回补（m04769）

用户原话："没字幕的第二天会补吗？"——**以前的答案是"不会"**：`state["waiting"]` 只写不读
（全项目 `state.get("waiting")` 读取次数 = 0），窗口一过（昨天 21:00 ~ 今天 21:00）就永久漏掉，
2026-11-06 已经堆了 13 条。

现在改成回补：每次开跑，**先**把 waiting 里的条目还原成候选，和当天新视频一起走同一条
"拿详情 → 判类型 → 下字幕 → 提交"链路。

| 什么情况进 waiting | status | 说明 | 等多久 |
|---|---|---|---|
| 下不到字幕 | `no_subs` | YouTube 还没生成字幕（直播回放尤其慢） | `waiting_retry_days`（20 天） |
| 全星座时间戳不全（< 12 个） | `hold` | 用户规则：不齐先不发 | `hold_max_days`（默认 **3 天**），还不齐就放弃 |
| 直播**预告**（还没开播） | `live_future` | 记下 `expect_at`，**到点之前不试**，省请求 | 到开播时间才开始试 |
| 直播**刚结束 / 正在播**取不到流 | `live_gone` | 通常过一阵会转成回放，不是失败 | `live_retry_days`（默认 **3 天**） |
| 正在直播（`is_live`） | `live_now` | 跳过，等结束后出回放 | 不进 waiting，下次扫描重新遇到再说 |

规则：

- 回补窗口 `waiting_retry_days: 20` 天（直播预告最长 16 天才开播，窗口必须盖住它）
- 每次最多回补 `waiting_retry_max: 40` 条，按"进队时间"从老到新
- 抓到字幕并**提交成功**后从 waiting 删掉；还是没有就刷新时间戳继续等
- 博主已从 `jb.docx` 删除的，回补时跳过并打一行日志（不会报错）
- **只看回放**（m04869）：`was_live=True` 且能取到流才算回放，正常走全流程；
  `is_live=True` 一律跳过。yt-dlp 对预告/刚结束的直播拿不到 `live_status`，
  只能在 `video_info` 报错时按文本判：`will begin in N days/hours` → `live_future`，
  `has ended` → `live_gone`（2026-11-06 实测：4 条预告 + 1 条已结束，全判对）
- **回放有字幕但时间戳不齐**（m04869 追问）：按 `hold` 处理，3 天内每天重试（描述可能后补），
  3 天后仍不齐就放弃，**不降级成能量发**——全星座的档位和排版都是另一套，降级发等于发错类别

日志里回补的条目前面带 `回补·` 前缀，方便和当天新视频区分。

## 18. 已确认不做的事

- **频道（series）缺了不补**（用户 2026-11-06 决定，选 A）：后台 123 个频道里没有的博主，
  文章照常发布，只是不挂合集页；日报里只作一行说明，**不进「要你处理」**。
  已知缺的 8 个：牧师、莫拉、Rag、魔法之谜、Deepa、杰伊塔罗、灵感之路、阿米莉亚。
  原因记录：后台频道是手工建的，80 个博主没建全；`GET /api/post/series/match` 对这几位返回 `{}`。
  若将来要补：后台手动建同名频道即可，`attach_series()` 能给已发布文章补挂；**不要**用程序试探建频道接口。

## 19. 观众付费解读类直播回放：不更新

用户 2026-11-06：这类直播是博主给**观众逐个看盘 / 按问题收费**，对我们受众没价值，不再更新。

- 例子：【Edgar】`$22.22 PER QUESTION`、`LIVE READINGS 25$ PER QUESTION!! All Signs`；
  【Anastasia】`LIVE Birth Chart Readings! October 12th, 2026`、`LIVE Birth Chart Readings - Ask me Anything!`
- 实测样本（2026-11-06）：Anastasia 的 streams 页 115 条里 72 条属于这类，Edgar 的 streams 页 168 条里 37 条；
  两人普通 videos 页 0 条（说明只出现在直播回放里，按标题判断不会误伤正常运势视频）。
- 判断方式：标题命中 `birth chart read` / `per question` / `live readings` 之一就跳过，
  日志与 `run-*.json` 里记 `观众付费解读类（标题命中「…」，按设定不更新）`。
- 关键词在 `rules.yaml` 的 `paid_live_patterns`，想加词直接改；代码在 `lib/core.py` 的
  `looks_paid_live()` / `is_candidate()`。
- 为什么不用「时长」或「All Signs」判：Edgar 这类标题里也写 All Signs（4 小时以内、时长合规），
  只看时长/标签会漏；也有 13 分钟的短回放（`799s LIVE Birth Chart Readings! August 3rd`），靠时长短也挡不住。

## 20. 日报口径（report.py）

- 直播相关报错**不算失败**：`This live event will begin…` / `This live event has ended…`
  在日报里单独一行「直播 N 条不算失败：预告没开播 / 刚结束还没出回放，按规则留着回头补」，
  不进「报错」、不进「要你处理」（用户 2026-11-06 要求"日报要与时俱进"）。
- 频道未匹配只作一行说明（见 §18）。
- 报表同时写文件与推送：`logs\report-latest.txt`、`logs\report-<时间戳>.txt`，
  推送通道在 `config.yaml` 的 `report.targets`（IM 群机器人走 markdown，上限 4096 字节）。

## 21. 标题「两个名字」：出稿就纠，不留到下一轮

现象（用户 m05021 2026-11-06）：`【Filho】[Filho]有人会向你表白…`、`【灵魂之爱】[灵魂之爱] 过去的沉重枷锁`。

- 成因（已核实）：**不是我们拼错**。我们提交的标题 42/42 条没有重复；是平台 AI 生成文章标题时
  自己补了一遍 `[博主名]`（正文标题来自 AI，不是我们的提交标题），我们再补 `【博主】` 前缀就成了两个。
- 两道防线：
  1. **出稿前预防**：`_ensure_title_tags()` 先 `core.strip_leading_name()` 剥掉标题开头自带的
     `[名字]`/`【名字】`/`(名字)`，再补前缀 —— 从源头不产生重复。
  2. **出稿后兜底**：`publish_one()` 排期成功后，用 `publish.dedupe_name()` 检查后台标题，
     命中 `^【X】[\[（【]X[\]）】]` 就调 `publish.retitle()` 改回单前缀（只改标题，
     正文/封面/价格/定时原样带回去，正文长度还会校验）。
- `retitle()` 的 body 已用真实文章（1080096126）只读验证：正文 4257 字完全一致、
  `published_on` 是 int、`style` 金额与定时不变、仍是 12 字段。
- 历史那 6 篇按用户要求**不动**（2026-11-06 当天）。

## 22. 运行环境：项目自带 .venv，别再用 Agent 环境 公共运行库

2026-11-08 用户决定「完全独立」。原因不是版本低，而是**Agent 环境 自带的 python 是精简运行库**，
只装了文档处理那几样（openpyxl/python-docx/pandas/pillow/lxml/numpy），**没有 requests / yt-dlp**，
所以 `import requests` 直接 `ModuleNotFoundError`。

- 现状：`<项目根>\.venv`，**不加** `--system-site-packages`，
  `Lib\site-packages` 只有自己的 5 个包：requests / yt-dlp / PyYAML / python-docx / tzdata。
- `run_daily.bat` 用 `set PYEXE=%~dp0.venv\Scripts\python.exe`，**不用** PATH 里的 python
  （那只是 `%USERPROFILE%\.local\bin\python.cmd` 垫片，bat 里不带 `call` 调 .cmd 不返回，后面步骤全丢）。
- **tzdata 是必需的**：Windows 上少它 `zoneinfo` 找不到 `Asia/Shanghai`，`pipeline.py` 起不来。
- 重建方式写进 `README.md`「外部依赖」和 `requirements.txt`；改依赖就重建，别往公共库装东西。
- 今晚（2026-11-08 凌晨）之前临时装进公共库的 yt-dlp / PyYAML 保留未删（删它属于改公共环境，收益小）。
- **2026-11-08 01:00 项目从 U 盘 F:\Agent 环境\Projects\yijitt-publish 搬到固态 <项目根>**
  （F 是 7.5 GB FAT32 U 盘，C/D/E 是同一块 NVMe 固态；封面也一起搬到 <项目根>\封面，
  config.yaml 的 cover_dir 已指向新位置；任务计划里的 .bat 路径已改成 E 盘；.venv 在新位置重建）。

## 24. 事故记录：2026-11-08 01:04 「验证」跑成了真提交

- **经过**：搬盘后我想做一次不花钱的全链路验证，跑了 pipeline.py --dry-run --all。
  但 --all 在 pipeline.py:1187-1191 里写的明明白白是「隐含 --commit」，而 --dry-run
  只对 --publish-only 的排期生效、**不拦提交**。结果真提交了 7 条、扣币。
  这条陷阱 2026-11-06 的子代理盲测就抓出来过，我自己又踩了一次。
- **后果**：任务 54481～54487（6 条出稿 + 1 条 pending/post_id=0），余额 2080 → 2050。
  阶段4/5 被我在 01:15 手动杀掉，所以 6 篇停成裸草稿（vis=0、style={}、无封面）。
- **处置（用户选 A）**：pipeline.py --adopt-orphans 6 --date 2026-11-08 捡回这 6 篇，
  补封面/¥0.29/频道/排期，6/6 成功，排进 11-08 的 08:15 / 10:15 / 11:15 / 21:10 / 22:10 / 23:10，
  11-08 那天总量从 31 条变 37 条。日志 logs\adopt-orphans-20261108.log。
- **教训**：想要"只扫不花钱"，只能 --dry-run 单独跑（不加 --all、不加 --commit）；
  任何带 --all 的命令都是真花钱的。以后验证链路先看 argparse 的 help 文本再按回车。

## 25. 项目位置（2026-11-08 起）

- 代码/配置/日志/state/.venv/Chrome 登录态：<项目根>\
- 封面：<项目根>\封面\（原 C:\path\to\封面）
- 外部仍不动的六项：`jb.docx`(D 盘)、clash 程序与配置(D 盘)、`ffmpeg.exe` 与 `deno.exe`(C:\tools\bin)
- 代码里不再有写死盘符：lib\rank.py、probe_energy.py 改成按 __file__ 推算项目根

## 26. 观众互动类不更新（2026-11-08）

- **用户 m05854**：Evan 那种"现场给观众做解读"的视频归"观众互动类"，以后不发
  （他举例的那篇 `1080096378`【Evan】占星师为观众解读 已由他自己下架，我没动）。
- **做法**：`rules.yaml` 新增 `viewer_interaction_patterns`，`lib/core.py` 新增
  `looks_viewer_interaction()`，在 `is_candidate()` 里排在"付费解读"之后判。
  命中就跳过，原因写"观众互动类（标题命中「…」，按设定不更新）"。
- **当前四条关键词**（都能在 rules.yaml 里改）：
  `reads?\s+(the\s+)?(audience|viewers?|subscribers?)`、
  `audience\s+(members?|readings?|questions?)`、
  `readings?\s+(for|with)\s+(the\s+)?(audience|viewers?|subscribers?)`、
  `live\s+(astrology|tarot|card|oracle)\s+readings?`
- **实测**：Evan "Astrologer Reads Audience Members…" → 命中 `Reads Audience`；
  "We Did Live Astrology Readings During an Eclipse…" → 命中 `Live Astrology Readings`；
  周运/月运、"Weekly Astro Live: The Week Ahead…" 不命中；
  "LIVE READINGS 25$ PER QUESTION" 仍走"付费解读"那条，不混。
- 和"付费解读"的区别：付费是**按问题/看盘收费的答疑**（Anastasia、Edgar），
  互动是**给现场观众/听众做解读**（Evan）。两类都不发，但关键词分开维护。

## 27. 首映（Premiere）按直播预告处理（2026-11-08）

- **背景**：2026-11-07 补跑时 3 条被当普通报错丢掉，报错文本是
  `ERROR: [youtube] <id>: Premieres in 36 minutes / 26 hours / 31 minutes`。
- **用户 m05854**：首映直接按直播预告处理。
- **做法**：`pipeline.py` 的 `process_one()` 在 `live event` 分支前加了
  `premieres? in (\d+)\s*(day|hour|minute|second)` 匹配 → 记 `status=live_future`、
  `expect_at=now+n*unit`（reason 写"首映（N 后开始，到点才试）"）。
  之后由 `retry_waiting()` 的门控在到点后自动重试（与直播预告同一套）。
- **验证**：离线用例（tests\test_core.py::test_premiere_treated_as_live_future）
  用假报错打进 `process_one()`，断言 status/expect_at 都对；26 项单测 0 failed。

## 28. 章节名 AI 正名（2026-11-08）

- **背景**：2026-11-08 晚 0 条全星座。查下来 Queen `hPW8wr-32w0` 的章节来自评论区，
  12 条里第 9–11 条写成 `SAG 02:01:00`、`CAP 02:14:00`、`AQUA 02:27:30`，
  `lib/core.py` 的 `_norm_zodiac()` 靠子串匹配、别名表只有全名，
  结果只认出 **9/12** → 按"全星座必须齐"被 hold（`hold_max_days: 3`，11-11 到期）。
  另外两条 Lina 是简介和评论区都没有时间戳，属于真缺，AI 也救不了。
- **用户 m06046**：思路改成"把评论区交给 AI 认"，而不是我原来提的加缩写表。
  **用户 m06108 定**：只要两层（本地免费网关 → 旧模型通道），**不做本地缩写表**。
（m07729 起第二层不是 旧模型通道 了，见 §37：换成 `llm.providers` 网关链。）
  **用户 m06139**：不改"评论区/简介"的取源顺序，只加 AI。
- **做法**：`lib/chapterai.py` 新增 `normalize_signs(cfg, chapters)`：
  只把"序号 + 章节名"发给模型（**时间戳完全不进 prompt**），要求回
  `{"1":"白羊座","9":"-"}` 这种映射，闭集只允许那 12 个中文名；
  只有"12 个标准名各一次"才采纳，否则返回 None。
  调用点在 `pipeline.py` 的 `process_one()`：仅当 `vtype==全星座` 且认不全时触发，
  命中后**只改 `chapter.name`、`seconds` 不动**，再复查一次；好了就继续走全流程，
  没好就照旧 hold。
- **调用顺序**（`config.yaml` 的 `chapterai` 段）：
  ① 本机模型网关（`http://127.0.0.1:3425/v1`，模型
  `local/model-a`，token 读 `~/.config/llm-gateway/.env` 的
  `LLM_GATEWAY_KEY`，不花钱、不走代理）
  ② ~~旧模型通道~~（m07729 已下线，见 §37：改为 `llm.providers` 里的其它网关）
  两层都失败 → 返回 None，行为与改动前完全一致（仍然 hold 等下次）。
- **实测**：拿 Queen 那 12 条真实章节跑真网关，**1.9 秒**认全 12 个
  （`SAG→射手座`、`CAP→摩羯座`、`AQUA→水瓶座`），秒数一条没变，`9/12 → 12/12`。
  离线单测 `tests\test_chapterai.py` 8 项全过（正常 / 乱答 / 只认出一部分 / 超时 /
  本来就齐不调模型 / 开关关掉 / 没 key / 第一个网关顶用就不调第二个）。
- **为什么不让模型给时间戳**：模型会"补全"出不存在的秒数，一旦写进提交章节，
  用户点进去就是错的时间点。名字可以猜，时间不能猜。
- **成本**：只有"全星座且认不全"才调，一晚通常 1 次、2 秒内；其余视频零调用。
- **依赖**：第一层依赖本机网关在跑。21:00 定时任务时若本机网关没开，自动落到
  下一个网关；整条链全不可用时仍然是 hold，不会崩。

## 29. 全星座"变少"的三个漏洞与修法（2026-11-09）

- **触发**：用户 m06430 说"最近的全星座少得有些异常"，并指出【Kitty】【Harmoni】
  这两个明明在更却没被扫到。
- **审计方法**：对 18 个"以前出过全星座"的频道各抓近 15 条
  （`yt-dlp --flat-playlist -J --playlist-end 15`，共 267 条，其中标题像全星座 115 条），
  逐条过 `core.is_candidate()` / `core.classify()`，再抽查 6 条长视频取详情看章节。
- **漏洞 1（语言）**：`ZODIAC_ALIASES` 原来只有英/中/西/葡，意大利语
  `ARIETE/TORO/GEMELLI`、俄语 `Овен/Телец/Близнецы`、波兰语 `Waga/Skorpion` 一个都认不出
  → 长视频被判 energy → 撞"能量 30 分钟上限"丢掉。实测：意大利Bucci `1ajwpKgXK8k`
  118 分 13 章节只命中 3/12、卡娅 `iOU4vm3luCc` 127 分 0/12、伊娃博士 `bdZ49L5K0Zc` 86 分 0/12。
- **漏洞 2（标签）**：`lib/core.py` 的 `is_candidate()` 里
  `re.search(r"#(shorts|tarotreading|lovetarot|tarot|fyp)\b")` 一票否决。
  Kitty 近 15 条里 **12 条全星座（48–165 分）标题带 `#tarot`，全被当 Shorts 丢掉**。
- **漏洞 3（判定入口太窄）**：全星座原来只认"标题有 all signs"或"章节命中 ≥10"，
  标题没写、章节又认不出的（`NEW MOON IN SCORPIO`、`OROSCOPO SETTIMANALE`、
  `для всех знаков`）只能归 energy。
- **修法 A（多语言别名）**：`ZODIAC_ALIASES` 补意/俄/波/法/德（以及葡语补全）
  共 60 余条；`_build_alias_matchers()` 把别名分两组：中文用包含匹配，
  其它语言用 `(?<![^\W\d_])别名(?![^\W\d_])` 字母边界整词匹配（`re.I`），
  避免 `toro` 命中 Toronto、`rak` 命中 track、`lew` 命中 jewel 这类误伤。
- **修法 B（标签）**：`#tarot/#tarotreading/#lovetarot/#fyp` 不再否决；
  只有 `#shorts` 且**时长 <10 分钟**才判 Shorts。
- **修法 C（AI 正名提前）**：`lib/chapterai.py` 的 `normalize_signs(..., min_signs=12)`
  加参数；新增 `pipeline.prejudge_signs(cfg, chs, duration)`——章节 ≥8 条、
  星座 <10、时长 ≥30 分钟、非选组时先问一次模型，`min_signs=10` 即可采纳；
  命中后 `core.classify()` 就能判出 all_signs，后面"已判全星座但不齐"那段不再重复问模型。
- **8 / 10 两个数字的来历**（用户 m06495 追问，回答见 m06507）：
  - **8** 是 `pipeline.py` 里"简介章节 <8 条才去评论区再抓"的门槛——正常全星座简介 ≥12 条，
    给足 8 条说明目录基本完整、只是名字认不出，没必要多花 13.5 秒抓评论。
  - **10** 是 `core.classify()` 判全星座的门槛——12 星座 + Intro = 13 条，
    容忍 2 条缺口；要求 12 太脆，一个错字（或一条 Intro 命名怪异）就整条崩。
  - 两个都是写代码时的经验值，不是平台规定，可在 `rules.yaml`/代码里调。
- **验证**：
  - 单测：`tests\test_core.py` 加 6 项（意/俄/波 12/12、整词匹配防误伤、`#tarot` 放行、
    `#fyp` 放行、`#shorts`+540 秒仍拦），`tests\test_chapterai.py` 加 2 项；全过。
  - 真实样本：Anastasia `L0xrBDvFFpw` 144 分、Simon `xGGLCCFCmmY` 72 分、
    意大利Bucci `1ajwpKgXK8k` 118 分、Evan `nrtBj3_X7E8` 160 分、卡娅 `iOU4vm3luCc` 127 分、
    伊娃博士 `bdZ49L5K0Zc` 86 分——改后**全部 12/12、类型 all_signs**。
  - 8 天窗口重扫（只读）：全星座从 3 条变 **12 条**（含 §30 提到的旧视频）。
- **成本**：AI 正名走本地免费网关，1–2 秒/条；只有"章节够多但认不全"才调。

## 30. 兜底链的窗口漏洞：老视频被当成新视频（2026-11-09）

- **现象**：8 天窗口（2026-11-01 00:00 ~ 11-08 23:59）重扫，12 条全星座里 8 条是旧视频：
  Kitty `abhBVb1ewx8` 2026-06-15、`ba2hTWlYtjE` 2026-07-22、`l8VySkRiqak` 2026-10-14，
  Edgar 2026-10-31 两条，伊娃博士 2026-11-01 / 10-31，Bucci 2026-11-02。
- **根因**：取源顺序是 RSS → 频道页兜底（`lib\feeds.py`）。两个都失败时，
  `pipeline.scan_one_channel()` 会退回 `yt.channel_videos()`（flat-playlist），
  **flat-playlist 的 `timestamp/upload_date` 全是空**，那条路没有任何日期过滤，
  于是把频道里任意老视频都当"新视频"。Kitty 那晚的日志形状正是
  "RSS 与频道页都没数据…45 个新视频"，一次捞进 5 个月前的片子。
- **修法**（两层）：
  1. `lib/core.py` 新增 `upload_date_in_window(upload_date, ws, we)`：
     按"上传日的整天区间"和窗口比，**只在整天区间与窗口完全不相交时才判假**，
     避免 21:00 窗口跨零点造成的日界误伤；日期认不出时放行（宁可放过，不误杀新视频）。
  2. `pipeline.py`：兜底分支截断成 `max_videos_per_channel` 条并打
     "窗口数据取不到，只按频道最新 N 条试（阶段2 用上传日期复核）"；
     `process_one()` 拿到详情后先过 `upload_date_in_window()`，
     不在窗口内直接 `skip：上传日期 YYYYMMDD 不在扫描窗口内（…）`，不进上传与提交。
- **验证**：
  - 单测：`tests\test_core.py` 新增 2 项（回扫窗口 6/7/10 月全判假、11-01~11-09 判真；
    跨零点日窗口不误杀、空值放行）。
  - 真跑探针（真网络 + 代理）：Kitty `abhBVb1ewx8`(20260615)、`ba2hTWlYtjE`(20260722)、
    Edgar `FPa3IEUYxTY`(20261031) → 全部 `skip：上传日期 … 不在扫描窗口内`；
    伊娃博士 `bdZ49L5K0Zc`(20261108)、Simon `xGGLCCFCmmY`(20261102) → `all_signs / ready`。
- **同一轮补发**：用户 m06690 定"那四条可以发"，只补本周的
  麦肯齐 `x3s0mU3T6o4`、意大利Bucci `1ajwpKgXK8k`、伊娃博士 `bdZ49L5K0Zc`、Simon `xGGLCCFCmmY`，
  旧的 8 条不发；扫出来的 59 条能量 + 9 条选组按用户要求**不补**。
- **已知未修**：`--blogger` 只筛"扫描哪个频道"，不筛回补池（`retry_waiting` 拉进来的
  其它博主的旧 waiting 条目照旧会被处理）；`retry_waiting()` 与当天候选之间也仍可能
  出现同一条视频被算两次（麦肯齐那次重复条目就是这个）。

---

## §31 单视频模式的博主名（2026-11-09）

**症状**：单视频补发时标题写成 `【测试】【全星座】…`，后台文章名也跟着错。

**原因**：`collect_candidates()` 的单视频分支拿 `yt.Video.channel` 去 `jb.docx` 里比对，
但频道名常带花字/后缀，比不出等值，就退回占位名「测试」：

- `Mackenzie Moon Tarot` vs 文档 `麦肯齐`（名字本身不同）
- `Lia Bucci ⭐️Spazio Indaco Official` vs `意大利Bucci`（带 emoji 后缀）
- `Dr Eva Ariah - Motywacja, Inspiracja, Świadomość` vs `伊娃博士`

**修法**：`Video` 新增 `uploader_id`（`video_info()` 从 dump-json 取 `uploader_id`，
没有再取 `channel_id`），`pipeline._blogger_from_video(bs, v)` 第一优先级按 handle 精确匹配
（`@Lia_Bucci` ↔ `jb.docx` 链接里的 `@Lia_Bucci`），失败才回落"名字相等 → 最长公共前缀 ≥5
→ 文档名是频道名的一段"。四条实测全对：`@MackenzieMoonTarot`→麦肯齐、`@Lia_Bucci`→意大利Bucci、
`@drEvaAriah`→伊娃博士、`@SimonAndTheStarsTV`→Simon。

**教训**：能用 handle 就别比显示名——显示名是给人看的，会带 emoji、副标题、翻译。

## §32 两个会静默出错的小坑

1. **`sch.plan(items, date, occ)` 的 `date` 必须是 `datetime.date` 对象**，传字符串会炸
   `AttributeError: 'str' object has no attribute 'year'`（`lib/schedule.py:118`）。
   同理 `pipeline.adopt_orphans(..., date=...)` 也要传对象。这个坑 11-06、11-09 各踩一次。
2. **`publish.retitle()` 会把空的 `style` 填成 `amount=29`、`scheduled_at=0`**（它的默认值），
   于是文章从"裸草稿"变成"有价格但没排期"，`adopt_orphans()` 因为 `style.amount` 非空就不再认领。
   顺序要反过来：**先 `publish()` 补价格/封面/排期，再 `retitle()` 改标题**；或者改完标题自己补发布。

## §33 2026-11-09 补发 4 条全星座（记录）

| 文章 | 博主 | 时刻 | 价格 | 频道 |
|---|---|---|---|---|
| 1080096691 | Simon | 11-09 16:15 | ¥0.79 | 168 |
| 1080096688 | 麦肯齐 | 11-09 19:15 | ¥0.79 | 197 |
| 1080096689 | 意大利Bucci | 11-10 09:15 | ¥0.79 | 581 |
| 1080096690 | 伊娃博士 | 11-10 14:15 | ¥0.79 | 454 |

- 提交共花 70 币（15+20+20+15），余额 1685 → 1615 → **1545**（补发前余额 1615，四条 70 币已在提交时扣）。
- 封面：`麦肯齐.png`、`意大利Bucci.png`、`【伊娃博士】.png`、`Simon.png`——注意前两个文件名**没有【】括号**，
  代码里 `【名】.png` 找不到时要再试 `名.png`。
- 三条是"先提交、后补发布"（提交脚本没有等 AI 出稿），所以出现过一次【测试】标题，已改回。

---

## §34 全星座又漏了：直播回放不在 /videos（2026-11-09，用户 m06903 反馈）

**用户看到的**：Kitty、Harmonia 等"最近一直在更全星座"的频道，我们一条都没扫到。

**三个原因叠在一起，缺一不可**：

1. **RSS 全挂**：`/feeds/videos.xml` 从 2026-11-06 起对所有频道返回 404（连 Google 官方频道也一样），
   所以取源实际只剩"频道页面解析"这一条路。
2. **只读 `/videos`**：很多塔罗频道把全星座做成**直播**，回放挂在 `/streams`，
   `/videos` 里根本没有。Kitty 近 15 条全是直播回放，`/videos` 页窗口内 0 条。
3. **相对时间认不出**：`parse_age()` 原来只匹配整串 `"6d ago"`（`^...$` 锚定），
   而直播回放显示的是 `"Streamed 2 days ago"`、首映是 `"Premiered 9 hours ago"`、
   中文界面是 `"直播时间：3 天前"` —— 全部返回 None，条目被当成"不知道什么时候"直接丢掉。
4. 附带：`/streams` 页的标题不在 `lockupMetadataViewModel` 里，只在
   `accessibilityContext.label`（`"<标题> 3 hours, 7 minutes"`），所以标题也解析不出来。

**修法**（`lib/feeds.py`）：

- `parse_age()` 改成"在字符串里搜 `<数字><单位> ago/前`"，支持英/中单位与 `Streamed/Premiered/Live` 前缀。
- `channel_page_entries(handle, proxy, tab="videos")` 加 `tab` 参数，可读 `/streams`。
- `recent_entries(..., fill_to=3)`：`/videos` 窗口内条数不足 3 时才再抓一路 `/streams`，
  按 video_id 去重后按时间排序——**不是每条频道都多抓一次**，避免请求量翻倍触发反爬。
- `/streams` 标题缺失时回退 `accessibilityContext.label`，并剥掉结尾的时长串。

**验证**（2026-11-09 13:5x，8 天窗口 11-01~11-08）：

| 频道 | 修前窗口内 | 修后窗口内 | 其中全星座 |
|---|---|---|---|
| Kitty `@kittylovetarot` | 0 | 4 | 3（11-08 / 11-06 / 11-01） |
| Harmoni `@HarmoniaTarot` | 0 | 5 | 5（含 11-07、11-09） |
| Evo `@Evolved_Intuition` | 2 | 2 | 2 |
| 意大利Bucci `@Lia_Bucci` | 2 | 2 | 2 |

单测：新增 `tests/test_feeds.py`（15 项，含 `Streamed 2 days ago`、`直播时间：3 天前` 等），0 failed。

**另一个需要知道的坑**：代理中途挂掉时，RSS 与页面请求全部失败，
那一轮会把整个频道判成"窗口内无新视频"——静默漏一整天。本次试跑就复现过（clash 进程退出），
所以日志里"RSS 与频道页都没数据"这句话要当告警看，不能当成"这个频道没更新"。

## §35 开跑前自检 cookie（2026-11-11）

**为什么要做**：cookie 是 2026-11-06 从 waimian Chrome 导出的，过期后 YouTube 不会让程序报错退出，而是"取详情失败 / 大面积没字幕"，跑完一轮才发现白干。2026-11-11 那轮就出现 `Sign in to confirm your age`。

**怎么做**：`preflight.check_cookie()` 在阶段1 之前用 `config.yaml` 的 `preflight.cookie_video_ids`（现为 `h9DKbYWRluw`、`2ejKR1NPI-E`）探一次详情，约 5–10 秒。

- 任一能取到详情 → `ok`，继续
- 报 `sign in to confirm / please sign in / confirm you're not a bot` 等 → `bad`，复用 `report.push()` 推一条IM 机器人提醒，**然后照常继续**（可能只有个别视频受限，不该整轮停）
- 报 `Video unavailable / 404` 或网络错误 → `unknown`，不报警（避免狼来了）
- 没有 cookie 文件或开关关掉 → `missing` / `disabled`，跳过

**边界**：只提醒、不自动修。cookie 只能人工在浏览器重新登录后导出。自检失败也不影响主流程（最坏多花几秒）。

## §36 本地 git 版本记录（2026-11-11）

**为什么**：此前改代码靠手写 `xxx.bak-20261106`，占地方又对不上号；2026-11-09 那份 166.8 MB 的整体备份也在 11-11 按用户要求删了。

**怎么做**：项目内 `git init`（无远端、不推送、代码不出本机），`.gitignore` 排除 `config.yaml`/`state.json`/`cookies.json`/`data/`/`logs/`/`封面/` 等；`run_daily.bat` 在 `report --push` 之后调用 `scripts\git_snapshot.py`，有改动就提交一条 `每日运行 YYYY-MM-DD HH:MM（N 个文件）`，没改动跳过，提交失败只记日志不影响主流程。

**常用**：`git log --oneline -10`、`git diff HEAD~1`、`git checkout -- <file>`、`git reset --hard HEAD~1`（慎用）。

## §37 模型调用统一走本机网关链（m07729）

**背景**：旧模型通道的账号 2026-11-11 报 `429 exceeded_current_quota_error`（`Your account … is suspended due to insufficient balance`），而章节筛选与标题排序当时是**直连 旧模型通道、没有兜底层**，一旦欠费就整块降级。用户 m07729 要求"多挂几个本地网关，把和旧模型通道有关的换干净"。

**做法**：新增 `src/tarot_pipeline/llm.py`。

- `providers(cfg)` 读 `config.yaml` 的 `llm.providers`（每项 `name`/`model`/可选 `base`/`key_env`/`key_file`），缺 key 的跳过。
- `chat(cfg, messages, max_tokens=None, timeout=None, tag="")` 按顺序试，HTTP 非 200、空正文、结构异常都换下一个，并把失败原因写日志 `[LLM 换下一个] <名字> 失败：…`；全部失败 `raise LLMError("全部网关都失败：…")`。
- 固定 `proxies=None`：本机 `127.0.0.1:3425` 走代理会超时。
- 调用方各自保留降级：`chapterai.screen()` 退回规则章节（`[章节筛选降级]`）、`chapterai.normalize_signs()` 退回 hold（`[星座正名降级]`）、`rank._ask()` 退回 RSS 原顺序（`[排序降级]`）。

**`translate.py` 同时瘦身**：删掉 `PROVIDERS`/`_key_and_base`/`_llm`/`chat()`/`SYSTEM_PROMPT` 与 旧模型分支，只剩"谷歌直译（带重试退避）→ 原文"；`config.yaml` 的 `translate` 段与 旧模型 key 一并删除。

**默认四链**（`config.yaml`）：`gateway-a`（`local/model-a`）→ `gateway-b`（`local/model-b`）→ `gateway-c`（`local/model-c`）→ `gateway-d`（`local/model-d`）。

**选型依据**（2026-11-11 实测，同一道具 12 章节章节名、含 `SAG`/`CAP`/`AQUA` 缩写，max_tokens 600，用例实际只有 11 个星座故 11/12 为满分）：

这里只留结论：实测几种网关都能在 6–8 秒内认全 11/12，最快的本地小模型 2.5 秒；限流或超时的网关按链自动降级。


**端到端验证**：

- 星座正名：Queen 12 章节 `9/12` → `[LLM 星座正名] 用 gateway-a 成功` → `12/12`，**2.6 秒**。
- 标题排序：4 条真实标题 → `标题排序：2,4,1,3`，**1.7 秒**。
- 换链：把第一条改成不存在的模型 → `gateway-a 失败：HTTP 404 …` → `gateway-b` 成功 `12/12`。
- 单测 78 项 0 failed（含新增 `tests/test_llm.py` 6 项）。

**边界**：这几个免费模型有日/时额度，`FreeUsageLimitError` 与原 旧模型通道 欠费同类——但现在是"换下一个"而不是"整块停摆"；万一全挂，也只是章节筛选回规则、正名回 hold、排序回原顺序，不影响提交与发布。

## §38 交接复核修掉的两处（m07968）

**① waiting 的"等 N 天就放弃"原来永不触发。** `retry_waiting()` 用 `rec["at"]` 判过期，而写回 waiting 时又把这个字段刷成当轮时间（`pipeline.py` 末尾），于是只要每晚被回补一次，`hold`（3 天）和 `live_gone`（3 天）就永远不会被丢弃。

修法：写回时保留 `first_at`（第一次进 waiting 的时间，之后只增不改），过期判定改用 `first_at`，老记录没有该字段时退回用 `at`。`state.json` 里现有 26 条 waiting 已按"当前 `at` = first_at"补齐（备份 `backup/state.bak-before-first_at.json`），所以这 26 条的计时从 2026-11-11 之前那几次重新开始算。回归用例 `tests	est_waiting.py` 8 项。

**② `PAUSE` 只拦 `run_daily.bat`，不拦手动 `run --all`。** `pipeline.py` 从不读 `PAUSE`，所以"暂停期间手滑跑一次"会照扣照发。这是设计现状，不改代码，写进 `RULES.md` 的红线表；`run_daily.bat` 里那两行检查仍是唯一的暂停入口。

**③ 余额类信息不再写死在交接文档里**（原写"约 415"，实际当天已充值到 4715）。运行手册改成"用 `status_snapshot.py --online` 查"，并记了 11-12 18:40 实测值；快照脚本新增 `--online`，输出余额与"还能跑约几轮"。
