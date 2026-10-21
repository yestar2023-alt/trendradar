# AI Video Keyword Radar — 每日 Sitemap 增量监控

只报告**可审计的新增 URL**，不把初次抓到的旧页面或 `lastmod` 修改时间当成新品发布日期。

## 功能

- 9 个预设来源：Summrs、TikTok Creative Center、CapCut、Viggle、Higgsfield、MakeViral、Zooop、PixVerse、Media.io。
- Sitemap：优先读取 `robots.txt` 的 `Sitemap:` 声明，兼容普通 `urlset`、`sitemapindex`、`.xml.gz` 和递归子站点地图。
- 模板目录：首页/模板页静态 HTML 链接增量。动态 JS 站点如无法取得公开列表，明确报错，不猜。
- 历史记录存储在 `data/state.json.gz`，每次成功抓取后覆盖，Git 历史提供逐日不可变的历史版本。
- 第一次成功抓取**只建立基线**；第二次成功抓取才有资格报 URL 差异。
- 子 Sitemap 丢失、列表采集成功页集合不一致时，跳过不可靠差异并保留上次快照。
- 合并同一个 URL 在 Sitemap/目录中的重复发现；对已发现的 URL 提取页面标题，规范化候选词并按已配置的别名合并。
- 每天输出 `reports/latest.md`、`reports/YYYY-MM-DD.md`、`reports/YYYY-MM-DD.csv`。
- 只产生**待核实的关键词候选**；热度、真实发布时间、搜索量与 Top 3 建站商机需要进一步验证，不会无中生有。
- 无须 OpenAI Key、浏览器插件、数据库、Vercel 或 Cloudflare Worker。全程 Python 标准库。

## 已安装到现有 GitHub 仓库的用法

文件布局：

```text
.github/workflows/ai-video-radar.yml
ai-video-radar/
  radar.py
  config.json
  tests/test_radar.py
  data/state.json.gz       # 自动首次生成
  reports/latest.md        # 自动生成
  reports/YYYY-MM-DD.md    # 自动生成
  reports/YYYY-MM-DD.csv   # 自动生成
```

在 GitHub 仓库 **Actions → AI Video URL Delta Radar → Run workflow** 先手动执行一次建立基线。定时运行时间为北京时间早上 07:00 左右（GitHub schedule 可能延迟）；随后由现有 ChatGPT 每日任务读取最新报告并在上午筛选机会。由于首次执行没有历史快照，`0` 个新增是正确结果。

### 运行本地测试

```bash
python -m unittest discover -s ai-video-radar/tests -v
python ai-video-radar/radar.py --root ai-video-radar
```

若使用**独立新仓库**而非嵌套目录：

```bash
python -m unittest discover -s tests -v
python radar.py --root .
```

GitHub Actions 自带 `GITHUB_TOKEN` 的 contents 写入权限，每次保存 gzip 快照、日报与 CSV 到仓库。不需要手动配置 token。部分仓库的分支保护可能阻止 `git push`，应检查 Actions 日志；不可绕开保护直接强推。

## 报告判断口径

- **Sitemap 新出现**：URL 在上次成功采集的 Sitemap 中不存在，今天存在；不等于刚上线。
- **目录新出现**：URL 今天出现在模板列表、此前不在列表中；可能是旧模板重新被推荐，不等于新建页。
- **已确认新热词**：还需要公开发布时间、TikTok/YouTube 独立传播证据和搜索意图验证。代码不会自动声称某词“爆了”。
- **首次发现时间**：监控系统本次检查的北京时间日期。不是创建时间。
- **0 新增**：可能是确实没有新 URL，也可能所有频道不可用，必须结合检查状态判断。
- 不依赖 sitemap `lastmod` 判定新增；`lastmod` 只记录在快照中。

## 哪些站点会有限制

TikTok Creative Center、CapCut 和部分模板商店高度依赖客户端 JS 或有访问限制。使用标准 HTTP 请求时可能读不到模板。**不会绕过访问控制、登录或 robots.txt**，日报会逐站显示失败原因。若某站长期无法提供可读的 Sitemap/静态列表，应给它接官方公开 API、RSS 或合法的浏览器自动化，不能把失败当作无更新。

## 修改监控源

编辑 `config.json`：

- `base`：站点域名。
- `listings`：公开的主页、模板目录或趋势列表路径。
- `path_patterns`：与主题有关的 URL 前缀，避免全站无关内页。
- `use_sitemap:false`：对实时榜单/JS 页面避免无价值的 Sitemap 扫描。
- `aliases`：确定属于同一玩法的别名才合并，避免不同舞蹈被误判同义词。

## 安全与维护

按每域名限速，限制响应大小、单站 URL 数和 Sitemap 子文件数量，只访问指定域名/其 www 别名，遵守公开的 robots 约束。无法读取 robots 时保守失败。若某站明显禁止自动抓取，请关闭该源或改走许可的数据接口。

公共仓库存储的都是公开 URL、标题、检查时间，不放 API Key 或个人数据。GitHub Actions 的定时运行可能因服务排队而延迟；长期不活动的公开仓库可能暂停 schedule，需定期检查 Actions。