#!/usr/bin/env bash
# unit.sh — 不调用模型，直接测 pt.sh 的本地子命令与隔离逻辑。几秒跑完。多机部分见 fleet.sh。
set -u
S=$(cd "$(dirname "$0")" && pwd)
PT="$S/../plugins/project-tracker/skills/project-tracker/scripts/pt.sh"
T=${KEEP_T:-$(mktemp -d)}; [ -n "${KEEP_T:-}" ] || trap 'rm -rf "$T"' EXIT
export PROJECT_TRACKER_ROOT="$T/root" PT_HOSTNAME=host-me PT_FLEET_JOBS="$T/no-fleet-jobs"
mkdir -p "$T/repoA/sub" "$T/repoB" "$T/other"
unset CLAUDE_PROJECT_DIR CLAUDE_CODE_SESSION_ID
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
D=$(date +%F)
# 0.6.10 的 state 模板（自由小节，不合格）：测旧排版的项目用它，简报应与 0.6.10 逐字一样
legacy_state(){ printf '# 当前状态\nUpdated: %s (session 1)\n\n## 一句话概括\n刚立项，尚未动手。\n\n## 快速启动\n```bash\n# 命令\n```\n\n## 已完成\n- 无\n\n## 进行中\n- 无\n\n## 别再试\n- 无\n\n## 已知问题\n- 无\n\n## 下一步\n1. <具体到能直接动手>\n' "$D" > "$PROJECT_TRACKER_ROOT/$1/state.md"; }

echo "# new"
out=$(cd "$T/repoA" && bash "$PT" new alpha "项目 A") ; rc=$?
check "new 退出 0"                     '[ $rc -eq 0 ]'
check "五个文件 + archive"             '[ -f "$T/root/alpha/charter.md" ] && [ -f "$T/root/alpha/plan.md" ] && [ -f "$T/root/alpha/state.md" ] && [ -f "$T/root/alpha/journal.md" ] && [ -f "$T/root/alpha/decisions.md" ] && [ -d "$T/root/alpha/archive" ]'
check "charter Workdir = 当前目录"      'grep -q "^Workdir: $T/repoA$" "$T/root/alpha/charter.md"'
check "charter Host = 本机"            'grep -q "^Host: host-me$" "$T/root/alpha/charter.md"'
check "无 {{ 残留"                     '! grep -rq --exclude-dir=.git "{{" "$T/root/alpha"'
check "INDEX 生成行（算出来的总览）"   'grep -q "^| alpha | 进行中 | $D journal | 0 天 | 0 | — | — | — |$" "$T/root/INDEX.md"'
check "ACTIVE = alpha"                 '[ "$(cat "$T/root/ACTIVE")" = alpha ]'
check "journal 首条是新格式标题"        'grep -qxF "## [$D] 决定 | 立项 | 建立项目档案" "$T/root/alpha/journal.md" && grep -q "^Did: *建立项目档案" "$T/root/alpha/journal.md"'
check "项目是 git 仓、分支 main、已首提交" '[ "$(git -C "$T/root/alpha" symbolic-ref --short HEAD)" = main ] && [ "$(git -C "$T/root/alpha" rev-list --count HEAD)" = 1 ] && [ -z "$(git -C "$T/root/alpha" status --porcelain)" ]'
check "允许推到工作树 (updateInstead)" '[ "$(git -C "$T/root/alpha" config receive.denyCurrentBranch)" = updateInstead ]'
check "重复 slug 拒绝"                 '! bash "$PT" new alpha "x" 2>/dev/null'
check "非法 slug 拒绝"                 '! bash "$PT" new Bad_Slug "x" 2>/dev/null'
(cd "$T/repoB" && bash "$PT" new beta "项目 B" "$T/repoB" "$T/repoA/sub" >/dev/null)
check "多 workdir 写入"                'grep -q "^Workdir: $T/repoB $T/repoA/sub$" "$T/root/beta/charter.md"'
check "--host 远程项目必须给 workdir"   '! bash "$PT" new gamma "G" --host host-far 2>/dev/null'
bash "$PT" new gamma "项目 G" --host host-far /srv/far >/dev/null
check "--host 写入 Host"               'grep -q "^Host: host-far$" "$T/root/gamma/charter.md"'

echo "# where / auto 隔离"
check "repoA 根只命中 alpha"           '[ "$(cd "$T/repoA" && bash "$PT" where)" = alpha ]'
check "repoA/sub 命中 alpha+beta"      '[ "$(cd "$T/repoA/sub" && bash "$PT" where | sort | tr "\n" " ")" = "alpha beta " ]'
check "repoB 只命中 beta"              '[ "$(cd "$T/repoB" && bash "$PT" where)" = beta ]'
check "无关目录命中 0"                 '[ -z "$(cd "$T/other" && bash "$PT" where)" ]'
mkdir -p "$T/srvlike"; sed -i "s|^Workdir: .*|Workdir: $T/srvlike|" "$T/root/gamma/charter.md"
check "Host 不是本机：路径命中也不算"   '[ -z "$(cd "$T/srvlike" && bash "$PT" where)" ]'
check "auto 无关目录静默"              '[ -z "$(cd "$T/other" && bash "$PT" auto)" ]'
out=$(cd "$T/repoB" && bash "$PT" auto)
check "auto 单命中 → brief beta"       'grep -q "项目简报: beta" <<<"$out" && ! grep -q "alpha" <<<"$out"'
echo alpha > "$T/root/ACTIVE"
out=$(cd "$T/repoA/sub" && bash "$PT" auto)
check "auto 多命中 + ACTIVE 在内 → brief alpha" 'grep -q "项目简报: alpha" <<<"$out" && ! grep -q "项目 B" <<<"$out"'
echo nothing > "$T/root/ACTIVE"
out=$(cd "$T/repoA/sub" && bash "$PT" auto)
check "auto 多命中 无 ACTIVE → 只列 slug" 'grep -q "多个进行中项目" <<<"$out" && ! grep -q "charter" <<<"$out"'
bash "$PT" new annot "带注释的 Workdir" "$T/repoB（代码源头）；另一台机器 \`x@y\`（仿真）" >/dev/null
check "Workdir 带注释也能命中"          '[ "$(cd "$T/repoB" && bash "$PT" where | sort | tr "\n" " ")" = "annot beta " ]'
bash "$PT" index annot "收起" 已放弃 >/dev/null
check "CLAUDE_PROJECT_DIR 优先于 PWD"  '[ "$(cd "$T/other" && CLAUDE_PROJECT_DIR="$T/repoB" bash "$PT" where)" = beta ]'

echo "# brief（state 不合格：同一套定长块，state 只取四类小节）"
legacy_state alpha
printf '\n## 2026-01-02 · session 2\nGoal: x\n\n## 2026-01-03 · session 3\nGoal: y\n\n## 2026-01-04 · session 4\nGoal: z\n' >> "$T/root/alpha/journal.md"
printf '## ADR-0001: 用 X\nDate: 2026-01-02\nStatus: 采纳\n\n**背景**：secret-body\n' >> "$T/root/alpha/decisions.md"
out=$(bash "$PT" brief alpha)
check "brief 设 ACTIVE"                '[ "$(cat "$T/root/ACTIVE")" = alpha ]'
check "brief 顺序 INDEX→lint→state→条件→journal 标题→去哪找" 'python3 - "$out" <<PY
import sys; s=sys.argv[1]; ks=["INDEX 行","= lint","= state.md（旧格式","= 条件","= journal 最近","= 去哪找"]
idx=[s.find(k) for k in ks]; sys.exit(0 if all(i>=0 for i in idx) and idx==sorted(idx) else 1)
PY'
check "工程项目：journal 只给最近的标题、不给正文" 'grep -q "^- J2026-01-04.1 \[旧格式\] session 4" <<<"$out" && ! grep -q "^Goal: z" <<<"$out"'
check "ADR 正文不进简报"               '! grep -q "secret-body" <<<"$out" && grep -q "decisions.md（为何转向）" <<<"$out"'
check "brief 不含其他项目"             '! grep -q "beta\|项目 B" <<<"$out"'
check "本机项目 brief 不提 Host"        '! grep -q "^Host:.*那台机器" <<<"$out"'
check "远程项目 brief 提示 Host"        'bash "$PT" brief gamma | grep -q "^Host: .*(host-far)"'
check "brief 不存在的 slug 报错"       '! bash "$PT" brief nope 2>/dev/null'
seq 1 120 | sed "s/^/- line /" >> "$T/root/alpha/state.md"
check "state >100 行告警"              'bash "$PT" brief alpha | grep -q "超过 100 行"'
bash "$PT" new wide "长行的 state" "$T/other/wide" >/dev/null
python3 -c "print('- ' + '字' * 9000)" >> "$T/root/wide/state.md"
check "state 行数没超但太长也告警"      'bash "$PT" brief wide | grep -q "\[warn\] state.md"'

echo "# brief 的 journal 预算"
bash "$PT" new big "大 journal" "$T/other/big" >/dev/null; legacy_state big
{ printf '\n## 2026-02-01 · session 2\nGoal: 早先的目标\n'
  python3 -c "
for i in range(400): print('续 %d：' % i + '证据' * 60)"
  printf 'Next: 倒数第二条的下一步\n\n## 2026-02-02 · session 3\nGoal: 最新的目标\nNext: 最新的下一步\n'; } >> "$T/root/big/journal.md"
out=$(bash "$PT" brief big)
check "超预算时简报不超过 8192 字节"     '[ "$(printf "%s\n" "$out" | wc -c)" -le 8192 ]'
check "大 journal：只给标题、不给正文"   'grep -q "J2026-02-02.1 \[旧格式\] session 3" <<<"$out" && ! grep -q "^续 \|^Goal: " <<<"$out"'
check "journal 原文没被动"             '[ "$(grep -c "^续 " "$T/root/big/journal.md")" = 400 ]'

echo "# brief 的 8 KB 上限"
bash "$PT" new fat "大 state" "$T/other/fat" >/dev/null; legacy_state fat
python3 - "$T/root/fat/state.md" <<'PYS'
import sys; p = sys.argv[1]; s = open(p, encoding="utf-8").read()
s = s.replace("## 进行中\n- 无", "## 进行中\n" + "".join("- 细节 %d：" % i + "过程" * 80 + "\n" for i in range(60)))
s = s.replace("1. <具体到能直接动手>", "1. 下一步写在这里")
open(p, "w", encoding="utf-8").write(s)
PYS
out=$(bash "$PT" brief fat)
check "大 state：简报不超过 8192 字节"   '[ "$(printf "%s\n" "$out" | wc -c)" -le 8192 ]'
check "大 state：留一句话与下一步，进行中放不全给去处" 'grep -q "^## 一句话概括" <<<"$out" && grep -q "^1. 下一步写在这里" <<<"$out" && grep -q "^- 细节 0：" <<<"$out" && ! grep -q "^- 细节 59：" <<<"$out" && grep -q "本节余下 [0-9]* 行未展开：cat $T/root/fat/state.md" <<<"$out"'
check "大 state：其余小节给出去处"        'grep -q "其余小节未展开：.*已完成.*cat $T/root/fat/state.md" <<<"$out"'
python3 - "$T/root/fat/state.md" "$T/root/fat/decisions.md" <<'PYS'
import sys; p, d = sys.argv[1], sys.argv[2]; s = open(p, encoding="utf-8").read()
s = s.replace("## 快速启动", "## 研究树\n焦点 H7：焦点写在这里\n\n## 资产\n" + "".join("- 资产 %d：" % i + "路径" * 60 + "\n" for i in range(40)) + "\n## 快速启动")
open(p, "w", encoding="utf-8").write(s)
open(d, "a", encoding="utf-8").write("".join("\n## ADR-%04d: 决策 %d " % (i, i) + "细节" * 50 + "\n" for i in range(1, 9)))
PYS
out=$(bash "$PT" brief fat)
check "焦点类小节（研究树）先占预算"        '[ "$(printf "%s\n" "$out" | wc -c)" -le 8192 ] && grep -q "^焦点 H7：焦点写在这里" <<<"$out" && grep -q "^1. 下一步写在这里" <<<"$out"'
check "焦点类小节有了，进行中与资产只给去处"  '! grep -q "^- 资产 0：\|^- 细节 0：" <<<"$out" && grep -q "其余小节未展开：资产、.*进行中" <<<"$out"'
check "ADR 不进简报"                        '! grep -q "^## ADR-0008" <<<"$out"'
check "没超上限的简报不提上限"            '! bash "$PT" brief alpha | grep -q "简报上限"'
out=$(bash "$PT" brief alpha)
check "journal 正文不进简报"             '! grep -q "^Goal: x" <<<"$out"'

