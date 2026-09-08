# Prompt 模板库：AI 教练使用指南

> **核心原则：先自己想，再用 AI。顺序反了就变成"外包大脑"。**

## 什么时候用什么 Prompt

| 场景 | Prompt 文件 | 使用时机 |
|:---|:---|:---|
| 每讲开始前 | [`00_before_each_lecture/preview_guide.md`](./00_before_each_lecture/preview_guide.md) | 读正文之前，花 5 分钟让 AI 帮你建立直觉框架 |
| 读完主路后 | [`01_after_reading/active_recall.md`](./01_after_reading/active_recall.md) | **最重要**。先自己复述，再让 AI 补漏 |
| 想深入理解 | [`01_after_reading/feynman_method.md`](./01_after_reading/feynman_method.md) | 用费曼法"教 AI"，检验自己是否真懂 |
| 公式看不懂 | [`02_math_deep_dive/socratic_guide.md`](./02_math_deep_dive/socratic_guide.md) | 苏格拉底式引导，不直接给答案 |
| 代码实践 | [`03_coding/pair_programming.md`](./03_coding/pair_programming.md) | 结对编程，先自己解释再让 AI 反馈 |
| 每讲结束时 | [`04_end_of_lecture/critical_review.md`](./04_end_of_lecture/critical_review.md) | 批判性收尾：软肋、决策场景、知识连接 |
| 生成知识卡片 | [`04_end_of_lecture/knowledge_card.md`](./04_end_of_lecture/knowledge_card.md) | 把一讲内容压缩成可检索的结构化卡片 |
| 学到里程碑 | [`05_global_review/milestone_review.md`](./05_global_review/milestone_review.md) | 每 5–10 讲做一次全局复盘 |
| 隔几天复习 | [`06_spaced_repetition/review_generator.md`](./06_spaced_repetition/review_generator.md) | 让 AI 根据你的历史复述出复习题 |
| 项目实践 | [`07_project/project_copilot.md`](./07_project/project_copilot.md) | 做项目时的 AI 结对伙伴 |
| 写报告 | [`07_project/report_writer.md`](./07_project/report_writer.md) | 把实验结果整理成结构化报告 |

## 每讲标准流程

```
预习（5min）→ 读主路（30-40min）→ 自己复述（5min）→ AI补漏（10min）→ 动手任务（20min）→ 沉淀（5min）
```

## 使用注意

1. **不要跳过"自己先想"这一步。** 每个Prompt都设计了"先写你的理解"环节，留空是故意的。
2. **Prompt 是起点，不是终点。** 用着用着你会发现哪些适合你、哪些需要改——改出来的就是你自己的 Prompt 库。
3. **推荐工具：** Claude（长文理解强）、ChatGPT/GPT-4o（推理好）、Cursor（代码实践时）。
4. **沉淀比收藏重要。** 用完一个 Prompt，把产出存到 `your_notes/`，不要只截图不整理。
