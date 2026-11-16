#!/usr/bin/env bash
# records.sh — 不调模型：短卡、目录 index.tsv、pt get / find / conditions、条件状态、新 lint、results 取卡的「结论」行。几秒跑完。
set -u
S=$(cd "$(dirname "$0")" && pwd)
PT="$S/../plugins/project-tracker/skills/project-tracker/scripts/pt.sh"
T=${KEEP_T:-$(mktemp -d)}; [ -n "${KEEP_T:-}" ] || trap 'rm -rf "$T"' EXIT
export PROJECT_TRACKER_ROOT="$T/root" PT_HOSTNAME=host-me PT_FLEET_JOBS="$T/no-fleet-jobs"
unset CLAUDE_PROJECT_DIR CLAUDE_CODE_SESSION_ID
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
mkdir -p "$T/w/r" "$T/w/e"
(cd "$T/w/r" && bash "$PT" new rr "研究" >/dev/null && bash "$PT" research rr >/dev/null)
(cd "$T/w/e" && bash "$PT" new ee "工程" >/dev/null)
R="$T/root/rr"; E="$T/root/ee"
sed -i 's/^- G1 <可判定的陈述>.*/- [ ] 旧写法的完成标准：能跑通/' "$E/charter.md"   # 模拟没迁移的旧项目
node(){ printf -- '---\ntitle: %s\nparent: %s\nstatus: %s\n%b---\n%b\n' "$2" "$3" "$4" "$5" "$6" > "$R/tree/$1.md"; }
node Q1 "根问题：怎样把误差压到 2 毫米" "" active '' '## 判别\n根。\n## 当前认识\n- 根认识\n'
node Q2 "子问题：筐能不能估" Q1 closed 'verdict: supported\n' '## 结论\n目的：看筐相对机器人能估多准\n结果：估不到毫米级，最好 3 mm [E2]\n\n答完，答案否定。'
node H1 "假设一：钢件平面拟合" Q1 closed 'verdict: refuted\n' '## 判别\n来源：盲出。\n命题：只拟合钢件平面就够。\n## 结论\n**目的**：看只用钢件平面能不能到 2 毫米\n怎么做：平面拟合加先验，\n  在 24 站上跑\n结果：高度 p95 15.3 mm，线是 2 mm [E1]\n结论：不成立，钢件平面不够\n\n机制：漆面梁读远。'
node H2 "假设二：旧节点没有卡" Q1 closed 'verdict: refuted\n' '## 判别\n来由：旧。\n做法：\n- 换一种打分\n## 结论\n不成立（E2）。读数 2.5 mm。\n## 复核更正（11-03）\n读数属实但口径错：应按严格分算，实为 7.50。'
node H3 "假设三：没跑就被取代" Q1 closed 'verdict: superseded\nby: H1\n' '## 判别\n要跑。\n## 结论\n被 H1 取代，未跑。'
node H4 "假设四：卡写得不齐" Q1 closed 'verdict: refuted\n' '## 结论\n目的：试试\n结果：坏了 99.9 mm [E99]'
node H5 "假设五：在做" Q1 active '' '## 判别\n预测。'
LONG=$(python3 -c "print('很长的读数' * 300)")
cat >> "$R/experiments.md" <<EOF
| E1 | H1 | 平面拟合 24 站 | 高度 p95 15.3 mm | run1 | 不过 G2=15.3，过 G1=1.8；不成立 | out/e1 |
| E2 | H2 | 换打分 | 2.5 mm（严格分 7.5） | run2 | 不过 G1=2.5 | out/e2 |
| ID-TOPK | H2 | 身份 top-k | G_5 +7.50 | run3 | 未定 | out/id |
| M1 | Q2 | 只挂问题的测量 | 筐面 sd 10–25 mm | run4 | 测量 | out/m1 |
| E3 | H5 | 长行 | $LONG | run5 | 过 G9 | out/e3 |
EOF
python3 - "$R/charter.md" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p, encoding="utf-8").read()
g = """- G1 作业级 p95 不超过 2 mm | 线: ≤2 mm | 尺: verifier 指标 | 来源: 用户定
- G2 高度误差 | 线: ≤10 mm | 尺: verifier | 来源: 推荐待定
- G3 用户手感 OK | 线: 用户确认 | 尺: journal 裁决 | 来源: 用户定
- G4 延迟 | 线: 待用户（推荐 ≤50 ms） | 尺: 以后定 | 来源: 推荐待定
- G5 旧目标 | 线: ≥1 | 尺: x | 来源: 用户定 | 不再适用（ADR-0002）
- G6 写不成格式的条件
"""
s = re.sub(r"(## 完成标准\n)(.*?)(\n## )", lambda m: m.group(1) + g + m.group(3), s, count=1, flags=re.S)
open(p, "w", encoding="utf-8").write(s)
PY
printf '\n## [2026-11-10] 结果 | G3 | 用户试过手感\nG3 过 E1（用户 11-10 原话「可以」）\nG4 不过 80 ms 台架实测\n' >> "$R/journal.md"
printf '\n## ADR-0002: 改目标（2026-11-09）\nStatus: 采纳\n正文\n' >> "$R/decisions.md"
bash "$PT" index rr "立了几个节点" >/dev/null
# 工程项目 ee：月归档里的旧条目、journal 里的旧格式条目、有卡的结果条目、补记（原始记录指回旧条目）、没卡的新结果条目
mkdir -p "$E/archive"
printf '# journal 2026-09\n\n## [2026-09-03] 结果 | 台架 | 归档里的旧结果\n旧的正文。\n' > "$E/archive/journal-2026-09.md"
cat >> "$E/journal.md" <<'EOF2'

