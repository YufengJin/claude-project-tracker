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
check "tree 默认：根的认识/约束/教训"   'grep -q "认识甲" <<<"$out" && grep -q "禁读锁箱切分" <<<"$out" && grep -q "旧根教训丙" <<<"$out"'
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
rm -f "$H"
out=$(bash "$PT" index rs "研究树就位")
check "index 渲染 tree.html 并一起提交"  '[ -f "$H" ] && [ -z "$(git -C "$R" status --porcelain)" ] && git -C "$R" ls-files | grep -qx tree.html && grep -q "告警 [0-9]* 条" <<<"$out"'
mkdir "$R/tree/H9.md"
out=$(bash "$PT" index rs "渲染坏了" 2>&1); rc=$?
check "渲染失败只告警，照常提交"         '[ $rc -eq 0 ] && grep -q "tree.html 没渲染成" <<<"$out" && git -C "$R" log -1 --format=%s | grep -q "渲染坏了"'
rmdir "$R/tree/H9.md"
check "没有研究树的项目 tree 报错、brief 照旧" '! bash "$PT" tree alpha 2>/dev/null && ! bash "$PT" brief alpha | grep -q "===== 研究树"'

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
