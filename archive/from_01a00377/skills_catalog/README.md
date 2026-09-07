# Guo Lab Knowledge Base 2026 — Research Agent Skills

此目录从 [`sunccchengze/-SKILL-`](https://github.com/sunccchengze/-SKILL-/tree/arena/019ffbe9-skill) 选取并导入 **100 个科研技能包**，并补充 **19 个记忆与搜索技能包**。

## 使用原则

- 按科研任务选择 1 个主技能、0–2 个支撑技能和 0–1 个审查技能；不要同时加载全部技能。
- 技能是工作方法，不取代研究者对数据、引文、实验、统计与结论的核验责任。
- 使用任何上游材料前，请核对其许可证、版本与适用边界。

## 来源与数量

- `academic-research-skills`：4
- `nature-skills`：19
- `paper-craft-skills`：3
- `paperspine`：1
- `research-paper-writing-skills`：1
- `aris`：20
- `scientific-agent-skills`：25
- `ai-research-skills`：15
- `hermes-agent`：12

## 目录说明

- `skills/<source>/<skill>/SKILL.md`：可直接读取的技能入口；相关上游包文件一并保留。
- `catalog/research-skills-100.json`：100 项科研技能的来源、固定提交、Git blob 校验值及本地安装路径清单。
- `catalog/memory-and-search-skills.json`：19 项记忆与搜索技能的来源、本地路径与 SHA-256 校验值清单。
- `skills/memory/`：长期记忆、知识库、会话归档与记忆健康管理能力。
- `skills/search/`：深度研究、学术检索、网页检索、多源信息发现与证据检索能力。

## 覆盖范围

文献发现与综述、研究构思与假设、实验设计与执行、统计与数据分析、论文写作与编译、图表与学术汇报、同行评审与回复、可复现 ML/AI 研究，以及生物信息、药物发现等专项研究能力；另有长期记忆、知识库管理和多源检索能力。

## 来源固定版本

导入时使用上游技能库分支 `arena/019ffbe9-skill`（提交 `65eaab17aae5434541463e9e1079904600aa45fc`）的科研来源锁定版本。