echo "# 会话绑定与压缩"
CLAUDE_CODE_SESSION_ID=sess-1 bash "$PT" brief alpha >/dev/null
check "brief 把会话绑到项目"            '[ "$(cat "$T/root/.sessions/sess-1")" = alpha ]'
check "没有会话号就不绑"               '[ "$(ls "$T/root/.sessions" | wc -l)" = 1 ]'
out=$(cd "$T/other" && printf '{"session_id":"sess-1","source":"compact"}' | bash "$PT" auto)
check "压缩后按绑定重新注入（不在 Workdir 里）" 'grep -q "项目简报: alpha" <<<"$out" && grep -q "上下文刚被压缩" <<<"$out" && ! grep -q "≤5 行汇报" <<<"$out"'
check "启动时不在 Workdir 里仍然静默"   '[ -z "$(cd "$T/other" && printf "{\"session_id\":\"sess-1\",\"source\":\"startup\"}" | bash "$PT" auto)" ]'
check "没绑过的会话压缩后静默"          '[ -z "$(cd "$T/other" && printf "{\"session_id\":\"sess-x\",\"source\":\"compact\"}" | bash "$PT" auto)" ]'
out=$(cd "$T/repoB" && printf '{"session_id":"sess-1","source":"compact"}' | bash "$PT" auto)
check "压缩后绑定优先于当前目录"        'grep -q "项目简报: alpha" <<<"$out" && ! grep -q "项目简报: beta" <<<"$out"'
out=$(cd "$T/repoB" && printf '{"session_id":"sess-x","source":"compact"}' | bash "$PT" auto)
check "没绑定时压缩后按目录注入并提示 checkpoint" 'grep -q "项目简报: beta" <<<"$out" && grep -q "上下文刚被压缩" <<<"$out"'
out=$(cd "$T/other" && printf '{"session_id":"sess-1","trigger":"auto"}' | bash "$PT" precompact)
check "precompact 给绑定的项目出压缩指令" 'grep -q "项目 alpha" <<<"$out" && grep -q "未入档的进展" <<<"$out"'
check "按目录注入的简报也绑定会话"       '[ "$(cat "$T/root/.sessions/sess-x")" = beta ]'
check "precompact 无关会话静默"         '[ -z "$(cd "$T/other" && printf "{\"session_id\":\"sess-y\"}" | bash "$PT" precompact)" ]'
check "precompact 按目录命中单个项目"    'cd "$T/repoB" && printf "{\"session_id\":\"sess-y\"}" | bash "$PT" precompact | grep -q "项目 beta"'
n0=$(ls "$T/root/.sessions" | wc -l)
check "会话号不合法不落盘"              '(cd "$T/other" && CLAUDE_CODE_SESSION_ID="../x" bash "$PT" brief alpha >/dev/null); [ ! -e "$T/root/x" ] && [ "$(ls "$T/root/.sessions" | wc -l)" = "$n0" ]'

echo "# index"
n0=$(git -C "$T/root/alpha" rev-list --count HEAD)
bash "$PT" index alpha "做到一半 | 有竖线" >/dev/null
check "index 写 state 一句话"          '[ "$(awk "/^## 一句话概括/{f=1;next} f&&NF{print;exit}" "$T/root/alpha/state.md")" = "做到一半 | 有竖线" ]'
check "index 只替换第一行，不动其他节"   'grep -q "^## 下一步" "$T/root/alpha/state.md" && ! grep -q "刚立项，尚未动手" "$T/root/alpha/state.md"'
check "INDEX 行更新"                    'grep -q "^| alpha | 进行中 | $D " "$T/root/INDEX.md"'
check "index 提交了一次 checkpoint"     '[ "$(git -C "$T/root/alpha" rev-list --count HEAD)" = $((n0+1)) ] && [ -z "$(git -C "$T/root/alpha" status --porcelain)" ] && git -C "$T/root/alpha" log -1 --format=%s | grep -q "^checkpoint @host-me: 做到一半"'
check "index 不动其他行"               'grep -q "^| beta | 进行中 |" "$T/root/INDEX.md"'
bash "$PT" index beta "全部通过" 已完成 >/dev/null
check "index 状态同步 charter"         'grep -q "^| beta | 已完成 |" "$T/root/INDEX.md" && grep -q "^Status: 已完成$" "$T/root/beta/charter.md"'
check "已完成排在进行中之后"           '[ "$(grep -n "^| alpha |" "$T/root/INDEX.md" | cut -d: -f1)" -lt "$(grep -n "^| beta |" "$T/root/INDEX.md" | cut -d: -f1)" ]'
check "已完成项目不再命中 where"       '[ -z "$(cd "$T/repoB" && bash "$PT" where)" ]'
check "index 非法状态拒绝"             '! bash "$PT" index alpha x 完蛋 2>/dev/null'
check "index 未知 slug 报错"           '! bash "$PT" index nope x 2>/dev/null'
printf '# 当前状态\nUpdated: x\n\n## 下一步\n1. y\n' > "$T/root/gamma/state.md"
bash "$PT" index gamma "补上一句话" >/dev/null
check "state 没有一句话一节时补上"      'grep -A1 "^## 一句话概括" "$T/root/gamma/state.md" | grep -q "补上一句话" && grep -q "^## 下一步" "$T/root/gamma/state.md"'

echo "# list"
out=$(bash "$PT" list)
check "list 含 INDEX、主机与 Workdir"  'grep -q "^| alpha |" <<<"$out" && grep -q "alpha.*@本机.*Workdir: $T/repoA" <<<"$out" && grep -q "gamma.*@host-far" <<<"$out"'
check "list 不含项目正文"              '! grep -q "完成标准\|Goal:" <<<"$out"'
check "非中心机 sync 拒绝"             '! bash "$PT" sync 2>/dev/null'

echo "# research 与研究树"
bash "$PT" new rs "研究 R" "$T/other/rs" >/dev/null; legacy_state rs
out=$(bash "$PT" research rs)
R="$T/root/rs"
check "research 建 verifier、experiments、tree/Q1.md" '[ -f "$R/verifier.md" ] && [ -f "$R/experiments.md" ] && [ -f "$R/tree/Q1.md" ] && grep -q "^title: 研究 R$" "$R/tree/Q1.md"'
check "research 提交且干净"            '[ -z "$(git -C "$R" status --porcelain)" ]'
check "台账模板有 node 列"             'grep -q "^| id | node |" "$R/experiments.md"'
check "research 写 .ignore / .gitattributes 并提交" '[ "$(cat "$R/.ignore")" = tree.html ] && [ "$(cat "$R/.gitattributes")" = "tree.html -diff" ] && git -C "$R" ls-files | grep -qx .ignore && git -C "$R" ls-files | grep -qx .gitattributes'
check "research 幂等"                  'bash "$PT" research rs | grep -q "已有"'
check "模板根节点无告警"                'bash "$PT" tree rs | sed -n "/^## 告警/,\$p" | grep -q "^(无)"'
cat > "$R/tree/Q1.md" <<'EOF'
---
title: 主问题 Q1
parent:          # 根
status: active
---
## 判别
为什么问：示例。

第二段不进祖先链。
## 当前认识
- 认识甲 <script>alert(1)</script>，见 [[H1]] 与 `code|x`
## 约束
- 禁读锁箱切分
## 教训
- 教训乙（适用：示例；出处 E1）
EOF
mk(){ printf -- '---\ntitle: %s\nparent: %s\nstatus: %s\n%b---\n%b\n' "$2" "$3" "$4" "$5" "$6" > "$R/tree/$1.md"; }
mk H1 "假设一 已否" Q1 closed 'verdict: refuted\n' '## 判别\n预测 A。\n## 结论\n不支持：读数见 E1，改走 [[H2]]。后半句。'
mk H2 "假设二 在做" Q1 active '' '## 判别\n预测 B；错的话 C。\n## 结论\n'
mk H3 "假设三 关了没写" Q1 closed '' '## 判别\n空。\n## 结论\n<!-- 待写 -->'
mk H4 "假设四 父悬空" Q9 open '' ''
mk H5 "假设五 被取代" Q1 closed 'verdict: superseded\nby: H99\n' '## 结论\n被取代。'
mk H6 "环甲" H7 parked '' ''
mk H7 "环乙" H6 parked '' ''
mk Q2 "旧根" "" closed 'verdict: supported\n' '## 结论\n答完了。\n## 教训\n- 旧根教训丙'
mk Q3 "子问题" Q1 open '' ''
cat >> "$R/experiments.md" <<'EOF'
| E1 | H1, H2 | 对照 a \| b | 0.5 | 成功 | 不支持 | p/x |
| E2 | H42 | 悬空 | - | 未跑 | - | - |
| E3 |  | 未挂接 | - | 未跑 | - | - |

