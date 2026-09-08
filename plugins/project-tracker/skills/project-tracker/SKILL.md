---
name: project-tracker
description: 为跨多次会话的长期任务在 .claude/project/<slug>/ 建立可恢复、可审计的档案（charter/plan/state/journal/decisions），新会话冷启动时用 5 行汇报恢复上下文。触发：用户说"开始/立一个项目"、"继续 XX"、"我们做到哪了"、"记录进度"、"存档 / checkpoint / handoff"、"long-horizon"、"要能追溯"，或提到 .claude/project；以及任何希望同一件事的状态、计划、决策跨会话持久的场景，即使没说"档案"二字。
argument-hint: "[new|resume|checkpoint|list] [slug]"
---

# Project Tracker

目标：让**另一个没有任何上下文的 Claude** 读完档案就能接着干。

## 三条不变量

1. `journal.md` 与 `decisions.md` **只追加**。它们是唯一事实来源，其他文件都能从它们重建。
2. `state.md` 与 `plan.md` 是**快照**，随时可覆盖；state 硬上限 100 行。
3. **只写 git 记不下来的东西**：意图、假设、失败的尝试、判断依据、用户原话。"改了什么"看 commit。

## 目录

```
.claude/project/
├── INDEX.md          # 所有项目：slug、名称、状态、最后更新
├── ACTIVE            # 一行：当前活跃项目的 slug（hooks 用）
└── <slug>/
    ├── charter.md    # 目标、验收标准、边界、验证方法。写一次，极少改
    ├── plan.md       # 怎么做。可重写
    ├── state.md      # 现在在哪 + 别再试的路 + 快速启动命令。可重写，≤100 行
    ├── journal.md    # append-only 会话日志
    ├── decisions.md  # append-only ADR
    └── archive/      # state/plan 压缩掉的旧内容
```

slug：小写连字符，定下后不改。模板见 [reference/templates.md](reference/templates.md)。

## 何时不用

任务一天内能完、只有一次会话：用 `--continue` 和 TodoWrite 就够，不要建档案。多人或多 agent 同时写同一个项目：用 issue tracker，markdown 会冲突。

## 模式判定

`$ARGUMENTS` 给了就按它走；没给就从用户措辞判断，仍不确定问一句。**任何模式第一步都是读 `INDEX.md`**，用户叫的名字可能是别名。

| 模式 | 触发 | 动作 |
|---|---|---|
| new | "开始做 X"、"立项目" | INDEX 里已有 → 转 resume；没有 → 问 charter，建目录 |
| resume | "继续 X"、"做到哪了" | 跑恢复协议，5 行汇报，再干活 |
| checkpoint | "记一下"、"存档"、"今天到这"、一段有结果的工作刚结束 | 按顺序写 5 个文件 |
| list | "有哪些项目" | 读 INDEX，列出，不展开 |

## new：先问 charter，再建目录

把下面 4 个问题**一次性**批量问，不要分四轮：

1. 做完是什么样？要**可判定**的标准（"p99 < 200ms"可以，"性能变好"不行）。
2. 明确不做什么？
3. 已知约束？（不能动的接口、deadline、兼容版本）
4. 怎么验证？（测试命令、对照实现、基线数据）

用户答不上的写 `待定` 并进 `Open questions`。**不要替用户猜然后写成事实**，后续会话会把它当用户原话执行。

然后：建 5 个文件、INDEX 加一行、`ACTIVE` 写 slug、journal 首条 `Did: 建立项目档案`。

## resume：恢复协议

优先跑 `scripts/brief.sh <slug>`，它按正确顺序和裁剪量输出全部所需内容。手动则按此顺序，**不要跳、不要多读**：

1. `INDEX.md` → 确认 slug
2. `charter.md` 全文
3. `state.md` 全文（主要上下文来源）
4. `journal.md` **最后 3 条**。只有 state 与 journal 对不上、或用户问历史时才往前翻
5. `decisions.md` 只扫 `## ADR-` 标题，碰到相关决策再读正文
6. `plan.md` 全文

然后给用户 **≤5 行**汇报：在哪、上次做了什么、下一步、卡在哪、有没有待定项要他拍板。不要贴文件原文。`ACTIVE` 改成这个 slug。

## checkpoint：这一步是全部价值所在

一次会话干了活却没 checkpoint，对未来等于没发生。**主动提议，不等用户开口。**触发点：plan 里一个步骤完成、一个完成标准翻绿、发现一条死路、要 `/compact` 或结束会话前。

写入顺序（不可重建的先写）：

1. **追加 journal 条目**。`Result` 必须带证据：跑了什么命令、看到什么输出、哪个测试从几个失败到几个。"应该能跑"不是证据。
2. **重写 state.md**。失败的尝试从 journal 的 `Learned` **提升到 state 的"别再试"**，否则下一个会话看不到。
3. **更新 plan.md**（若变）。重大方向调整先在 journal 记一条为什么。
4. **追加 decisions.md**（若做了架构级选择）。推翻旧决定只新增 ADR 并把旧条目 Status 改成"已推翻（见 ADR-00NN）"，这是唯一允许的改动。
5. **更新 INDEX.md** 的状态和日期。

完成标准打勾的唯一依据是 journal 里有对应证据条目。整个 checkpoint 应在几分钟内完成。

## 写作规则

- 判据："一个月后在另一个话题的会话里这条还有用吗"。目标、决策、约束、死路：有用。"改了 3 个 typo"：没用。
- **用户说的和你推断的分开**。推测要标"（推测）"。
- 字段固定，不写散文。以后要 grep、按字段提取，只有结构化的捞得出来。
- state 超 100 行就把"已完成"挪进 `archive/state-YYYY-MM-DD.md`，只留一行摘要。
- 会话号 N = `grep -c '^## ' journal.md` + 1。**一次会话只有一条 journal**：同一会话内再次 checkpoint（含自我核验）只改写本会话这条末尾条目，不新开 session 号；历史条目仍不可改。

## 让流程变硬性（推荐）

skill 靠描述触发，不是百分之百可靠。两个加固手段，见 [reference/hooks.md](reference/hooks.md)：

- `SessionStart` hook 在启动、resume、compact 后自动跑 `brief.sh`，把 ACTIVE 项目的简报注入上下文，compaction 后不丢状态。
- `PreCompact` hook 提醒先 checkpoint。

以及项目 `CLAUDE.md` 加一段：

```markdown
## 项目档案
状态在 .claude/project/<slug>/。会话开始读 charter、state、journal 最后 3 条；
有结果就追加 journal 并重写 state；架构决策追加 decisions。
```
