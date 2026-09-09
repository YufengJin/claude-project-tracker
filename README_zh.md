# project-tracker

[English](README.md)

一个 Claude Code / Codex 插件，为**跨多次会话**的长期任务维护一份**可恢复、可审计**的档案。档案放在你正在做的仓库里，
路径 `.claude/project/<slug>/`：

| 文件 | 作用 | 可变性 |
|---|---|---|
| `charter.md` | 目标、完成标准、不做什么、约束、怎么验证 | 写一次，极少改 |
| `plan.md` | 打算怎么做 | 快照，随时重写 |
| `state.md` | 现在在哪、别再试的路、快速启动命令 | 快照，≤ 100 行 |
| `journal.md` | 每个会话一条，带证据 | **只追加** |
| `decisions.md` | 架构决策记录（ADR） | **只追加** |

一个没有任何上下文的新会话读完档案，用 5 行汇报就能接着干。每个结果、每条死路、每个决策都带证据 checkpoint，
git 记不下来的东西（意图、假设、失败的尝试、用户原话）不会丢。

一个 skill，四种模式：`new` / `resume` / `checkpoint` / `list`。

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

- `SessionStart`（startup / resume / compact）跑 `brief.sh --if-active`，把 `ACTIVE` 项目的简报注入上下文。仓库里没有
  `.claude/project/ACTIVE` 时静默。
- `PreCompact` 在压缩上下文前提醒先 checkpoint。

### Codex CLI

```bash
codex plugin marketplace add YufengJin/claude-project-tracker   # 或本地 clone 路径
codex plugin add project-tracker@project-tracker
```

或者把 skill 目录链进用户级 skill 目录：

```bash
ln -s /path/to/claude-project-tracker/plugins/project-tracker/skills/project-tracker ~/.codex/skills/project-tracker
```

Codex 没有 SessionStart hook，恢复时由 skill 自己跑 `scripts/brief.sh`。

## 怎么用

平时不需要点名 skill，自然措辞就会触发，中英文都行。

### 立项目

> "立一个项目：把 config 解析从 argparse 迁到 click。"

skill 先读 `INDEX.md`（你叫的名字可能是已有项目的别名），然后**一次性**问四个 charter 问题：

1. 做完是什么样？要可判定的标准（"p99 < 200ms" 可以，"性能变好" 不行）
2. 明确不做什么？
3. 已知约束？（不能动的接口、deadline、兼容版本）
4. 怎么验证？（测试命令、对照实现、基线数据）

答不上的写 `待定` 进 *Open questions*，不会替你猜。然后建五个文件、INDEX 加一行、`ACTIVE` 写 slug、journal 记首条。
你也可以在同一句话里把四个答案一起给出。

### 继续

> "继续 auth-refactor，我们做到哪了？"

skill 跑 `scripts/brief.sh <slug>`，按冷启动需要的顺序和裁剪量输出：INDEX 行、`charter.md`、`state.md`、journal **最后 3 条**、
ADR 标题、`plan.md`。然后给你 ≤5 行：在哪、上次做了什么、下一步、卡在哪、有没有要你拍板的。不贴文件原文。然后开始干活。

### Checkpoint

> "记一下" / "存档" / "今天到这"

plan 里一步完成、一条完成标准翻绿、发现一条死路、要 `/compact` 之前，skill 也会**主动提议** checkpoint。写入顺序按"不可重建的先写"：

1. 追加 `journal.md` 条目，`Result` 必须带证据：跑了什么命令、看到什么输出、几个失败变几个
2. 重写 `state.md`，把 journal 里失败的尝试提升到 *别再试*
3. `plan.md` 有变就更新
4. 做了架构级选择就追加 ADR 到 `decisions.md`
5. 更新 `INDEX.md` 的状态和日期

完成标准打勾的唯一依据是 journal 里有对应证据。一次会话只写一条 journal，同一会话再次 checkpoint 只改写这一条。

### 列出

> "有哪些项目？"

读 `INDEX.md`，列出 slug、名称、状态、最后更新。不展开、不写文件。

### 显式调用

```
/project-tracker new <slug>          # Claude Code
/project-tracker resume <slug>
/project-tracker checkpoint
/project-tracker list

codex '$project-tracker resume <slug>'   # Codex
```

`brief.sh` 也可以在仓库根目录单独跑：

```bash
bash ~/.claude/plugins/cache/project-tracker/project-tracker/0.1.0/skills/project-tracker/scripts/brief.sh <slug>
bash .../brief.sh list          # 打印 INDEX.md
bash .../brief.sh --if-active   # ACTIVE 项目的简报，没有则静默（hook 跑的就是这个）
```

### 让它变硬性

skill 靠描述触发，是概率性的。三层叠加，任何一层失效另外两层兜底：

- 上面的 hook 在每次会话开始确定性地把状态灌回上下文
- 项目 `CLAUDE.md` / `AGENTS.md` 加一段，把规则说成硬性的：

  ```markdown
  ## 项目档案
  状态在 .claude/project/<slug>/。会话开始读 charter、state、journal 最后 3 条；
  有结果就追加 journal 并重写 state；架构决策追加 decisions。
  ```

- skill 本身提供细节和模板（`reference/templates.md`）

把 `.claude/project/` 提交进 git，档案随仓库走，每次 checkpoint 都能 diff。

### 何时不用

一天内、一个会话能做完的任务：`--continue` 加 todo 就够了。多人或多 agent 同时写同一个项目：用 issue tracker，markdown 会冲突。

## 布局

```
.claude-plugin/marketplace.json        仓库根即 marketplace（Claude Code）
.agents/plugins/marketplace.json       Codex 注册
plugins/project-tracker/
  .claude-plugin/plugin.json
  .codex-plugin/plugin.json
  skills/project-tracker/              唯一事实来源
    SKILL.md
    reference/templates.md             五个文件 + INDEX/ACTIVE 的模板
    reference/hooks.md                 hook 说明与可选的 Stop 门禁
    scripts/brief.sh                   按恢复协议顺序输出项目简报
  .agents/skills -> ../skills          Codex / OpenCode / OpenHands
  .claude/skills -> ../skills          Claude Code 项目级
  hooks/hooks.json                     Claude Code SessionStart / PreCompact
tests/                                 带预置档案的夹具仓库 + 跨模型跑批脚本
```

## 测试

`tests/` 下是一个带预置档案的夹具仓库和跑批脚本，对 list / resume / checkpoint / new 四个场景分别用 Claude Code（opus、fable）
和 Codex 非交互跑一遍，检查触发、写入顺序、只追加不变量。见 [tests/README.md](tests/README.md)。

## License

MIT.
