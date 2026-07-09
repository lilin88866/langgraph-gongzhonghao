---
name: wechat-write
description: 本工程本地公众号文案创作辅助。基于 `/workflow/rewrite/candidates` 的公众号候选文章提炼标题、结构和选题参考，再交给 wechat-rewrite 生成可复核草稿；不依赖外部数据密钥。
---

# 公众号文案创作

本 skill 使用 `langgraph-study` 本地候选文章作为写作参考，不访问第三方 API，也不需要额外密钥。

## 工作流程

1. 理解用户想写的主题、受众和核心观点。
2. 用本地候选搜索脚本查找相关公众号文章：

```bash
python3 "$SKILL_PATH/scripts/fetch_gzh_trends.py" --keyword "<关键词>" --max-items 10 --output-format json
```

3. 从候选文章里提炼标题结构、开头钩子、读者收益和常见表达。
4. 结合用户素材生成公众号草稿，或继续交给 `wechat-rewrite` 主链路做改写和合规复核。

## 输出格式

```markdown
### 推荐标题
1. ...

### 正文内容
...

### 核心观点
...

### 推荐标签
#AI #公众号 #改写

### 参考来源
1. [标题](链接) - 作者 - 阅读数
```

## 注意事项

- 参考数据只来自本地候选缓存，不声称全网覆盖。
- 候选不足时，先到 `/workflow/rewrite` 手动更新订阅号文章。
- 发布前必须人工复核事实、版权、图片和敏感表述。