## 2026-10-02 · session 4
- Did: 量了延迟。第二句不该出现。
- Result: 中位 80 ms。

## [2026-11-12] 结果 | 链路 | 七路相机 15 Hz 零丢
目的：看七路相机能不能同时稳定出图。
怎么做：60 秒录包，数各路帧率与丢帧。
结果：七路全 15 Hz，丢帧 0；延迟中位 80 ms。
结论：带宽够用，延迟还没达标。

后面的过程原文。

## [2026-10-02] 结果 | 补记 | 延迟中位 80 ms，没到 50 ms
目的：量端到端延迟。
怎么做：时间戳对拍。
结果：中位 80 ms。
结论：没到推荐的 50 ms。

原始记录：J2026-10-02.1 Result

## [2026-09-03] 结果 | 补记 | 归档那天的补记
目的：补记归档月份的结果。
怎么做：x。
结果：y。
结论：编号接着归档里的数。

## [2026-11-13] 结果 | 链路 | 没写卡的新结果
直接写了过程，没写卡。
EOF2
LONGCARD=$(python3 -c "print('很长' * 120)")
printf '\n## [2026-11-14] 结果 | 长卡 | 卡太长\n目的：%s\n怎么做：a\n结果：b\n结论：c\n' "$LONGCARD" >> "$E/journal.md"
git -C "$E" add journal.md archive && git -C "$E" -c user.name=t -c user.email=t@t commit -qm "journal 样本"

echo "# 目录 index.tsv"
I="$R/index.tsv"
check "checkpoint 后生成目录，表头七列"      '[ -f "$I" ] && [ "$(head -n1 "$I")" = "$(printf "编号\t类型\t状态\t日期\t标题\t一行结果\t位置")" ]'
check "目录不进提交（.git/info/exclude）"   'grep -qx index.tsv "$R/.git/info/exclude" && [ -z "$(git -C "$R" status --porcelain)" ] && ! git -C "$R" ls-files | grep -qx index.tsv'
check "节点、台账（非 E 前缀也算）、条件、ADR、journal 都有行" 'for x in Q1 H1 E1 ID-TOPK M1 G1 ADR-0002; do grep -q "^$x	" "$I" || exit 1; done; grep -q "^J261110-1	journal	结果" "$I"'
check "问题节点已答 / 未答，没读数被取代的假设标未跑" 'grep -q "^Q2	问题	已答	" "$I" && grep -q "^Q1	问题	未答	" "$I" && grep -q "^H3	假设	未跑	" "$I" && grep -q "^H1	假设	不成立	" "$I"'
check "日期取 git（台账行与已关节点）"      'D=$(date +%F); grep -q "^E1	台账	不过 G2、过 G1	$D	" "$I" && grep -q "^H1	假设	不成立	$D	" "$I"'
check "有卡的取卡，旧节点标原文摘取"          'grep -q "^H1	.*	高度 p95 15.3 mm，线是 2 mm \[E1\]	tree/H1.md$" "$I" && grep -q "^H2	.*	（原文摘取）" "$I"'
check "一行一条：表头 + 7 节点 + 5 台账 + 6 条件 + 1 ADR（模板注释里的不算）+ 2 journal" '[ "$(wc -l < "$I")" = 22 ]'

