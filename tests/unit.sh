#!/usr/bin/env bash
# unit.sh — 不调用模型，直接测 pt.sh 的本地子命令与隔离逻辑。几秒跑完。多机部分见 fleet.sh。
set -u
S=$(cd "$(dirname "$0")" && pwd)
PT="$S/../plugins/project-tracker/skills/project-tracker/scripts/pt.sh"
T=${KEEP_T:-$(mktemp -d)}; [ -n "${KEEP_T:-}" ] || trap 'rm -rf "$T"' EXIT
export PROJECT_TRACKER_ROOT="$T/root" PT_HOSTNAME=host-me
mkdir -p "$T/repoA/sub" "$T/repoB" "$T/other"
unset CLAUDE_PROJECT_DIR CLAUDE_CODE_SESSION_ID
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
D=$(date +%F)

echo "# new"
out=$(cd "$T/repoA" && bash "$PT" new alpha "项目 A") ; rc=$?
check "new 退出 0"                     '[ $rc -eq 0 ]'
check "五个文件 + archive"             '[ -f "$T/root/alpha/charter.md" ] && [ -f "$T/root/alpha/plan.md" ] && [ -f "$T/root/alpha/state.md" ] && [ -f "$T/root/alpha/journal.md" ] && [ -f "$T/root/alpha/decisions.md" ] && [ -d "$T/root/alpha/archive" ]'
check "charter Workdir = 当前目录"      'grep -q "^Workdir: $T/repoA$" "$T/root/alpha/charter.md"'
check "charter Host = 本机"            'grep -q "^Host: host-me$" "$T/root/alpha/charter.md"'
check "无 {{ 残留"                     '! grep -rq --exclude-dir=.git "{{" "$T/root/alpha"'
check "INDEX 生成行（含主机、state 一句话）" 'grep -q "^| alpha | 项目 A | 进行中 | 本机 | $D | 刚立项，尚未动手。 |$" "$T/root/INDEX.md"'
check "ACTIVE = alpha"                 '[ "$(cat "$T/root/ACTIVE")" = alpha ]'
check "journal 首条 session 1 @host"   'grep -q "^## $D · session 1 · @host-me$" "$T/root/alpha/journal.md" && grep -q "^Did: *建立项目档案" "$T/root/alpha/journal.md"'
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

echo "# brief"
printf '\n## 2026-01-02 · session 2\nGoal: x\n\n## 2026-01-03 · session 3\nGoal: y\n\n## 2026-01-04 · session 4\nGoal: z\n' >> "$T/root/alpha/journal.md"
printf '## ADR-0001: 用 X\nDate: 2026-01-02\nStatus: 采纳\n\n**背景**：secret-body\n' >> "$T/root/alpha/decisions.md"
out=$(bash "$PT" brief alpha)
check "brief 设 ACTIVE"                '[ "$(cat "$T/root/ACTIVE")" = alpha ]'
check "brief 顺序 charter→state→journal→ADR→plan" 'python3 - "$out" <<PY
import sys; s=sys.argv[1]; ks=["INDEX 行","charter.md","state.md","journal.md 最后 3 条","decisions.md 标题","= plan.md"]
idx=[s.find(k) for k in ks]; sys.exit(0 if all(i>=0 for i in idx) and idx==sorted(idx) else 1)
PY'
check "journal 只给最后 3 条"          'grep -q "^## .*session 2" <<<"$out" && ! grep -q "^## .*session 1" <<<"$out" && grep -q "本会话 session 号 = 5" <<<"$out"'
check "ADR 只给标题"                   'grep -q "ADR-0001" <<<"$out" && ! grep -q "secret-body" <<<"$out"'
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
bash "$PT" new big "大 journal" "$T/other/big" >/dev/null
{ printf '\n## 2026-02-01 · session 2\nGoal: 早先的目标\n'
  python3 -c "
for i in range(400): print('续 %d：' % i + '证据' * 60)"
  printf 'Next: 倒数第二条的下一步\n\n## 2026-02-02 · session 3\nGoal: 最新的目标\nNext: 最新的下一步\n'; } >> "$T/root/big/journal.md"
