#!/usr/bin/env bash
# unit.sh — 不调用模型，直接测 pt.sh 的本地子命令与隔离逻辑。几秒跑完。多机部分见 fleet.sh。
set -u
S=$(cd "$(dirname "$0")" && pwd)
PT="$S/../plugins/project-tracker/skills/project-tracker/scripts/pt.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export PROJECT_TRACKER_ROOT="$T/root" PT_HOSTNAME=host-me
mkdir -p "$T/repoA/sub" "$T/repoB" "$T/other"
unset CLAUDE_PROJECT_DIR
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