echo "# pt get"
out=$(bash "$PT" get rr H1)
check "卡四行、续行并进上一项、粗体去掉"   'grep -q "^卡：" <<<"$out" && grep -q "^  目的：看只用钢件平面能不能到 2 毫米$" <<<"$out" && grep -q "^  怎么做：平面拟合加先验， 在 24 站上跑$" <<<"$out" && grep -q "^  结论：不成立，钢件平面不够$" <<<"$out"'
check "挂着的台账行按列名给、指向上级"     'grep -q "^台账 1 行：" <<<"$out" && grep -q "^    读数：高度 p95 15.3 mm" <<<"$out" && grep -q "^上级：Q1 \[未答\]" <<<"$out" && grep -q "^判定的条件：不过 G2（E1）、过 G1（E1）" <<<"$out"'
out=$(bash "$PT" get rr H2)
check "旧节点：原文摘取，结论取更正后的说法" 'grep -q "原文摘取" <<<"$out" && grep -q "结论取自「更正」" <<<"$out" && grep -q "^  结论：（更正）读数属实但口径错：应按严格分算，实为 7.50。" <<<"$out" && grep -q "^  怎么做：换一种打分" <<<"$out"'
check "台账行有读数：结果取最后一行读数"     'grep -q "^  结果：\[ID-TOPK\] G_5 +7.50" <<<"$out"'
out=$(bash "$PT" get rr Q2)
check "问题节点：两行卡、直接挂的测量"       'grep -q "^  目的：看筐相对机器人" <<<"$out" && grep -q "^  结果：估不到毫米级" <<<"$out" && ! grep -q "^  结论：" <<<"$out" && grep -q "直接挂在这个问题上的测量 1 行" <<<"$out" && grep -q "^  M1 · " <<<"$out"'
out=$(bash "$PT" get rr ID-TOPK)
check "非 E 编号的台账行能取，给判的节点与上级问题" 'grep -q "^ID-TOPK · 台账行" <<<"$out" && grep -q "^判的节点：H2" <<<"$out" && grep -q "^上级问题：Q1" <<<"$out"'
out=$(bash "$PT" get rr H5)
n=$(printf '%s\n' "$out" | wc -c)
check "超过 3 KB 分页，给接着看的命令"       '[ "$n" -le 3200 ] && grep -q "（第 1/[0-9]* 页，每页 ≤3 KB；接着看：pt get rr H5 --page 2）" <<<"$out"'
out=$(bash "$PT" get rr H5 --page 2)
check "第 2 页接着给"                        'grep -q "很长的读数" <<<"$out" && grep -q "第 2/" <<<"$out"'
check "ADR、journal、条件都能取"             'bash "$PT" get rr ADR-0002 | grep -q "^## ADR-0002: 改目标" && bash "$PT" get rr J261110-1 | grep -q "^G3 过 E1" && bash "$PT" get rr G1 | grep -q "^G1 \[不过\]"'
check "journal 编号的旧写法与不带年份的写法也认" 'bash "$PT" get rr J2026-11-10.1 | grep -q "^J261110-1 · journal · 结果" && bash "$PT" get rr J1110-1 | grep -q "^G3 过 E1"'

