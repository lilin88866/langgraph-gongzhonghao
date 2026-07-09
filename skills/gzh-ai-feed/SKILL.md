---
name: gzh-ai-feed
description: 本工程本地 AI 公众号信息源。读取 langgraph-study `/workflow/rewrite/candidates` 候选文章，按阅读量和热度整理 AI 公众号日报，不依赖外部数据密钥。
---

# AI公众号信息源

读取本工程已经拉取的公众号候选文章，按阅读量和热度找出适合改写、选题参考和日报整理的 AI 内容。

---

## 能力概述

- **本地候选整理**：从 `/workflow/rewrite/candidates` 读取候选文章，按阅读量和热度排序
- **智能聚类**：自动从当天内容中发现话题方向（Agent、大模型、AI绘画...），每天的分类由内容决定
- **终端表格**：分类 + 标题 + 作者 + 阅读/点赞/评论数，一目了然
- **可视化日报**：深色主题 HTML，封面图、互动数据、文章直链、日期导航
- **无外部鉴权**：不使用外部数据密钥，依赖工程已配置的 `wechat-download-api`

---

## 使用方式

```bash
# 生成本地候选日报
python3 "$SKILL_PATH/assets/daily_report.py"

# 自定义关注方向
python3 "$SKILL_PATH/assets/daily_report.py" --keywords "AI Agent,RAG,LangChain,Prompt"

# 强制刷新本地候选后生成
python3 "$SKILL_PATH/assets/daily_report.py" --refresh
```

生成的 HTML 日报保存在 `~/Downloads/QoderReports/`。终端同步输出文章表格。

---

## 首次使用

1. 启动本工程开发服务：`python scripts/start_dev_server.py`
2. 打开 `/workflow/rewrite`，登录并手动更新订阅号文章
3. 运行本 skill 脚本生成日报

---

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--keywords` | 关注的话题方向，逗号分隔 | `AI,人工智能,大模型,GPT,Agent,AI绘画` |
| `--count` | 扫描文章数量 | `200` |
| `--date` | 兼容参数，本地候选接口忽略具体日期 | — |
| `--output-dir` | 输出目录 | `~/Downloads/QoderReports` |
| `--no-open` | 不自动打开浏览器 | — |

---

## 依赖

```bash
pip3 install requests
```

---

## 常见问题

**Q：日报里的分类是怎么来的？**
A：完全由当天内容决定。从文章话题、分类标签和标题关键词中自动识别聚类，每天的热点方向不同。

**Q：怎么看到更多文章？**
A：先在 `/workflow/rewrite` 手动更新订阅号文章，再用 `--count` 扩大展示数量。

**Q：HTML 搜索怎么用？**
A：本地版生成静态 HTML，可在浏览器中使用页面搜索。

**Q：搜索和日报是什么关系？**
A：日报来自当前本地候选缓存；需要新数据时先刷新 `/workflow/rewrite`。

**Q：订阅后日报存在哪？**
A：默认 `~/Downloads/QoderReports/`。

