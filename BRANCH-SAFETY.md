# 🩸 Arena Agent 生存手册（Mr.GUO 版）

> 面向所有进入本仓库的 AI agent 与人类协作者。**动手之前先读完这页。**  
> 核心内容学自 [`sunccchengze/SCZ_Archived`](https://github.com/sunccchengze/SCZ_Archived) 的 `BRANCH-SAFETY.md`  
> （其源头又来自 `turbine-blade-ai-platform` 的 `HANDOFF.md` 实战踩坑）。  
> **本仓于 2026-09-07 引入并首次实测快进推送。**

---

# 第一部分：⭐ 快进推送 —— 把内容送上 main 而不碰 PR

**这是本页最重要的操作。** 它让你既能把成果合进 `main`，又完全不触发  
「PR 合并/关闭 → 会话远程通道被关」这个陷阱（原因见第二部分铁律 2）。

## 一行命令

```bash
git push origin <你的分支>:main
```

就这一条。**不开 PR、不合 PR、不关 PR**，`main` 直接前进到你分支的位置。  
会话通道毫发无损，你可以继续干活。

## 为什么安全

| | PR 合并 | 快进推送 |
|---|---|---|
| `main` 拿到你的内容 | ✅ | ✅ |
| 触发 Arena 关闭远程通道 | 🩸 **会** | ✅ 不会 |
| 之后还能 push / gh | ❌ | ✅ 能 |
| 留下 PR 记录 / review | ✅ | ❌ 没有 |
| 产生 merge commit | 会 | 不会（线性历史） |

`git push <分支>:main` 走的是**纯 Git 协议**，GitHub 那边只是把 `main`  
这个 ref 往前挪一格，压根没有「PR 被合并/关闭」这个事件，自然不会触发关闭通道。

## 完整操作流程（照抄即可）

```bash
# ── 0. 前置：确认工作区干净、提交都已 commit ──────────────
git status --short

# ── 1. 自检：main 必须是你分支的祖先，否则不能快进 ─────────
git fetch origin main
git merge-base --is-ancestor origin/main HEAD \
  && echo "✅ FF 安全，可以推" \
  || echo "❌ main 有你没有的提交，先 rebase"

# ── 2. 先推自己的分支（保命，铁律 1：绝不攒提交）───────────
git push origin <你的分支>

# ── 3. 快进推送到 main ────────────────────────────────
git push origin <你的分支>:main

# ── 4. 核对：两个 ref 应指向同一个 commit ──────────────────
git ls-remote --heads origin | sed 's#refs/heads/##'
```

## 万一第 1 步说「需要先 rebase」

说明 `main` 上有你分支没有的提交，快进不成立。**不要用 `-f` 强推**——  
那会覆盖掉 `main` 上别人的工作。正确做法：

```bash
git fetch origin main
git rebase origin/main      # 把你的提交挪到 main 之上
# 解决冲突后
git push origin <你的分支>          # 你自己的分支必要时可 -f
git push origin <你的分支>:main     # 再快进
```

## 边界与代价（诚实说明）

- **没有 PR 记录、没有 code review。** 对单人 / Arena 会话仓很合适。
- **要求线性历史。** `main` 必须是你分支的祖先。
- **不适用于受保护分支。** 若 `main` 开了 branch protection 要求 PR，  
  这条推送会被拒绝——那种情况下只能开 PR，并把合并留到会话**最后一步**（或留给主人在网页点）。
- **本仓实测**：见文末「本仓落地记录」。

---

# 第二部分：五条铁律

> 前几代 AI 都栽过，看完再动手。

### 1. 推送优先于一切

每完成一个可交付单元，立刻 `commit` + `push`。**绝不攒提交。**  
**未推送的提交 = 不存在的提交。**

### 2. 🩸 绝不主动合并 / 关闭 PR

Arena 会在 PR **合并或关闭**后**立刻关闭本会话的远程通道**，  
之后所有 `push` / `gh` 全失败。

→ 合并 PR 只能是会话的**最后一个动作**，或留给仓库主人在 GitHub 网页点。  
**要继续干活就让 PR 开着——更好：根本不开 PR，用第一部分的快进推送。**

```bash
gh pr create ...   # ✅ 开 PR 没问题（但本仓优先用快进）
gh pr merge  ...   # 🩸 关闭远程通道
gh pr close  ...   # 🩸 同样关闭远程通道
```

三个易错点：
- 触发事件是「合并**或关闭**」，不只是合并。
- **别用「分支还在不在」判断**——分支通常好端端在，通道照样已关。
- 通道一关，**尚未推送的提交就永久丢失**。

### 3. 推不上去时，立刻导 patch 存档，然后如实上报

不要静默跳过、不要假装成功。

```bash
git format-patch origin/main..HEAD -o /tmp/patches/
git bundle create /tmp/backup.bundle HEAD
```

### 4. 引用任何数字前先自己复现，不许照抄

本仓库的「三条写作铁律」与此同构：没有出处的话不写、跑不通的代码不交、对不上的数字不填。  
答不出口径，比数字低一点致命得多。

### 5. 遇到权限 / 网络 / 环境问题，直接说，不要绕过去假装完成

沙盒有网络白名单；GitHub App 无 `workflows` 权限。

---

# 第三部分：血泪教训与通用坑

## ⚠️ 前兆信号：TLS 报错

推送前常先撞一次 gnutls TLS 报错，看着像抖动，**其实可能是会话将关闭的前兆**；  
别机械重试超 2–3 次。立刻 commit 并尝试推送；推不上去就导 patch 存档并上报（铁律 3）。

## 其他通用坑

| # | 坑 |
|---|---|
| 1 | `node_modules` / `.venv` / `corpus/txt` 等不跨会话持久；重要产物别只放被 ignore 的目录 |
| 2 | 会话权限不确定：**开工先 `git ls-remote` 探一次** |
| 3 | 聊天里贴 patch 会被改坏（空白/HTML 实体）→ 用整篇覆盖恢复，别死磕 `git apply` |
| 4 | 沙盒有出口白名单：GitHub/PyPI 通，很多外部域名 TLS 直接失败 |
| 5 | 测连通性用 `curl -o /dev/null -w "%{http_code}"` 发 **GET**；`HEAD` 可能假阳性 |
| 6 | 🩸 **GitHub App 无 `workflows` 权限**：推送含 `.github/workflows/*.yml` 的提交会被拒绝 |
| 7 | 本仓白皮书是**派生物**：改 `docs/lectures/` 后必须 `make whitepaper`，否则 F4 红灯 |

---

# 第四部分：本仓落地记录

| 日期 | 动作 | 结果 |
| :--- | :--- | :--- |
| 2026-09-07 | 引入本手册；分支 `arena/01a07a05-mr-guo` 含 TOC 修复 + 分叉吸收 | 见下方实测 |
| 2026-09-07 | `git push origin arena/01a07a05-mr-guo:main`（快进） | 待写入（执行后更新 tip SHA） |

### 从 SCZ_Archived 学到、已在本仓使用的招

1. **快进推 main、不碰 PR** —— 保会话通道（本页第一部分）。
2. **身份卡 + 台账** —— 吸收外部材料时写清来源 tip / 映射 / 不吸什么（见 `archive/from_01a00377/README.md`）。
3. **排除清单当负例证据** —— 9 篇非团队论文 JSON 保留，防止回流进成果表。
4. **大体积通用技能不整包并** —— 只留 catalog 索引，需要时回源仓拉（与归档仓「容量边界」同理）。

### 来源

- [`sunccchengze/SCZ_Archived`](https://github.com/sunccchengze/SCZ_Archived) → `BRANCH-SAFETY.md` / `MANIFEST.md` / `README.ARCHIVE.md` 模式  
- 更早源头：`sunccchengze/turbine-blade-ai-platform` → `HANDOFF.md`