echo "# journal 条目：编号、卡、补记"
IE=$(python3 "$(dirname "$PT")/query.py" index "$E" >/dev/null; cat "$E/index.tsv")
check "编号 J+YYMMDD-序号；同一日期先数月归档再数 journal.md" 'grep -q "^J260903-1	journal	结果	2026-09-03	台架 | 归档里的旧结果	归档里的旧结果	archive/journal-2026-09.md:3$" <<<"$IE" && grep -q "^J260903-2	journal	结果	2026-09-03	补记 | 归档那天的补记	" <<<"$IE" && grep -q "^J261002-1	journal		2026-10-02	session 4	" <<<"$IE" && grep -q "^J261002-2	journal	结果	2026-10-02	补记 | 延迟中位 80 ms" <<<"$IE"'
check "一行结果：有卡取结论，没卡取标题里的一句话" 'grep -q "^J261112-1	.*	带宽够用，延迟还没达标。	journal.md:" <<<"$IE" && grep -q "^J261113-1	.*	没写卡的新结果	journal.md:" <<<"$IE"'
out=$(bash "$PT" get ee J261112-1)
check "pt get 取单条：头一行编号与有卡，下面原文" 'grep -q "^J261112-1 · journal · 结果 · 2026-11-12 · 有卡" <<<"$out" && grep -q "^目的：看七路相机" <<<"$out" && grep -q "^后面的过程原文。" <<<"$out" && ! grep -q "补记" <<<"$out"'
out=$(bash "$PT" get ee J261002-1)
check "补记与原条目互相指" 'grep -q "^补记卡：J261002-2" <<<"$out" && bash "$PT" get ee J261002-2 | grep -q "^补记的原条目：J261002-1"'
out=$(bash "$PT" brief ee)
check "工程项目简报：最近有结论的取有卡结果条目的结论行" 'grep -q "^===== 最近有结论的 4 条" <<<"$out" && grep -q "^- J261112-1 11-12 .* — 带宽够用，延迟还没达标。" <<<"$out" && ! grep -q "J261113-1" <<<"$out"'
out=$(bash "$PT" lint ee)
check "lint：新写的结果条目没卡只提示；J 卡超长" 'grep -q "^ee: card-missing: 提示：近 14 天 1 条「结果」条目没有卡（J261113-1）" <<<"$out" && grep -q "^ee: card-format: J261114-1（journal.md:[0-9]*）的卡：[0-9]* 字节，超过 600" <<<"$out"'

check "不存在的编号：提示 find，退出非 0"     'o=$(bash "$PT" get rr H99); [ $? -ne 0 ] && grep -q "pt find rr H99" <<<"$o"'

echo "# pt find"
out=$(bash "$PT" find rr 钢件)
check "按词找：返回目录里的行"               'grep -q "^H1	" <<<"$out" && grep -q "^编号	" <<<"$out"'
check "多个词都要出现，不分大小写"           'bash "$PT" find rr id-topk 身份 | grep -q "^ID-TOPK	" && ! bash "$PT" find rr id-topk 钢件 >/dev/null'
check "源文件改了目录自动重算"               'sed -i "s/^title: 假设五：在做/title: 假设五：改了名字/" "$R/tree/H5.md"; bash "$PT" find rr 改了名字 | grep -q "^H5	"'

echo "# 条件"
out=$(bash "$PT" conditions rr)
check "状态只从点名的判定算：最近 不过、最好 1.8" 'grep -q "^G1 \[不过\] 作业级" <<<"$out" && grep -q "线 ≤2 mm；最近 不过 2.5（E2，.*）；最好 过 1.8（E1，" <<<"$out"'
check "数值判定、journal 判定、线未定、不再适用、写不成格式" 'grep -q "^G2 \[不过\]" <<<"$out" && grep -q "^G3 \[过\] 用户手感 OK" <<<"$out" && grep -q "最近 过（E1，2026-11-10）" <<<"$out" && grep -q "^G4 \[线未定\]" <<<"$out" && grep -q "^G5 \[不再适用\]" <<<"$out" && grep -q "^G6 \[线未定\]" <<<"$out" && grep -q "（格式：缺「线:」" <<<"$out"'
check "推荐线：原样显示，对推荐线差多少标明是推荐线，状态仍线未定" 'grep -q "线 待用户定，推荐 ≤50 ms；最近 不过 80（J261110-1，2026-11-10）；对推荐线差 30（推荐线，不是定了的线）" <<<"$out"'
check "journal 判定带证据文字"                 'grep -q "2026-11-10 过 E1（journal.md:[0-9]*） E1（用户 11-10 原话「可以」）" <<<"$out"'
check "点名了没登记的条件"                   'grep -q "点名了没登记的条件：G9" <<<"$out"'
out=$(bash "$PT" conditions ee)
check "没登记的项目：原样列旧完成标准，标未登记" 'grep -q "^未登记" <<<"$out" && grep -q "^  - \[ \] 旧写法的完成标准：能跑通" <<<"$out"'

check "新建项目的模板条件行：线未定"          'bash "$PT" new nn "新的" "$T/w/e" >/dev/null; bash "$PT" conditions nn | grep -q "^G1 \[线未定\] <可判定的陈述>"'

