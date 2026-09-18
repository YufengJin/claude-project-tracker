# project-tracker

[English](README.md)

一个 Claude Code / Codex 插件，为**跨多次会话**的长期任务维护一份**可恢复、可审计**的档案。档案统一放在
**全局目录** `~/.claude/project/<slug>/`，不放在仓库里，不用一个个文件夹找。每个项目在 charter 里记自己属于
哪些代码目录（`Workdir:`），一个会话只加载当前目录命中的那一个项目。

| 文件 | 作用 | 可变性 |
|---|---|---|
| `charter.md` | 目标、完成标准、不做什么、约束、怎么验证、`Workdir` | 写一次，极少改 |
| `plan.md` | 打算怎么做 | 快照，随时重写 |
| `state.md` | 现在在哪、别再试的路、快速启动命令 | 快照，≤ 100 行 |
| `journal.md` | 每个会话一条，带证据 | **只追加** |
| `decisions.md` | 架构决策记录（ADR） | **只追加** |

一个没有任何上下文的新会话读完档案，用 5 行汇报就能接着干。每个结果、每条死路、每个决策都带证据 checkpoint，
git 记不下来的东西（意图、假设、失败的尝试、用户原话）不会丢。

一个 skill 四种模式：`new` / `resume` / `checkpoint` / `list`。一个脚本 `pt.sh` 负责机械的事。

## 安装

### Claude Code

```bash
claude plugin marketplace add YufengJin/claude-project-tracker
claude plugin install project-tracker@project-tracker
```

本地开发直接指目录：

```bash
claude --plugin-dir /path/to/claude-project-tracker/plugins/project-tracker
```

插件自带两个 hook（`hooks/hooks.json`）：

- `SessionStart`（startup / resume / compact）跑 `pt.sh auto`：当前目录恰好命中一个进行中项目就注入它的简报；
  命中多个只列 slug、不加载任何档案，等你点名；命中零个静默。
- `PreCompact` 在压缩上下文前提醒 checkpoint。

### Codex CLI

```bash
codex plugin marketplace add YufengJin/claude-project-tracker
codex plugin add project-tracker@project-tracker
```

或把 skill 软链到用户 skill 目录：

```bash
ln -s /path/to/claude-project-tracker/plugins/project-tracker/skills/project-tracker ~/.codex/skills/project-tracker
```

Codex 没有 SessionStart hook，resume 时由 skill 自己跑 `pt.sh brief <slug>`。

## 存储与隔离

```
~/.claude/project/            # 可用 PROJECT_TRACKER_ROOT 覆盖
├── INDEX.md                  # 一行一个项目：slug、名称、状态、最后更新、一句话
├── ACTIVE                    # 最近一次 brief 的 slug，仅在同目录多项目时做平局裁决
└── <slug>/
    ├── charter.md            # 含  Workdir: /绝对路径 [/另一个路径 ...]
    ├── plan.md  state.md  journal.md  decisions.md
    └── archive/
```

- `Workdir` 可写多个目录，一个项目可以横跨两个仓库。
- 一个会话只碰一个 `<slug>/`。`list` 只读 `INDEX.md`。其他项目的文件不打开、不引用、不总结，即使同一个 Workdir。
  切项目就是一次 `resume`。
- 迁移原来放在仓库里的档案：把 `.claude/project/<slug>` 拷到 `~/.claude/project/`，在 charter 的 `Slug:` 下面
  加一行 `Workdir:`。

## `pt.sh`

```bash
PT=~/.claude/plugins/cache/project-tracker/project-tracker/0.2.0/skills/project-tracker/scripts/pt.sh
bash $PT list                                  # INDEX + 每个项目的 Workdir
bash $PT where                                 # 当前目录命中的进行中项目
bash $PT auto                                  # SessionStart hook 跑的
bash $PT brief <slug>                          # 按恢复顺序输出简报，设 ACTIVE
bash $PT new <slug> "<名称>" [workdir ...]     # 从模板建五个文件、INDEX 加行、ACTIVE 指向
bash $PT index <slug> "<一句话>" [状态]        # 更新 INDEX 日期/一句话；给状态则同步 charter
```

