# 本地公众号搜索数据格式

`wechat-search` 的本工程版从 `/workflow/rewrite/candidates` 读取候选文章。

## JSON 输出

```json
{
  "keyword": "AI Agent",
  "source": "langgraph-study local wechat-download-api",
  "articles": [],
  "latestHotArticles": [],
  "summary": {}
}
```

## 文章字段

- `title`
- `author`
- `url`
- `clicksCount`
- `likeCount`
- `commentCount`
- `totalScore`
- `summary`

无需配置外部数据密钥。
