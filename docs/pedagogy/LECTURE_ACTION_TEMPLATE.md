# 每讲行动闭环嵌入模板

> 本文件说明如何在每讲的章末区域嵌入行动闭环。
> 实际修改请改 `docs/lectures/` 下的讲稿源文件后重新运行装配脚本。

## 嵌入位置

在每讲现有的「章末：30 秒复述 · 自测 · 元数据」**之前**，插入以下 4 个区块：

### 区块 1：预习提示（在「本讲开场 90 秒」之前）

```markdown
> 🎯 **开讲前（5 分钟）**：用 [预习向导 Prompt](../../../prompts/per_lectures/LXX_preview.md)
> 让 AI 帮你建立直觉框架，再开始读正文。
```

### 区块 2：数学缓坡旁的 AI 提示（在 §3 关键公式旁）

```markdown
> 🤖 **卡壳？** 把你的困惑发给 AI，用 [苏格拉底引导 Prompt](../../../prompts/02_math_deep_dive/socratic_guide.md)。
```

### 区块 3：动手任务（在「自测」之后、元数据之前）

```markdown
### 动手任务

**任务描述：** [该讲的具体任务]

**产出文件：** `your_notes/experiments/LXX_[任务名].md`

**验收标准：** 文件存在且包含 [具体要求]

> 🤖 **做完后**：用 [批判收尾 Prompt](../../../prompts/per_lectures/LXX_review.md) 做深度加工。
```

### 区块 4：沉淀清单（在元数据之后）

```markdown
### 沉淀清单

学完本讲，你应该产出以下文件：

- [ ] `your_notes/knowledge_cards/LXX_[标题].md` — 知识卡片
- [ ] `your_notes/experiments/LXX_[任务名].md` — 动手任务记录
- [ ] 个人 Prompt 库中新增 [X] 个 Prompt

> 📝 **知识卡片模板**：[templates/knowledge_card_template.md](../../../templates/knowledge_card_template.md)
```

## 示例：第 01 讲的完整嵌入

见 `docs/lectures/01.md` 的改造版本。
