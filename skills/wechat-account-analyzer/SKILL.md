---
name: wechat-account-analyzer
description: 本工程本地公众号账号诊断。基于 `/workflow/rewrite/candidates` 中匹配账号的文章，统计阅读、点赞、评论和互动率，输出轻量运营建议；不依赖外部数据密钥。
---

# 公众号账号诊断

本 skill 已适配 `langgraph-study` 本地数据链路。它不访问第三方账号指数 API，只基于当前工程拉取到的候选文章做轻量分析。

## 使用方式

```bash
# 按公众号名称诊断
python3 "$SKILL_PATH/scripts/wechat_analyzer.py" "公众号名称"

# 强制刷新候选后诊断
python3 "$SKILL_PATH/scripts/wechat_analyzer.py" "公众号名称" --refresh

# 输出 JSON
python3 "$SKILL_PATH/scripts/wechat_analyzer.py" "公众号名称" --json
```

## 输出结构

1. 账号信息
2. 综合评分
3. 近期待选文章数据
4. 优化建议
5. 行业对标说明

## 评分说明

本地版综合评分来自：

- 当前候选文章数量
- 平均阅读数
- 点赞和评论形成的互动率

它适合做本地候选池里的轻量判断，不代表全网行业评级。

## 注意

- 若无数据，请先在 `/workflow/rewrite` 手动更新订阅号文章。
- 候选缓存不一定覆盖账号全部历史文章。
- 诊断结论用于运营参考，发布前仍需人工判断。
