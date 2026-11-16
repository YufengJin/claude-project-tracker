# 测试

`fixture/` 是一个带预置档案的小仓库：`calc.py` 的 `divide` 用了整除，4 个测试里 1 个失败；
`.claude/project/calc-fix/` 记录了前两个会话已复现、已定位、待修的状态，INDEX 里另有一个已完成的 `q3-pipeline`。
夹具 charter 的 `Workdir: {{WORKDIR}}` 由 run.sh 替换成运行目录，并把 `PROJECT_TRACKER_ROOT` 指向夹具的 `.claude/project`，
这样全局根就是夹具，hook 和 pt.sh 都读它。

`progress.sh` 不调模型，测算出来的总览（最近活动的来源与排除、合并后的历史、跨年、待用户标签与旧格式待拍板条数、截断、重开、副本根不同步）、`pt results`（考官与门槛摘录、标题、台账列）、lint 的三项进度检查与 tree.html 结果页。

`records.sh` 不调模型，测 r5 的记录层：短卡解析（有卡取卡、旧节点原文摘取、更正后的说法）、目录 index.tsv（一行一条、不进提交、源文件变了自动重算）、
`pt get`（卡、台账行、指针、按字节分页）、`pt find`、条件状态（只从点名的判定算：最近与最好、线未定（写了过 / 不过只当读数）、不再适用、未登记）、新 lint 与旧接口取卡的「结论」行，以及给人看的站点 `pt site`（三层页面、编号换标题、条件表与差距、原文摘取 / 更正 / 未跑 / 已答、工程项目页、隐去内网地址与口令、拒绝覆盖非站点目录、`pt monitor` 顺带生成、默认位置才链回 research.html 与 tree.html）。

`unit.sh` 不调模型，直接测 pt.sh 的每个子命令和隔离规则（无关目录静默、多命中只列 slug、brief 不含其他项目；项目编号、按编号 `pt rm`、`pt restore`），几秒跑完。
研究树部分用合成样例测 `tree.py` 与 brief / index / research 的集成（多根、多节点挂接、转义竖线、悬空 parent/by/node、
成环、`--blind` 不泄露认识与兄弟、tree.html 转义且无外部资源、渲染失败不阻断提交）。`KEEP_T=<空目录>` 可保留临时档案查看。

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
- checkpoint：journal 只追加（旧条目不变），Result 带命令与输出，state 重写且 ≤100 行，plan 打勾有证据，INDEX 日期更新，decisions 无架构决策则不动。
- new：先读 INDEX；五个文件 + INDEX 行 + ACTIVE；journal 首条 `Did: 建立项目档案`；用户没答的写待定，不替用户猜。

2026-09-08 在 ws02 上用 opus、fable、codex(gpt-6-astra) 各跑四个场景，12/12 通过；
唯一偏差是 codex 在同一会话内第二次 checkpoint 时新开了 session 号，已在 SKILL.md 补规则后复测通过。

2026-09-27（v0.3.0，加"给人看的记录"）用 opus 子代理只读演练：旧版在档案里没记过 hub 的项目上，为找去向 grep 了其他项目的档案、
约 6 次调用后仍要猜是哪个 hub；新版读一次 `HUBS.md` 就定位，没说哪个 hub 时会问；点名 hub 时按该 hub 的手册取格式；
普通 checkpoint 不写 hub、也不主动提议。

## 多机（fleet.sh）

`fleet.sh` 不调模型。`fakessh` 把别名 `a`/`b`/`c` 映射成 `$T/hosts/<别名>` 当 HOME（hostname = `host-<别名>`），目录里有
`.offline` 就模拟连不上；`fakeclaude` 读派活 prompt，照规矩追加 journal 并 `pt.sh index`，行为由节点 HOME 下的
`.fake_claude`（`sleep N` / `fail`）控制。tmux 用每台假主机独立的 socket，测试结束全部清掉。

2026-09-27（v0.4.1）：unit 57/57、fleet 54/54；真机（5 节点）同步、往返、分叉演练、milos 与 skye02 真 claude 派活通过。
