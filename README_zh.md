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
├── INDEX.md                  # 生成的索引：slug、名称、状态、主机、最后提交日期、一句话
├── ACTIVE                    # 最近一次 brief 的 slug，仅在同目录多项目时做平局裁决
├── FLEET                     # 仅中心机：每行一个节点的 ssh 别名（私有，不发布）
└── <slug>/                   # 一个 git 仓；一次 checkpoint 一个提交
    ├── charter.md            # 含  Workdir: /绝对路径 [...]  与  Host: <hostname>
    ├── plan.md  state.md  journal.md  decisions.md
    └── archive/
```

- `Workdir` 可写多个目录，一个项目可以横跨两个仓库。`Host` 写这些路径在哪台机器上；`where` / `auto` 只认
  Host 是本机的项目。
- `INDEX.md` 由档案生成（charter 字段、最后提交日期（迁移提交不算）、state「一句话概括」首行），不要手改。
- 一个会话只碰一个 `<slug>/`。`list` 只读 `INDEX.md`。其他项目的文件不打开、不引用、不总结，即使同一个 Workdir。
  切项目就是一次 `resume`。
- 迁移原来放在仓库里的档案：把 `.claude/project/<slug>` 拷到 `~/.claude/project/`，在 charter 的 `Slug:` 下面
  加一行 `Workdir:`。

## `pt.sh`

```bash
PT=~/.claude/plugins/cache/project-tracker/project-tracker/0.4.0/skills/project-tracker/scripts/pt.sh
bash $PT list                                  # INDEX + 每个项目的主机与 Workdir（中心机先同步）
bash $PT where                                 # 当前目录命中的、本机的进行中项目
bash $PT auto                                  # SessionStart hook 跑的
bash $PT brief <slug>                          # 按恢复顺序输出简报，设 ACTIVE
bash $PT new <slug> "<名称>" [--host H] [workdir ...]  # 建档（git 仓），ACTIVE 指向
bash $PT index <slug> "<一句话>" [状态]        # 写一句话/状态、提交、重建 INDEX
bash $PT migrate                               # 升级 0.3 档案（先备份，幂等）
bash $PT sync [-q] [别名 ...]                  # 中心机：与节点快进同步
bash $PT dispatch <slug> "<任务>" [--wait]     # 中心机：派节点本机的 Claude 干活
bash $PT runs [slug | --wait <run>]            # 中心机：派活状态
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

### 给人看的记录（可选）

> "把这个项目的进展放到 hub 上。"

档案是写给下一个 agent 的。只有你要一份给人读的记录时，skill 才另写，去向列在 `~/.claude/project/HUBS.md`。
这个文件归你自己，不进本仓库：每个 hub（团队 wiki、个人站……）一小段，写在哪、谁能看、先读哪份手册。
格式和发布流程听那个 hub 自己的手册。没有这个文件，skill 会问写到哪。页面位置记进 `state.md`，下个会话就知道去哪更新。

```markdown
## 多机：一台中心机管全机队（可选）

项目在代码所在的机器上立：工作站、GPU 服务器、机器人都行。一台**中心机**看得到、也能接管全部项目。
节点上只需要 `git` 和 `sshd`，节点也不需要能连回中心机。

```
          中心机（全部档案 + 派活）              ~/.claude/project/FLEET:  gpu1
          │  ssh + git，只由中心机发起                                     robot-a
     ┌────┴─────┬──────────┐                                             robot-b  # 常离线
    gpu1     robot-a    robot-b     每个节点只存 Host 是它自己的项目
```

- **同步只快进。** 中心机逐个项目比较两边：谁领先听谁的。两边都有对方没有的提交就标**分叉**：不自动合并、
  拒绝派活，由下一个 agent 用 `git merge` 按语义合（journal 两边条目都留，state 重写）。不信任任何时间戳。
- 不搬半截：checkpoint 由 `pt index` 提交；节点有未提交改动、15 分钟内改过档案、或有派活在跑时，中心机不推。
  空闲 30 分钟的未提交改动（忘了 checkpoint，或旧版插件根本不提交）由中心机的探测代为提交。
- 中心机上 `pt list`、`pt brief` 先同步；systemd 用户定时器每 15 分钟同步一次，节点离线前的最后状态也不会丢
  （见 `reference/hooks.md`）。
- **接管**：在中心机上照常 resume、checkpoint，下次同步推回节点。轻活 `ssh <别名>`；长跑或要那台机器硬件的，
  `pt dispatch <slug> "<任务>" --wait` 在那台机器的 tmux 里跑 `claude -p`（默认 bypassPermissions，
  `PT_DISPATCH_MODE` 可改），它在那边 checkpoint，结果同步回来。状态、退出码、日志在节点的
  `~/.claude/project/.runs/<run>/`。
- 代码在别的机器上的项目：`pt new <slug> "<名称>" --host <别名> /那台机器上的路径`，下次同步就在那台机器上建好。
- 配置：把节点别名（与 `~/.ssh/config` 一致）写进 `~/.claude/project/FLEET`，每台机器跑一次 `pt migrate`，然后 `pt sync`。

已知限制：和节点共用同一个 Unix 账户的人，能读那台机器上的档案和派活日志。

## team-wiki（全团队可见）
- 内容仓：~/team-site/src/content/notes/，一篇 = <topic>/index.mdx
- 先读：它的 AGENTS.md。push main 即上线。
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
    scripts/pt.sh                      list / where / auto / brief / new / index / migrate
    scripts/fleet.sh                   中心机：sync / dispatch / runs（由 pt.sh source）
    scripts/probe.sh                   经 ssh 在节点上跑，只需要 git
    reference/templates/*.md           五个文件模板，占位符 {{SLUG}} {{NAME}} {{DATE}} {{WORKDIR}} {{HOST}}
    reference/writing.md               字段规则与正反例
    reference/hooks.md                 hook 如何隔离上下文；手动安装
  hooks/hooks.json                     SessionStart / PreCompact
tests/
  unit.sh                              直接测 pt.sh 与隔离规则，不调模型，几秒
  fleet.sh  fakessh  fakeclaude        多机同步与派活，用假主机模拟
  run.sh / eval.sh / scenarios.sh      跑模型的四场景测试
```

## 测试

`bash tests/unit.sh` 覆盖 `pt.sh` 每个子命令与隔离规则。`bash tests/fleet.sh` 模拟一台中心机和三个节点（桩 `ssh`
把别名映射到本地 HOME，桩 `claude` 扮演被派出去的 agent）：导入、推回、分叉与合并恢复、节点正在写/空闲、中心正在写、
离线、隐私、首次下发、slug 冲突、派活成功/失败/中途崩溃。`tests/run.sh <opus|fable|codex>` 用夹具仓库非交互跑四个模式，
`tests/eval.sh` 打印证据。见 [tests/README.md](tests/README.md)。

## License

MIT.
