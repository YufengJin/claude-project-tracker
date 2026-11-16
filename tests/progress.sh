#!/usr/bin/env bash
# progress.sh — 算出来的进度总览（pt list / INDEX / --tsv）、pt results、lint 的三项进度检查、tree.html 结果页。不调模型，几秒跑完。
set -u
S=$(cd "$(dirname "$0")" && pwd)
SD="$S/../plugins/project-tracker/skills/project-tracker/scripts"
PT="$SD/pt.sh"
T=${KEEP_T:-$(mktemp -d)}; [ -n "${KEEP_T:-}" ] || trap 'rm -rf "$T"' EXIT
export PROJECT_TRACKER_ROOT="$T/root" PT_HOSTNAME=host-me PT_FLEET_JOBS="$T/jobs" PT_TODAY=2026-11-16
unset CLAUDE_PROJECT_DIR CLAUDE_CODE_SESSION_ID GIT_AUTHOR_DATE GIT_COMMITTER_DATE
R="$T/root"; mkdir -p "$T/w"
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
# 在 <日期> 提交 <slug> 的全部改动：cm <slug> <YYYY-MM-DD> <说明>
cm(){ (cd "$R/$1" && git add -A && GIT_AUTHOR_DATE="$2T12:00:00" GIT_COMMITTER_DATE="$2T12:00:00" \
      git -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -qm "$3"); }
# pt new / research 的提交固定在 09-01，免得真实的今天混进最近活动
ptd(){ (cd "$T/w" && GIT_AUTHOR_DATE=2026-09-01T12:00:00 GIT_COMMITTER_DATE=2026-09-01T12:00:00 bash "$PT" "$@" >/dev/null); }
mk(){ ptd new "$1" "项目 $1" "$T/w"; }
jh(){ printf '\n## [%s] %s | x | %s\nDid: x\n' "$2" "$3" "$4" >> "$R/$1/journal.md"; }
node(){ printf -- '---\ntitle: %s\nparent: %s\nstatus: %s\n%b---\n\n## 结论\n%s\n' "$3" "$4" "$5" "$6" "$7" > "$R/$1/tree/$2.md"; }
row(){ grep "^| $1 |" "$R/INDEX.md"; }
lst(){ bash "$PT" list --no-sync >/dev/null; }
# 新建档案的 journal 首条写的是真实今天，测试按 PT_TODAY 算：统一改成指定日期
redate(){ sed -i "s/^## \[[0-9-]*\] 决定 | 立项/## [$2] 决定 | 立项/" "$R/$1/journal.md"; }

echo "# 最近活动：提交、journal 非运维、节点变化取最晚；不算 autosync、合并、批量迁移"
mk act; redate act 2026-11-01; cm act 2026-11-01 "checkpoint @host-me: 开工"
jh act 2026-11-05 结果 "真做了"; cm act 2026-11-05 "checkpoint @host-me: 做了"
jh act 2026-11-12 运维 "整理格式"; cm act 2026-11-12 "state：按快照层新约定重写；旧 state 原样移入 archive"
echo x >> "$R/act/charter.md"; cm act 2026-11-13 "charter: Host「ws02」改成规范主机名 host-me"
echo y >> "$R/act/state.md"; cm act 2026-11-14 "记忆迁入：旧目录记忆原文迁到 references"
echo z >> "$R/act/state.md"; cm act 2026-11-15 "autosync @host-me (idle)"
lst
check "运维条目、autosync、批量迁移的提交都不算"     'row act | grep -q "^| act | 进行中 | 2026-11-05 journal | 11 天 |"'
mk hand; redate hand 2026-10-01; cm hand 2026-10-01 x; echo w >> "$R/hand/plan.md"; cm hand 2026-11-10 "journal: 手写的提交说明也算"
lst
check "不带 checkpoint 前缀的手写提交也算"           'row hand | grep -q "| 2026-11-10 提交 |"'

echo "# 多机同步合并后的历史"
mk mrg; redate mrg 2026-11-01; ptd research mrg; cm mrg 2026-11-01 "research @host-me"
git -C "$R/mrg" checkout -q -b side
node mrg H1 "另一台机器上的假设" Q1 closed 'verdict: refuted\n' "否（E1）。"; cm mrg 2026-11-08 "checkpoint @host-b: H1 否"
git -C "$R/mrg" checkout -q main; echo m >> "$R/mrg/state.md"; cm mrg 2026-11-06 "checkpoint @host-me: 本机进展"
(cd "$R/mrg" && GIT_AUTHOR_DATE=2026-11-15T12:00:00 GIT_COMMITTER_DATE=2026-11-15T12:00:00 \
  git -c user.name=t -c user.email=t@t merge -q --no-edit -m "Merge remote-tracking branch 'b/main'" side)
