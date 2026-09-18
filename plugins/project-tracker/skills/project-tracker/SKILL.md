---
name: project-tracker
description: 为跨多次会话的长期任务在全局目录 ~/.claude/project/<slug>/ 建立可恢复、可审计的档案（charter/plan/state/journal/decisions），新会话冷启动时用 5 行汇报恢复上下文。触发：用户说"开始/立一个项目"、"继续 XX"、"我们做到哪了"、"记录进度"、"存档 / checkpoint / handoff"、"有哪些项目"、"long-horizon"、"要能追溯"，或提到 .claude/project；以及任何希望同一件事的状态、计划、决策跨会话持久的场景，即使没说"档案"二字。
---

# Project Tracker

目标：让**另一个没有任何上下文的 Claude** 读完档案就能接着干。

## 存储：全局，按项目隔离

所有档案在 `~/.claude/project/`（可用 `PROJECT_TRACKER_ROOT` 覆盖），不在仓库里。一个项目一个目录，`charter.md` 的 `Workdir:` 记它属于哪些代码目录（可多个）。

```
~/.claude/project/
├── INDEX.md        # 所有项目一行一个：slug、名称、状态、最后更新、一句话
├── ACTIVE          # 最近一次 brief 的 slug，仅作多项目同目录时的平局裁决
└── <slug>/
    ├── charter.md  # 目标、完成标准、边界、验证方法、Workdir。写一次，极少改
    ├── plan.md     # 怎么做。可重写
    ├── state.md    # 现在在哪 + 别再试的路 + 快速启动。可重写，≤100 行
    ├── journal.md  # 只追加，一会话一条
    ├── decisions.md# 只追加的 ADR
    └── archive/    # state 压缩掉的旧内容
```

**隔离规则**：一个会话只碰一个 `<slug>/`。`list` 只读 INDEX；`resume`/`checkpoint` 只读写当前项目目录；其他项目的文件不打开、不引用、不总结，即使它们在同一个 Workdir。要切项目就走一次 `resume`。

## 三条不变量

1. `journal.md` 与 `decisions.md` **只追加**。它们是唯一事实来源，其他文件都能从它们重建。
2. `state.md` 与 `plan.md` 是**快照**，随时可覆盖；state 硬上限 100 行。
3. **只写 git 记不下来的东西**：意图、假设、失败的尝试、判断依据、用户原话。"改了什么"看 commit。

## 工具

一个脚本 `scripts/pt.sh`（下文 `pt`）。机械的事交给它，你只负责内容。

| 命令 | 作用 |
|---|---|
| `pt list` | 打印 INDEX，每个 slug 附 Workdir |
| `pt where` | 当前目录命中的进行中项目 |
| `pt brief <slug>` | 按恢复顺序打印简报并设 ACTIVE |
| `pt new <slug> "<名称>" [workdir …]` | 从模板建档、INDEX 加行、ACTIVE 指向；workdir 默认当前目录 |
| `pt index <slug> "<一句话>" [状态]` | 更新 INDEX 日期/一句话；给状态则同步 charter |

SessionStart hook 跑 `pt auto`：当前目录只命中一个进行中项目就自动注入简报；命中多个只列 slug 等用户点名；命中零个静默。

## 模式

先看 `$ARGUMENTS`；没给就从措辞判断，仍不确定问一句。用户叫的名字可能是别名，**先 `pt list` 对 slug**（list 只读 INDEX，不会污染上下文）。

| 模式 | 触发 | 动作 |
|---|---|---|
| list | "有哪些项目" | `pt list`，列出，不展开 |
| new | "开始做 X"、"立项目" | INDEX 里已有 → 转 resume；没有 → 问 charter，`pt new`，填内容 |
| resume | "继续 X"、"做到哪了" | `pt brief <slug>`，≤5 行汇报，再干活 |
| checkpoint | "记一下"、"存档"、"今天到这"、一段有结果的工作刚结束 | 按顺序写 5 步 |

### new

把 4 个问题**一次性**批量问，不要分四轮：

1. 做完是什么样？要**可判定**的标准（"p99 < 200ms"可以，"性能变好"不行）。
2. 明确不做什么？
3. 已知约束？（不能动的接口、deadline、兼容版本）
4. 怎么验证？（测试命令、对照实现、基线数据）

答不上的写 `待定` 进 `Open questions`，**不要替用户猜**。然后 `pt new <slug> "<名称>" [workdir…]`（项目跨仓库就给多个 workdir），把回答填进 charter，写 plan。slug 小写连字符，定下后不改。

### resume

`pt brief <slug>` 输出的顺序就是阅读顺序：INDEX 行 → charter → state → journal 最后 3 条 → ADR 标题 → plan。**不要多读**：只有 state 与 journal 对不上、或用户问历史，才往前翻 journal 或读 ADR 正文。

然后 **≤5 行**汇报：在哪、上次做了什么、下一步、卡在哪、待拍板项。不贴文件原文。

### checkpoint：这一步是全部价值所在

一次会话干了活却没 checkpoint，对未来等于没发生。**主动提议，不等用户开口。**触发点：plan 一步完成、完成标准翻绿、发现死路、要 `/compact` 或结束会话前。

写入顺序（不可重建的先写）：

1. **追加 journal**。`Result` 必须带证据：跑了什么命令、看到什么输出。"应该能跑"不是证据。session 号 brief 已打印。
2. **重写 state**。journal 的 `Learned` 里失败的路**提升到 state 的"别再试"**，否则下个会话看不到。
3. **更新 plan**（若变）。重大方向调整先在 journal 记为什么。
4. **追加 decisions**（若做了架构级选择）。推翻旧决定只新增 ADR 并把旧条目 Status 改成"已推翻（见 ADR-00NN）"。
5. `pt index <slug> "<一句话>" [状态]`。项目做完或放弃在这里给状态。

完成标准打勾的唯一依据是 journal 里有对应证据条目。同一会话再次 checkpoint 只改写本会话那条 journal，不新开 session 号。

## 写作规则

字段固定、不写散文，详见 [reference/writing.md](reference/writing.md)。用户说的和你推断的分开，推测标"（推测）"。判据：一个月后在另一个话题的会话里这条还有用吗。

## 何时不用

一天内、一次会话能完的任务：`--continue` + TodoWrite 就够。多人或多 agent 同时写同一项目：用 issue tracker。
