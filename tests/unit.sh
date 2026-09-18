#!/usr/bin/env bash
# unit.sh — 不调用模型，直接测 pt.sh 的每个子命令与隔离逻辑。几秒跑完。
set -u
S=$(cd "$(dirname "$0")" && pwd)
PT="$S/../plugins/project-tracker/skills/project-tracker/scripts/pt.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export PROJECT_TRACKER_ROOT="$T/root"
mkdir -p "$T/repoA/sub" "$T/repoB" "$T/other"
unset CLAUDE_PROJECT_DIR
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

echo "# new"
out=$(cd "$T/repoA" && bash "$PT" new alpha "项目 A") ; rc=$?
check "new 退出 0"                     '[ $rc -eq 0 ]'
check "五个文件 + archive"             '[ -f "$T/root/alpha/charter.md" ] && [ -f "$T/root/alpha/plan.md" ] && [ -f "$T/root/alpha/state.md" ] && [ -f "$T/root/alpha/journal.md" ] && [ -f "$T/root/alpha/decisions.md" ] && [ -d "$T/root/alpha/archive" ]'
check "charter Workdir = 当前目录"      'grep -q "^Workdir: $T/repoA$" "$T/root/alpha/charter.md"'
check "无 {{ 残留"                     '! grep -rq "{{" "$T/root/alpha"'
check "INDEX 有行"                     'grep -q "^| alpha | 项目 A | 进行中 | $(date +%F) |" "$T/root/INDEX.md"'
check "ACTIVE = alpha"                 '[ "$(cat "$T/root/ACTIVE")" = alpha ]'
check "journal 首条 session 1"         'grep -q "session 1" "$T/root/alpha/journal.md" && grep -q "^Did: *建立项目档案" "$T/root/alpha/journal.md"'
check "重复 slug 拒绝"                 '! bash "$PT" new alpha "x" 2>/dev/null'
check "非法 slug 拒绝"                 '! bash "$PT" new Bad_Slug "x" 2>/dev/null'
(cd "$T/repoB" && bash "$PT" new beta "项目 B" "$T/repoB" "$T/repoA/sub" >/dev/null)
check "多 workdir 写入"                'grep -q "^Workdir: $T/repoB $T/repoA/sub$" "$T/root/beta/charter.md"'

echo "# where / auto 隔离"
check "repoA 根只命中 alpha"           '[ "$(cd "$T/repoA" && bash "$PT" where)" = alpha ]'
check "repoA/sub 命中 alpha+beta"      '[ "$(cd "$T/repoA/sub" && bash "$PT" where | sort | tr "\n" " ")" = "alpha beta " ]'
check "repoB 只命中 beta"              '[ "$(cd "$T/repoB" && bash "$PT" where)" = beta ]'
check "无关目录命中 0"                 '[ -z "$(cd "$T/other" && bash "$PT" where)" ]'
check "auto 无关目录静默"              '[ -z "$(cd "$T/other" && bash "$PT" auto)" ]'
out=$(cd "$T/repoB" && bash "$PT" auto)
check "auto 单命中 → brief beta"       'grep -q "项目简报: beta" <<<"$out" && ! grep -q "alpha" <<<"$out"'
echo alpha > "$T/root/ACTIVE"
out=$(cd "$T/repoA/sub" && bash "$PT" auto)
check "auto 多命中 + ACTIVE 在内 → brief alpha" 'grep -q "项目简报: alpha" <<<"$out" && ! grep -q "项目 B" <<<"$out"'
echo nothing > "$T/root/ACTIVE"
out=$(cd "$T/repoA/sub" && bash "$PT" auto)
check "auto 多命中 无 ACTIVE → 只列 slug" 'grep -q "多个进行中项目" <<<"$out" && ! grep -q "charter" <<<"$out"'
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
check "brief 不存在的 slug 报错"       '! bash "$PT" brief nope 2>/dev/null'
seq 1 120 | sed "s/^/- line /" >> "$T/root/alpha/state.md"
check "state >100 行告警"              'bash "$PT" brief alpha | grep -q "超过 100 行"'

echo "# index"
bash "$PT" index alpha "做到一半 | 有竖线" >/dev/null
check "index 改日期与一句话，转义竖线"  'grep -q "^| alpha | 项目 A | 进行中 | $(date +%F) | 做到一半 ／ 有竖线 |$" "$T/root/INDEX.md"'
check "index 不动其他行"               'grep -q "^| beta | 项目 B | 进行中 |" "$T/root/INDEX.md"'
bash "$PT" index beta "全部通过" 已完成 >/dev/null
check "index 状态同步 charter"         'grep -q "^| beta | 项目 B | 已完成 |" "$T/root/INDEX.md" && grep -q "^Status: 已完成$" "$T/root/beta/charter.md"'
check "已完成项目不再命中 where"       '[ -z "$(cd "$T/repoB" && bash "$PT" where)" ]'
check "index 未知 slug 报错"           '! bash "$PT" index nope x 2>/dev/null'

echo "# list"
out=$(bash "$PT" list)
check "list 含 INDEX 与 Workdir"       'grep -q "^| alpha |" <<<"$out" && grep -q "alpha.*Workdir: $T/repoA" <<<"$out"'
check "list 不含项目正文"              '! grep -q "完成标准\|Goal:" <<<"$out"'

echo; echo "passed=$pass failed=$fail"; [ $fail -eq 0 ]
