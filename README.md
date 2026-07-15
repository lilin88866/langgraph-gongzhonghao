# AI Hotspot Multi-Agent Study

This project sketches a LangGraph-style multi-agent workflow for tracking AI-related hot topics across Douyin, Xiaohongshu, WeChat Official Accounts, and Toutiao-compatible content APIs.

## MVP Scope

- Discover data source plans from a product-oriented research brief.
- Collect search results, account profiles, article details, and work lists through platform-specific agents.
- Normalize platform payloads into a shared content schema.
- Filter AI-related content, score cross-platform hotness, cluster trends, and produce product insight cards.
- Generate a traceable report that keeps source links and raw payloads available for review.

## Design Docs

- [AI 热点数据多 Agent 方案](docs/ai_hotspot_agent_plan.md): product decomposition, agent responsibilities, workflow, MVP scope, and code mapping.

## Package Layout

- `app/schemas/`: shared state and domain models.
- `app/agents/`: focused agent nodes with explicit inputs and outputs.
- `app/tools/`: content API client protocols and mock adapters.
- `app/graphs/`: workflow assembly and execution.
- `app/config/`: MVP platform and scoring defaults.
- `external/`: local external service definitions, not vendored Python package code.
- `scripts/`: helper scripts for starting and checking external services.

Run the demo workflow:

```bash
python -m app.graphs.ai_hotspot_graph
```

## 工程流程总览

本工程可以按四条主线理解：开发服务启动流、AI 热点多 Agent 流、微信公众号改写工作台流，以及 skills 辅助工具流。

### 1. 开发服务启动流

推荐入口是：

```bash
python scripts/start_dev_server.py
```

启动后会完成以下动作：

1. 读取 `.env` 配置。
2. 启动或检查外部 `wechat-download-api` 服务。
3. 启动公众号订阅文章刷新调度。
4. 启动 `app.server:app` FastAPI 服务。
5. 暴露工作台页面和 API，例如 `/workflow/rewrite`、`/workflow/article/html`、`/workflow/video/agent`、`/workflow/graph`。

### 2. AI 热点多 Agent 主流程

完整热点分析链路是：

```text
任务调度
  -> 数据源发现
  -> 平台采集
  -> 数据标准化
  -> AI 相关性识别
  -> 热度评分
  -> 趋势分析
  -> 产品洞察
  -> 选题策略
  -> 质量控制
  -> 报告生成
  -> 人工审核
```

主要映射关系：

| 阶段 | 模块 |
| --- | --- |
| 任务调度 | `app/agents/task_router.py` |
| 数据源发现 | `app/agents/source_discovery.py` |
| 平台采集 | `app/agents/platform_collection.py` |
| 数据标准化 | `app/agents/normalization.py` |
| AI 相关性识别 | `app/agents/ai_relevance.py` |
| 热度评分 | `app/agents/hotness_scoring.py` |
| 趋势分析 | `app/agents/trend_analysis.py` |
| 产品洞察 | `app/agents/product_insight.py` |
| 选题策略 | `app/agents/content_strategy.py` |
| 质量控制 | `app/agents/quality_control.py` |
| 报告生成 | `app/agents/report_generation.py` |

workflow 入口在 `app/graphs/ai_hotspot_graph.py`。安装 LangGraph 时可编译真实 graph；未安装时使用顺序执行 fallback，方便本地调试。

### 3. 微信公众号数据下载流

微信公众号数据由 `app/tools/wechat_download_api.py` 对接本地自建 `wechat-download-api` 服务。这个文件只做底层下载和字段标准化，不混入热榜、账号评分或 HTML 生成逻辑。

主要链路：

```text
wechat-download-api
  -> 搜公众号 / 订阅公众号 / 读取订阅列表
  -> 拉文章列表
  -> 拉文章详情
  -> 标准化成 RawContent / NormalizedContent
  -> 写入本地缓存和 workflow state
```

相关缓存：

- `.cache/wechat_article_lists`：公众号文章列表缓存。
- `.cache/wechat_article_details`：文章详情缓存。
- `.cache/workflow_rewrite_state.json`：改写工作台候选 workflow 缓存。

### 4. 微信公众号改写工作台流

浏览器入口：

```text
/workflow/rewrite
```

候选文章来源：