echo "# lint（只报不拦）"
out=$(bash "$PT" lint rr)
check "已关节点没有卡（汇成一行）"           'grep -q "^rr: card-missing: 已关节点 2 个没有短卡" <<<"$out"'
check "卡字段不齐"                           'grep -q "^rr: card-format: H4 的卡：缺 怎么做、结论" <<<"$out"'
check "卡里的编号目录里没有"                 'grep -q "^rr: card-ref: H4 的卡引用了目录里没有的编号：E99" <<<"$out" && ! grep -q "card-ref: H1" <<<"$out"'
check "数字溯源只作提示"                     'grep -q "^rr: card-number: 提示：H4 的卡里 99.9" <<<"$out" && ! grep -q "card-number: 提示：H1" <<<"$out"'
check "条件行写不成格式、点名没登记的条件"   'grep -q "^rr: cond-format: 条件 G6" <<<"$out" && grep -q "^rr: cond-format: 判定点名了 G9" <<<"$out"'

echo "# 旧接口：results / tree 取卡的「结论」行，简报定长"
check "pt results 有卡的取卡的结论行"         'bash "$PT" results rr | grep -q " H1 refuted 假设一：钢件平面拟合 — 不成立，钢件平面不够 \[E1\]"'
check "pt tree --all 有卡的取卡的结论行"      'bash "$PT" tree rr --all --no-html | grep -q "^- H1 \[refuted\] .* —— 不成立，钢件平面不够"'
out=$(bash "$PT" brief rr)
check "简报 ≤8 KB，有条件块、最近卡、去哪找"  '[ "$(printf "%s\n" "$out" | wc -c)" -le 8192 ] && grep -q "^===== 条件（" <<<"$out" && grep -q "^- G1 \[不过\]" <<<"$out" && grep -q "^- H1 \[不成立\] .* — 不成立，钢件平面不够" <<<"$out" && grep -q "pt get rr <编号>" <<<"$out"'
out=$(bash "$PT" brief ee)
check "工程项目简报：条件未登记、没有前沿块" 'grep -q "^===== 条件：未登记" <<<"$out" && grep -q "^===== 最近有结论的" <<<"$out" && ! grep -q "= 前沿" <<<"$out"'

