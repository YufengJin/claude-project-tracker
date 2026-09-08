# Hooks：让恢复和 checkpoint 不依赖 skill 触发

skill 描述触发是概率性的。下面两个 hook 把最关键的两步变成确定性的。

## 1. SessionStart：自动注入 ACTIVE 项目简报

新会话、`--resume`、`/compact` 之后都会跑。compaction 后尤其重要：摘要可能把项目状态压掉，这里从磁盘重新灌回来。

通过 plugin 安装时这两个 hook 已由插件的 `hooks/hooks.json` 提供（路径用 `${CLAUDE_PLUGIN_ROOT}`），不必手配。手动安装 skill 时写进 `~/.claude/settings.json` 或项目 `.claude/settings.json`：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|compact",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/skills/project-tracker/scripts/brief.sh --if-active",
            "timeout": 10
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "echo '[project-tracker] 即将压缩上下文。若 .claude/project/ACTIVE 指向的项目本会话有进展且未 checkpoint，压缩后请立即追加 journal 并重写 state。'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`--if-active`：`.claude/project/ACTIVE` 不存在时静默退出，不污染无关项目的上下文。

## 2. PreCompact：提醒 checkpoint

见上面配置。PreCompact 不能阻断，只能提醒；真正的写入由 compaction 后的 SessionStart 简报 + skill 规则兜底。

## 3. Stop 门禁（可选，默认不装）

可以用 Stop hook 在"有代码改动但 journal 没新条目"时阻止结束。实践中噪音大：小改动、纯问答会话都会被拦。如果确实要硬性保证，条件建议同时满足：

- `ACTIVE` 存在
- `git diff --stat HEAD` 非空或本会话有新 commit
- `journal.md` 的 mtime 早于最近一次源码改动

用 `decision: "block"` + `reason` 输出，最多阻断一次。不满足全部条件就放行。

## 与 CLAUDE.md 的分工

- hooks：确定性地把状态灌回上下文
- CLAUDE.md：告诉 Claude 规则是硬性的
- skill：提供怎么做的细节和模板

三者叠加，任何一个失效另外两个兜底。