out=$(bash "$PT" brief big)
check "超预算时简报仍然很小"            '[ "$(printf %s "$out" | wc -c)" -lt 30000 ]'
check "三条的标题都在"                 'grep -q "^## .*session 1" <<<"$out" && grep -q "^## .*session 2" <<<"$out" && grep -q "^## .*session 3" <<<"$out"'
check "最新一条完整、上一条留结尾"      'grep -q "^Goal: 最新的目标" <<<"$out" && grep -q "^Next: 最新的下一步" <<<"$out" && grep -q "^Next: 倒数第二条的下一步" <<<"$out" && grep -q "^续 399：" <<<"$out"'
check "省掉的开头给出行号"             'grep -q "省略 journal.md 第 [0-9]*–[0-9]* 行" <<<"$out" && ! grep -q "^续 0：" <<<"$out" && ! grep -q "早先的目标" <<<"$out"'
check "journal 原文没被动"             '[ "$(grep -c "^续 " "$T/root/big/journal.md")" = 400 ]'
check "预算可调"                       '[ "$(PT_BRIEF_JOURNAL_BYTES=900000 bash "$PT" brief big | grep -c "^续 ")" = 400 ]'
out=$(bash "$PT" brief alpha)
check "没超预算的 journal 原样打印"     '! grep -q "省略 journal.md" <<<"$out" && grep -q "^Goal: x" <<<"$out"'

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
check "INDEX 行更新并转义竖线"          'grep -q "^| alpha | 项目 A | 进行中 | 本机 | $D | 做到一半 ／ 有竖线 |$" "$T/root/INDEX.md"'
check "index 提交了一次 checkpoint"     '[ "$(git -C "$T/root/alpha" rev-list --count HEAD)" = $((n0+1)) ] && [ -z "$(git -C "$T/root/alpha" status --porcelain)" ] && git -C "$T/root/alpha" log -1 --format=%s | grep -q "^checkpoint @host-me: 做到一半"'
check "index 不动其他行"               'grep -q "^| beta | 项目 B | 进行中 |" "$T/root/INDEX.md"'
bash "$PT" index beta "全部通过" 已完成 >/dev/null
check "index 状态同步 charter"         'grep -q "^| beta | 项目 B | 已完成 |" "$T/root/INDEX.md" && grep -q "^Status: 已完成$" "$T/root/beta/charter.md"'
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
bash "$PT" new rs "研究 R" "$T/other/rs" >/dev/null
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
ok=d["slug"]=="rs" and len(N)==s.count("<article id=\"n-")-("n-__ledger" in s) and N[ix["H2"]]["p"]==ix["Q1"] and N[ix["H2"]]["n"]>=1
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
check "brief 用研究树替代台账末行"       'grep -q "===== 研究树" <<<"$out" && grep -q "^- H2 假设二 在做" <<<"$out" && ! grep -q "experiments.md 末 15 行" <<<"$out"'
check "未冻结的考官卡全文打印"           'grep -q "^## 数据与暴露史" <<<"$out"'
sed -i "s/^Updated: .*/Updated: $D   Status: 已冻结（用户确认；改考官走 ADR）/" "$R/verifier.md"
out=$(bash "$PT" brief rs)
check "冻结考官只打印状态行 + 两节"      'grep -q "Status: 已冻结" <<<"$out" && grep -q "^## 指标与聚合定义" <<<"$out" && grep -q "^## 判定依据" <<<"$out" && ! grep -q "^## 数据与暴露史" <<<"$out" && grep -q "其余节读原文" <<<"$out"'
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
check "没有研究树的项目 tree 报错、brief 照旧" '! bash "$PT" tree alpha 2>/dev/null && ! bash "$PT" brief alpha | grep -q "===== 研究树"'