## 旧表（没有 node 列）
| ID | 问题 | 结论 |
|---|---|---|
| R0 | 旧问题 \| 带竖线 | 支持 |
EOF
out=$(bash "$PT" tree rs)
check "tree 默认：根的认识/约束/教训"   'grep -q "认识甲" <<<"$out" && grep -q "禁读锁箱切分" <<<"$out"'
check "tree 默认：已关的根只给指引"     '! grep -q "旧根教训丙" <<<"$out" && grep -q "教训 见 pt tree rs --ctx Q2" <<<"$out"'
check "tree 默认：active 带祖先链与台账" 'grep -q "^- H2 假设二 在做" <<<"$out" && grep -q "链: Q1 主问题 Q1" <<<"$out" && grep -q "台账: E1" <<<"$out"'
check "tree 默认：open/parked 标题"     'grep -q "^- Q3 \[open\] 子问题" <<<"$out" && grep -q "^- H6 \[parked\]" <<<"$out"'
check "tree 默认不列已关分支"           '! grep -q "假设一 已否" <<<"$out" && grep -q "已关 4 个" <<<"$out"'
check "台账计数（多表、转义竖线）"       'grep -q "台账 4 行，挂到节点的 2 行" <<<"$out"'
check "告警：悬空 parent / by / node"   'grep -q "H4: parent Q9 不存在" <<<"$out" && grep -q "H5: by H99 不存在" <<<"$out" && grep -q "台账 E2.*node H42 不存在" <<<"$out"'
check "告警：closed 无 verdict / 结论"  'grep -q "H3: closed 但没有 verdict" <<<"$out" && grep -q "H3: closed 但结论为空" <<<"$out" && ! grep -q "H1: closed" <<<"$out"'
check "告警：成环"                     'grep -q "成环: H[67] → H[67] → H[67]" <<<"$out"'
out=$(bash "$PT" tree rs --all)
check "--all 列已关分支与结论首句"       'grep -q "^- H1 \[refuted\] 假设一 已否 —— 不支持：读数见 E1，改走 \[\[H2\]\]。$" <<<"$out" && grep -q "^- H5 \[superseded → H99\]" <<<"$out"'
out=$(bash "$PT" tree rs --ctx H2)
check "--ctx：根约束/认识/教训 + 祖先首段" 'grep -q "根 Q1 · 约束" <<<"$out" && grep -q "认识甲" <<<"$out" && grep -q "判别: 为什么问：示例。" <<<"$out" && ! grep -q "第二段不进祖先链" <<<"$out"'
check "--ctx：兄弟一行 + 本节点全文"     'grep -q "^- H1 \[closed/refuted\] 假设一 已否" <<<"$out" && grep -q "^预测 B；错的话 C。" <<<"$out"'
check "--ctx：台账行原样（多节点挂接）"  'grep -qF "| E1 | H1, H2 | 对照 a \| b |" <<<"$out" && grep -q "^| id | node |" <<<"$out" && ! grep -q "E3" <<<"$out"'
check "--ctx 父节点带子节点的台账行"     'bash "$PT" tree rs --ctx Q1 | grep -qF "| E1 | H1, H2 |"'
out=$(bash "$PT" tree rs --ctx H2 --blind)
check "--blind：判别 + 约束 + 考官两节" 'grep -q "预测 B" <<<"$out" && grep -q "禁读锁箱切分" <<<"$out" && grep -q "^### 指标与聚合定义" <<<"$out" && grep -q "^### 判定依据" <<<"$out"'
check "--blind 不含认识、兄弟、教训"     '! grep -q "认识甲\|假设一\|教训乙\|数据与暴露史" <<<"$out"'
check "--ctx 不存在的节点报错"          '! bash "$PT" tree rs --ctx H404 2>/dev/null'
check "--next Q / H"                   '[ "$(bash "$PT" tree rs --next Q)" = Q4 ] && [ "$(bash "$PT" tree rs --next H)" = H8 ]'
H="$R/tree.html"
check "tree.html 生成"                 '[ -f "$H" ] && grep -q "<article id=\"n-H2\"" "$H"'
check "html 转义正文"                  'grep -qF "&lt;script&gt;alert(1)&lt;/script&gt;" "$H" && ! grep -qF "<script>alert(1)" "$H"'
check "html [[ID]] 变成跳转、行内代码"   'grep -qF "<a class=\"ref\" href=\"#H1\">H1</a>" "$H" && grep -qF "<code>code|x</code>" "$H"'
check "html 挂接台账行（转义竖线还原成单元格）" 'grep -qF "<td>对照 a | b</td>" "$H"'
check "html 无外部资源"                 '! grep -qiE "https?://|src=|<link|@import|url\(" "$H"'
check "html 有总览图：SVG 容器、内嵌数据（先序、父下标、台账行数）" 'grep -q "<svg id=gsvg" "$H" && python3 - "$H" <<PY
import json,re,sys; s=open(sys.argv[1]).read()
d=json.loads(re.search(r"<script type=application/json id=gdata>(.*?)</script>",s,re.S).group(1))
N=d["nodes"]; ix={n["i"]:k for k,n in enumerate(N)}
ok=d["slug"]=="rs" and len(N)==s.count("<article id=\"n-")-("n-__ledger" in s)-("n-__results" in s) and N[ix["H2"]]["p"]==ix["Q1"] and N[ix["H2"]]["n"]>=1
ok=ok and all(n["p"]<k for k,n in enumerate(N)) and "H99" not in N[ix["H5"]]["b"]
sys.exit(0 if ok else 1)
PY'
check "html 视图切换与本项目专属的 localStorage 键" 'grep -q "id=vg type=button" "$H" && grep -q "id=vl type=button" "$H" && grep -q "KEY=.pt-tree:.+DATA.slug" "$H" && ! grep -q "pt-tree-hc" "$H"'
check "html 多根都在左侧树"             'python3 - "$H" <<PY
import re,sys; s=open(sys.argv[1]).read(); nav=s[s.index("<nav>"):s.index("</nav>")]
top=re.findall(r"<nav><ul>(.*)</ul></nav>",s,re.S)[0]
sys.exit(0 if all(f"data-id=\"{i}\"" in nav for i in ["Q1","Q2","H4","H6","H7"]) else 1)
PY'
out=$(bash "$PT" brief rs)
check "brief 给前沿、不给台账末行"       'grep -q "===== 前沿" <<<"$out" && grep -q "^- H2 \[在做\] 假设二" <<<"$out" && ! grep -q "experiments.md 末 15 行" <<<"$out"'
check "考官卡只给指针"                   'grep -q "verifier.md（考官）" <<<"$out" && ! grep -q "^## 数据与暴露史" <<<"$out"'
sed -i "s/^Updated: .*/Updated: $D   Status: 已冻结（用户确认；改考官走 ADR）/" "$R/verifier.md"
out=$(bash "$PT" brief rs)
check "冻结后考官卡也只给指针"            'grep -q "verifier.md（考官）" <<<"$out" && ! grep -q "^## 判定依据" <<<"$out"'
printf 'build/\n' > "$R/.ignore"; rm -f "$R/.gitattributes"; git -C "$R" add -A >/dev/null; git -C "$R" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -qm "改 ignore"
bash "$PT" index rs "研究树就位" >/dev/null; bash "$PT" index rs "研究树就位二" >/dev/null
check "index 补 .ignore / .gitattributes：保留原内容、只补一次、随提交" '[ "$(cat "$R/.ignore")" = "$(printf "build/\ntree.html")" ] && [ "$(cat "$R/.gitattributes")" = "tree.html -diff" ] && [ -z "$(git -C "$R" status --porcelain)" ]'
rm -f "$H"
out=$(bash "$PT" index rs "研究树就位")
check "index 渲染 tree.html 并一起提交"  '[ -f "$H" ] && [ -z "$(git -C "$R" status --porcelain)" ] && git -C "$R" ls-files | grep -qx tree.html && grep -q "告警 [0-9]* 条" <<<"$out"'
chmod 000 "$R/tree"   # tree/ 读不了：tree.py 整个失败
out=$(bash "$PT" index rs "渲染坏了" 2>&1); rc=$?
chmod 755 "$R/tree"
check "渲染失败只告警，照常提交"         '[ $rc -eq 0 ] && grep -q "tree.html 没渲染成" <<<"$out" && git -C "$R" log -1 --format=%s | grep -q "渲染坏了"'
check "没有研究树的项目 tree 报错、brief 没有前沿" '! bash "$PT" tree alpha 2>/dev/null && ! bash "$PT" brief alpha | grep -q "===== 前沿"'