| 接口 | 用途 |
| --- | --- |
| `/workflow/rewrite/candidates` | 默认改写候选 |
| `/workflow/wechat/articles` | 今日订阅流，默认读本地 workflow 缓存 |
| `/workflow/rewrite/hot-candidates` | `wechat-10w-hot` 高热榜 |
| `/workflow/rewrite/knowledge-candidates` | 知识型优先候选 |

手动更新订阅号文章时走：

```text
/workflow/rewrite/subscriptions/refresh/stream
```

更新流程：

```text
清理旧缓存
  -> 调 wechat-download-api 拉订阅文章
  -> 标准化
  -> AI 相关性识别
  -> 热度评分
  -> 质量控制
  -> 写 workflow 缓存
  -> 返回候选列表
```

用户选择一篇文章改写时走：

```text
/workflow/rewrite/selected/stream
```

改写流程：

```text
读取候选缓存
  -> 根据 content_id 找文章
  -> 补拉全文详情
  -> 提取原文图片
  -> 图片 OCR 增强
  -> 调 wechat-rewrite Agent
  -> 长度和相似度检查
  -> 质量控制
  -> 返回 Markdown 和 HTML
```

改写核心在 `app/agents/wechat_article_writing.py`，主要负责生成原文骨架、构建改写 prompt、调用 Qwen 或 fallback、本地兜底稿、相似度检测、长度检测和合规报告。

### 5. Skills 辅助工具流

`skills/local_wechat_feed.py` 是当前本地微信数据的统一适配层，供热榜、HTML 报告和账号分析复用。

支持的数据源：

| source | 数据来源 |
| --- | --- |
| `auto` | 自动优先尝试 feed / hot / cache / download |
| `cache` | `/workflow/rewrite/candidates` |
| `feed` | `/workflow/wechat/articles` |
| `hot` | `/workflow/rewrite/hot-candidates` |
| `download` | 直接调 `WechatDownloadApiClient` |

常用命令：

```bash
# 本地热榜 Markdown
python3 skills/wechat-10w-hot/scripts/fetch_hot_articles.py --type AI --source feed --limit 10 --output-format markdown

# 生成本地热榜 HTML
python3 skills/wechat-10w-hot/scripts/generate_hot_html.py --source feed --type AI --limit 10 --output 本地高热榜.html

# 分析某个公众号账号
python3 skills/wechat-account-analyzer/scripts/wechat_analyzer.py 智能体AI --source auto --limit 100
```

### 6. 视频生成辅助流

视频入口是 `/workflow/video/agent`。流程是：

```text
用户输入视频任务
  -> 判断任务类型
  -> 搜教材 PDF 或使用本地素材
  -> 生成视频脚本
  -> 生成配音、字幕、分镜
  -> 调 video-renderer / Remotion
  -> 输出视频、音频、字幕和帧图
  -> 人工复核
```

### 总体数据流

```text
外部数据源
  -> app/tools/* 下载适配器
  -> RawContent
  -> NormalizationAgent
  -> NormalizedContent
  -> AIRelevanceAgent
  -> HotnessScoringAgent
  -> TrendAnalysisAgent
  -> ProductInsightAgent
  -> ContentStrategyAgent
  -> QualityControlAgent
  -> Report / Article / Rewrite / Hot List / Account Analysis / Video
```

一句话总结：本工程先把微信公众号等平台内容下载成本地统一数据，再通过多 Agent 做 AI 相关性、热度、趋势和质量判断，最后把结果用于公众号改写、热榜、账号分析、报告和视频生成。

## Development Server

Install the optional server dependencies:

```bash
python -m pip install -e ".[server]"
```

Install video rendering dependencies if you use `/workflow/video`:

```bash
python -m pip install -e ".[video]"
python -m pip install nodeenv
python scripts/setup_remotion_node.py
```

Start both the external `wechat-download-api` service and the `langgraph-study` API server:

```bash
python scripts/start_dev_server.py
```

The script does three things:

- Creates `.env` files from examples when missing.
- Starts `external/wechat-download-api` with Docker Compose.
- Starts a WeChat refresh scheduler that fetches subscribed account history in batches every 2 hours by default.
- Starts `app.server:app` with `uvicorn --reload`, watching `app/`, `scripts/`, and `external/`.

Useful endpoints:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/external/wechat/health
curl -X POST http://localhost:8000/workflow/run
curl http://localhost:8000/workflow/article
```

Open `http://localhost:8000/workflow/article/html` to read the WeChat article draft generated by the article-writing agent from the selected hotspot evidence.

