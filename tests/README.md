# 测试

`fixture/` 是一个带预置档案的小仓库：`calc.py` 的 `divide` 用了整除，4 个测试里 1 个失败；
`.claude/project/calc-fix/` 记录了前两个会话已复现、已定位、待修的状态，INDEX 里另有一个已完成的 `q3-pipeline`。
夹具 charter 的 `Workdir: {{WORKDIR}}` 由 run.sh 替换成运行目录，并把 `PROJECT_TRACKER_ROOT` 指向夹具的 `.claude/project`，
这样全局根就是夹具，hook 和 pt.sh 都读它。

`unit.sh` 不调模型，直接测 pt.sh 的每个子命令和隔离规则（无关目录静默、多命中只列 slug、brief 不含其他项目），几秒跑完。

`scenarios.sh` 定义四个场景的提示词（list / resume / checkpoint / new），都用自然措辞，不显式点名 skill。

`run.sh <opus|fable|codex>` 把夹具复制到 `runs/<model>-<scenario>/`，非交互跑一遍，记录 `out.jsonl` 和 git 改动。
`eval.sh runs/<dir>` 打印证据：skill 是否触发、pt.sh 是否被调用、最终回复、git 改动，以及按场景的检查
（checkpoint：journal 前两条是否逐字节不变、新条目内容、state/plan/charter/INDEX；new：新目录五件套、INDEX、ACTIVE）。

准备夹具的 venv（运行前一次）：

```bash
cd tests/fixture && uv venv .venv && uv pip install -p .venv/bin/python pytest && git init -q && git add -A && git commit -qm fixture
```

Claude Code 用 `claude -p --model <id>`，Codex 用 `codex exec`，两者都以用户级 skill 目录里的 project-tracker 为准。

## 判定标准

- list：读 INDEX 列出，不展开、不写文件。
- resume：跑 pt.sh brief 或按顺序读文件，≤5 行汇报，ACTIVE 指向该 slug，不改代码。
- checkpoint：journal 只追加（旧条目不变），Result 带命令与输出，state 重写且 ≤100 行，plan/charter 打勾有证据，INDEX 日期更新，decisions 无架构决策则不动。
- new：先读 INDEX；五个文件 + INDEX 行 + ACTIVE；journal 首条 `Did: 建立项目档案`；用户没答的写待定，不替用户猜。

2026-09-08 在 ws02 上用 opus、fable、codex(gpt-6-astra) 各跑四个场景，12/12 通过；
唯一偏差是 codex 在同一会话内第二次 checkpoint 时新开了 session 号，已在 SKILL.md 补规则后复测通过。