echo s >> "$R/mrg/state.md"; cm mrg 2026-11-16 "autosync @host-me (idle)"
lst
check "合并提交与 autosync 不算；另一台机器的节点变化经合并认得出" 'row mrg | grep -q "| 2026-11-08 节点 | 8 天 |"'
check "进度：active / 已关"                          'row mrg | grep -q "| active 1 / 已关 1 |"'

echo "# 等用户：待拍板/待用户/等用户小节；有日期只认行首的 [待用户 MM-DD]，旧格式只数条目"
mk pend; redate pend 2026-11-15; cm pend 2026-11-15 x
python3 - "$R/pend/state.md" <<'PY'
import re,sys; p=sys.argv[1]; s=open(p).read()
s=s.replace("## 待拍板\n无\n", "## 待拍板\n1. [待用户 11-10] 要不要换方案：正文里写了 10-01 与 2026-09-01，这些不算\n   续行也提到 09-15\n2. [待用户 11-14] 第二件\n")
s=s.replace("## 下一步\n", "## 下一步\n- 11-01 前做完（下一步里的日期也不算）\n")
open(p,"w").write(s)
PY
lst
check "两条，最老 6 天（正文与别的小节里的日期不算）"  'row pend | grep -q "| 2（最老 6 天） |"'
check "等用户的项目排最前"                           '[ "$(sed -n "/^|---/{n;p;q}" "$R/INDEX.md" | cut -d"|" -f2 | tr -d " ")" = pend ]'
python3 - "$R/pend/state.md" <<'PY'
import sys; p=sys.argv[1]; s=open(p).read(); s=s.replace("2. [待用户 11-14] 第二件\n","2. [待用户 11-14] 第二件\n3. 旧写法没有标签\n"); open(p,"w").write(s)
PY
lst
check "待拍板里有不带标签的条目（旧格式）只数顶层条目、无日期" 'row pend | grep -q " 天 | 3（旧格式，无日期） |"'
mk leg; redate leg 2026-11-14; cm leg 2026-11-14 x
printf '# s\n## 现在\n乱写\n\n## 待拍板（用户）\n1. 甲\n   续行不算一条\n   - 子条目也不算\n2. 乙：正文里的 [待用户 11-01] 不算日期\n\n## 还留着（待用户定是否删）\n- 丙\n\n## 下一步\n- 等用户回话（正文不猜）\n' > "$R/leg/state.md"
printf '# s\n## 现在\n乱写\n\n## 等用户\n暂无\n' > "$R/hand/state.md"
lst
check "旧格式：标题含待拍板/待用户的小节都数，续行与子条目不算" 'row leg | grep -q " 天 | 3（旧格式，无日期） |"'
check "旧格式小节写「暂无」算 0"                       'row hand | grep -q " 天 | 0 |"'
check "INDEX 说明「—」不等于没在等"                    'grep -q "「—」= 没有这种小节，不等于没在等" "$R/INDEX.md"'
check "state 不合格又没有待拍板小节显示 —"            'printf "# s\n## 现在\n乱写\n" > "$R/hand/state.md"; lst; row hand | grep -q "天 | — |"'
check "跨年：12-30 的待用户到 2027-01-03 是 4 天"     'python3 - "$R/pend/state.md" <<PY
import sys; p=sys.argv[1]; s=open(p).read(); s=s.replace("3. 旧写法没有标签\n","").replace("[待用户 11-10]","[待用户 12-30]").replace("[待用户 11-14]","[待用户 01-02]"); open(p,"w").write(s)
PY
PT_TODAY=2027-01-03 bash "$PT" list --no-sync >/dev/null; row pend | grep -q "| 2（最老 4 天） |"'
check "跨年：journal 2026-12-30 的条目到 2027-01-03 是 4 天" 'jh pend 2026-12-30 结果 "年底"; PT_TODAY=2027-01-03 bash "$PT" list --no-sync >/dev/null; row pend | grep -q "| 2026-12-30 journal | 4 天 |"'
lst

