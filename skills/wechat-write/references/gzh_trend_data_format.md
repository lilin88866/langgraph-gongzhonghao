# 本地公众号候选数据格式

本工程版 `wechat-write` 使用 `skills/local_wechat_feed.py` 读取 `/workflow/rewrite/candidates`。

## 主要字段

| 字段 | 说明 |
| --- | --- |
| `title` | 文章标题 |
| `author` | 公众号/作者 |
| `url` | 原文链接 |
| `clicksCount` | 阅读数 |
| `likeCount` | 点赞数 |
| `commentCount` | 评论数 |
| `totalScore` | 本地热度分 |
| `summary` | 候选准备状态说明 |

## 注意

- 数据来自本工程配置的 `wechat-download-api`。
- 不使用第三方数据服务。
- 不需要额外的外部数据密钥。
