# Hooks：让恢复和 checkpoint 不依赖 skill 触发

skill 描述触发是概率性的。两个 hook 把最关键的两步变成确定性的。插件安装后由 `hooks/hooks.json` 自动提供，不必手配。

## SessionStart → `pt.sh auto`

startup、`--resume`、`/compact` 之后都跑。逻辑：

1. 在 `~/.claude/project/*/charter.md` 里找 `Status: 进行中` 且 `Workdir:` 包含当前目录的项目
2. 命中 1 个 → 注入该项目简报（等价 `pt.sh brief <slug>`）
3. 命中多个 → `ACTIVE` 在其中就用它；否则只列 slug，让用户点名，不加载任何档案
4. 命中 0 个 → 静默。无关目录的会话不会看到任何项目内容

这就是上下文隔离的保证：一个会话最多只加载一个项目，且只在它自己的代码目录里。

## PreCompact → 提醒 checkpoint

PreCompact 不能阻断，只能提醒。压缩后 SessionStart(compact) 会重新灌简报，真正的写入靠 skill 的 checkpoint 规则兜底。

## 手动安装 skill 时

写进 `~/.claude/settings.json`：

```json
{
  "hooks": {
    "SessionStart": [{ "matcher": "startup|resume|compact", "hooks": [
      { "type": "command", "command": "bash ~/.claude/skills/project-tracker/scripts/pt.sh auto", "timeout": 10 }
    ]}],
    "PreCompact": [{ "matcher": "*", "hooks": [
      { "type": "command", "command": "echo '[project-tracker] 即将压缩上下文。若本会话有项目进展且未 checkpoint，压缩后请立即追加 journal 并重写 state。'", "timeout": 5 }
    ]}]
  }
}
```

## Stop 门禁（可选，默认不装）

可用 Stop hook 在"有代码改动但 journal 没新条目"时阻止结束。实践中噪音大。若确实要硬保证，条件同时满足才拦：`pt.sh where` 非空、`git diff --stat HEAD` 非空、journal mtime 早于最近源码改动。`decision: "block"` + `reason`，最多拦一次。

## 分工

- hooks：确定性地把状态灌回上下文
- 项目 `CLAUDE.md` 一段：告诉 Claude 规则是硬性的
- skill：怎么做的细节和模板

任何一个失效另外两个兜底。
