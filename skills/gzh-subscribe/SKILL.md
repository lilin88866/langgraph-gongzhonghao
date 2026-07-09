---
name: gzh-subscribe
description: 本工程本地公众号订阅追踪。管理关注账号名称，并基于 langgraph-study `/workflow/rewrite/candidates` 候选文章生成订阅日报；不依赖外部数据密钥。
---

# 公众号订阅追踪

这个 skill 适配 `langgraph-study` 当前工程，使用本地 `wechat-download-api` 和 `/workflow/rewrite` 候选文章缓存，不使用外部数据密钥或第三方数据服务。

## 前置条件

1. 启动本工程服务：`python scripts/start_dev_server.py`
2. 打开 `/workflow/rewrite`，完成微信登录并点击“手动更新订阅号文章”
3. 使用本 skill 管理关注账号和生成日报

## 常用命令

```bash
# 添加订阅账号名称
python3 "$SKILL_PATH/assets/subscribe.py" add "公众号名称" --category "关注账号"

# 查看订阅
python3 "$SKILL_PATH/assets/subscribe.py" list

# 从本地候选文章里筛选订阅账号相关内容
python3 "$SKILL_PATH/assets/subscribe.py" fetch

# 生成 HTML 日报
python3 "$SKILL_PATH/assets/subscribe.py" report
```

## 输出

- 终端 Markdown 表格：标题、作者、阅读、热度分、链接
- HTML 日报：默认保存到 `~/Downloads/QoderGzhReports/`

## 注意

- 本地版只读取当前工程候选数据，不直接订阅第三方平台。
- 如果没有数据，先在 `/workflow/rewrite` 手动更新订阅号文章。
- 发布或改写前仍需人工复核来源、事实、版权和合规风险。
