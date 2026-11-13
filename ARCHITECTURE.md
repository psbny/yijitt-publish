# 架构说明

这份文档讲"代码是怎么组织的、数据怎么流、为什么这么分"，运营规则与历史坑见 `RULES.md`。

## 一、分层

```
cli.py           只做一件事：把子命令分发给 pipeline / report / tools
   │
pipeline.py      编排层：五阶段流水线、状态机、日志与报告落盘
   │
   ├─ feeds.py       发现层：这个频道最近更新了哪些视频
   ├─ youtube.py     抓取层：详情、章节、字幕、截帧（yt-dlp 封装）
   ├─ core.py        规则层：纯函数判定（类型/时长/星座/付费解读/Shorts/窗口）
   ├─ chapterai.py   纠错层：章节名让模型认星座（时间戳绝不交给模型）
├─ preflight.py   开跑前自检：探一条视频，判断 cookie 是否失效（失效推IM，不中断）
   ├─ rank.py        取舍层：多视频博主挑前 3
   ├─ schedule.py    排期层：价格、时段、发布日
   ├─ publish.py     写入层：正文/封面/频道/定时 + 标题纠重
   └─ backend.py      接口层：后台 API 客户端（登录态、重试、错误分类）
```

分层的原则：**规则层不碰网络，抓取层不碰业务判断**。`core.py` 全是纯函数，所以测试可以完全离线跑；`youtube.py` / `backend.py` 只管把外部世界翻译成字典，不决定"这条要不要发"。

## 二、一次运行的五个阶段

| 阶段 | 干什么 | 并发 | 失败会怎样 |
| --- | --- | --- | --- |
| 1 扫描 | 每个频道取最近 15 条，按窗口过滤，初筛标题 | 4 | 单频道失败不影响整轮；整轮全失败要当告警（代理挂了） |
| 2 处理 | 取详情/章节/字幕 → `core.classify` → 截图 → 算费用 | 4 | 这条记 `skip/no_subs/error/hold`，留状态日后重试 |
| 3 提交 | srt 提交给平台 AI，拿 task_id | 1（串行） | 400/502/503/超时按"假失败"处理，用 file_hash 反查是否已受理 |
| 4 等稿 | 轮询任务直到出稿 | 8 | 超时记 `ai_incomplete`，不阻塞其它条 |
| 5 发布 | 封面/价格/频道/定时 | 3 | 标题纠重、正文太短拒写（防清空文章） |

阶段之间通过 `state.json` 交接：阶段 3 成功写 `pending`，阶段 4 出稿写 `post_id`，阶段 5 写完排期把条目移出 `pending`。

## 三、取源的三级兜底

YouTube 侧经常抽风，所以 `feeds.py` 是链式的：

1. **RSS**：`/feeds/videos.xml`，快，但出口 IP 被挡时整片 404。
2. **频道页 `/videos`**：解析 `lockupMetadataViewModel`，能拿到相对时间（`6d ago` / `2 天前`）。
3. **频道页 `/streams`**：塔罗频道的全星座常做成直播，回放只出现在这里；标题藏在 `accessibilityContext.label`。

只有上一级拿不到窗口内的 3 条时才降级，避免 80 个频道请求翻倍。**兜底失效是静默的**——整轮会显示"窗口内无新视频"，所以日志里 `RSS 与频道页都没数据` 要当告警看。

## 四、判类型的顺序

```
1. 时长 < 下限（默认 8 分钟）        → skip
2. 标题命中 观众付费解读             → skip（如 PER QUESTION / BIRTH CHART READINGS）
3. 标题命中 观众互动类               → skip（如 Reads the Audience）
4. 带 #shorts 且时长 < 10 分钟       → skip
5. 章节 ≥8 且星座命中 <10 且时长足   → 先让 chapterai 正名一次，认齐就继续
6. 结构票：章节里有 Opción/Pile/选项 → 选组
7. 结构票：认出 ≥10 个星座           → 全星座
8. 结构票：没有章节                  → 能量
9. 标题票 / 记忆票兜底（只在前面的结构票都没结论时用）
```

结构票优先是刻意的：标题是博主自己写的、爱怎么写怎么写；章节结构是"这条视频怎么组织的"的客观证据。

## 五、状态机（state.json）

```
候选 ──处理──┬─ skip/error ──────────────► 不记录（下次还会重新判）
             ├─ no_subs/hold/live_* ─────► waiting（带 expect_at/tries，按天数过期）
             ├─ duplicate ───────────────► videos（不再当候选）
             └─ ready ──提交──► pending ──出稿──► 发布 ──► videos
                                    └─ AI 超时 ──► ai_incomplete（留待人工/重跑）
```

`waiting` 里的条目每轮开跑前会被 `retry_waiting()` 重新拉成候选（网关门控：`expect_at` 未到不试、超期丢弃），所以"今天没字幕"不代表永远放弃。

## 六、外部依赖与边界

| 依赖 | 用途 | 失效时的表现 |
| --- | --- | --- |
| clash（7890） | 访问 YouTube | 整轮 0 候选（静默），日志有"代理不可用" |
| deno | 解 YouTube JS 挑战 | 部分视频取不到流，报 `Requested format is not available` |
| yt-dlp | 抓 YouTube | 报错进 `error`，不影响其它条 |
| 平台后台 API | 提交/排期 | 登录态过期返回 401；额度不足会退款并触发 `PAUSE` |
| 本机模型网关链（`llm.providers`） | 章节筛选 / 星座正名 / 标题排序 | 按顺序换下一个网关；全失败各自降级（筛选回规则、正名 hold、排序用原顺序） |
| IM 机器人 webhook | 日报 | 推送失败只影响通知，不影响发布 |

## 七、为什么不把时间戳交给模型

模型会"编"时间戳。全星座/选组的时间戳是发布页的章节分段，写错等于把观众带到错误的位置，所以 `chapterai` 只允许模型输出"第几条 = 哪个星座"，`seconds` 永远来自本地 `parse_chapters()` 的正则解析；对不上就整条不采纳，退回 hold。

## 八、测试

`tests/` 里全部离线（不联网、不读 key）：

- `test_core.py`：判定规则、星座多语言别名、窗口函数、排期时间。
- `test_feeds.py`：页面/Age 解析（`Streamed 2 days ago`、`直播时间：3 天前`）。
- `test_chapterai.py`：AI 正名的正常/乱答/超时/开关关闭/网关优先。

跑法：`python tests/test_core.py`（每个文件都能单独跑，末尾打印 `N failed`）。