echo "# 研究树回归（坏输入、注入、冲突）"
TP="$(dirname "$PT")/tree.py"
mkdir -p "$T/rbw"
bash "$PT" new rb "回归 B" "$T/rbw" >/dev/null; legacy_state rb; bash "$PT" research rb >/dev/null
B="$T/root/rb"
nd(){ printf '%b' "$2" > "$B/tree/$1"; }
fmn(){ nd "$1.md" "---\ntitle: $2\nparent: $3\nstatus: $4\n$5---\n$6\n"; }
tw(){ python3 "$TP" "$B" --no-html "$@" 2>&1; }
gq(){ git -C "$B" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
# S1 class 属性注入
fmn H1 '<img src=x onerror=alert(3)>' Q1 'x" onmouseover="alert(1)' 'verdict: y" onfocus="alert(2)" autofocus x="\n' '## 判别\n<b onmouseover=alert(4)>x</b>'
python3 "$TP" "$B" --render >/dev/null
check "S1 html 没有 on* 事件属性（status/verdict/标题注入都转义）" 'python3 - "$B/tree.html" <<PY
import sys, html.parser
bad = []
class P(html.parser.HTMLParser):
    def handle_starttag(self, tag, attrs):
        bad.extend(k for k, v in attrs if k.startswith("on") or k == "autofocus")
P().feed(open(sys.argv[1]).read()); sys.exit(1 if bad else 0)
PY'
check "S1 注入串在图数据里被转义（无 <，解析回原文）" 'python3 - "$B/tree.html" <<PY
import json,re,sys; s=open(sys.argv[1]).read()
raw=re.search(r"<script type=application/json id=gdata>(.*?)</script>",s,re.S).group(1)
d=json.loads(raw); t=[n for n in d["nodes"] if n["i"]=="H1"][0]
sys.exit(0 if "<" not in raw and ">" not in raw and r"\\u003cimg src=x onerror=alert(3)\\u003e" in raw and t["t"]=="<img src=x onerror=alert(3)>" and t["s"]=="unknown" else 1)
PY'
check "S1 未知 status/verdict 的 class 是 s-unknown / v-unknown" 'grep -q "class=\"n s-unknown v-unknown\"" "$B/tree.html"'
check "S1 非法 status 计入「其他」"    'grep -q "data-st=\"other\" checked> 其他 1" "$B/tree.html" && grep -q "data-status=\"other\"" "$B/tree.html"'
# S2 注释里的结论、未闭合注释
fmn H1 "注释里的结论" Q1 closed 'verdict: refuted\n' '## 判别\n真判别\n<!--\n## 结论\n草稿：别信\n-->'
fmn H2 "未闭合注释" Q1 closed 'verdict: refuted\n' '## 判别\nx\n## 结论\n<!-- 待写\n## 教训\n不该算'
out=$(tw)
check "S2 注释里的 ## 结论 不算节"       'grep -q "H1: closed 但结论为空" <<<"$out"'
check "S2 未闭合 <!-- 去到文末并告警"    'grep -q "H2: 注释 <!-- 没闭合" <<<"$out" && grep -q "H2: closed 但结论为空" <<<"$out"'
# S3 台账：注释与代码块里的行不算实验
cat >> "$B/experiments.md" <<'EOF'
| E1 | H1 | 真行 | 1 | 成功 | 支持 | p |
<!--
| E8 | H88 | 注释里的行 | - | - | - | - |
-->
| E2 | H1 | 注释后同表的行 | 1 | 成功 | 支持 | p |

```
| id | node |
|---|---|
| E9 | H99 |
```
EOF
out=$(tw)
check "S3 注释、代码块里的表格行不进台账" 'grep -q "台账 2 行" <<<"$out" && ! grep -q "H88\|H99" <<<"$out" && ! grep -q "表外的行" <<<"$out"'
# S4 --blind 隐去节点引用、### 结论 不进判别、无考官卡明说
fmn H3 "盲测对象" Q1 active '' '## 判别\n候选 [[H1]] 排第一，[[H2]] 第二。\n### 结论\n泄露的结论'
out=$(tw --ctx H3 --blind)
check "S4 --blind 把 [[ID]] 换成 [[…]] 并在顶部告警" 'head -n1 <<<"$out" | grep -q "判别引用了 2 个节点" && grep -q "候选 \[\[…\]\] 排第一" <<<"$out" && ! grep -q "\[\[H1\]\]" <<<"$out"'
check "S4 ### 结论 不混进判别"           '! grep -q "泄露的结论" <<<"$out" && grep -q "H3: 「### 结论」当成一节" <<<"$(tw)"'
mv "$B/verifier.md" "$T/v.bak"
check "S4 无 verifier.md 时明说无考官卡" 'tw --ctx H3 --blind | grep -q "无考官卡"'
mv "$T/v.bak" "$B/verifier.md"
rm -f "$B/tree/H"[123].md
gq add -A >/dev/null; gq commit -qm base
# S5 tree.html 冲突自动重渲染；其他冲突拒绝提交
fmn H4 "主线标题" Q1 open '' ''
fmn H5 "分支前" Q1 open '' ''
python3 "$TP" "$B" --render >/dev/null; gq add -A; gq commit -qm m1
gq checkout -qb side; fmn H5 "分支改的标题" Q1 open '' ''; python3 "$TP" "$B" --render >/dev/null; gq commit -qam side
gq checkout -q main; fmn H4 "主线改的标题" Q1 open '' ''; python3 "$TP" "$B" --render >/dev/null; gq commit -qam main2
gq merge -q side >/dev/null 2>&1
check "S5 前提：tree.html 处于冲突"       '[ -n "$(git -C "$B" ls-files -u -- tree.html)" ]'
out=$(bash "$PT" index rb "合并后 checkpoint" 2>&1); rc=$?
check "S5 index 重渲染并收下冲突的 tree.html" '[ $rc -eq 0 ] && [ -z "$(git -C "$B" ls-files -u)" ] && [ "$(git -C "$B" rev-list --parents -1 HEAD | wc -w)" = 3 ] && grep -q "主线改的标题" "$B/tree.html" && grep -q "分支改的标题" "$B/tree.html"'
gq checkout -qb side2; echo "分支加的一行" >> "$B/charter.md"; gq commit -qam s2
gq checkout -q main; echo "主线加的一行" >> "$B/charter.md"; gq commit -qam m3
gq merge -q side2 >/dev/null 2>&1
n0=$(git -C "$B" rev-list --count HEAD)
out=$(bash "$PT" index rb "不该提交" 2>&1); rc=$?
check "S5 有没合完的冲突：index 拒绝并列出文件" '[ $rc -ne 0 ] && grep -q "没合完的冲突.*charter.md" <<<"$out" && [ -z "$(git -C "$B" status --porcelain state.md)" ] && [ "$(git -C "$B" rev-list --count HEAD)" = "$n0" ]'
gq add charter.md
out=$(bash "$PT" index rb "标记还在" 2>&1); rc=$?
check "S5 冲突标记被 add 进去了也拒绝"    '[ $rc -ne 0 ] && grep -q "冲突.*charter.md" <<<"$out" && [ "$(git -C "$B" rev-list --count HEAD)" = "$n0" ]'
gq reset -q; git -C "$B" show HEAD:charter.md > "$B/charter.md"; gq checkout -qb side3; echo "分支三" >> "$B/charter.md"; gq commit -qam s3
gq checkout -q main; echo "主线三" >> "$B/charter.md"; gq commit -qam m4; gq merge -q side3 >/dev/null 2>&1
git -C "$B" show HEAD:charter.md > "$B/charter.md"   # 在工作区里改好（不 git add）
out=$(bash "$PT" index rb "工作区里合好了" 2>&1); rc=$?
check "S5 工作区里已改好的冲突（无标记）照常提交" '[ $rc -eq 0 ] && [ -z "$(git -C "$B" ls-files -u)" ] && [ "$(git -C "$B" rev-list --parents -1 HEAD | wc -w)" = 3 ]'
check "S5 tree.py 对含冲突标记的节点告警" 'printf -- "---\ntitle: t\nparent: Q1\nstatus: open\n---\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> side\n" > "$B/tree/H6.md"; tw | grep -q "H6: 含合并冲突标记"'
rm -f "$B/tree/H6.md"; git -C "$B" show HEAD:charter.md > "$B/charter.md"; echo "合好的一行" >> "$B/charter.md"; gq add -A; gq commit -qm resolved
check "S5 brief 分叉提示写 tree.html 不用手合" 'grep -q "tree.html 不用手合，pt index 会重新生成" "$(dirname "$PT")/pt.sh"'
# S6 pt new 名称含 sed 特殊字符
out=$(bash "$PT" new sedname 'A|B & \1 C/D' "$T/other/x" 2>&1); rc=$?
check "S6 名称含 | & \\1 照原样写进 charter" '[ $rc -eq 0 ] && [ "$(head -n1 "$T/root/sedname/charter.md")" = "# A|B & \1 C/D" ] && bash "$PT" list --no-sync | grep -qF "A|B & \1 C/D ｜ Workdir"'
out=$(bash "$PT" new sedbad "$(printf 'a\nb')" "$T/other/x" 2>&1); rc=$?
check "S6 sed 处理不了的名称：报错且不留空档案" '[ $rc -ne 0 ] && [ ! -e "$T/root/sedbad" ]'
# M1 Status 带括号注
sed -i "s/^Status:.*/Status: 进行中 (探索期)/" "$B/charter.md"
check "M1 Status「进行中 (探索期)」where 照样命中" '(cd "$T/rbw" && bash "$PT" where) | grep -qx rb'
check "M1 INDEX 状态列按括号前的状态值算" 'bash "$PT" list --no-sync >/dev/null; grep -q "^| rb | 进行中 |" "$T/root/INDEX.md"'
check "M1 precompact 命中带注的进行中项目" '(cd "$T/rbw" && bash "$PT" precompact </dev/null) | grep -q "项目 rb"'
# M2 考官卡「未冻结」不算冻结
sed -i "s/^Updated: .*/Updated: $D   Status: 未冻结（等用户）/" "$B/verifier.md"
check "M2 未冻结的考官卡：简报只给指针"   'o=$(bash "$PT" brief rb); grep -q "verifier.md（考官）" <<<"$o" && ! grep -q "^## 数据与暴露史" <<<"$o"'
# M3 渲染用唯一临时文件、不留残留
for k in 1 2 3 4 5 6; do python3 "$TP" "$B" --render >/dev/null 2>"$T/race.$k" & done; wait
check "M3 并发渲染都成功、无临时文件残留" '! grep -q . "$T"/race.* && [ -z "$(ls -A "$B" | grep tmp)" ] && [ -r "$B/tree.html" ] && [ "$(stat -c %a "$B/tree.html")" != 600 ]'
# M4 坏文件不让整棵树崩
printf -- '---\ntitle: \xff\xfe 坏编码\n---\n' > "$B/tree/H7.md"
mkdir "$B/tree/H8.md"; ln -s "$T/nowhere" "$B/tree/H9.md"
printf '\xef\xbb\xbf---\ntitle: BOM 节点\nparent: Q1\nstatus: open\n---\n' > "$B/tree/H10.md"
out=$(tw); rc=$?
check "M4 非 UTF-8、目录、坏软链只告警"   '[ $rc -eq 0 ] && ! grep -q Traceback <<<"$out" && grep -q "tree/H7.md: 不是 UTF-8" <<<"$out" && grep -q "tree/H8.md: 忽略的文件（是目录）" <<<"$out" && grep -q "tree/H9.md: 忽略的文件（坏软链）" <<<"$out"'
check "M4 BOM 节点照常读 frontmatter"     'grep -q "^- H10 \[open\] BOM 节点" <<<"$out" && ! grep -q "H10: 没有 frontmatter" <<<"$out"'
rm -rf "$B/tree/H7.md" "$B/tree/H8.md" "$B/tree/H9.md" "$B/tree/H10.md"
# M5 一句话不能有换行
cp "$B/state.md" "$T/state.bak"
out=$(bash "$PT" index rb "$(printf '第一行\n## 注入的节')" 2>&1); rc=$?
check "M5 一句话含换行：拒绝、state 不变" '[ $rc -ne 0 ] && cmp -s "$B/state.md" "$T/state.bak"'
check "M5 一句话纯空白：拒绝"            '! bash "$PT" index rb "   " 2>/dev/null'
# M6 / M7 / M8
fmn Q2 "搁置的问题" Q1 parked '' ''
fmn H11 "搁置问题下的假设" Q2 open '' ''
fmn Q3 "已关的问题" Q1 closed 'verdict: supported\n' '## 结论\nTODO'
fmn H12 "已关问题下还在做" Q3 active '' '## 判别\n预测。'
fmn Q4 "子假设全关" Q1 active '' '## 判别\n为什么问。'
fmn H13 "关了的子假设" Q4 closed 'verdict: refuted\n' '## 结论\n不支持（E1）。'
out=$(tw)
check "M6 前沿行写出父节点的搁置状态"    'grep -q "^- H11 \[open\] 搁置问题下的假设（Q2 下，父 Q2 parked）" <<<"$out" && grep -q "^- H12 已关问题下还在做（父 Q3 closed）" <<<"$out"'
check "M6 父已 closed 的 active 节点告警" 'grep -q "H12: active，但父 Q3 已 closed" <<<"$out"'
check "M7 子假设全关的 active 问题有提示"  'sed -n "/^- Q4 /,/^- /p" <<<"$out" | grep -q "子假设全关：决定答完"'
check "M8 结论写 TODO 算空"              'grep -q "Q3: closed 但结论为空" <<<"$out"'
rm -f "$B/tree/"{Q2,H11,Q3,H12,Q4,H13}.md
# M9 台账解析
cat > "$B/experiments.md" <<'EOF'
# 实验台账
## 一
| ID | **Node(s)** | 读数 |
|-|:-:|-|
| E1 | H4 | 1 |
| E2 | H5 | 2 | 多一列 |

| E3 | H4 | 表外 |

## 二
id | 节点 ID | 读数
---|---|---
E4 | `H4`（主）/ **H5** 和 H4 | 3
E5 | N/A | -
EOF
out=$(tw)
check "M9 |-| 分隔行、无前导竖线的表、表头 **Node(s)** / 节点 ID" 'grep -q "台账 4 行，挂到节点的 3 行" <<<"$out"'
check "M9 列数不符告警带行号"            'grep -q "experiments.md 第 6 行：4 列，表头 3 列" <<<"$out"'
check "M9 表后的竖线行告警「表外的行」"   'grep -q "experiments.md 第 8 行：表外的行" <<<"$out"'
check "轻 node 单元格规范化（反引号、括号注、/、和、N/A、去重）" 'tw --ctx H5 | grep -qF "E4 | \`H4\`（主）/ **H5** 和 H4 | 3" && ! grep -q "node N\b\|node A\b\|node 和" <<<"$out"'
# M10 frontmatter
nd H14.md '---\ntitle: 没闭合\nparent: Q1\nstatus: open\n## 判别\nx\n'
nd H15.md '---\ntitle: 块列表\nparent:\n  - Q1\nstatus: open\nsttaus: open\nstatus: parked\nverdict： x\n---\n'
out=$(tw)
check "M10 未闭合 frontmatter 在 ## 前截断并告警" 'grep -q "H14: frontmatter 没闭合" <<<"$out" && grep -q "^- H14 \[open\] 没闭合（Q1 下）" <<<"$out"'
check "M10 块列表、全角冒号、未知键、重复键都告警" 'grep -q "H15: frontmatter 的 parent 写成了块列表" <<<"$out" && grep -q "H15: frontmatter 用了全角冒号" <<<"$out" && grep -q "H15: frontmatter 未知键 sttaus" <<<"$out" && grep -q "H15: frontmatter 重复的键 status" <<<"$out"'
rm -f "$B/tree/H14.md" "$B/tree/H15.md"
# M11 两个 ## 结论
fmn H16 "两次结论" Q1 closed 'verdict: refuted\n' '## 结论\n旧结论：支持。\n## 结论\n新结论：其实否了。'
out=$(tw --all)
check "M11 同名节告警、取最后一个"       'grep -q "H16: 有 2 个「## 结论」" <<<"$out" && grep -q "^- H16 \[refuted\] 两次结论 —— 新结论：其实否了。" <<<"$out"'
rm -f "$B/tree/H16.md"
# M12 不合规的文件名不当节点
for f in h33.md H027.md README.md H27-old.md "H27 .md"; do fmn "${f%.md}" "坏名 $f" Q1 open '' ''; done
out=$(tw)
check "M12 不合规文件名一律忽略并告警"    '[ "$(grep -c "忽略的文件（文件名不是" <<<"$out")" = 5 ] && ! grep -q "坏名" <<<"$out"'
rm -f "$B/tree/"{h33,H027,README,H27-old}.md "$B/tree/H27 .md"
# M13 / M14 / M15 html
fmn H17 "html 标记" Q1 open '' '## 判别\n**粗 [链](http://a/**b) 与 `c**d`**；私有区 \xee\x80\x800\xee\x80\x81 字符\n[x](#[[Q1]])'
python3 "$TP" "$B" --render >/dev/null; rc=$?
check "M13 粗体跨不进链接 URL、私有区字符不崩" '[ $rc -eq 0 ] && python3 - "$B/tree.html" <<PY
import sys, re
s = open(sys.argv[1]).read(); a = s[s.index("id=\"n-H17\""):]; a = a[:a.index("</article>")]
ok = a.count("<strong>") == a.count("</strong>") and "href=\"http://a/**b\"" in a and "<code>c**d</code>" in a and "href=\"#<" not in a
sys.exit(0 if ok else 1)
PY'
check "M14 正文与表格长串可断行"          'grep -q "article,td{overflow-wrap:anywhere}" "$B/tree.html"'
check "M15 搜索只看标题与正文、ID 精确命中" 'grep -q "<div class=body>" "$B/tree.html" && grep -q "querySelector(.\.body.)" "$B/tree.html" && grep -q "ex?id===ex" "$B/tree.html"'
check "轻 html：hash 解码容错、没有节点提示、nav title、顶栏告警数" 'grep -q "try{id=decodeURIComponent(id);}catch" "$B/tree.html" && grep -q "id=miss" "$B/tree.html" && grep -q "title=\"H17 html 标记\"" "$B/tree.html"'
rm -f "$B/tree/H17.md"
# M16 根约束引用另一个根
nd Q1.md '---\ntitle: 根一\nparent:\nstatus: active\n---\n## 判别\n为什么问。\n## 约束\n- 协议同 [[Q5]]\n'
fmn Q5 "根五" '' parked '' '## 约束\n- 根五的禁读切分'
fmn H18 "根一下的假设" Q1 active '' '## 判别\n预测。'
check "M16 --ctx 带上被引用根的约束"      'tw --ctx H18 | grep -q "根五的禁读切分"'
check "M16 --blind 也带"                 'tw --ctx H18 --blind | grep -q "根五的禁读切分"'
# M17 abandoned
fmn H19 "预算停了" Q1 closed 'verdict: abandoned\n' '## 结论\n用户决定停（预算用完，2026-10-20）。'
check "M17 verdict abandoned 合法"       '! tw | grep -q "H19:"'
# 轻：parent/by 规范化与告警
fmn H20 "双括号父" '[[Q1]]' open '' ''
fmn H21 "两个父" 'Q1, Q5' open '' ''
fmn H22 "自指 by" Q1 closed 'verdict: superseded\nby: H22\n' '## 结论\n被取代。'
fmn H23 "多余的 by" Q1 closed 'verdict: refuted\nby: [[H19]]\n' '## 结论\n否。'
fmn H24 "空判别在做" Q1 active '' '## 判别\n'
out=$(tw)
check "轻 parent [[Q1]] 去括号"           '! grep -q "H20:" <<<"$out" && grep -q "^- H20 \[open\] 双括号父（Q1 下）" <<<"$out"'
check "轻 parent 多个值告警"              'grep -q "H21: parent 只能一个" <<<"$out"'
check "轻 by 指向自己、非 superseded 写 by 告警" 'grep -q "H22: by 指向自己" <<<"$out" && grep -q "H23: 写了 by 但 verdict 不是 superseded" <<<"$out" && ! grep -q "H23: by" <<<"$out"'
check "轻 active 假设判别为空告警"        'grep -q "H24: 假设 active 但判别为空" <<<"$out"'
rm -f "$B/tree/"H2[0-4].md "$B/tree/H19.md" "$B/tree/H18.md" "$B/tree/Q5.md"
# 轻：深链与长前沿
rm -f "$B/tree/H4.md" "$B/tree/H5.md"
python3 - "$B/tree" <<'PY'
import sys, os
d = sys.argv[1]
for k in range(100, 2100):
    open(os.path.join(d, f"H{k}.md"), "w").write(f"---\ntitle: 链 {k}\nparent: {'Q1' if k == 100 else f'H{k-1}'}\nstatus: open\n---\n")
PY
out=$(timeout 60 python3 "$TP" "$B" 2>&1); rc=$?
check "轻 2000 层深链不崩、open 超 50 条截断" '[ $rc -eq 0 ] && grep -q "另有 1950 个，见 pt tree rb --all" <<<"$out" && [ "$(timeout 60 python3 "$TP" "$B" --all --no-html | grep -c "^- H[0-9]* \[open\]")" = 2000 ]'
rm -f "$B/tree/"H[0-9][0-9][0-9]*.md
# M18：brief / precompact / index 用法；pt research 补 Q1、冻结后不再催
printf '\n## 当前认识\n- 一条写错地方的认识\n' >> "$B/state.md"
check "M18 brief 提示 state 里的当前认识应在根节点" 'bash "$PT" brief rb | grep -q "研究项目这两节应在根节点"'
check "M18 precompact 有研究树时要列节点与台账改动" '(cd "$T/rbw" && bash "$PT" precompact </dev/null) | grep -q "改过 status/verdict 的节点"'
check "M18 index 用法写明一句话不是提交说明" 'bash "$PT" index 2>&1 | grep -q "不是提交说明"'
sed -i "s/^Updated: .*/Updated: $D   Status: 已冻结（用户确认）/" "$B/verifier.md"
rm -f "$B/tree/"*.md
out=$(bash "$PT" research rb)
check "轻 research：tree/ 没有节点时补 Q1，冻结后不催填考官卡" '[ -f "$B/tree/Q1.md" ] && grep -q "考官卡已冻结" <<<"$out" && ! grep -q "先填 verifier.md" <<<"$out"'

echo "# monitor（全局研究监控 research.html）"
export PROJECT_TRACKER_ROOT="$T/mon"
M="$T/mon"; NOW=$(date +%s)
at(){ export GIT_COMMITTER_DATE="@$((NOW - $1)) +0000" GIT_AUTHOR_DATE="@$((NOW - $1)) +0000"; }
nd(){ printf -- '---\ntitle: %s\nparent: %s\nstatus: %s\n%b---\n## 判别\n预测。\n## 结论\n%b\n' "$3" "$4" "$5" "$6" "$7" > "$M/$1/tree/$2.md"; }
at 1800000; bash "$PT" new ra "研究甲" "$T/other/ra" >/dev/null; bash "$PT" research ra >/dev/null   # 20 天前：窗口外
at 4900; bash "$PT" new rb "研究乙" "$T/other/rb" >/dev/null; bash "$PT" research rb >/dev/null
bash "$PT" new plain "普通项目" "$T/other/plain" >/dev/null
at 4000; nd ra H1 "甲一" Q1 open "" ""; nd ra H2 "甲二" Q1 open "" ""; nd ra Q2 "甲根二" "" open "" ""
bash "$PT" index ra "加三个节点" >/dev/null
check "pt index 研究项目后生成 research.html" '[ -f "$M/research.html" ]'
at 3000; nd rb H1 '乙一 <script>alert(1)</script> " onmouseover=x' Q1 open "" ""; bash "$PT" index rb '<img src=x onerror=alert(2)>' >/dev/null
at 2000; nd ra H1 "甲一" Q1 active "" ""; bash "$PT" index ra "H1 转 active" >/dev/null
at 1000; nd ra H1 "甲一" Q2 active "" ""; nd ra H2 "甲二" Q1 closed 'verdict: refuted\n' "否：E1。"; bash "$PT" index ra "H2 否，H1 挪到 Q2" >/dev/null
at 800; nd ra H2 "甲二" Q1 closed 'verdict: inconclusive\n' "说不清：E1。"; bash "$PT" index ra "H2 改判" >/dev/null
at 500; rm "$M/rb/tree/H1.md"; git -C "$M/rb" add -A; git -C "$M/rb" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -qm "手工 @far-box: 删 H1"
at 100; bash "$PT" index plain "普通项目不进页面" >/dev/null
unset GIT_COMMITTER_DATE GIT_AUTHOR_DATE
ev=$(python3 "$(dirname "$PT")/monitor.py" "$M" --events | cut -f2-6)
exp=$(printf '%s\n' "rb	H1	del	open	far-box" "ra	H2	verdict	closed/refuted → closed/inconclusive	本机" \
  "ra	H1	parent	Q1 → Q2	本机" "ra	H2	status	open → closed/refuted	本机" "ra	H1	status	open → active	本机" \
  "rb	H1	add	open	本机" "ra	H1	add	open	本机" "ra	H2	add	open	本机" "ra	Q2	add	open	本机" "rb	Q1	add	active	本机")
check "时间线：新增/状态/结论/换父/删除、机器、跨项目按时间倒序、窗口外不算" '[ "$ev" = "$exp" ]'
out=$(bash "$PT" monitor); HT="$M/research.html"
check "pt monitor 汇报并重写"            'grep -q "2 个研究项目" <<<"$out" && grep -q "10 条动态" <<<"$out"'
check "非研究项目不进卡片，只在顶部总览"  '! grep -q "href=\"plain/tree.html\"" "$HT" && grep -q "<td class=sl title=\"[^\"]*\">plain</td>" "$HT" && grep -q "href=\"ra/tree.html\"" "$HT" && grep -q "href=\"rb/tree.html\"" "$HT"'
check "卡片按最近 tree/ 变动倒序（rb 先）" '[ "$(grep -o "<article class=card><h3><a href=\"r[ab]/" "$HT" | cut -d\" -f2 | tr -d "\n")" = "rb/ra/" ]'
check "事件链到节点（删除的只到 tree.html）" 'grep -q "href=\"ra/tree.html#H2\"" "$HT" && grep -q "<li><a class=id href=\"rb/tree.html\">H1</a>" "$HT"'
check "焦点路径：根 → 活跃叶，带标题悬停" 'grep -q "<a class=id href=\"ra/tree.html#Q2\" title=\"甲根二\">Q2</a><span class=sep>›</span><a class=id href=\"ra/tree.html#H1\" title=\"甲一\">H1</a>" "$HT"'
check "计数条与图标（active / ? / 共）"   'grep -q "active 1" "$HT" && grep -q "inconclusive 1" "$HT" && grep -q "共 4" "$HT"'
check "无外部 URL"                       '! grep -qiE "https?:|//[a-z0-9]" "$HT"'
check "无 on* 属性"                       '! grep -qiE "<[^>]*[[:space:]]on[a-z]+=" "$HT"'
check "注入串被转义"                     'grep -q "&lt;script&gt;alert(1)&lt;/script&gt;" "$HT" && grep -q "&lt;img src=x onerror=alert(2)&gt;" "$HT" && ! grep -q "<script>alert\|<img" "$HT"'
check "不是中心机：不写上次同步；带自动刷新开关" '! grep -q "上次同步" "$HT" && grep -q "id=ar checked" "$HT"'
python3 "$(dirname "$PT")/monitor.py" "$M" --out "$T/elsewhere/r.html" >/dev/null
check "--out 别处：链接改成相对档案根"    'grep -q "href=\"../mon/ra/tree.html#H1\"" "$T/elsewhere/r.html"'
check "monitor 不动项目档案"              '[ -z "$(git -C "$M/ra" status --porcelain)" ] && [ -z "$(git -C "$M/rb" status --porcelain)" ] && ! ls "$M"/*/research.html 2>/dev/null'
export PROJECT_TRACKER_ROOT="$T/root"

echo "# serve（只读 HTTP，身份白名单，路径白名单）"
SV="$T/srv"; mkdir -p "$SV/ra/tree" "$SV/nt" "$SV/ln/tree" "$T/outside/tree"
echo '<p>RESEARCH</p>' > "$SV/research.html"; echo '<p>TREE-RA</p>' > "$SV/ra/tree.html"
echo secret > "$SV/ra/state.md"; echo secret > "$SV/ra/journal.md"; echo '<p>NT</p>' > "$SV/nt/tree.html"
echo '<p>OUTSIDE</p>' > "$T/outside/tree.html"; ln -s "$T/outside" "$SV/evil"; ln -s "$T/outside/tree.html" "$SV/ln/tree.html"
SERVE="$(dirname "$PT")/serve.py"
check "没有 .serve.conf 拒绝启动"          '! python3 "$SERVE" --root "$SV" run --port 0 2>"$T/sv.err" && grep -q "serve.conf" "$T/sv.err"'
printf 'port=18443\nallow=Me@Example.com, other@example.com\n' > "$SV/.serve.conf"
python3 "$SERVE" --root "$SV" run --port 0 >"$T/sv.out" 2>"$T/sv.log" & SVPID=$!
for _ in $(seq 50); do grep -q listening "$T/sv.out" 2>/dev/null && break; sleep 0.1; done
U="http://127.0.0.1:$(sed -n 's/.*127.0.0.1:\([0-9]*\).*/\1/p' "$T/sv.out")"
code() { curl -s --path-as-is -o /dev/null -w '%{http_code}' "$@"; }
ME=(-H 'Tailscale-User-Login: me@example.com')
check "只监听 127.0.0.1"                  'grep -q "^listening on 127.0.0.1:" "$T/sv.out"'
check "无身份头 403"                       '[ "$(code "$U/")" = 403 ]'
check "非白名单身份 403"                   '[ "$(code -H "Tailscale-User-Login: x@evil.com" "$U/")" = 403 ]'
check "Host 不是本机/ts.net 403（防 DNS rebinding）" '[ "$(code "${ME[@]}" -H "Host: evil.com" "$U/")" = 403 ]'
check "白名单身份 / → research.html"       'curl -s "${ME[@]}" "$U/" | grep -q RESEARCH && [ "$(code "${ME[@]}" "$U/research.html")" = 200 ]'
check "白名单身份（大小写无关）tree.html 200" 'curl -s -H "Tailscale-User-Login: OTHER@example.com" "$U/ra/tree.html" | grep -q TREE-RA'
check "带查询串与锚点照常"                 '[ "$(code "${ME[@]}" "$U/ra/tree.html?x=1")" = 200 ]'
for p in /../ /ra/../research.html /%2e%2e/research.html /ra/%2e%2e/ra/tree.html /ra%2ftree.html /ra/state.md /ra/journal.md /ra/tree/ /nope/tree.html /nt/tree.html /evil/tree.html /ln/tree.html /.serve.conf //etc/passwd /RA/tree.html; do
  check "拒绝 $p"                          '[ "$(code "${ME[@]}" "$U$p")" = 404 ]'
done
check "POST 405"                           '[ "$(code "${ME[@]}" -X POST "$U/")" = 405 ]'
check "HEAD 200 无正文"                    '[ "$(curl -s -I "${ME[@]}" "$U/" -o /dev/null -w "%{http_code} %{size_download}")" = "200 0" ]'
hd=$(curl -s -D - -o /dev/null "${ME[@]}" "$U/"); hd403=$(curl -s -D - -o /dev/null "$U/")
check "响应头齐全（200 与 403 都有）"       'for h in "Cache-Control: no-cache" "X-Content-Type-Options: nosniff" "Content-Security-Policy: default-src '"'"'none'"'"'" "Referrer-Policy: no-referrer"; do grep -qi "^$h" <<<"$hd" && grep -qi "^$h" <<<"$hd403" || exit 1; done'
check "日志记下身份"                       'grep -q "me@example.com" "$T/sv.log"'
kill $SVPID 2>/dev/null; wait $SVPID 2>/dev/null
python3 "$SERVE" --root "$SV" run --port 0 --allow-local >"$T/sv2.out" 2>/dev/null & SVPID=$!
for _ in $(seq 50); do grep -q listening "$T/sv2.out" 2>/dev/null && break; sleep 0.1; done
U2="http://127.0.0.1:$(sed -n 's/.*127.0.0.1:\([0-9]*\).*/\1/p' "$T/sv2.out")"
check "--allow-local：无头放行，坏身份仍 403" '[ "$(code "$U2/")" = 200 ] && [ "$(code -H "Tailscale-User-Login: x@evil.com" "$U2/")" = 403 ]'
kill $SVPID 2>/dev/null; wait $SVPID 2>/dev/null
printf 'port=18443\n' > "$SV/.serve.conf"
check "allow 为空拒绝启动"                 '! python3 "$SERVE" --root "$SV" run --port 0 2>/dev/null'
check "pt serve 经 pt.sh 转发（--root 取档案根）" 'PROJECT_TRACKER_ROOT="$T/none" bash "$PT" serve run 2>&1 | grep -q "没有档案根"'

echo "# migrate（0.3 档案）"
export PROJECT_TRACKER_ROOT="$T/old"
mkdir -p "$T/old/legacy" "$T/old/elsewhere"
for f in charter plan state journal decisions; do
  sed -e "s|{{SLUG}}|legacy|g; s|{{NAME}}|旧项目|g; s|{{DATE}}|2026-01-01|g; s|{{WORKDIR}}|$T/repoA|g; /^Host:/d; s| · @{{THIS_HOST}}||" \
    "$S/../plugins/project-tracker/skills/project-tracker/reference/templates/$f.md" > "$T/old/legacy/$f.md"
  sed -e "s|{{SLUG}}|elsewhere|g; s|{{NAME}}|别处项目|g; s|{{DATE}}|2026-01-01|g; s|{{WORKDIR}}|/home/nobody/x|g; /^Host:/d; s| · @{{THIS_HOST}}||" \
    "$S/../plugins/project-tracker/skills/project-tracker/reference/templates/$f.md" > "$T/old/elsewhere/$f.md"
done
sed -i 's/^Status:.*/Status: 暂停/' "$T/old/elsewhere/charter.md"
printf '# 项目索引\n\n| Slug | 名称 | 状态 | 最后更新 | 一句话 |\n|------|------|------|----------|--------|\n| legacy | 旧项目 | 进行中 | 2026-01-05 | 旧的一句话 |\n| elsewhere | 别处项目 | 进行中 | 2026-01-06 | 在别处 |\n' > "$T/old/INDEX.md"
out=$(bash "$PT" migrate)
check "migrate 先备份"                 'ls "$T/old/.backup/"pre-0.4-*.tgz >/dev/null && tar tzf "$T/old/.backup/"pre-0.4-*.tgz | grep -q "legacy/charter.md"'
check "Workdir 在本机 → Host=本机"      'grep -q "^Host: host-me$" "$T/old/legacy/charter.md"'
check "Workdir 不在本机 → 待定位 + 提示" 'grep -q "^Host: 待定位$" "$T/old/elsewhere/charter.md" && grep -q "elsewhere.*待定位" <<<"$out"'
check "INDEX 一句话写进 state 首行"     '[ "$(awk "/^## 一句话概括/{f=1;next} f&&NF{print;exit}" "$T/old/legacy/state.md")" = "旧的一句话" ] && grep -q "刚立项，尚未动手" "$T/old/legacy/state.md"'
check "状态不一致时提示"               'grep -q "elsewhere.*状态不一致 INDEX=进行中 charter=暂停" <<<"$out"'
check "迁移后是 git 仓且干净"           '[ -z "$(git -C "$T/old/legacy" status --porcelain)" ] && git -C "$T/old/legacy" log -1 --format=%s | grep -q "^migrate to 0.4"'
check "INDEX 重建为新格式"             'grep -q "| 现在最信的一条 |" "$T/old/INDEX.md" && grep -q "^| legacy | 进行中[^|]* | 2026-01-01 journal |" "$T/old/INDEX.md"'
check "迁移提交不算最近活动（取 journal 日期）" 'grep -q "^| elsewhere | 暂停 | 2026-01-01 journal |" "$T/old/INDEX.md"'
n1=$(git -C "$T/old/legacy" rev-list --count HEAD)
bash "$PT" migrate >/dev/null
check "migrate 幂等"                   '[ "$(git -C "$T/old/legacy" rev-list --count HEAD)" = "$n1" ] && [ "$(grep -c "旧的一句话" "$T/old/legacy/state.md")" = 1 ] && [ "$(grep -c "^Host:" "$T/old/legacy/charter.md")" = 1 ]'

echo "# where 护栏：Workdir 是主目录、/ 或主目录的上级时不算命中"
unset GIT_COMMITTER_DATE GIT_AUTHOR_DATE
GR="$T/guard"; GH="$T/gp/home"; mkdir -p "$GH/sub" "$GH/repo" "$T/gp/other"
gw(){ (export PROJECT_TRACKER_ROOT="$GR" HOME="$GH"; cd "$1" && bash "$PT" "${2:-where}" </dev/null); }
(export PROJECT_TRACKER_ROOT="$GR" HOME="$GH"
 bash "$PT" new ghome "主目录" "$GH" >/dev/null; bash "$PT" new gtilde "波浪号" "~" >/dev/null
 bash "$PT" new gslash "根目录" / >/dev/null; bash "$PT" new gparent "上级" "$T/gp" >/dev/null
 bash "$PT" new grepo "正常仓库" "~/repo" >/dev/null; echo nothing > "$GR/ACTIVE")
check "Workdir=\$HOME / ~ / / / 上级：在 ~ 下不命中"  '[ -z "$(gw "$GH")" ]'
check "同上：在 ~ 的子目录也不命中"                    '[ -z "$(gw "$GH/sub")" ]'
check "上级目录的 Workdir 在 ~ 之外也不算"            '[ -z "$(gw "$T/gp/other")" ]'
check "~/repo 照常命中且只命中它"                     '[ "$(gw "$GH/repo")" = grepo ]'
check "从 ~ 开会话 auto 静默"                         '[ -z "$(gw "$GH" auto)" ]'

echo "# INDEX 最后更新不算 autosync 提交"
AR="$T/asy"
(export PROJECT_TRACKER_ROOT="$AR" GIT_AUTHOR_DATE="2026-01-02T10:00:00" GIT_COMMITTER_DATE="2026-01-02T10:00:00"
 cd "$T/other" && bash "$PT" new syn "同步项目" "$T/other" >/dev/null && sed -i "s/^## \[$D\]/## [2026-01-02]/" "$AR/syn/journal.md" &&
 bash "$PT" index syn "旧进展" >/dev/null)
echo "改动" >> "$AR/syn/state.md"
git -C "$AR/syn" -c user.name=pt -c user.email=pt@x commit -qam "autosync @host-me (idle)"
PROJECT_TRACKER_ROOT="$AR" bash "$PT" list --no-sync >/dev/null
check "autosync 之后最近活动仍是上次 checkpoint 的日期" 'grep -q "^| syn | 进行中[^|]* | 2026-01-02 " "$AR/INDEX.md"'
PROJECT_TRACKER_ROOT="$AR" bash "$PT" index syn "新进展" >/dev/null
check "再 checkpoint 就是今天"                          'grep -q "^| syn | 进行中 | $D 提交 |" "$AR/INDEX.md"'

echo "# lint（只读体检）"
LR="$T/lint"; mkdir -p "$T/lw/a" "$T/lw/b" "$LR/.fleet/hosts/far"; echo host-far > "$LR/.fleet/hosts/far/hostname"
lt(){ PROJECT_TRACKER_ROOT="$LR" bash "$PT" lint "$@" 2>&1; }
(export PROJECT_TRACKER_ROOT="$LR"
 bash "$PT" new fresh "刚建" "$T/lw/a" >/dev/null
 bash "$PT" new good "干净" "$T/lw/b" >/dev/null
 bash "$PT" new wsh "别名主机" --host ws02 /x >/dev/null
 bash "$PT" new far "远端" --host far /srv/nowhere >/dev/null
 bash "$PT" new gone "目录没了" "$T/lw/missing" >/dev/null
 bash "$PT" new big "膨胀" "$T/lw/b" >/dev/null && bash "$PT" research big >/dev/null)
OLD=$(date -d "-10 days" +%F); OLDS=$(date -d "-10 days" +%m-%d); NEWS=$(date -d "-2 days" +%m-%d)
G="$LR/good"
printf '# 计划\nUpdated: %s\n\n## 步骤\n- [x] 1. 做完了\n' "$D" > "$G/plan.md"
printf '# 当前状态\nUpdated: %s (session 2)\n\n## 一句话概括\n好。\n\n## 焦点\n步骤 1\n\n## 下一步\n1. 跑测试\n\n## 待拍板\n- 选 A 还是 B（%s）\n- 没写日期的一条\n' "$D" "$NEWS" > "$G/state.md"
sed -i 's/<[^>]*>/已填/g' "$G/charter.md"
printf '# 当前状态\nUpdated: %s (session 3)\n\n## 待拍板（%s）\n- 老问题（%s 提出）\n  续行 %s 补充\n- 新问题 %s\n\n## 已完成\n- x\n' "$OLD" "$OLDS" "$OLDS" "$OLDS" "$NEWS" > "$LR/fresh/state.md"
printf '\n## %s · session 2 · @host-me\nDid: x\n' "$D" >> "$LR/fresh/journal.md"
B="$LR/big"
head -c 110000 /dev/zero | tr '\0' 'x' | fold -w 100 >> "$B/journal.md"
seq 1 120 | sed 's/^/- 行 /' >> "$B/state.md"
{ printf -- '---\ntitle: 根\nparent:\nstatus: active\n---\n## 当前认识\n'; head -c 4000 /dev/zero | tr '\0' 'a'; printf '\n## 教训\n'; head -c 3000 /dev/zero | tr '\0' 'b'; printf '\n'; } > "$B/tree/Q1.md"
{ printf -- '---\ntitle: 大假设\nparent: Q1\nstatus: open\n---\n## 判别\n'; head -c 6000 /dev/zero | tr '\0' 'c'; printf '\n'; } > "$B/tree/H2.md"
for p in "$LR"/*/; do git -C "$p" add -A >/dev/null; git -C "$p" -c user.name=t -c user.email=t@t commit -qm fixture >/dev/null; done
sum0=$(find "$LR" -type f -not -path '*/.git/*' -exec md5sum {} + | sort | md5sum)
out=$(lt --all); rc=$?
check "lint 退出 0"                           '[ $rc -eq 0 ]'
check "干净项目没有发现"                       '! grep -q "^good:" <<<"$out"'
check "格式 <slug>: <检查名>: <一句话>"         '! grep -v "^$" <<<"$out" | grep -v "^共 " | grep -qvE "^[a-z0-9-]+: [a-z-]+: .+"'
check "state 落后 journal"                     'grep -q "^fresh: state-stale: .*落后 10 天" <<<"$out"'
check "待拍板标题日期过期"                     'grep -q "^fresh: pending-stale: 「待拍板（$OLDS）」标题日期" <<<"$out"'
check "待拍板条目过期（续行并入，新条目不报）"  '[ "$(grep -c "^fresh: pending-stale: .*里「" <<<"$out")" = 1 ] && grep -q "老问题.*已过 10 天" <<<"$out"'
check "刚建的项目报模板占位（charter/state；plan 单列）" '[ "$(grep -c "^fresh: template: \(charter\|plan\|state\)\.md" <<<"$out")" = 1 ] && grep -q "^fresh: plan-template: plan.md 还是模板（<步骤>" <<<"$out" && grep -q "^big: template: state.md.*<只写 1 条可执行的动作>" <<<"$out"'
check "decisions 模板注释里的 <决策标题> 不报"  '! grep -q "decisions.md" <<<"$out"'
check "journal 超 100 KB"                      'grep -q "^big: journal-size: " <<<"$out"'
check "state 超上限"                           'grep -q "^big: state-size: .*超过 100 行或 24000 字节" <<<"$out"'
check "Host 别名报出，FLEET 里的主机名不报"     'grep -q "^wsh: host: Host「ws02」不是规范主机名" <<<"$out" && ! grep -q "^far: host" <<<"$out"'
check "远端项目不查 Workdir"                    '! grep -q "^far: workdir-missing" <<<"$out"'
check "本机 Workdir 不存在"                     'grep -q "^gone: workdir-missing: .*$T/lw/missing 不存在" <<<"$out"'
check "没有焦点也没有下一步"                    'grep -q "^fresh: no-focus: " <<<"$out" && ! grep -q "^big: no-focus" <<<"$out"'
check "根节点认识加教训超 6 KB"                 'grep -q "^big: tree-root-size: 根 Q1 .*6.8 KB" <<<"$out"'
check "单节点超 5 KB"                           'grep -q "^big: tree-node-size: 节点 H2 5.9 KB" <<<"$out" && [ "$(grep -c "^big: tree-node-size" <<<"$out")" = 2 ]'
check "--all 末尾给计数"                        'tail -n1 <<<"$out" | grep -q "^共 6 个项目，.*state-stale 1，pending-stale 2，.*tree-node-size 2，state-format [0-9]*，tree-know 1，journal-entry 1，status 0，plan-template [0-9]*，status-tree 0，idle 0，plan-open 0，card-missing [0-9]*，card-format 0，card-ref 0，card-number 0，cond-format 0$"'
check "单个 slug 只查它、不给计数"              'o=$(lt good fresh); grep -q "^fresh:" <<<"$o" && ! grep -q "^共 " <<<"$o"'
check "未知 slug 也退出 0"                      'lt nope >/dev/null; [ $? -eq 0 ]'
check "lint 不改任何文件、不提交"               '[ "$(find "$LR" -type f -not -path "*/.git/*" -exec md5sum {} + | sort | md5sum)" = "$sum0" ] && [ -z "$(for p in "$LR"/*/; do git -C "$p" status --porcelain; done)" ]'

