# project-tracker

为跨多次会话的长期任务建立**可恢复、可审计**的项目档案。档案放在项目仓库的
`.claude/project/<slug>/` 下：`charter`（目标与验收）、`plan`（怎么做）、`state`（现在在哪，≤100 行）、
`journal`（只追加的会话日志）、`decisions`（只追加的 ADR）。新会话冷启动时读档案，用 5 行汇报恢复上下文。

一个 skill，四种模式：`new` / `resume` / `checkpoint` / `list`。用户说"立一个项目"、"继续 XX"、
"我们做到哪了"、"记一下 / 存档"就会触发，也可以显式 `/project-tracker resume <slug>`。

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

- `SessionStart`（startup / resume / compact）跑 `brief.sh --if-active`，把 `ACTIVE` 项目的简报注入上下文。没有 `.claude/project/ACTIVE` 时静默。
- `PreCompact` 提醒先 checkpoint。

### Codex CLI

```bash
codex plugin marketplace add /path/to/claude-project-tracker
codex plugin install project-tracker@project-tracker
```

或者把 skill 目录链进 `~/.codex/skills/`：

```bash
ln -s /path/to/claude-project-tracker/plugins/project-tracker/skills/project-tracker ~/.codex/skills/project-tracker
```

Codex 没有 SessionStart hook，恢复时由 skill 主动跑 `scripts/brief.sh`。

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
```

## 测试

`tests/` 下是一个带预置档案的夹具仓库和跑批脚本，对 list / resume / checkpoint / new 四个场景
分别用 Claude Code（opus、fable）和 Codex 跑一遍，检查触发、写入顺序、只追加不变量。
见 `tests/README.md`。

## License

MIT.
