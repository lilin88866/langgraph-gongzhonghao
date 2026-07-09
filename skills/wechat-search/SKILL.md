---
name: wechat-search
description: 本工程本地公众号候选文章搜索。按关键词从 `/workflow/rewrite/candidates` 中筛选文章，辅助选题、改写和热点分析；不依赖外部数据密钥。
dependency:
  python:
    - 纯标准库
---

# 公众号热门文章查询

本 skill 已改成本工程本地版：读取 `langgraph-study` 的 `/workflow/rewrite/candidates` 候选文章，不访问第三方数据服务，也不需要外部数据密钥。

## 前置条件

1. 启动服务：`python scripts/start_dev_server.py`
2. 打开 `/workflow/rewrite`
3. 点击“手动更新订阅号文章”，让本地候选缓存有数据

## 使用方式

```bash
# 按关键词搜索本地候选
python3 "$SKILL_PATH/scripts/fetch_gzh_trends.py" --keyword "AI Agent" --output-format markdown

# 展示当前候选热门
python3 "$SKILL_PATH/scripts/fetch_gzh_trends.py" --keyword "" --max-items 20 --output-format markdown

# 强制刷新后搜索
python3 "$SKILL_PATH/scripts/fetch_gzh_trends.py" --keyword "大模型" --refresh --output-format json
```

## 输出字段

- `articles`：匹配关键词的候选文章
- `latestHotArticles`：当前本地候选热门文章
- `summary`：本工程候选缓存摘要

## 使用建议

- 搜不到时，先在 `/workflow/rewrite` 手动更新订阅号文章。
- 本地排序以候选的阅读数和热度分为主，不声称覆盖全网。
- 文章改写继续使用 `wechat-rewrite` 主链路。