echo "# 快照层：固定小节 state 的新简报"
export PROJECT_TRACKER_ROOT="$T/snap"
mkdir -p "$T/sw/e" "$T/sw/r"
(cd "$T/sw/e" && bash "$PT" new eng "工程项目" >/dev/null)
check "pt new 的 state 模板就是合格的固定小节" 'python3 "$(dirname "$PT")/brief.py" --check "$T/snap/eng/state.md"'
check "工程项目保留 plan（清单模板）"   'grep -q "^- \[ \] <步骤> → 验证：<命令或判据>" "$T/snap/eng/plan.md"'
(cd "$T/sw/r" && bash "$PT" new rsn "研究项目" >/dev/null && bash "$PT" research rsn >/dev/null)
check "研究项目：pt research 删掉没动过的模板 plan" '[ ! -e "$T/snap/rsn/plan.md" ] && [ -z "$(git -C "$T/snap/rsn" status --porcelain)" ]'
(cd "$T/sw/e" && bash "$PT" new eng2 "改过 plan" >/dev/null); printf '# 计划\n\n- [ ] 真步骤 → 验证：pytest\n' > "$T/snap/eng2/plan.md"; bash "$PT" research eng2 >/dev/null
check "改过的 plan 不删"                '[ -f "$T/snap/eng2/plan.md" ]'
SR="$T/snap/rsn"
cat > "$SR/state.md" <<'EOF'
# 当前状态
Updated: 2026-01-01

