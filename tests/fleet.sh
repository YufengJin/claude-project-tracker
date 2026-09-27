#!/usr/bin/env bash
# fleet.sh — 多机测试，不调模型。fakessh 把别名映射到本地假 HOME（hosts/<别名>），
# fakeclaude 代替被派出去的 agent。中心机 = hub（有 FLEET）。
set -u
S=$(cd "$(dirname "$0")" && pwd)
PT="$S/../plugins/project-tracker/skills/project-tracker/scripts/pt.sh"
T=$(mktemp -d)
export FAKE_HOSTS="$T/hosts" PT_SCRIPT="$PT"
export PROJECT_TRACKER_ROOT="$T/hub/.claude/project" PT_HOSTNAME=host-hub
export PT_SSH="$S/fakessh" PT_GIT_SSH="$S/fakessh" PT_CLAUDE="$S/fakeclaude"
export PT_QUIET=0 PT_IDLE=100000 PT_WAIT_INTERVAL=1
export PT_TMUX="tmux -L pttest$$-\$PT_HOSTNAME"
cleanup() { for h in a b c; do tmux -L "pttest$$-host-$h" kill-server 2>/dev/null; done; rm -rf "$T"; }
trap cleanup EXIT
unset CLAUDE_PROJECT_DIR
mkdir -p "$T/hosts/a/work" "$T/hosts/b/work" "$T/hosts/c" "$PROJECT_TRACKER_ROOT" "$T/hub/work"
printf 'a   # 服务器\nb\nc   # 常离线\n' > "$PROJECT_TRACKER_ROOT/FLEET"
touch "$T/hosts/c/.offline"

pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; [ -n "${out:-}" ] && sed 's/^/       | /' <<<"$out" | head -n 15; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
# 在节点上跑 pt（模拟那台机器上的本地会话）
npt() { local a=$1; shift; ( export HOME="$T/hosts/$a" PT_HOSTNAME="host-$a"; unset PROJECT_TRACKER_ROOT; cd "$HOME/work" 2>/dev/null || cd "$HOME"; bash "$PT" "$@" ); }
hpt() { ( cd "$T/hub/work" && bash "$PT" "$@" ); }
H="$PROJECT_TRACKER_ROOT"
NA="$T/hosts/a/.claude/project"; NB="$T/hosts/b/.claude/project"
first() { awk '/^## 一句话概括/{f=1;next} f&&NF{print;exit}' "$1"; }
head_of() { git -C "$1" rev-parse HEAD; }

echo "# 导入：节点立项，中心看得到"
npt a new pa "A 上的项目" >/dev/null
out=$(hpt sync)
check "中心导入 pa"                     '[ -f "$H/pa/charter.md" ] && grep -q "pa: ↓ 新导入" <<<"$out"'
check "学到别名 → hostname"             '[ "$(cat "$H/.fleet/hosts/a/hostname")" = host-a ]'
check "中心副本 Host=host-a，与节点同一提交" 'grep -q "^Host: host-a$" "$H/pa/charter.md" && [ "$(head_of "$H/pa")" = "$(head_of "$NA/pa")" ]'
check "离线节点报告不可达"               'grep -q "^c: 不可达" <<<"$out"'
out=$(hpt list --no-sync)
check "list 显示别名"                   'grep -q "^| pa | A 上的项目 | 进行中 | a |" <<<"$out" && grep -q "pa .*@a " <<<"$out"'

echo "# 节点 checkpoint → 中心快进"
npt a index pa "节点进展1" >/dev/null
out=$(hpt sync -q)
check "快进"                            'grep -q "pa: ↓ 快进" <<<"$out" && [ "$(first "$H/pa/state.md")" = 节点进展1 ]'
check "-q 不打印在线行"                  '! grep -q ": 在线（" <<<"$out"'

echo "# 中心接管：中心 checkpoint → 推回节点"
printf '\n## x · session 2 · @host-hub\nDid: 中心干活\n' >> "$H/pa/journal.md"
hpt index pa "中心进展2" >/dev/null
out=$(hpt sync -q)
check "推送到节点"                       'grep -q "pa: ↑ 推送到 a" <<<"$out"'
check "节点工作树已更新且干净"            '[ "$(first "$NA/pa/state.md")" = 中心进展2 ] && grep -q "中心干活" "$NA/pa/journal.md" && [ -z "$(git -C "$NA/pa" status --porcelain)" ] && [ "$(head_of "$NA/pa")" = "$(head_of "$H/pa")" ]'