echo "# 停滞、矛盾、重开与 lint 的三项检查"
mk old; redate old 2026-10-01; cm old 2026-10-01 x
mk done; redate done 2026-11-10; printf -- '# 计划\n- [x 11-01] 一\n- [ ] 二\n' > "$R/done/plan.md"; sed -i 's/^Status:.*/Status: 已完成/' "$R/done/charter.md"; cm done 2026-11-10 x
mk para; redate para 2026-11-10; ptd research para
node para H1 "还开着" Q1 active "" ""; sed -i 's/^Status:.*/Status: 暂停/' "$R/para/charter.md"; cm para 2026-11-10 x
lst
check "进行中 14 天没活动标 ⚠停滞"                  'row old | grep -q "^| old | 进行中 ⚠停滞 |"'
check "暂停但树上还有 active 标 ⚠矛盾"              'row para | grep -q "^| para | 暂停 ⚠矛盾（树上 2 个 active） |"'
check "排序：等用户（有日期）> 等用户（旧格式）> 停滞 > 矛盾 > 其余" '[ "$(grep -o "^| [a-z]* |" "$R/INDEX.md" | tr -d "| " | head -n 4 | tr "\n" " ")" = "pend leg old para " ]'
out=$(bash "$PT" lint old done para)
check "lint idle"                                    'grep -q "^old: idle: 进行中，但最近活动 2026-10-01（journal）已过 46 天" <<<"$out"'
check "lint plan-open"                               'grep -q "^done: plan-open: 已完成，但 plan.md 还有 1 个未勾项" <<<"$out"'
check "lint status-tree"                             'grep -q "^para: status-tree: 状态「暂停」，但研究树还有 2 个 active 节点（H1、Q1）" <<<"$out"'
sed -i 's/^Status:.*/Status: 进行中/' "$R/done/charter.md" "$R/para/charter.md"; jh old 2026-11-16 结果 "重开"
lst; out=$(bash "$PT" lint old done para)
check "重开后三项都不再报，标记也撤掉"               '! grep -q "idle\|plan-open\|status-tree" <<<"$out" && ! grep -q "⚠" <<<"$(row old; row done; row para)"'
check "重开后最近活动是新条目"                       'row old | grep -q "| 2026-11-16 journal | 0 天 |"'

echo "# 现在最信的一条（截到一行）与 --tsv"
python3 - "$R/act/state.md" <<'PY'
import sys; p=sys.argv[1]; s=open(p).read()
s+="\n## 当前认识\n<!-- 注释不算 -->\n先说明一句，不是条目\n\n1. **主分** bop 0.71 | 门槛 0.75，"+"很长"*60+"\n   续行并入第一条\n2. 第二条\n"
open(p,"w").write(s)
PY
lst
check "取第 1 条、去粗体、竖线转义、截到一行"          'row act | grep -q "| 主分 bop 0.71 ／ 门槛 0.75，很长很长.*… |$" && [ "$(row act | wc -l)" = 1 ]'
check "工程项目 state 可以有「当前认识」（仍合格）"    'python3 "$SD/brief.py" --check "$R/act/state.md"'
check "研究项目 state 的「当前认识」不算固定小节"      'cp "$R/act/state.md" "$R/para/state.md"; ! python3 "$SD/brief.py" --check "$R/para/state.md"'
tsv=$(bash "$PT" list --no-sync --tsv)
check "--tsv 表头与列数"                             '[ "$(head -n1 <<<"$tsv")" = "$(printf "slug\tname\tstatus\thost\tact\tact_src\tdays\tpend_n\tpend_days\tprogress\trunning\tflags\tbelief\tsummary")" ] && [ "$(awk -F"\t" "{print NF}" <<<"$tsv" | sort -u)" = 14 ]'
check "--tsv 不截断最信的一条"                       'grep "^act	" <<<"$tsv" | grep -q "续行并入第一条"'

echo "# 在跑：本机 fleet 任务里记了 slug、还在跑的"
mkdir -p "$T/jobs/j1" "$T/jobs/j2" "$T/jobs/j3" "$T/bin"
echo act > "$T/jobs/j1/slug"; echo act > "$T/jobs/j2/slug"; echo 0 > "$T/jobs/j2/exit"; echo old > "$T/jobs/j3/slug"
printf '#!/bin/sh\nshift 2; for u; do case $u in fleet-j1) echo active;; *) echo inactive;; esac; done\n' > "$T/bin/systemctl"; chmod +x "$T/bin/systemctl"
PATH="$T/bin:$PATH" bash "$PT" list --no-sync >/dev/null
check "act 1 个在跑（结束的、单元不在的不算）"         'row act | grep -q "| 1 | [^|]* |$" && row old | grep -q "| 0 | [^|]* |$"'
check "没有 fleet 任务目录时显示 —"                   'PT_FLEET_JOBS="$T/none" bash "$PT" list --no-sync >/dev/null; row act | grep -q "| — | [^|]* |$"'

