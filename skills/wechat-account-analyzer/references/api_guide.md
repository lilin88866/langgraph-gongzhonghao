# 本地接口参考

```text
GET /workflow/rewrite/candidates
```

查询参数：

| 参数 | 说明 |
| --- | --- |
| `refresh` | 是否强制刷新候选 |
| `cache_only` | 是否只读缓存 |

本地脚本通过 `LANGGRAPH_STUDY_BASE_URL` 定位服务，默认 `http://127.0.0.1:8000`。