echo "# 节点刚改过 → 等它安静再推"
hpt index pa "中心进展3" >/dev/null
out=$(PT_QUIET=100000 hpt sync -q)
check "推迟"                            'grep -q "pa: a 上 .* 分钟前刚改过，下轮再推" <<<"$out" && [ "$(first "$NA/pa/state.md")" = 中心进展2 ]'
out=$(hpt sync -q)
check "安静后推送"                       'grep -q "pa: ↑ 推送到 a" <<<"$out" && [ "$(first "$NA/pa/state.md")" = 中心进展3 ]'

echo "# 节点正在写（未提交）→ 不推、不搬半截"
hpt index pa "中心进展4" >/dev/null
echo "节点写到一半" >> "$NA/pa/state.md"
out=$(hpt sync -q)
check "不推，节点内容原样"               'grep -q "pa: a 上有未提交改动，下轮再推" <<<"$out" && grep -q "节点写到一半" "$NA/pa/state.md"'
check "中心没拿到半截"                   '! grep -q "节点写到一半" "$H/pa/state.md"'

echo "# 两边都写 → 分叉，只报告不合并"
npt a index pa "节点进展5" >/dev/null
pre_hub=$(head_of "$H/pa"); pre_node=$(head_of "$NA/pa")
out=$(hpt sync -q)
check "标分叉"                          'grep -q "pa: ⚠ 与 a 分叉" <<<"$out" && [ "$(cat "$H/.fleet/forked/pa")" = a ]'
check "两边都没被动"                     '[ "$(head_of "$H/pa")" = "$pre_hub" ] && [ "$(head_of "$NA/pa")" = "$pre_node" ]'
check "INDEX 标红"                      'grep -q "^| pa |.*⚠分叉 " "$H/INDEX.md"'
out=$(hpt brief pa)
check "brief 给合并步骤"                 'grep -q "⚠ 与 a 分叉" <<<"$out" && grep -q "merge a/main" <<<"$out"'
out=$(hpt dispatch pa "随便" 2>&1)
check "分叉时拒绝派活"                   'grep -q "分叉，先合并" <<<"$out"'
# agent 按语义合并：state 取合并后的现状，journal 两边都留
git -C "$H/pa" merge -q a/main >/dev/null 2>&1
git -C "$H/pa" checkout -q --theirs state.md 2>/dev/null
hpt index pa "合并完成" >/dev/null
out=$(hpt sync -q)
check "合并后推回、分叉解除"             'grep -q "pa: ↑ 推送到 a" <<<"$out" && [ ! -f "$H/.fleet/forked/pa" ] && [ "$(head_of "$NA/pa")" = "$(head_of "$H/pa")" ]'
check "合并提交含两边"                   'git -C "$H/pa" merge-base --is-ancestor "$pre_hub" HEAD && git -C "$H/pa" merge-base --is-ancestor "$pre_node" HEAD'

echo "# 中心自己有未提交改动 → 不快进"
npt a index pa "节点进展6" >/dev/null
echo "中心写到一半" >> "$H/pa/plan.md"
out=$(hpt sync -q)
check "中心脏时跳过快进，改动保留"        'grep -q "pa: 中心有未提交改动，本轮不快进" <<<"$out" && grep -q "中心写到一半" "$H/pa/plan.md"'
git -C "$H/pa" checkout -q plan.md
out=$(hpt sync -q)
check "干净后快进"                       'grep -q "pa: ↓ 快进" <<<"$out" && [ "$(first "$H/pa/state.md")" = 节点进展6 ]'

echo "# 旧版插件的档案（非 git、无 Host）"
mkdir -p "$NB/old-b"
for f in charter plan state journal decisions; do
  sed -e "s|{{SLUG}}|old-b|g; s|{{NAME}}|B 上的旧项目|g; s|{{DATE}}|2026-01-01|g; s|{{WORKDIR}}|$T/hosts/b/work|g; /^Host:/d; s| · @{{THIS_HOST}}||" \
    "$S/../plugins/project-tracker/skills/project-tracker/reference/templates/$f.md" > "$NB/old-b/$f.md"