## 用法

通常不用点名 skill，自然措辞就会触发。

### 立项目

> "立一个项目：把 config 解析从 argparse 迁到 click。"

先查 `INDEX.md`（名字可能是已有项目的别名），再**一次性**问四个 charter 问题：做完什么样（要可判定）、
明确不做什么、已知约束、怎么验证。答不上的写"待定"进 Open questions，不替你猜。然后 `pt.sh new` 建档，
`Workdir` 默认当前目录（跨仓库可多给几个），skill 再把回答填进 charter 和 plan。

### 继续

> "继续 auth-refactor，我们做到哪了？"

`pt.sh brief <slug>` 按顺序输出冷启动所需：INDEX 行、`charter.md`、`state.md`、journal **最后三条**、ADR 标题、
`plan.md`。然后 ≤5 行汇报：在哪、上次做了什么、下一步、卡在哪、待拍板项。

### Checkpoint

> "记一下" / "存档" / "今天到这"

plan 一步完成、完成标准翻绿、发现死路、`/compact` 之前，skill 会**主动提议** checkpoint。写入顺序按不可重建优先：

1. 追加 `journal.md`，`Result` 带证据（命令、输出、failed→passed）
2. 重写 `state.md`，把 journal 里失败的路提升到"别再试"
3. `plan.md` 有变则更新
4. 有架构级选择则追加 ADR
5. `pt.sh index <slug> "<一句话>" [状态]`，项目完成或放弃在这里给状态

一次会话只有一条 journal；同一会话再次 checkpoint 改写本会话这条。

### 列表

> "有哪些项目？"

`pt.sh list`，不进任何项目目录。

### 显式调用

```
/project-tracker new <slug>
/project-tracker resume <slug>
/project-tracker checkpoint
/project-tracker list
```

### 让流程变硬性

skill 触发是概率性的。三层互相兜底：hook 确定性地灌状态；项目 `CLAUDE.md` 一段把规则变硬；skill 提供细节和模板。

```markdown
## 项目档案
档案在 ~/.claude/project/<slug>/（全局）。会话开始读 Workdir 含本仓库的那个项目的 charter、state、journal 最后 3 条；
有结果就追加 journal 并重写 state；架构决策追加 decisions。不打开其他项目的档案。
```

### 何时不用

一天内、一次会话能完的任务：`--continue` + todo 就够。多人或多 agent 同时写同一项目：用 issue tracker。

## 目录

```
.claude-plugin/marketplace.json        仓库根即 marketplace（Claude Code）
.agents/plugins/marketplace.json       Codex 注册
plugins/project-tracker/
  .claude-plugin/plugin.json
  .codex-plugin/plugin.json
  skills/project-tracker/              唯一事实来源
    SKILL.md
    scripts/pt.sh                      list / where / auto / brief / new / index
    reference/templates/*.md           五个文件模板，占位符 {{SLUG}} {{NAME}} {{DATE}} {{WORKDIR}}
    reference/writing.md               字段规则与正反例
    reference/hooks.md                 hook 如何隔离上下文；手动安装
  hooks/hooks.json                     SessionStart / PreCompact
tests/
  unit.sh                              直接测 pt.sh 与隔离规则，不调模型，几秒
  run.sh / eval.sh / scenarios.sh      跑模型的四场景测试
```

## 测试

`bash tests/unit.sh` 覆盖 `pt.sh` 每个子命令与隔离规则。`tests/run.sh <opus|fable|codex>` 用夹具仓库非交互跑四个模式，
`tests/eval.sh` 打印证据。见 [tests/README.md](tests/README.md)。

## License

MIT.