echo "# 研究树回归（坏输入、注入、冲突）"
TP="$(dirname "$PT")/tree.py"
mkdir -p "$T/rbw"
bash "$PT" new rb "回归 B" "$T/rbw" >/dev/null; bash "$PT" research rb >/dev/null
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
gq checkout -qb side2; echo "分支加的一行" >> "$B/plan.md"; gq commit -qam s2
gq checkout -q main; echo "主线加的一行" >> "$B/plan.md"; gq commit -qam m3
gq merge -q side2 >/dev/null 2>&1
n0=$(git -C "$B" rev-list --count HEAD)
out=$(bash "$PT" index rb "不该提交" 2>&1); rc=$?
check "S5 有没合完的冲突：index 拒绝并列出文件" '[ $rc -ne 0 ] && grep -q "没合完的冲突.*plan.md" <<<"$out" && [ -z "$(git -C "$B" status --porcelain state.md)" ] && [ "$(git -C "$B" rev-list --count HEAD)" = "$n0" ]'
gq add plan.md
out=$(bash "$PT" index rb "标记还在" 2>&1); rc=$?
check "S5 冲突标记被 add 进去了也拒绝"    '[ $rc -ne 0 ] && grep -q "冲突.*plan.md" <<<"$out" && [ "$(git -C "$B" rev-list --count HEAD)" = "$n0" ]'
gq reset -q; git -C "$B" show HEAD:plan.md > "$B/plan.md"; gq checkout -qb side3; echo "分支三" >> "$B/plan.md"; gq commit -qam s3
gq checkout -q main; echo "主线三" >> "$B/plan.md"; gq commit -qam m4; gq merge -q side3 >/dev/null 2>&1
git -C "$B" show HEAD:plan.md > "$B/plan.md"   # 在工作区里改好（不 git add）
out=$(bash "$PT" index rb "工作区里合好了" 2>&1); rc=$?
check "S5 工作区里已改好的冲突（无标记）照常提交" '[ $rc -eq 0 ] && [ -z "$(git -C "$B" ls-files -u)" ] && [ "$(git -C "$B" rev-list --parents -1 HEAD | wc -w)" = 3 ]'
check "S5 tree.py 对含冲突标记的节点告警" 'printf -- "---\ntitle: t\nparent: Q1\nstatus: open\n---\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> side\n" > "$B/tree/H6.md"; tw | grep -q "H6: 含合并冲突标记"'
rm -f "$B/tree/H6.md"; git -C "$B" show HEAD:plan.md > "$B/plan.md"; echo "合好的一行" >> "$B/plan.md"; gq add -A; gq commit -qm resolved
check "S5 brief 分叉提示写 tree.html 不用手合" 'grep -q "tree.html 不用手合，pt index 会重新生成" "$(dirname "$PT")/pt.sh"'
# S6 pt new 名称含 sed 特殊字符
out=$(bash "$PT" new sedname 'A|B & \1 C/D' "$T/other/x" 2>&1); rc=$?
check "S6 名称含 | & \\1 照原样写进 charter" '[ $rc -eq 0 ] && [ "$(head -n1 "$T/root/sedname/charter.md")" = "# A|B & \1 C/D" ] && grep -qF "| sedname | A／B & \1 C/D |" "$T/root/INDEX.md"'
out=$(bash "$PT" new sedbad "$(printf 'a\nb')" "$T/other/x" 2>&1); rc=$?
check "S6 sed 处理不了的名称：报错且不留空档案" '[ $rc -ne 0 ] && [ ! -e "$T/root/sedbad" ]'
# M1 Status 带括号注
sed -i "s/^Status:.*/Status: 进行中 (探索期)/" "$B/charter.md"
check "M1 Status「进行中 (探索期)」where 照样命中" '(cd "$T/rbw" && bash "$PT" where) | grep -qx rb'
check "M1 INDEX 按进行中排序（排在已放弃前）" 'bash "$PT" list --no-sync >/dev/null; [ "$(grep -n "^| rb |" "$T/root/INDEX.md" | cut -d: -f1)" -lt "$(grep -n "^| annot |" "$T/root/INDEX.md" | cut -d: -f1)" ]'
check "M1 precompact 命中带注的进行中项目" '(cd "$T/rbw" && bash "$PT" precompact </dev/null) | grep -q "项目 rb"'
# M2 考官卡「未冻结」不算冻结
sed -i "s/^Updated: .*/Updated: $D   Status: 未冻结（等用户）/" "$B/verifier.md"
check "M2 未冻结的考官卡全文打印"        'bash "$PT" brief rb | grep -q "^## 数据与暴露史"'
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
check "非研究项目不进页面"               '! grep -q "plain" "$HT" && grep -q "href=\"ra/tree.html\"" "$HT" && grep -q "href=\"rb/tree.html\"" "$HT"'
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
check "INDEX 重建为新格式"             'grep -q "| 主机 |" "$T/old/INDEX.md" && grep -q "^| legacy | 旧项目 | 进行中 | 本机 | 2026-01-01 | 旧的一句话 |$" "$T/old/INDEX.md"'
check "迁移提交不算最后更新（取 journal 日期）" 'grep -q "^| elsewhere | 别处项目 | 暂停 | 待定位 | 2026-01-01 |" "$T/old/INDEX.md"'
n1=$(git -C "$T/old/legacy" rev-list --count HEAD)
bash "$PT" migrate >/dev/null
check "migrate 幂等"                   '[ "$(git -C "$T/old/legacy" rev-list --count HEAD)" = "$n1" ] && [ "$(grep -c "旧的一句话" "$T/old/legacy/state.md")" = 1 ] && [ "$(grep -c "^Host:" "$T/old/legacy/charter.md")" = 1 ]'

echo; echo "passed=$pass failed=$fail"; [ $fail -eq 0 ]