## 一句话概括
研究进行中。

## 焦点
Q3：子问题在判 H4。

## 下一步
跑 H4 的 E2。

## 待拍板
1. [待用户 01-01] 选 A 还是 B

## 线程
- [进行中] 跑 E2

## 入口与产物
- 仓库 ~/repo

## 快速启动
```bash
make test
```

## 别再试
- 别再试 X
EOF
nq(){ printf -- '---\ntitle: %s\nparent: %s\nstatus: %s\n%b---\n%b\n' "$2" "$3" "$4" "$5" "$6" > "$SR/tree/$1.md"; }
nq Q1 "根问题" "" active '' '## 判别\n为什么。\n## 当前认识\n- 根认识-甲\n## 约束\n- 根约束-乙\n## 教训\n- 根教训-丙'
nq Q3 "子问题" Q1 active '' '## 判别\n子。\n## 当前认识\n- 子认识-丁'
nq Q6 "旁支问题" Q1 closed 'verdict: supported\n' '## 结论\n答完。\n## 当前认识\n- 旁支认识-戊'
nq Q7 "搁置子问题" Q3 parked '' '## 当前认识\n- 搁置认识-己'
nq H4 "假设四" Q3 active '' '## 判别\n预测。'
nq H5 "假设五" Q3 open '' ''
{ for i in 1 2 3 4 5 6 7 8 9; do printf '\n## [2026-01-%02d] 结果 | H4 | 第 %d 条\n正文-%d\n' "$i" "$i" "$i"; done
  printf '\n## [2026-01-10] 运维 | 磁盘 | 清理\n运维正文\n'; } >> "$SR/journal.md"