echo "# 缓存"
lst; t0=$(date +%s%N); lst; t1=$(date +%s%N)
check "缓存命中（第二次 list）"                        '[ -f "$R/.cache/progress.json" ]'
echo q >> "$R/old/state.md"; jh old 2026-11-16 决定 "再一条"; sed -i 's/^Status:.*/Status: 暂停/' "$R/old/charter.md"; lst
check "文件一改缓存就失效"                           'row old | grep -q "^| old | 暂停 |"'

echo "# pt results"
python3 - "$R/mrg" <<'PY'
import sys,os; d=sys.argv[1]
def node(i, t, st, v, concl):
    open(os.path.join(d,"tree",i+".md"),"w").write(f"---\ntitle: {t}\nparent: Q1\nstatus: {st}\n{v}---\n\n## 结论\n{concl}\n")
node("H2","写了日期的","closed","verdict: supported\n","成立（2026-10-20，E2）：读数 0.9。后面不算。")
node("H3","没写日期的","closed","verdict: refuted\n","不成立：E3 掉分。")
node("H4","还开着的","active","","")
open(os.path.join(d,"experiments.md"),"a").write("\n| id | node | 问题 / 对照 | 读数 | 运行 | 结论 | 证据 |\n|---|---|---|---|---|---|---|\n| E2 | H2 | a | 0.9 | r | 支持 | p |\n| E3 | H3 | b | 0.1 | r | 不支持 | p |\n| E4 | H4 | c | 0.5 | r |  | p |\n| E5 | H4 | d | 0.6 | r | 部分 | p |\n| E6 | H4 | e | 完成：0.7 | r | 预测：0.8 | p |\n| E7 | H4 | f 漏了几格 | 0.9 |\n")
PY
cm mrg 2026-11-16 "checkpoint @host-me: H2 H3 关"
node mrg H5 "刚关还没提交" Q1 closed 'verdict: abandoned\n' "放弃。"
out=$(bash "$PT" results mrg)
check "已关节点按日期倒序：未提交 > 入档 > 结论里写的日期"  '[ "$(grep -oE "^(未提交|入档 [0-9-]+|[0-9-]{10}) H[0-9]+" <<<"$out" | tr "\n" ";")" = "未提交 H5;入档 2026-11-16 H3;入档 2026-11-08 H1;2026-10-20 H2;" ]'
check "行格式：日期 ID verdict 标题 — 结论首句 [台账 id]" 'grep -qx "2026-10-20 H2 supported 写了日期的 — 成立（2026-10-20，E2）：读数 0.9。 \[E2\]" <<<"$out"'
check "未关节点的台账行：读数与结论各带列名"          'grep -qx "E5 H4\[active\] 读数：0.6 ｜ 结论：部分" <<<"$out" && grep -qx "E4 H4\[active\] 读数：0.5" <<<"$out"'
check "结论列写的是预测也照列名给，读数不丢"          'grep -qx "E6 H4\[active\] 读数：完成：0.7 ｜ 结论：预测：0.8" <<<"$out"'
check "格数与表头不符的行原样给，不按列名猜"          'grep -qx "E7 H4\[active\] （格数与表头不符，原样）H4 | f 漏了几格 | 0.9" <<<"$out"'
check "verifier.md 还是模板占位时给一行指针"          'grep -qx "考官与门槛：见 verifier.md（没有标题含门槛 / 指标 / 主分的小节可摘）" <<<"$out"'
printf '# 考官卡\n\n## 目标与真值\n不摘这节\n\n## 指标与聚合定义\n- 主分：bop 均值\n%s\n过线：主分 ≥ 0.75\n\n## 判定依据\n不摘\n' "$(for k in $(seq 30); do printf -- "- 长说明 %s 很长很长很长很长很长很长\n" "$k"; done)" > "$R/mrg/verifier.md"
out=$(bash "$PT" results mrg)
gate=$(sed -n "/^考官与门槛/,/^现在最信的一条/p" <<<"$out")
check "考官与门槛：摘标题含指标的小节、过线行先保、不超过 600 字节" 'sed -n 2p <<<"$out" | grep -q "^考官与门槛（摘自 verifier.md「指标与聚合定义」" && grep -q "过线：主分 ≥ 0.75" <<<"$gate" && grep -q "主分：bop 均值" <<<"$gate" && ! grep -q "不摘" <<<"$gate" && [ "$(sed "1d;\$d" <<<"$gate" | wc -c)" -le 700 ]'
printf '# 考官卡\n\n## 目标与真值\n只有目标\n' > "$R/mrg/verifier.md"
check "摘不到给一行指针"                              'bash "$PT" results mrg | grep -qx "考官与门槛：见 verifier.md（没有标题含门槛 / 指标 / 主分的小节可摘）"'
rm "$R/mrg/verifier.md"
check "没有 verifier.md 不出考官与门槛"               '! bash "$PT" results mrg | grep -q "考官与门槛"'
for k in $(seq 60); do node mrg "H$((k+10))" "批量 $k $(printf '长%.0s' $(seq 40))" Q1 closed 'verdict: refuted\n' "否 $(printf '长%.0s' $(seq 40))。"; done
out=$(bash "$PT" results mrg); full=$(bash "$PT" results mrg --all)
check "默认不超过 4 KB，截掉的给去处，标题截断"         '[ "$(printf "%s\n" "$out" | wc -c)" -le 4096 ] && grep -q "本节另有 .* 条未列：pt results mrg --all" <<<"$out" && grep -q "E7 H4" <<<"$out" && grep -q " refuted 批量 [0-9]* 长*… — 否 " <<<"$out"'
check "--all 全量"                                   '[ "$(grep -c " refuted 批量 .* — 否 " <<<"$full")" = 60 ]'
mk eng; redate eng 2026-11-16; printf -- '# 计划\n- [x 11-01] 第一步 → 证据 a\n- [ ] 第二步\n' > "$R/eng/plan.md"
python3 - "$R/eng/state.md" <<'PY'
import sys; p=sys.argv[1]; s=open(p).read(); s=s.replace("## 入口与产物","## 线程\n- [已推送 abc1234] 修好了 X\n- [进行中] 别的\n\n## 入口与产物"); open(p,"w").write(s)
PY
out=$(bash "$PT" results eng)
check "工程项目：plan 已勾项与已推送线程"              'grep -q "^plan 已勾 1/2" <<<"$out" && grep -qx -- "- \[x 11-01\] 第一步 → 证据 a" <<<"$out" && grep -qx -- "- \[已推送 abc1234\] 修好了 X" <<<"$out" && ! grep -q "进行中\] 别的" <<<"$out"'

