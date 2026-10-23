# AI 视频上游监控测试版

仅用于测试 YouTube 官方频道 RSS 数据能否在 GitHub Actions 环境可靠采集，和基于成功历史快照的视频 URL 差分。

- 一期源：League of Legends 官方频道；不代表全球热门视频覆盖
- RSS 首次成功抓取建立基线，不声称视频今日发布或 AI 趋势爆发
- 每次采集输出北京时间、视频原始上传时间、首次观测时间以及失败原因
- 测试分支不覆盖既有九站日报；PR 仅执行测试和上传诊断制品
- 正式部署前需要增加持久化快照步骤，否则每次 Actions 的新容器都会重新基线
- 没有 YouTube API Key，不宣称实际播放量

运行：`python -m unittest discover -s ai-video-radar/upstream/tests -v`，以及 `python ai-video-radar/upstream/upstream.py --root ai-video-radar/upstream`。