for i in 1 2 3 4 5; do printf '\n## ADR-%04d: 决定 %d\nStatus: 采纳\n**背景**：adr-body-%d\n' "$i" "$i" "$i" >> "$SR/decisions.md"; done
echo "secret-charter-body" >> "$SR/charter.md"; echo "secret-verifier-body" >> "$SR/verifier.md"
out=$(bash "$PT" brief rsn); printf '%s\n' "$out" > "$T/snap-brief.txt"
check "合格 state 走新排版、块的顺序对" 'python3 - "$out" <<PY
import sys; s=sys.argv[1]; ks=["INDEX 行","= lint","= state.md","焦点问题的当前认识","= 条件","最近有结论","= 前沿","= 去哪找"]
idx=[s.find(k) for k in ks]; sys.exit(0 if all(i>=0 for i in idx) and idx==sorted(idx) else 1)
PY'
check "state 全文在"                    'grep -q "^- 别再试 X" <<<"$out" && grep -q "^- \[进行中\] 跑 E2" <<<"$out" && grep -q "^make test" <<<"$out"'
check "焦点链：根与 Q3 的当前认识，不含已关 / 搁置 / 链外的" 'grep -q "^- 根认识-甲" <<<"$out" && grep -q "^- 子认识-丁" <<<"$out" && ! grep -q "旁支认识-戊\|搁置认识-己\|根约束-乙" <<<"$out"'
check "前沿：计数加 active / open 标题"  'grep -q "^计数：" <<<"$out" && grep -q "^- H4 \[在做\] 假设四（Q3 下）" <<<"$out" && grep -q "^- H5 \[待做\] 假设五" <<<"$out" && ! sed -n "/= 前沿/,/= 去哪找/p" <<<"$out" | grep -q "^- Q6 \[\|^- Q7 \["'
check "最近有结论：已关的 Q6 一行，没写卡标（摘）" 'grep -q "^- Q6 \[已答\] .* 旁支问题 — （摘）答完。" <<<"$out"'
check "journal 与 ADR 正文、标题都不进研究项目简报" '! grep -q "第 9 条\|正文-9\|adr-body\|ADR-0001: <决策标题>" <<<"$out" && grep -q "journal 新条目：## \[YYYY-MM-DD\]" <<<"$out"'
check "charter / 考官卡正文只给指针"    '! grep -q "secret-charter-body\|secret-verifier-body" <<<"$out" && grep -q "verifier.md（考官）" <<<"$out" && grep -q "experiments.md（读数只在这里）" <<<"$out" && grep -q "decisions.md（为何转向）" <<<"$out" && grep -q "pt get rsn <编号>" <<<"$out" && grep -q "pt find rsn <词>" <<<"$out"'
check "lint 告警块（state 落后 journal）" 'grep -q "^state-stale: " <<<"$out"'
check "新简报不超过 8192 字节"          '[ "$(wc -c < "$T/snap-brief.txt")" -le 8192 ]'
check "工程项目：模板 plan 不进简报，lint 报出" 'o=$(bash "$PT" brief eng); grep -q "^plan-template: " <<<"$o" && ! grep -q "plan.md（计划）" <<<"$o" && ! grep -q "^- \[ \] <步骤>" <<<"$o"'
check "填过的 plan 进指针表"            'bash "$PT" brief eng2 | grep -q "plan.md（计划）"'
python3 -c "print('## 当前认识\n' + ''.join('- 长认识 %d：' % i + '证据' * 100 + '\n' for i in range(60)))" >> "$SR/tree/Q3.md"
for i in $(seq 10 70); do printf '\n## [2026-01-%02d] 结果 | H4 | %s\n' "$((i % 28 + 1))" "$(printf '长标题%.0s' $(seq 1 30))" >> "$SR/journal.md"; done
out=$(bash "$PT" brief rsn); n=$(printf '%s\n' "$out" | wc -c)
check "当前认识很大时仍不超过 8192 字节，按条放、余下给 pt get" '[ "$n" -le 8192 ] && grep -q "^- 长认识 0：" <<<"$out" && grep -q "Q3 余下 [0-9]* 条：pt get rsn Q3" <<<"$out" && grep -q "^- \[进行中\] 跑 E2" <<<"$out" && grep -q "= 去哪找" <<<"$out"'
check "不合格（多一节）：同样的块，state 只取四类小节" 'printf "\n## 已完成\n- x\n" >> "$SR/state.md"; o=$(bash "$PT" brief rsn); grep -q "= state.md（旧格式" <<<"$o" && grep -q "其余小节未展开：.*已完成" <<<"$o" && grep -q "^跑 H4 的 E2。" <<<"$o" && grep -q "选 A 还是 B" <<<"$o"'

