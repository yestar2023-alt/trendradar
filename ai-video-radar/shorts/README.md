# AI Shorts 24h Discovery（上游主动搜索）

## 目标和界限

主动发现全球 YouTube 最近 24 小时发布的、作者自述通过 AI 生成的短视频，不依赖既有九站模板或关键词差集。它会抓取原始视频链接、实际 API 发布时间、观看量、点赞评论、首次观察时间，以及之后每 4 小时的真实数据采样。

**不是 YouTube 官方 Shorts 完整榜单。** `search.list(videoDuration=short)` 只表示少于 4 分钟；脚本进一步限制至不超过 180 秒，但 YouTube 的公开 Data API 未提供完整视频宽高比或可靠 isShort 字段，因此无法证明它们一定属于 Shorts。仍需要视频核验。

**AI 制作并未自动得到画面验证。** 仅有标题和标签的 AI 自述，报告标记为“作者元数据声明”，还不能认定真的是 AI 生成视频。教程、工具测评被降权。视频热度不等于 Google 搜索关键词需求。

## 如何运行

- 复用仓库现有 GitHub Actions Secret `YOUTUBE_API_KEY`，不会输出或提交 Key。
- 工作流：`.github/workflows/ai-video-shorts-discovery.yml`。
- 运行频率：北京时间 00:15、04:15、08:15、12:15、16:15、20:15，GitHub schedule 可能延迟。
- 已启用 API v3 时，PR 的 Actions 运行会做真实搜索并上传调试制品；合并进 master 后首次建立持久快照，后续生成真实历史差分。
- 输出：`reports/latest.md`、`reports/latest.csv`、`reports/YYYY-MM-DD.md`，历史快照存 `data/state.json`。
- 本地：`python -m unittest discover -s ai-video-radar/shorts/tests -v`；设置 `YOUTUBE_API_KEY` 后运行 `python ai-video-radar/shorts/discover.py --root ai-video-radar/shorts`。

## 搜索策略与配额

默认每 4 小时 8 个全球关键词搜索，主打新发布的 AI dance、AI cat、AI animation、AI meme、AI transformation、AI generated shorts 和西语 AI 视频。其中多数按观看量排序，少量按发布时间排序捕捉低播放新作品。

2026 年 10 月 15 日更新的 YouTube 官方文档明确规定：`search.list` 目前默认每项目每天最多 100 次调用的独立 Search Queries 配额桶，通常每次消耗 1 次搜索额度；不是旧文档经常提到的“每次 100 点”。8 次 × 6 轮 = 每天最多 48 次搜索，且每次只取 1 页（上限 50 条）。`videos.list` 另按基础 API 调用配额计费。应在 Google Cloud 中查看项目的**实际配额**，如有其他项目使用同一个 Key/项目，则会共享配额。此机制和限额未来可能变化。

文档：
- https://developers.google.com/youtube/data/reference/rest/v3/search/list
- https://developers.google.com/youtube/data/determine_quota_cost
- https://support.google.com/youtube/answer/15424877

## 报告解读

- **最近 24h 发布候选**：使用 `videos.list.snippet.publishedAt` 在当前扫描窗口内严格验证；搜索索引可能延迟。
- **首次观察时间**：我们第一次真实获取该视频，不等于上线日期。
- **作者自述 AI 制作**：由公开标题和标签推测，没逐帧核验。
- **参考热度门槛**：默认观看量至少 1,500，且发布以来平均每小时至少 160。该平均值不是瞬时增长率。
- **观测增速**：只有两次以上真实采样后才可计算；不得根据单次观看量编造。
- **候选 Shorts**：当前仅验证时长，无法单靠 API 验证纵横比及 Shorts 正式归类。
- **SEO Top**：本脚本不自动推荐建站；需要 ChatGPT 或人工进一步核验跨平台二创、竞品、Google 搜索意图及版权风险。

## 注意

搜到什么由 YouTube 搜索索引决定，无法保证覆盖全部 AI Shorts。下一个阶段应加入固定早期二创作者频道与跨语种新话题发现，并避免仅用“AI”词盲搜导致漏报。多次扫描可能因搜索排序变化遇到旧视频重新出现，但发布窗口核验不会把旧视频误判为最近 24h 发布。

## 第二层：具体玩法归组与旧词排除

同一轮视频采集后，`themes.py` 读取 **真实已保存的 data/state.json**，不重复消耗 YouTube API 配额。

输出：
- `reports/themes-latest.md`：可复刻视频玩法研究清单，每个主题含原始视频URL、作者账号数、首次系统观察时间、观看量与两次采样增长。
- `reports/themes-latest.json`：结构化主题证据，可供未来 AI/人工做图像核验和 SEO 分析。
- `reports/YYYY-MM-DD-themes.md`：当日记录，避免旧版覆盖。

归组策略是**明确名字或镜头**的窄规则（比如 Black Cat Clapping、Cinema Breakout、双图混搭、食物长树），不把所有 AI cat、AI dance、AI transformation 当同一趋势。跨账号数只计算频道 ID 不同、标题/标签声称 AI 的作品，排除教程和新闻解说。这个“跨账号”只是文字线索，仍需要核验视频画面是否真正模仿相同镜头或动作。

针对已知存量玩法引用更早的公开历史证据，标为「已有玩法/不算今日新词」。纯单频道系列、未核实肖像/音乐/电影 IP 内容列为待查。**自动报告永远不给“确认新关键词”**，仍需独立核验 TikTok/YouTube 早期二创、竞品首次上线和 Google 搜索意图。

本阶段不下载第三方视频，不自动生成有版权风险的视频，不自动创建 SEO 页面或域名。
