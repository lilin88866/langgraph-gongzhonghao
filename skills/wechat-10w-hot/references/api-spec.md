# 本地候选接口说明

本工程版 `wechat-10w-hot` 使用本地服务：

```text
GET /workflow/rewrite/candidates?refresh=false&cache_only=true
```

可通过环境变量覆盖服务地址：

```bash
export LANGGRAPH_STUDY_BASE_URL=http://127.0.0.1:8000
```

## 返回用途

- 按阅读数和本地热度分排序。
- 生成 Markdown 或 HTML 候选榜单。
- 不声称覆盖全网 10w+ 文章，只反映本地订阅号候选池。