echo "# 给人看的站点（pt site）"
out=$(bash "$PT" site 2>&1)
SITE="$T/root/site"
check "生成三层：总览、两类项目页、节点页"   'grep -q "^site：" <<<"$out" && [ -f "$SITE/index.html" ] && [ -f "$SITE/p/rr.html" ] && [ -f "$SITE/p/ee.html" ] && [ -f "$SITE/p/rr/H1.html" ] && [ -f "$SITE/p/rr/Q2.html" ] && [ -f "$SITE/.pt-site" ]'
P="$SITE/p/rr.html"; H="$SITE/p/rr"
check "总览：判词色条、条件过 x/y、工程项目条件未登记" 'grep -q "class=\"bar\"" "$SITE/index.html" && grep -q "条件过 0/" "$SITE/index.html" && grep -q "条件未登记" "$SITE/index.html"'
check "项目页：条件表（线未定不画差距、不再适用）" 'grep -q "<th>差多少</th>" "$P" && grep -q "id=\"cond-G4\"" "$P" && grep -q "线未定" "$P" && grep -q "不再适用" "$P" && grep -q "研究树图" "$P"'
check "条件表：最好值离线差多少（按线的方向）" 'grep -q "<td data-l=\"差多少\">差 5.3</td>" "$P" && grep -q "<td data-l=\"差多少\">已到线</td>" "$P"'
check "条件表：推荐线、对推荐线差、值列只写数、证据文字点进条目页" 'grep -q "待用户定，推荐 ≤50 ms" "$P" && grep -q "<td data-l=\"差多少\">对推荐线差 30</td>" "$P" && grep -q "<td data-l=\"最近\">2.5</td>" "$P" && ! grep -q "data-l=\"最近\">不过" "$P" && grep -q "class=\"evn\" href=\"rr/J261110-1.html\"[^>]*>（用户 11-10 原话「可以」）</a>" "$P" && [ -f "$H/J261110-1.html" ]'
check "研究项目页：没卡的旧节点一行、问题分组顶上是问题卡" '! grep -q "class=\"ct\" href=\"rr/H2.html\"" "$P" && grep -q "<li data-s=\"已判\">.*假设二：旧节点没有卡" "$P" && grep -q "id=\"g-Q2\".*<dt>目的</dt><dd>看筐相对机器人" "$P"'
EP="$SITE/p/ee.html"
check "工程项目页：有卡的四行卡、没卡的标题加第一句、条目页" 'grep -q "<dt>结论</dt><dd>带宽够用，延迟还没达标。" "$EP" && grep -q "session 4</a>：Did: 量了延迟。 <span class=\"muted\">（已补卡 1 张）" "$EP" && ! grep -q "第二句不该出现" "$EP" && [ -f "$SITE/p/ee/J261112-1.html" ] && grep -q "<h2>条目原文</h2>" "$SITE/p/ee/J261112-1.html" && grep -q "后面的过程原文" "$SITE/p/ee/J261112-1.html" && grep -q "补记自：<a class=\"ref\" href=\"J261002-1.html\"" "$SITE/p/ee/J261002-2.html"'
check "项目页：最近有结论的实验、按问题分组、可筛" 'grep -q "<h2>最近有结论的实验</h2>" "$P" && grep -q "id=\"g-Q1\"" "$P" && grep -q "data-f=\"已判\"" "$P" && grep -q "data-f=\"搁置\"" "$P"'
check "项目页：编号换成短标题与「证据」，不裸露" 'grep -q ">证据</a>" "$P" && ! sed "s/<[^>]*>//g" "$P" | grep -qE "(^|[^A-Za-z0-9])(E1|E2|H1|H2|Q2)([^A-Za-z0-9]|$)"'
check "节点页：卡在上、证据表、判据、原文、释义"  'grep -q "<dt>怎么做</dt><dd>平面拟合加先验" "$H/H1.html" && grep -q "id=\"row-E1\"" "$H/H1.html" && grep -q "<h2>事先定的判据</h2>" "$H/H1.html" && grep -q "节点原文" "$H/H1.html" && grep -q "<h2>本页编号与术语</h2>" "$H/H1.html"'
check "节点页：原文摘取、更正后的说法、未跑、已答" 'grep -q "原文摘取" "$H/H2.html" && grep -q "（更正）读数属实但口径错" "$H/H2.html" && grep -q ">未跑<" "$H/H3.html" && grep -q ">已答<" "$H/Q2.html" && grep -q "M1" "$H/Q2.html"'
check "工程项目页：条件未登记原样列旧写法、最近结果与决定" 'grep -q "未登记" "$SITE/p/ee.html" && grep -q "旧写法的完成标准：能跑通" "$SITE/p/ee.html" && grep -q "<h2>最近的结果</h2>" "$SITE/p/ee.html" && grep -q "<h2>最近的决定</h2>" "$SITE/p/ee.html" && ! grep -q "研究树图" "$SITE/p/ee.html"'
check "不依赖外网资源、亮暗两套、单页 ≤1 MB"  '! grep -rlE "(src|href)=\"(https?:)?//" "$SITE" && grep -q "prefers-color-scheme:dark" "$P" && [ -z "$(find "$SITE" -name "*.html" -size +1000k)" ]'
printf '\n内网 100.64.1.2:8443，token=abcdefgh12345\n' >> "$R/tree/H5.md"
bash "$PT" site >/dev/null 2>&1
check "页面隐去内网地址与口令"                '! grep -rq "100.64.1.2\|abcdefgh12345" "$SITE" && grep -q "内网地址" "$H/H5.html"'
git -C "$R" checkout -q -- tree/H5.md
mkdir -p "$T/notsite"; echo x > "$T/notsite/keep.txt"
check "--out 指向别的非空目录：拒绝覆盖"      '! bash "$PT" site --out "$T/notsite" 2>/dev/null && [ -f "$T/notsite/keep.txt" ]'
rm -rf "$SITE"; python3 "$(dirname "$PT")/monitor.py" "$T/root" >/dev/null 2>&1
check "pt monitor 顺带生成站点；research.html 有入口" '[ -f "$SITE/p/ee.html" ] && grep -q "site/index.html" "$T/root/research.html"'
check "站点不进项目档案"                      '[ -z "$(git -C "$R" status --porcelain)" ] && [ "$(git -C "$E" status --porcelain)" = " M charter.md" ]'   # ee 的 charter 是上面故意改的

echo; echo "passed=$pass failed=$fail"; [ $fail -eq 0 ]