echo "# 快照层：pt tree 打焦点链的当前认识"
sed -i '/^## 已完成$/,$d' "$SR/state.md"
out=$(bash "$PT" tree rsn)
check "pt tree 打出焦点链上非根问题节点的当前认识" 'grep -q "^## 焦点链的当前认识（焦点 Q3, H4，取自state「焦点」）" <<<"$out" && grep -q "^### Q3 \[active\] 子问题" <<<"$out" && ! grep -q "旁支认识-戊" <<<"$out"'
check "--roots-only 与 0.6.10 一样不打"  '! python3 "$(dirname "$PT")/tree.py" "$SR" --no-html --roots-only | grep -q "焦点链"'
sed -i 's/^Q3：子问题在判 H4。$/还没定。/' "$SR/state.md"
check "state 焦点没写节点时取进行中的叶节点" 'bash "$PT" tree rsn | grep -q "^## 焦点链的当前认识（焦点 H4，取自进行中的叶节点）"'

echo "# 快照层：pt index 写 Updated"
bash "$PT" index rsn "研究推进" >/dev/null
check "index 把 Updated 写成今天"        '[ "$(grep -c "^Updated: $D$" "$SR/state.md")" = 1 ]'
printf '# 当前状态\n\n## 焦点\nx\n' > "$T/snap/eng/state.md"; bash "$PT" index eng "无 Updated" >/dev/null
check "没有 Updated 行就补在标题后"      '[ "$(sed -n 2p "$T/snap/eng/state.md")" = "Updated: $D" ]'

echo "# 快照层：lint 新检查"
LQ="$T/snap/rsn"
printf '## 当前认识更新（01-02）\n- 追加的\n' >> "$LQ/tree/Q1.md"
printf '\n## [2026-01-30] 结果 | H4 | 太长\n%s\n' "$(head -c 4000 /dev/zero | tr '\0' 'z')" >> "$LQ/journal.md"
printf '\n## 2026-01-31 · session 9 · @x\n%s\n' "$(head -c 4000 /dev/zero | tr '\0' 'y')" >> "$LQ/journal.md"
sed -i 's/^Status:.*/Status: 进行中 (探索期)/' "$LQ/charter.md"
printf '# s\n\n## 一句话概括\nx\n\n## 已完成\n- y\n' > "$T/snap/eng2/state.md"
out=$(bash "$PT" lint rsn eng2 eng)
check "state-format：缺哪节、多了哪节"    'grep -q "^eng2: state-format: .*缺 焦点、下一步；多了 已完成" <<<"$out" && ! grep -q "^rsn: state-format" <<<"$out"'
check "state-format：超 3 KB 报超了多少"  'grep -q "^rsn: state-format: .*超 3.0 KB 上限 [0-9]* 字节" <<<"$(python3 -c "print(\"- \" + \"字\" * 1200)" >> "$LQ/state.md"; bash "$PT" lint rsn)"'
check "tree-know：问题节点当前认识超 3 KB" 'grep -q "^rsn: tree-know: Q3 的「当前认识」.*超过 3.0 KB" <<<"$out"'
check "tree-know：追加小节"               'grep -q "^rsn: tree-know: Q1 有 1 个追加小节（「当前认识更新（01-02）」" <<<"$out"'
check "journal-entry：只查新格式条目"     'grep -q "^rsn: journal-entry: 条目「\[2026-01-30\] 结果 | H4 | 太长」" <<<"$out" && [ "$(grep -c "^rsn: journal-entry" <<<"$out")" = 1 ]'
check "status：不在规范取值"              'grep -q "^rsn: status: charter Status「进行中 (探索期)」不是规范取值" <<<"$out"'
check "plan-template：只查工程项目"       'grep -q "^eng: plan-template: " <<<"$out" && ! grep -q "^eng2: plan-template" <<<"$out" && ! grep -q "^rsn: plan-template" <<<"$out"'
check "认得出 0.6.10 的 plan 模板"         'printf "# 计划\n\n## 步骤\n- [ ] 1. <当前步骤> ← 进行中\n" > "$T/snap/eng/plan.md"; bash "$PT" lint eng | grep -q "^eng: plan-template: .*<当前步骤>"'

echo "# 快照层：journal-archive"
JR="$T/snap/eng"; PM=$(date -d "$(date +%Y-%m-01) -1 day" +%Y-%m); CM=$(date +%Y-%m)
{ printf '# Journal（只追加）\n\n## 无日期的老条目\n老正文\n'
  for m in 2025-09 2025-10; do for i in $(seq 1 30); do printf '## %s-%02d · session %d · @x\n%s\n\n' "$m" "$((i % 28 + 1))" "$i" "$(head -c 2000 /dev/zero | tr '\0' 'o')"; done; done
  printf '## [%s-02] 结果 | t | 上月\n```\n## 代码块里的不算标题\n```\n\n' "$PM"
  printf '## 认不出日期但在新条目之后\nx\n'
  printf '## [%s-01] 决定 | t | 当月\n末尾\n' "$CM"; } > "$JR/journal.md"
git -C "$JR" add -A >/dev/null; git -C "$JR" -c user.name=t -c user.email=t@t commit -qm big
JPY="$(dirname "$PT")/journal.py"
stat(){ python3 -c "
import sys; sys.path.insert(0, '$(dirname "$PT")'); import journal, glob
ents = []
for p in sys.argv[1:]:
    ents += journal.split(journal.read_raw(p))[1]
print(len(ents), sum(len(e.encode()) for e in ents))" "$@"; }
s0=$(stat "$JR/journal.md")
echo "未提交的进展" >> "$JR/state.md"
out=$(bash "$PT" journal-archive eng); rc=$?
s1=$(stat "$JR/journal.md" "$JR"/archive/journal-*.md)
check "journal-archive 条数与总字节数守恒" '[ $rc -eq 0 ] && [ "$s0" = "$s1" ] && [ "$(cut -d" " -f1 <<<"$s0")" = 64 ]'
check "按月分文件，认不出日期的旧条目进 early" '[ "$(grep -c "^## " "$JR/archive/journal-2025-09.md")" = 30 ] && [ "$(grep -c "^## " "$JR/archive/journal-2025-10.md")" = 30 ] && grep -q "^## 无日期的老条目" "$JR/archive/journal-early.md"'
check "当月、上月与其后的无日期条目留下，代码块不拆" 'grep -q "^## \[$PM-02\]" "$JR/journal.md" && grep -q "^## \[$CM-01\]" "$JR/journal.md" && grep -q "^## 认不出日期但在新条目之后" "$JR/journal.md" && grep -q "^## 代码块里的不算标题" "$JR/journal.md"'
check "顶部留一行说明并提交（只提交 journal 与归档）" 'sed -n 2p "$JR/journal.md" | grep -q "^> 归档：" && [ "$(git -C "$JR" status --porcelain)" = " M state.md" ] && git -C "$JR" log -1 --format=%s | grep -q "^journal-archive @host-me"'
check "搬走的条目一字不改、journal 只多了说明行" 'python3 - "$JR" <<PY
import subprocess, sys; d = sys.argv[1]
old = subprocess.run(["git", "-C", d, "show", "HEAD~1:journal.md"], capture_output=True, text=True).stdout
arc = "".join(open(f"{d}/archive/journal-{m}.md", encoding="utf-8").read() for m in ("early", "2025-09", "2025-10"))
new = open(f"{d}/journal.md", encoding="utf-8").read().split("\n", 2)
sys.exit(0 if old == new[0] + "\n\n" + arc + new[2][1:] else 1)   # 原文 = 标题 + 归档（原顺序）+ 留下的
PY'
out=$(bash "$PT" journal-archive eng)
check "不到 100 KB 不搬"                  'grep -q "不用搬" <<<"$out" && [ "$(git -C "$JR" log -1 --format=%s | cut -c1-15)" = "journal-archive" ]'
export PROJECT_TRACKER_ROOT="$T/root"

echo; echo "passed=$pass failed=$fail"; [ $fail -eq 0 ]
