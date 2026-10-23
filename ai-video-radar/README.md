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
## SEO 关键词复核（KGR / EKGR / KDROI）

2026-10-23 起，每次扫描除原报告外，还会针对最近 7 份日报中的候选生成：

- `reports/seo-latest.csv`（最新 SEO 数据表）
- `reports/YYYY-MM-DD-seo.csv`（每日快照）
- `reports/latest.md` 的“SEO 指标复核”板块

**不伪造任何数据**。没有真实月搜索量、标题竞争数、自然搜索 KD 或 CPC 时，显示“— / 等待真实数据”。Google Ads `competition_index` 不等于 SEO 关键词难度 KD，也不会拿它替代。

指标计算方式：

- KGR = Allintitle 搜索结果估计数 / 月均搜索量（仅 volume > 0 时计算）。
- EKGR = Allintitle × (1 + KD / 100) / 月均搜索量（要求有效 KD）。
- KDROI 分数 = 月均搜索量 × CPC(USD) / (KD + 1)（是 kdroi.io 定义的**机会分数**，不是实际的投资收益率，也不等于别处的 KDROI 百分比）。

经典 KGR 更适用于月量较低（常见约 250 以下）的稳定长尾搜索词。刚出现 1–7 天的新热词，其 12 个月搜索量经常没有或滞后，不能因为缺值或为零直接判定不值得做。

### 无需付费 API：导入真实数据

在 `data/keyword_metrics.csv` 填入第三方数据，列名：

```csv
keyword,volume,allintitle,kd,cpc,source,checked_at,location,language
```

例如（**数字仅说明格式，绝非当前市场实测数据**）：

```csv
example ai dance,120,12,20,1.50,my-own-seo-export,2026-10-23,United States,English
```

可以把 Semrush、Ahrefs 或其他来源整理成这些列：`volume` 为指定市场月均搜索量，`allintitle` 为 Google 同一市场/语言的 allintitle 估算结果数，`kd` 为自然搜索 KD(0–100)，`cpc` 为美元；最好填写源名称、采集日期、地区和语言。重复词请保留一行。默认按规范化后的完整关键词匹配，不会擅自把不同玩法混在一起。

编辑并提交 CSV 会触发 Actions 再次运行（也可以手动 Run workflow），**不需要付费账户**。单独核查某个词：

```bash
python ai-video-radar/seo_metrics.py --root ai-video-radar --keyword "firestarter dance ai" --keyword "dime dime baby ai"
```

终端直接打印实际有的数据和缺失项，同时生成 `reports/seo-manual.csv`。

### 可选：通过 DataForSEO 自动获取（按 API 用量付费）

默认 **关闭**，GitHub Actions 不调用任何付费 SEO API。

在仓库 **Settings → Secrets and variables → Actions**：

1. 添加 Repository secrets `DATAFORSEO_LOGIN` 和 `DATAFORSEO_PASSWORD`，**不要把凭证放进 CSV 或代码中**。
2. 添加 Repository variable `SEO_AUTO_FETCH` = `1`，再设 `SEO_MAX_KEYWORDS_PER_RUN` = `3`（最多允许 10）。
3. 如果还需要 **KGR/EKGR 的 Allintitle 结果**，添加 variable `SEO_FETCH_ALLINTITLE` = `1`。这个开关默认关闭，因为包含 `allintitle:` 的 SERP 请求在 DataForSEO 官方计价中按**5 倍**收费。
4. 默认仅查询 `United States / English` 的 SEO 市场指标；可设 `SEO_LOCATION` / `SEO_LANGUAGE` 以更换市场。**这不会改变主雷达的全球监测范围。**

自动模式使用 DataForSEO Labs Google Keyword Overview 读取 `volume`、`cpc` 和自然搜索 `keyword_difficulty`。单独启用 Allintitle 时通过付费 Google SERP API 读取近似结果数。缓存到 `data/seo_metrics_cache.json`，同一个词默认不自动重复付费抓取；数据无法提供则注明。CSV 同名记录覆盖缓存，便于手动修正。重抓需要清理相应缓存记录再执行。

**注意**：不同 SEO 平台的 KD 计算不同；Allintitle 结果数量是搜索引擎近似估计，不是精确网页计数。不要把 KGR/KDROI 当成谷歌算法或确定收入。建站决策仍需要检查真实 SERP、短视频社媒证据、搜索意图、模型成本和潜在收益。

相关文档：
- DataForSEO Keyword Overview: https://docs.dataforseo.com/v3/dataforseo_labs-google-keyword_overview-live/
- DataForSEO Google Organic Live Advanced: https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/
- kdroi.io 定义：https://www.kdroi.io/faq