echo "# tree.html：节点标题下的 verdict 与结论首句、结果页"
bash "$PT" tree mrg >/dev/null; H="$R/mrg/tree.html"
check "列表里已关节点标题下一行 verdict + 结论首句"   'grep -q "<div class=cs title=\"成立（2026-10-20，E2）：读数 0.9。\"><span class=\"b v-supported\">supported</span> 成立" "$H"'
check "结果页与入口"                                 'grep -q "<article id=\"n-__results\" hidden><h2>结果 · mrg</h2>" "$H" && grep -q "<a href=\"#__results\">结果</a></header>" "$H"'
check "结果页：已关节点带标题，台账行读数与结论各带列名" 'grep -q "<td>写了日期的 — 成立（2026-10-20，E2）" "$H" && grep -q "<td>读数：完成：0.7 ｜ 结论：预测：0.8</td>" "$H"'
check "图数据带结论首句"                              'grep -q "\"c\":\"不成立：E3 掉分。\"" "$H"'

echo "# 档案根不是默认位置（副本）时不做多机同步"
printf 'nohost\n' > "$R/FLEET"
err=$(PT_SSH=false PT_GIT_SSH=false bash "$PT" list 2>&1 >/dev/null)
check "pt list 不同步、说明原因"                       'grep -q "不是默认位置：不做多机同步" <<<"$err" && [ ! -e "$R/.fleet/hosts/nohost" ]'
check "pt sync 拒绝"                                   '! PT_SSH=false PT_GIT_SSH=false bash "$PT" sync >/dev/null 2>&1 && [ ! -e "$R/.fleet/hosts/nohost" ]'
rm "$R/FLEET"

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