done
out=$(hpt sync -q b)
check "正在写（不空闲）→ 不碰"           'grep -q "old-b: b 上还没有提交" <<<"$out" && [ ! -d "$NB/old-b/.git" ] && [ ! -d "$H/old-b" ]'
touch -d "2 hours ago" "$NB/old-b"/*.md
out=$(PT_IDLE=3600 hpt sync -q b)
check "空闲 → 代为提交并导入"            'grep -q "old-b: ↓ 新导入" <<<"$out" && [ -z "$(git -C "$NB/old-b" status --porcelain)" ]'
check "代为补 Host"                      'grep -q "^Host: host-b$" "$NB/old-b/charter.md" && grep -q "^Host: host-b$" "$H/old-b/charter.md"'

echo "# 中心立项给节点 → 首次下发；隐私"
hpt new hubmade "中心立给 a 的项目" --host a /srv/x >/dev/null
hpt new hubonly "中心自己的项目" >/dev/null
out=$(hpt sync -q)
check "--host 别名换成 hostname"         'grep -q "^Host: host-a$" "$H/hubmade/charter.md"'
check "首次下发到 a"                     'grep -q "hubmade: ↑ 首次下发到 a" <<<"$out" && [ "$(head_of "$NA/hubmade")" = "$(head_of "$H/hubmade")" ] && [ -f "$NA/hubmade/state.md" ]'
check "a 只有自己的项目"                 '[ "$(ls "$NA" | grep -v -e INDEX.md -e ACTIVE | sort | tr "\n" " ")" = "hubmade pa " ]'
check "b 只有自己的项目"                 '[ "$(ls "$NB" | grep -v -e INDEX.md -e ACTIVE | sort | tr "\n" " ")" = "old-b " ]'
rm -rf "$NA/hubmade"
out=$(hpt sync -q a)
check "节点上删了 → 报告、不重建"        'grep -q "hubmade: a 上已经没有这个项目" <<<"$out" && [ ! -d "$NA/hubmade" ]'

echo "# slug 冲突"
npt b new pa "B 上同名的项目" >/dev/null
out=$(hpt sync -q b)
check "报告冲突、不动中心副本"            'grep -q "pa: ⚠ slug 冲突" <<<"$out" && grep -q "^Host: host-a$" "$H/pa/charter.md"'
rm -rf "$NB/pa"; git -C "$H/pa" remote remove b

echo "# 中心 brief / list 会先同步"
npt a index pa "brief 前节点的新进展" >/dev/null
out=$(hpt brief pa)
check "brief 拿到最新"                   'grep -q "brief 前节点的新进展" <<<"$out"'
check "brief 提示 Host 与两种干法"       'grep -q "^Host: a (host-a)" <<<"$out" && grep -q "ssh a" <<<"$out" && grep -q "pt.sh dispatch pa" <<<"$out"'
npt a index pa "list 前节点的新进展" >/dev/null
out=$(hpt list)
check "list 拿到最新 + 在线统计"         'grep -q "^| pa |.*list 前节点的新进展 |$" <<<"$out" && grep -q "已同步：2/3 台节点在线" <<<"$out"'

echo "# 中心自己的空闲未提交改动（旧版会话写的）"
echo "旧版会话写的" >> "$H/hubonly/state.md"
touch -d "2 hours ago" "$H/hubonly"/*.md "$H/hubonly/archive/.keep"
PT_IDLE=3600 hpt sync -q >/dev/null
check "同步时代为提交"                   '[ -z "$(git -C "$H/hubonly" status --porcelain)" ] && git -C "$H/hubonly" log -1 --format=%s | grep -q "^autosync @host-hub (idle)"'
echo "合并到一半" >> "$H/hubonly/plan.md"; git -C "$H/hubonly" rev-parse HEAD > "$H/hubonly/.git/MERGE_HEAD"
touch -d "2 hours ago" "$H/hubonly"/*.md
PT_IDLE=3600 hpt sync -q >/dev/null
check "合并进行中不代为提交"             '[ -n "$(git -C "$H/hubonly" status --porcelain)" ]'
rm -f "$H/hubonly/.git/MERGE_HEAD"; git -C "$H/hubonly" checkout -q plan.md

echo "# 派活"
out=$(hpt dispatch hubonly "x" 2>&1)
check "本机项目不派"                     'grep -q "Host 就是本机" <<<"$out"'
out=$(hpt dispatch pa "跑一下测试并记录" --wait 2>&1); rc=$?
check "--wait 成功返回 0"                '[ $rc -eq 0 ] && grep -q "===== 派活 pa-.*：done 0 =====" <<<"$out"'
check "结果同步回中心 journal"           'grep -q "^Did:      dispatched pa-" "$H/pa/journal.md" && [ "$(head_of "$H/pa")" = "$(head_of "$NA/pa")" ]'
check "打印新 journal 与输出尾"          'grep -q "dispatched pa-" <<<"$out" && grep -q "摘要：完成" <<<"$out"'
check "agent 在 Workdir 里跑"            'grep -q "cwd=$T/hosts/a/work" "$H/pa/journal.md"'
check "占用标记已清"                     '[ ! -f "$H/.fleet/active/pa" ]'
run1=$(ls "$H/.fleet/runs" | head -n1)
check "runs 显示 done 0"                 'hpt runs pa | grep -q "$run1 .*done 0"'

echo "sleep 4" > "$T/hosts/a/.fake_claude"
out=$(hpt dispatch pa "慢任务" 2>&1)
run2=$(sed -n 's/.*已派出 \([a-z0-9-]*\) .*/\1/p' <<<"$out")
check "不带 --wait 立即返回"             '[ -n "$run2" ] && [ -f "$H/.fleet/active/pa" ]'
sleep 1
out=$(hpt dispatch pa "再来一个" 2>&1)
check "同一项目不重复派"                 'grep -q "已有派活 $run2" <<<"$out"'
out=$(hpt index pa "中心想插一脚" 2>&1)
check "派活期间中心不许 checkpoint"      'grep -q "正在改 pa" <<<"$out"'
check "runs 显示 running"                'hpt runs pa | grep -q "$run2 .*running"'
out=$(hpt runs --wait "$run2" 2>&1); rc=$?
check "runs --wait 等到结束"             '[ $rc -eq 0 ] && grep -q "done 0" <<<"$out" && grep -q "dispatched $run2" "$H/pa/journal.md"'

