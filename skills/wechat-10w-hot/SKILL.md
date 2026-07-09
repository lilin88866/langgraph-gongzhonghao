---
name: wechat-10w-hot
description: 本工程本地公众号高热文章榜。按 `/workflow/rewrite/candidates` 中的阅读数和热度分排序，生成候选榜单和 HTML 报告；不依赖外部数据密钥。
---

# 公众号高热文章榜

本 skill 是本工程本地版，不再使用第三方 10w+ 数据接口。它读取当前项目候选文章，按阅读数和热度分生成榜单。

## 前置条件

- 启动 `langgraph-study` 服务
- 在 `/workflow/rewrite` 手动更新订阅号文章

## 常用命令

```bash
# 总榜
python3 "$SKILL_PATH/scripts/fetch_hot_articles.py" --type "总排名" --mode preview --limit 10 --output-format markdown

# 按关键词/领域筛选
python3 "$SKILL_PATH/scripts/fetch_hot_articles.py" --type "科技数码" --limit 20 --output-format markdown

# 输出 HTML
python3 "$SKILL_PATH/scripts/fetch_hot_articles.py" --type "AI" --output-format html --output "本地高热榜.html"
```

## 输出策略

- 初次展示前 10-20 条候选。
- 需要更多时增加 `--limit`。
- 本地版不承诺文章达到 10w+，只展示候选数据中的阅读数。

## 适用场景

- 快速查看本地订阅号候选中哪些文章更热。
- 为 `wechat-rewrite` 选择优先改写对象。
- 生成内部选题参考榜单。
