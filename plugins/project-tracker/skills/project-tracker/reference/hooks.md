# Hooks：让恢复和 checkpoint 不依赖 skill 触发

skill 描述触发是概率性的。两个 hook 把最关键的两步变成确定性的。插件安装后由 `hooks/hooks.json` 自动提供，不必手配。

## SessionStart → `pt.sh auto`

startup、`--resume`、压缩（手动或自动）之后都跑。逻辑：

1. 在 `~/.claude/project/*/charter.md` 里找 `Status: 进行中` 且 `Workdir:` 包含当前目录的项目
2. 命中 1 个 → 注入该项目简报（等价 `pt.sh brief <slug>`）
3. 命中多个 → `ACTIVE` 在其中就用它；否则只列 slug，让用户点名，不加载任何档案
4. 命中 0 个 → 静默。无关目录的会话不会看到任何项目内容

这就是上下文隔离的保证：一个会话最多只加载一个项目，且只在它自己的代码目录里。

例外是压缩之后：`pt.sh brief` / `pt.sh new` 会把会话绑到项目（`~/.claude/project/.sessions/<session_id>`，30 天后自动清），压缩后的 SessionStart 按这个绑定重新注入同一个项目的简报，会话不在 Workdir 里开也一样。这时简报末尾不再要求 5 行汇报，而是提示把摘要里未入档的进展先 checkpoint。

## PreCompact → `pt.sh precompact`

PreCompact hook 的 stdout 会并进压缩指令。会话绑了项目（或当前目录只命中一个项目）时，它让摘要单列一节「未入档的进展」，压缩后的 checkpoint 就有材料可写；其他会话静默。

## 压缩阈值：Claude Code 的设置

上面两个 hook 管的是"压缩时不丢进展"，多早压缩由 Claude Code 决定。1M 上下文的模型默认要到几十万 token 才自动压缩，而每次请求都要把整段上下文重读一遍，长会话因此很贵。档案写全之后可以放心调低：

- 会话里 `/autocompact 300000`（按模型保存），或 `~/.claude/settings.json` 里 `"autoCompactWindow": 300000`（10 万到 100 万）。
- 子代理的提示缓存默认只留 5 分钟，等一次长命令就整段重写；`"subagentPromptCacheTtl": "1h"` 可以改成 1 小时。

## 手动安装 skill 时

写进 `~/.claude/settings.json`：

```json
{
  "hooks": {
    "SessionStart": [{ "matcher": "startup|resume|compact", "hooks": [
      { "type": "command", "command": "bash ~/.claude/skills/project-tracker/scripts/pt.sh auto", "timeout": 10 }
    ]}],
    "PreCompact": [{ "matcher": "*", "hooks": [
      { "type": "command", "command": "bash ~/.claude/skills/project-tracker/scripts/pt.sh precompact", "timeout": 10 }
    ]}]
  }
}
```

## Stop 门禁（可选，默认不装）

可用 Stop hook 在"有代码改动但 journal 没新条目"时阻止结束。实践中噪音大。若确实要硬保证，条件同时满足才拦：`pt.sh where` 非空、`git diff --stat HEAD` 非空、journal mtime 早于最近源码改动。`decision: "block"` + `reason`，最多拦一次。

## 中心机定时同步（多机时）

中心机（有 `~/.claude/project/FLEET`）上 `pt list` / `pt brief` 会先同步，但节点离线前的最后状态只有定时同步才抓得到。用 systemd 用户定时器，每 15 分钟一次（机器要 `loginctl enable-linger $USER`）：

```ini
# ~/.config/systemd/user/pt-sync.service
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'exec bash "$(ls -d ~/.claude/plugins/cache/project-tracker/project-tracker/*/skills/project-tracker/scripts/pt.sh | sort -V | tail -n1)" sync -q'

# ~/.config/systemd/user/pt-sync.timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
[Install]
WantedBy=timers.target
```

`systemctl --user daemon-reload && systemctl --user enable --now pt-sync.timer`；日志 `journalctl --user -u pt-sync`。ExecStart 每次取已安装的最新版本，升级插件不用改定时器。

## 分工

- hooks：确定性地把状态灌回上下文
- 项目 `CLAUDE.md` 一段：告诉 Claude 规则是硬性的
- skill：怎么做的细节和模板

任何一个失效另外两个兜底。
