# AI 视频上游雷达（YouTube Data API 试运行版）

## 当前状态

本目录独立于现有九站 Sitemap 监控。GitHub PR 运行单元测试和真实 API 探针；**缺少 Google API Key 时不假装采集成功**。

- 官方 API：channels.list → uploads playlist → playlistItems.list → videos.list。
- videos.list.snippet.publishedAt 作为平台视频发布时间，不拿播放列表加入时间冒充发布日期。
- 第一次成功只建基线；随后相对于上次成功快照新增的视频 ID 才计入增量。
- videos.list.statistics.viewCount 保存真实观看量和采样时间；拿不到时显示未知，不填零。
- 失败保留上次成功快照；保留视频 first_seen 与最近 48 次真实播放量采样。
- 新视频不等于确认的新 AI 视频玩法；仍需核验二创、搜索意图、竞品。
- 第一批仅监控 League of Legends 官方频道，最多扫描上传列表前 100 个视频，不代表全球监控。

## Google Cloud 一次性设置

1. 打开 https://console.cloud.google.com/apis/library/youtube.googleapis.com ，在自己的 Google Cloud 项目启用 **YouTube Data API v3**。
2. 打开 https://console.cloud.google.com/apis/credentials ，点击创建 API key；在 API restrictions 中限定 **YouTube Data API v3**。GitHub hosted runner 没有稳定出口 IP，避免设置不兼容的固定 IP 限制。
3. 打开 https://github.com/yestar2023-alt/trendradar/settings/secrets/actions ，选择 **New repository secret**。Name 填 YOUTUBE_API_KEY，Secret 填新 API key。
4. 返回 https://github.com/yestar2023-alt/trendradar/pull/2 的 Checks，进入 Actions 重新执行运行检查。

**不要将 Key 发到聊天中或写入仓库。** Actions 只通过 secrets.YOUTUBE_API_KEY 注入运行环境，源码和报告不包含它。

官方文档：
- https://developers.google.com/youtube/v3/getting-started
- https://developers.google.com/youtube/data/reference/rest/v3/playlistItems/list
- https://developers.google.com/youtube/data/reference/rest/v3/videos/list

## 执行

本地单测命令：

    python -m unittest discover -s ai-video-radar/upstream/tests -v

本地扫描：

    python ai-video-radar/upstream/upstream.py --root ai-video-radar/upstream

需要先通过临时环境变量 YOUTUBE_API_KEY 提供密钥，不能提交至源码。

## 当前 PR 与定时部署

测试 PR 不修改 master，不影响原九站日报。只有**明确合并 PR**后，才会在 master 依照计划每 4 小时执行并持久化状态文件。PR 自身不会写入历史快照，每次 Actions 的工作目录都是新的；因此 PR 可以验证真实 API 可用性和模拟增量，不能冒充已通过实际跨运行新增测试。GitHub schedule 可能延迟。

报错：
- 缺少 YOUTUBE_API_KEY：到 GitHub Actions Secrets 设置。
- HTTP 403 / accessNotConfigured：项目没有启用 YouTube Data API v3。
- HTTP 403 / quotaExceeded：查看 Google Cloud 配额。
- HTTP 400/403 / keyInvalid：检查密钥与限制。
- 成功来源为 0：日报标注数据未更新，不能判断今日新增。