Open `http://localhost:8000/workflow/rewrite` to use the visual rewrite workspace. It shows hot WeChat articles with red/yellow/green selection lights, lets a user choose one article, then sends that article to the WeChat rewrite agent for a publishable rewrite.

Open `http://localhost:5000/login.html` once after the WeChat service starts, then scan the QR code before running real WeChat collection.

### Platform Setup

Run the platform checker before using the full workflow:

```bash
python scripts/check_platform.py
```

#### macOS

Recommended setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[server,graph,video]"
cd video-renderer && npm install && cd ..
python scripts/start_dev_server.py
```

Prerequisites:

- Docker Desktop for `wechat-download-api` and optional Docker Ollama.
- Node.js/npm for Remotion 3.0 video rendering.
- A configured `.env` copied from `.env.example`.

#### Windows

Windows is supported best through WSL2. Recommended setup inside WSL2:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[server,graph,video]"
cd video-renderer && npm install && cd ..
python scripts/start_dev_server.py
```

Use Docker Desktop with the WSL2 backend enabled. Native PowerShell can run parts of the project, but WSL2 is the safer path for Docker services, local paths, and development scripts.

If you run natively on Windows, use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

## Real Data Clients

The workflow uses mock data by default. Configure platform API environment variables to switch a platform to a real HTTP client:

```bash
export DOUYIN_API_BASE_URL="https://provider.example.com/douyin"
export DOUYIN_API_KEY="..."
export XIAOHONGSHU_API_BASE_URL="https://provider.example.com/xiaohongshu"
export XIAOHONGSHU_API_KEY="..."
export WECHAT_API_BASE_URL="https://provider.example.com/wechat"
export WECHAT_API_KEY="..."
export TOUTIAO_API_BASE_URL="https://provider.example.com/toutiao"
export TOUTIAO_API_KEY="..."
```

Optional endpoint overrides:

```bash
export DOUYIN_SEARCH_QUERY_PATH="/v1/search"
export DOUYIN_ACCOUNT_INFO_PATH="/v1/accounts"
export DOUYIN_ARTICLE_DETAIL_PATH="/v1/articles"
export DOUYIN_WORK_LIST_PATH="/v1/works"
```

Use the same pattern for `XIAOHONGSHU_*`, `WECHAT_*`, and `TOUTIAO_*`. Set `CONTENT_API_REQUIRE_REAL=1` to disable mock fallback.

### Xiaohongshu via ForgeRSS