echo "fail" > "$T/hosts/a/.fake_claude"
out=$(hpt dispatch pa "会失败" --wait 2>&1); rc=$?
check "agent 失败 → 非零、报 rc"         '[ $rc -ne 0 ] && grep -q "done 3" <<<"$out" && grep -q boom <<<"$out"'

echo "nocommit" > "$T/hosts/a/.fake_claude"
out=$(hpt dispatch pa "忘了提交" --wait 2>&1); rc=$?
check "agent 忘了提交 → runner 补提交并同步回来" '[ $rc -eq 0 ] && grep -q "agent 未提交的改动" <<<"$(git -C "$H/pa" log -1 --format=%s)" && [ -z "$(git -C "$NA/pa" status --porcelain)" ] && [ "$(grep -c "^Did:      dispatched" "$H/pa/journal.md")" = 3 ]'

echo "sleep 60" > "$T/hosts/a/.fake_claude"
out=$(hpt dispatch pa "会被打断" 2>&1)
run4=$(sed -n 's/.*已派出 \([a-z0-9-]*\) .*/\1/p' <<<"$out")
sleep 1
tmux -L "pttest$$-host-a" kill-session -t "pt-$run4" 2>/dev/null
sleep 1
check "进程没了又没写结束 → unknown"     'hpt runs pa | grep -q "$run4 .*unknown"'
out=$(hpt index pa "打断后中心接着干" 2>&1)
check "unknown 后标记清掉、可以 checkpoint" 'grep -q "已提交" <<<"$out" && [ ! -f "$H/.fleet/active/pa" ]'
rm -f "$T/hosts/a/.fake_claude"

touch "$T/hosts/a/.offline"
out=$(hpt dispatch pa "离线" 2>&1)
check "节点离线不派"                     'grep -q "同步 a 失败" <<<"$out"'
out=$(hpt brief pa 2>&1)
check "节点离线仍可 brief（用缓存）"     'grep -q "项目简报: pa" <<<"$out" && grep -q "a 上次不可达" <<<"$out"'
rm -f "$T/hosts/a/.offline"

echo; echo "passed=$pass failed=$fail"; [ $fail -eq 0 ]