Use [ForgeRSS](https://github.com/tmwgsicp/ForgeRSS) to generate a Xiaohongshu RSS feed, then let `langgraph-study` read the generated XML. This keeps ForgeRSS as an external crawler under `external/ForgeRSS`, similar to `external/wechat-download-api`.

Set up ForgeRSS:

```bash
python scripts/setup_forgerss.py
```

ForgeRSS requires a logged-in browser profile for Xiaohongshu:

```bash
cd external/ForgeRSS
.venv/bin/python -m generators.social.xiaohongshu.scraper --login
```

On native Windows, use:

```powershell
cd external\ForgeRSS
.\.venv\Scripts\python.exe -m generators.social.xiaohongshu.scraper --login
```

Generate the Xiaohongshu feed:

XHS_USER_ID="https://www.xiaohongshu.com/user/profile/<user_id>?xsec_token=..." \
  python ../../scripts/run_forgerss_xiaohongshu.py
```

Then configure `langgraph-study`:

```bash
XIAOHONGSHU_PROVIDER=forgerss
XIAOHONGSHU_FORGERSS_FEED_FILE=external/ForgeRSS/feeds/feed_xiaohongshu_user.xml
# Or read from an HTTP-served feed:
# XIAOHONGSHU_FORGERSS_FEED_URL=http://localhost:8001/feeds/feed_xiaohongshu_user.xml
```

Check login/feed status:

```bash
python scripts/check_forgerss_xiaohongshu.py
```

### Self-Hosted WeChat Data

Use a self-hosted [wechat-download-api](https://github.com/tmwgsicp/wechat-download-api) service for free WeChat article data integration.

`langgraph-study` manages it as an external HTTP service under `external/wechat-download-api`. The third-party source code is not copied into the Python package; the workflow talks to the service through `WECHAT_DOWNLOAD_API_BASE_URL`.

The recommended development server starts this service automatically:

```bash
python scripts/start_dev_server.py
```

If you run `uvicorn app.server:app` directly, the FastAPI startup hook also starts the local `wechat-download-api` when `WECHAT_PROVIDER=wechat_download`, `WECHAT_DOWNLOAD_API_BASE_URL` points to `localhost`, and `WECHAT_DOWNLOAD_API_AUTO_START` is not disabled.

You can also start the external service manually:

```bash
python scripts/start_wechat_download_api.py
```

Then open `http://localhost:5000/login.html` and scan the QR code with a WeChat Official Account admin account.

Check the service:

```bash
python scripts/check_wechat_download_api.py
```

Configure the workflow by copying `.env.example` to `.env` and adjusting the base URL:

```bash
cp .env.example .env
# Edit WECHAT_DOWNLOAD_API_BASE_URL if your service is not on localhost:5000.
python -m app.graphs.ai_hotspot_graph
```

Recommended `.env` values:

```bash
CONTENT_API_REQUIRE_REAL=1
WECHAT_PROVIDER=wechat_download
WECHAT_DOWNLOAD_API_BASE_URL=http://localhost:5000
WECHAT_DOWNLOAD_API_AUTO_START=1
WECHAT_DOWNLOAD_DEFAULT_FAKEIDS=
WECHAT_ACCOUNT_AUTO_SUBSCRIBE=0
WECHAT_ACCOUNT_DISCOVERY_LIMIT=20
WECHAT_ACCOUNT_DISCOVERY_KEYWORDS=AI,AIGC,Agent,智能体,人工智能,Claude,Claude Code,ChatGPT,OpenAI,DeepSeek,Gemini,Qwen,通义千问,大模型,生成式AI,AI工具,AI产品,AI应用,AI编程,AI自动化,提示词,Prompt,promot,LangGraph,LangChain,langchain,loop,RAG,MCP
WECHAT_ACCOUNT_MATCH_KEYWORDS=AI,agent,人工智能,Claude,claud,智能体,大模型
WECHAT_COLLECTION_DISCOVERED_ACCOUNT_LIMIT=10
WECHAT_COLLECTION_INCLUDE_SEARCH_PLANS=0
# Optional. Leave unset to use skills/wechat-rewrite.
# WECHAT_REWRITE_SKILL_DIR=skills/wechat-rewrite
XIAOHONGSHU_PROVIDER=forgerss
XIAOHONGSHU_FORGERSS_FEED_FILE=external/ForgeRSS/feeds/feed_xiaohongshu_user.xml
QWEN_API_KEY=your_dashscope_api_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.7-plus
QWEN_TIMEOUT_SECONDS=300
QWEN_FALLBACK_API_KEY=ollama
QWEN_FALLBACK_BASE_URL=http://localhost:11434/v1
QWEN_FALLBACK_MODEL=qwen2.5:7b
QWEN_FALLBACK_TIMEOUT_SECONDS=300
WECHAT_AUTO_REFRESH=1
WECHAT_REFRESH_INTERVAL_SECONDS=14400
WECHAT_REFRESH_HISTORY_COUNT=20
WECHAT_REFRESH_REQUEST_TIMEOUT_SECONDS=300
WECHAT_REFRESH_BATCH_SIZE=2
WECHAT_REFRESH_USE_RSS_POLL=0
```

The adapter maps workflow dimensions to the self-hosted API:

- `ACCOUNT_INFO` -> `GET /api/public/searchbiz`
- `WORK_LIST` -> `GET /api/public/articles`
- `SEARCH_QUERY` -> `GET /api/public/articles/search`, or first `GET /api/public/searchbiz` when no fakeid is configured
- `ARTICLE_DETAIL` -> `POST /api/article`

Set `CONTENT_API_REQUIRE_REAL=1` in `.env` to disable mock fallback. The app loads `.env` automatically when it starts.

When `WECHAT_PROVIDER=wechat_download`, `PlatformCollectionAgent` delegates WeChat source plans to `WechatDownloadCollectionAgent`, which checks the external service health and then calls `WechatDownloadApiClient`.

`WechatAccountDiscoveryAgent` runs before collection. It searches WeChat accounts by task keywords plus `WECHAT_ACCOUNT_DISCOVERY_KEYWORDS`, filters accounts matching AI/model/Agent/workflow keywords, and only calls `POST /api/rss/subscribe` when `WECHAT_ACCOUNT_AUTO_SUBSCRIBE=1` is explicitly enabled. Discovered accounts are shown in the report under `自动发现公众号`. Collection reads articles from the first `WECHAT_COLLECTION_DISCOVERED_ACCOUNT_LIMIT` discovered accounts so one report request does not try to fetch every subscribed account. When discovered accounts are available, search plans are skipped by default; set `WECHAT_COLLECTION_INCLUDE_SEARCH_PLANS=1` to run keyword article search as well.

`WechatArticleWritingAgent` uses project-local publishing skills under `skills/` by default. If you need an override, set `WECHAT_REWRITE_SKILL_DIR` to a relative or absolute skill folder such as `skills/wechat-rewrite`. The main rewrite rules come from `wechat-rewrite`, and the rewrite prompt also includes the local workflow skills: `wechat-ai-topic-selector`, `title-generator`, `xiaolin-rewrite`, `source-organizer`, `image-caption-prompt`, and `wechat-prohibited-word`. Together they contribute topic selection, title optimization,公众号改写 format, 小林笔记式结构, source/copyright checks, image prompt suggestions, and pre-publish risk checks. The model client is OpenAI-compatible: configure `QWEN_API_KEY`, `QWEN_BASE_URL`, and `QWEN_MODEL` for DashScope or another compatible cloud provider. To fall back to local Ollama only when the cloud model returns a quota/balance error, configure `QWEN_FALLBACK_API_KEY=ollama`, `QWEN_FALLBACK_BASE_URL=http://localhost:11434/v1`, `QWEN_FALLBACK_MODEL=qwen2.5:7b`, and leave `QWEN_FALLBACK_AUTO_START=1`. The development server starts Docker Ollama and pulls the fallback model automatically; set `QWEN_FALLBACK_AUTO_PULL=0` if you only want to start the container. Without `QWEN_API_KEY`, the API returns a clear "model not configured" status plus the prompt instead of pretending a model rewrite happened.

Check the local Ollama rewrite model:

```bash
# Docker option, also run automatically by scripts/start_dev_server.py when enabled.
python scripts/start_ollama_docker.py

# Then verify the OpenAI-compatible endpoint.
python scripts/check_ollama_model.py
```

Auto-refresh downloaded WeChat articles:

```bash
# Run once now.
python scripts/refresh_wechat_downloads.py --once

# Run forever, defaults to every 2 hours.
python scripts/refresh_wechat_downloads.py
```

The dev server starts this scheduler automatically. Set `WECHAT_AUTO_REFRESH=0` to disable it. The scheduler fetches recent history for subscribed accounts through `POST /api/admin/history/fetch`. It processes accounts in batches (`WECHAT_REFRESH_BATCH_SIZE=2`) and stores its cursor in `.wechat_refresh_state.json`, so each cycle continues from the previous account. Some refreshes can take a few minutes, so `WECHAT_REFRESH_REQUEST_TIMEOUT_SECONDS` defaults to 300 seconds. Set `WECHAT_REFRESH_USE_RSS_POLL=1` if you also want to trigger `POST /api/rss/poll`.

Run the local regression tests without a live WeChat service:

```bash
python -m unittest discover -s tests
```

Run an end-to-end smoke test against a live `wechat-download-api` service:

```bash
CONTENT_API_REQUIRE_REAL=1 \
WECHAT_PROVIDER=wechat_download \
WECHAT_DOWNLOAD_API_BASE_URL=http://localhost:5000 \
python -m app.graphs.ai_hotspot_graph
```

If search returns accounts but no articles, set known account IDs to avoid discovery drift:

```bash
WECHAT_DOWNLOAD_DEFAULT_FAKEIDS=fakeid_1,fakeid_2
```

Common failure points:

- `missing_client:wechat`: `WECHAT_PROVIDER=wechat_download` or `WECHAT_DOWNLOAD_API_BASE_URL` is missing.
- `fetch_failed:wechat:*`: the self-hosted service is not running, login expired, or the endpoint returned non-JSON/HTTP error.
- Empty `ARTICLE_DETAIL` results: default source plans do not include article URLs; detail fetching works when `SourcePlan.metadata["url"]` or `query` is a WeChat article URL.
