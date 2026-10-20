#!/usr/bin/env bash
# pt.sh — project-tracker 的入口脚本。档案根目录：${PROJECT_TRACKER_ROOT:-~/.claude/project}
#
#   pt.sh list [--no-sync]                     打印索引（中心机先同步全机队）
#   pt.sh where                                当前目录命中的、Host=本机的进行中项目（slug 一行一个）
#   pt.sh auto                                 SessionStart hook 用：命中 1 个→brief；多个→提示；0 个→静默；压缩后按会话绑定重新注入
#   pt.sh precompact                           PreCompact hook 用：让压缩摘要留下还没入档的进展
#   pt.sh brief <slug>                         按恢复顺序输出简报，把 ACTIVE 设为该 slug，并把本会话绑到它
#   pt.sh new <slug> "<名称>" [--host H] [workdir ...]   建档（git 仓 + 首次提交）；workdir 默认当前目录
#   pt.sh index <slug> "<一句话>" [状态]       写一句话（进 state 与 INDEX，不是提交说明）与状态、提交这次 checkpoint、重建 INDEX
#   pt.sh research <slug>                      研究项目：加考官卡 verifier.md、实验台账 experiments.md、研究树 tree/Q1.md
#   pt.sh tree <slug> [--all | --ctx ID [--blind] | --next Q|H]   研究树：打印上下文并重写 tree.html
#   pt.sh monitor [--out PATH]                 全局研究监控：所有有 tree/ 的项目汇成 <档案根>/research.html（各 tree.html 的入口 + 最近动态）
#   pt.sh migrate                              把 0.3 及以前的档案升级到 0.4（先备份；幂等）
#   pt.sh sync [-q] [别名 ...]                 中心机：与节点同步（只快进；分叉只报告不合并）
#   pt.sh dispatch <slug> "<任务>" [--wait]    中心机：派项目 Host 上的 Claude 去干
#   pt.sh runs [slug | --wait <run>]           中心机：派活状态 / 等某次派活结束
#
# 隔离原则：任何子命令只读写一个 <slug>/ 目录；list 只读各项目 charter 字段与 state 的一句话；
# monitor 只读各研究项目的 tree/ 与 git 历史，只写档案根的 research.html。
set -u

ROOT="${PROJECT_TRACKER_ROOT:-$HOME/.claude/project}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="$HERE/../reference/templates"
CWD="$(cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null && pwd -P)"
TODAY="$(date +%F)"
THIS_HOST="${PT_HOSTNAME:-$(hostname -s)}"
SLUG_RE='^[a-z0-9]+(-[a-z0-9]+)*$'
# brief 里 journal 的字节预算（约 6000 个汉字）。journal 本身只追加、不删，预算只管简报打印多少
JOURNAL_BUDGET="${PT_BRIEF_JOURNAL_BYTES:-18000}"
STATE_MAX_BYTES=24000
SESS_DIR="$ROOT/.sessions"
HOOK_IN=""

die() { echo "pt.sh: $*" >&2; exit 1; }
section() { printf '\n===== %s =====\n' "$1"; }

# hook 把一段 JSON 喂给 stdin（session_id、source …）。手工调用时 stdin 是终端或空，读不到就算了
hook_input() { [ -t 0 ] || IFS= read -r -d '' -t 2 HOOK_IN || true; }
hook_field() { printf '%s' "$HOOK_IN" | sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1; }
session_id() { local s; s="$(hook_field session_id)"; echo "${s:-${CLAUDE_CODE_SESSION_ID:-}}"; }

# 会话 ↔ 项目的绑定：brief / new 时记下，压缩后 hook 靠它知道该重新注入哪个项目（会话不在 Workdir 里开也行）
bind_session() {
  local sid; sid="$(session_id)"
  [[ "$sid" =~ ^[A-Za-z0-9_-]+$ ]] || return 0
  mkdir -p "$SESS_DIR" && printf '%s\n' "$1" > "$SESS_DIR/$sid"
  find "$SESS_DIR" -type f -mtime +30 -delete 2>/dev/null
  return 0
}
bound_slug() {
  local sid s; sid="$(session_id)"
  [[ "$sid" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
  s="$(head -n1 "$SESS_DIR/$sid" 2>/dev/null)"
  [ -n "$s" ] && [ -f "$ROOT/$s/charter.md" ] && echo "$s"
}

# journal_tail <file> <起始行>：打印起始行之后的条目。标题都留；正文从最新往回留到预算为止，省掉的给行号
journal_tail() {
  LC_ALL=C awk -v start="$2" -v budget="$JOURNAL_BUDGET" '
    NR >= start { n++; line[n] = $0; no[n] = NR }
    END {
      for (i = n; i >= 1; i--) {
        if (line[i] ~ /^## /) { keep[i] = 1; continue }
        if (full) continue
        if (used > 0 && used + length(line[i]) > budget) { full = 1; continue }
        keep[i] = 1; used += length(line[i])
      }
      for (i = 1; i <= n; i++) {
        if (keep[i]) {
          if (cut) { printf "…（省略 journal.md 第 %d–%d 行，约 %d 字节；要查再读原文）\n", from, no[i-1], cut; cut = 0 }
          print line[i]
        } else { if (!cut) from = no[i]; cut += length(line[i]) }
      }
    }' "$1"
}

# 读 charter 里的字段：field <slug> <Key>
field() { sed -n "s/^$2:[[:space:]]*//p" "$ROOT/$1/charter.md" 2>/dev/null | head -n1; }

# Workdir 里的路径，一行一个。容忍 agent 顺手写的注释：路径在第一个括号/分号/逗号处截断，不像路径的片段丢掉
workdirs() { field "$1" Workdir | tr ' ' '\n' | sed -E 's/(（|\(|；|;|，|,).*//' | grep -E '^[~/]'; }

# 档案 git 用固定身份，不依赖各机的 git 配置
g() { local d=$1; shift; git -C "$d" -c user.name=project-tracker -c user.email="pt@$THIS_HOST" -c commit.gpgsign=false "$@"; }

repo_init() {
  if [ ! -d "$1/.git" ]; then
    git init -q "$1" && git -C "$1" symbolic-ref HEAD refs/heads/main
  fi
  git -C "$1" config receive.denyCurrentBranch updateInstead
}

# conflict_files <dir>：还没合好的文件，一行一个——合并中、文件里还留着冲突标记（<<<<<<< / >>>>>>>）的，
# 加上任何还带冲突标记的 .md。在工作区里改好了（没有标记）的冲突文件不算，pt index 的 add -A 会收下它
CONFLICT_MARK='^(<<<<<<<|>>>>>>>)( |$)'
conflict_files() {
  local f
  { git -C "$1" ls-files -u | cut -f2 | sort -u | while IFS= read -r f; do
      [ -f "$1/$f" ] && grep -qE "$CONFLICT_MARK" "$1/$f" && echo "$f"
    done
    git -C "$1" grep --untracked -lE "$CONFLICT_MARK" -- '*.md' 2>/dev/null; } | sort -u
}

# commit_all <dir> <message>：有改动才提交。有冲突不提交（add -A 会把冲突标记当内容收进去）
commit_all() {
  local u
  repo_init "$1" || return 1
  u="$(conflict_files "$1")"
  [ -z "$u" ] || die "$1 有没合完的冲突（文件里还有 <<<<<<< / >>>>>>> 标记），先合并再 checkpoint：$(echo $u)"
  g "$1" add -A || return 1
  g "$1" diff --cached --quiet && return 0
  g "$1" commit -q -m "$2"
}

# sed 替换串转义（分隔符用 |）
sed_esc() { local s=$1; s=${s//\\/\\\\}; s=${s//&/\\&}; s=${s//|/\\|}; printf '%s' "$s"; }

# 项目的 Host。旧档案没有这个字段：Workdir 在本机存在就算本机，否则为空（待定位）
host_of() {
  local h p; h="$(field "$1" Host)"
  if [ -n "$h" ]; then echo "$h"; return; fi
  for p in $(workdirs "$1"); do
    p="${p/#\~/$HOME}"; [ -d "$p" ] && { echo "$THIS_HOST"; return; }
  done
}

# 中心机上 hostname → FLEET 别名（由 sync 学到）
alias_of_host() {
  local f
  for f in "$ROOT"/.fleet/hosts/*/hostname; do
    [ -f "$f" ] && [ "$(cat "$f")" = "$1" ] && { basename "$(dirname "$f")"; return 0; }
  done
  return 1
}

host_label() {
  local h; h="$(host_of "$1")"
  [ -n "$h" ] || { echo "待定位"; return; }
  [ "$h" = "$THIS_HOST" ] && { echo "本机"; return; }
  alias_of_host "$h" || echo "$h"
}

# 某 slug 的 Workdir 是否包含当前目录
hits_cwd() {
  local p
  for p in $(workdirs "$1"); do
    p="${p/#\~/$HOME}"
    p="$(cd "$p" 2>/dev/null && pwd -P)" || continue
    case "$CWD/" in "$p"/*) return 0 ;; esac
  done
  return 1
}

# state.md「## 一句话概括」下第一行 = INDEX 的一句话
summary_of() { awk '/^## 一句话概括/{f=1;next} f&&/^## /{exit} f&&NF{print;exit}' "$ROOT/$1/state.md" 2>/dev/null; }

# set_summary <slug> <text> <replace|insert>：替换或在最前面插入那一行；没有这一节就补上
set_summary() {
  local f="$ROOT/$1/state.md" tmp
  [ -f "$f" ] || die "缺 $f"
  tmp="$(mktemp "$f.XXXX")"
  if grep -q '^## 一句话概括' "$f"; then
    S="$2" M="$3" awk '
      /^## 一句话概括/ { print; f=1; next }
      f && !done && /^## / { print ENVIRON["S"]; print ""; done=1 }
      f && !done && NF { print ENVIRON["S"]; done=1; if (ENVIRON["M"]=="replace") next }
      { print }
      END { if (f && !done) print ENVIRON["S"] }' "$f" > "$tmp"
  else
    S="$2" awk '
      !done && /^## / { print "## 一句话概括"; print ENVIRON["S"]; print ""; done=1 }
      { print }
      END { if (!done) { print ""; print "## 一句话概括"; print ENVIRON["S"] } }' "$f" > "$tmp"
  fi
  mv "$tmp" "$f"
}

# 最后更新：最后一次提交的日期（迁移提交不算）；只有迁移提交时取 journal 最后一条的日期
last_update() {
  local d="$ROOT/$1" u
  u="$(git -C "$d" log -1 --format=%as --invert-grep --grep='^migrate to 0\.4' 2>/dev/null)"
  [ -n "$u" ] || u="$(grep -oE '^## [0-9]{4}-[0-9]{2}-[0-9]{2}' "$d/journal.md" 2>/dev/null | tail -n1 | cut -c4-)"
  [ -n "$u" ] || u="$(date -r "$d/state.md" +%F 2>/dev/null)"
  echo "$u"
}

# Status 的状态值：「进行中 (探索期)」「进行中（…）」都算进行中
status_of() { field "$1" Status | sed -E 's/[[:space:]（(].*//'; }
status_rank() { case "$1" in 进行中) echo 1 ;; 暂停) echo 2 ;; 已完成) echo 3 ;; 已放弃) echo 4 ;; *) echo 5 ;; esac; }

# INDEX.md 是生成视图：名称/状态/Host 取 charter，日期取最后一次提交，一句话取 state
render_index() {
  [ -d "$ROOT" ] || return 0
  local d s st upd sum flag tmp
  tmp="$(mktemp "$ROOT/.INDEX.XXXX")"
  {
    printf '# 项目索引\n\n由 pt.sh 从各项目档案生成，不要手改。\n\n'
    printf '| Slug | 名称 | 状态 | 主机 | 最后更新 | 一句话 |\n|------|------|------|------|----------|--------|\n'
    for d in "$ROOT"/*/; do
      s="$(basename "$d")"
      [ -f "$d/charter.md" ] || continue
      st="$(field "$s" Status)"
      upd="$(last_update "$s")"
      sum="$(summary_of "$s")"; sum="${sum//|/／}"
      flag=""; [ -f "$ROOT/.fleet/forked/$s" ] && flag="⚠分叉 "
      printf '%s\t%s\t| %s | %s | %s | %s | %s | %s%s |\n' "$(status_rank "$(status_of "$s")")" "$upd" \
        "$s" "$(sed -n '1s/^# *//p' "$d/charter.md" | sed 's/|/／/g')" "$st" "$(host_label "$s")" "$upd" "$flag" "$sum"
    done | sort -t$'\t' -k1,1n -k2,2r | cut -f3-
  } > "$tmp" && mv "$tmp" "$ROOT/INDEX.md"
}

# 全局研究监控页 research.html：有研究项目（tree/）才写；失败只告警
render_monitor() {
  ls -d "$ROOT"/*/tree >/dev/null 2>&1 || return 0
  python3 "$HERE/monitor.py" "$ROOT" >/dev/null 2>&1 || echo "[warn] research.html 没生成（照常继续）：pt.sh monitor 看原因"
  return 0
}

# 多机部分（中心机的 sync / dispatch / runs）
. "$HERE/fleet.sh"

cmd_list() {
  [ -d "$ROOT" ] || die "没有 $ROOT（还没有任何项目）"
  if is_hub && [ "${1:-}" != --no-sync ] && [ -z "${PT_NO_SYNC:-}" ]; then
    fleet_sync -q --summary
  fi
  render_index
  cat "$ROOT/INDEX.md"
  echo
  local d s
  for d in "$ROOT"/*/; do
    s="$(basename "$d")"
    [ -f "$d/charter.md" ] && printf '  %-24s @%-14s Workdir: %s\n' "$s" "$(host_label "$s")" "$(field "$s" Workdir)"
  done
}

cmd_where() {
  local d s
  for d in "$ROOT"/*/; do
    s="$(basename "$d")"
    [ -f "$d/charter.md" ] || continue
    [ "$(status_of "$s")" = "进行中" ] || continue
    [ "$(host_of "$s")" = "$THIS_HOST" ] || continue
    hits_cwd "$s" && echo "$s"
  done
  return 0
}

cmd_brief() {
  local SLUG="$1" DIR="$ROOT/$1" MODE="${2:-}" h a=""
  # 中心机：远程项目先同步这一个；本机还没有的先全机队同步一次
  if is_hub; then
    [ -f "$DIR/charter.md" ] || fleet_sync -q >/dev/null 2>&1
    h="$(field "$SLUG" Host)"
    if [ -n "$h" ] && [ "$h" != "$THIS_HOST" ] && a="$(alias_of_host "$h")"; then
      fleet_sync_one "$a" "$SLUG" -q >/dev/null 2>&1
    fi
  fi
  [ -d "$DIR" ] || die "项目不存在: $DIR（先 pt.sh list）"
  printf '%s\n' "$SLUG" > "$ROOT/ACTIVE"
  bind_session "$SLUG"
  render_index

  echo "[project-tracker] 项目简报: $SLUG  ($DIR)"
  echo "只读写这个目录；其他项目的档案与本会话无关，不要打开。"
  h="$(host_of "$SLUG")"
  if [ "$h" != "$THIS_HOST" ]; then
    a="$(alias_of_host "$h" 2>/dev/null)"
    echo "Host: ${a:-?} (${h:-待定位}) —— 代码与硬件在那台机器上，Workdir 按那台机器解释；本机这份档案照常读写。"
    if is_hub && [ -n "$a" ]; then
      echo "轻活直接 ssh $a '<命令>'；重活、长跑或要那台机器的硬件，用 pt.sh dispatch $SLUG \"<任务>\" --wait 派它本机的 Claude。"
      echo "同步：$(fleet_host_status "$a")"
    fi
  fi
  if [ -f "$ROOT/.fleet/forked/$SLUG" ]; then
    a="$(cat "$ROOT/.fleet/forked/$SLUG")"
    echo "⚠ 与 $a 分叉：两边都有对方没有的提交。干活前先合并：git -C $DIR merge $a/main，"
    echo "  冲突按语义合（journal 两边条目都保留、state 重写成合并后的现状；tree.html 不用手合，pt index 会重新生成），提交后 pt.sh sync $a。"
  fi
  [ -f "$ROOT/.fleet/active/$SLUG" ] && echo "派活 $(cat "$ROOT/.fleet/active/$SLUG") 正在改这个项目：结束前不要 checkpoint（pt.sh runs $SLUG）。"

  section "INDEX 行"; grep -F "| $SLUG |" "$ROOT/INDEX.md" || echo "(INDEX 中没有此 slug)"
  section "charter.md"; cat "$DIR/charter.md" 2>/dev/null || echo "(缺失)"
  section "state.md";   cat "$DIR/state.md"   2>/dev/null || echo "(缺失)"
  [ -f "$DIR/verifier.md" ] && { section "verifier.md"; verifier_brief "$DIR/verifier.md"; }
  if [ -d "$DIR/tree" ]; then
    section "研究树（pt tree $SLUG；节点上下文 --ctx ID，已关分支 --all，全图 tree.html）"
    python3 "$HERE/tree.py" "$DIR" --no-html 2>&1 || echo "(tree.py 失败；直接读 $DIR/tree/)"
    if [ -f "$DIR/state.md" ] && awk '/^## (当前认识|别再试)/{f=1;next} /^## /{f=0} f&&NF&&!/^[-*]?[[:space:]]*无[[:space:]]*$/{x=1} END{exit !x}' "$DIR/state.md"; then
      echo "[warn] state.md 还有「当前认识」或「别再试」：研究项目这两节应在根节点（tree/ 根的 ## 当前认识 / ## 教训），state 不复写"
    fi
  elif [ -f "$DIR/experiments.md" ]; then
    section "experiments.md 末 15 行（全表读原文）"; tail -n 15 "$DIR/experiments.md"
  fi

  section "journal.md 最后 3 条"
  if [ -f "$DIR/journal.md" ]; then
    local TOTAL START
    TOTAL=$(grep -c '^## ' "$DIR/journal.md")
    START=$(grep -n '^## ' "$DIR/journal.md" | tail -n 3 | head -n 1 | cut -d: -f1)
    echo "(共 $TOTAL 条，本会话 session 号 = $((TOTAL + 1))，标题写 @$THIS_HOST)"
    [ -n "$START" ] && journal_tail "$DIR/journal.md" "$START"
  else
    echo "(缺失)"
  fi

  section "decisions.md 标题"
  grep -E '^## ADR-' "$DIR/decisions.md" 2>/dev/null || echo "(无 ADR)"

  section "plan.md"; cat "$DIR/plan.md" 2>/dev/null || echo "(缺失)"

  if [ -f "$DIR/state.md" ]; then
    local LINES BYTES; LINES=$(wc -l < "$DIR/state.md"); BYTES=$(wc -c < "$DIR/state.md")
    if [ "$LINES" -gt 100 ] || [ "$BYTES" -gt "$STATE_MAX_BYTES" ]; then
      printf '\n[warn] state.md %s 行 / %s 字节，超过 100 行或 %s 字节的上限，checkpoint 时压缩进 archive/\n' "$LINES" "$BYTES" "$STATE_MAX_BYTES"
    fi
  fi
  if [ -f "$DIR/journal.md" ]; then
    local LAST; LAST=$(awk '/^## /{n=0} {n+=length($0)+1} END{print n+0}' "$DIR/journal.md")
    [ "$LAST" -gt 12000 ] && printf '\n[warn] journal 最后一条 %s 字节：条目写增量，长回报与证据放产物文件只记路径\n' "$LAST"
  fi
  if [ "$MODE" = compact ]; then
    printf '\n[project-tracker] 上下文刚被压缩，以上是档案里的现状。压缩摘要里有、档案里还没有的进展，先 checkpoint（追加一条新的 journal，session 号见上），再接着做手上的事；不用向用户复述简报。\n'
  else
    printf '\n[project-tracker] 读完给用户 ≤5 行汇报：在哪 / 上次做了什么 / 下一步 / 卡在哪 / 待拍板项。\n'
  fi
}

# 考官卡：状态值（括号前那段）以「冻结」「已冻结」开头时只打印状态行与两节判据，其余读原文；「未冻结」「待冻结」不算
verifier_brief() {
  local st; st="$(grep -m1 'Status:' "$1" | sed 's/.*Status:[[:space:]]*//; s/[（(].*//')"
  case "$st" in
    冻结*|已冻结*) grep -m1 'Status:' "$1"
            awk '/^## /{f=($0 ~ /^## *(指标|判定依据)/)} f' "$1"
            printf '\n(考官已冻结：其余节读原文 %s)\n' "$1" ;;
    *)      cat "$1" ;;
  esac
}

cmd_tree() {
  local SLUG="${1:-}"; [ -n "$SLUG" ] || die "用法: pt.sh tree <slug> [--all | --ctx ID [--blind] | --next Q|H]"
  [[ "$SLUG" =~ $SLUG_RE ]] && [ -f "$ROOT/$SLUG/charter.md" ] || die "项目不存在: $SLUG"
  shift
  command -v python3 >/dev/null || die "pt tree 要 python3"
  python3 "$HERE/tree.py" "$ROOT/$SLUG" "$@"
}

cmd_auto() {
  [ -d "$ROOT" ] || exit 0
  hook_input
  local hits active bound src mode=""
  src="$(hook_field source)"; [ "$src" = compact ] && mode=compact
  bound="$(bound_slug)"
  hits="$(cmd_where)"
  # 压缩之后：会话绑过项目就重新注入那个项目，不管当前目录在哪
  if [ -n "$bound" ] && { [ -n "$mode" ] || printf '%s\n' "$hits" | grep -qx "$bound"; }; then
    cmd_brief "$bound" "$mode"; return
  fi
  [ -z "$hits" ] && exit 0
  active="$(head -n1 "$ROOT/ACTIVE" 2>/dev/null | tr -d '[:space:]')"
  if [ "$(printf '%s\n' "$hits" | wc -l)" -eq 1 ]; then
    cmd_brief "$hits" "$mode"
  elif [ -n "$active" ] && printf '%s\n' "$hits" | grep -qx "$active"; then
    cmd_brief "$active" "$mode"
  else
    echo "[project-tracker] 当前目录有多个进行中项目：$(printf '%s' "$hits" | tr '\n' ' ')"
    echo "未加载任何档案。用户说\"继续 <slug>\"后再跑 pt.sh brief <slug>。"
  fi
}

# PreCompact hook 的 stdout 会并进压缩指令：让摘要把还没入档的进展留下来，压缩后才补得了 checkpoint
cmd_precompact() {
  [ -d "$ROOT" ] || exit 0
  hook_input
  local slug hits
  slug="$(bound_slug)"
  if [ -z "$slug" ]; then
    hits="$(cmd_where)"
    [ -n "$hits" ] && [ "$(printf '%s\n' "$hits" | wc -l)" -eq 1 ] && slug="$hits"
  fi
  [ -n "$slug" ] || exit 0
  echo "本会话在做 project-tracker 项目 $slug（档案 $ROOT/$slug）。摘要里单列一节「未入档的进展」，写上次 checkpoint（pt.sh index）之后的：结果和证据（命令、数字、产物路径）、走不通的路和原因、做出的决定和用户原话、还在后台跑的任务和它的完成标记、下一步。压缩后要据此补 journal。"
  [ -d "$ROOT/$slug/tree" ] && echo "这个项目有研究树：摘要里另列改过 status/verdict 的节点、新建的节点（ID 与标题）、台账新增或回填的行（实验 id），压缩后据此补 tree/ 与 experiments.md。"
  return 0
}

cmd_new() {
  local SLUG="${1:-}" NAME="${2:-}" HOSTV="$THIS_HOST"
  [ -n "$SLUG" ] && [ -n "$NAME" ] || die "用法: pt.sh new <slug> \"<名称>\" [--host H] [workdir ...]"
  shift 2
  if [ "${1:-}" = --host ]; then
    [ -n "${2:-}" ] || die "--host 后面要跟主机名或 FLEET 别名"
    HOSTV="$2"; shift 2
    [ -f "$ROOT/.fleet/hosts/$HOSTV/hostname" ] && HOSTV="$(cat "$ROOT/.fleet/hosts/$HOSTV/hostname")"
    [ "$HOSTV" = "$THIS_HOST" ] || [ $# -gt 0 ] || die "项目在别的机器上时要写明 workdir（那台机器上的绝对路径）"
  fi
  [[ "$SLUG" =~ $SLUG_RE ]] || die "slug 只能是小写字母、数字、连字符: $SLUG"
  local DIR="$ROOT/$SLUG"
  [ -e "$DIR" ] && die "已存在: $DIR（改用 pt.sh brief $SLUG）"
  local WORKDIR="${*:-$CWD}"
  case "$NAME$WORKDIR$HOSTV" in *$'\n'*|*$'\r'*) die "名称、workdir、host 里不能有换行" ;; esac

  mkdir -p "$DIR/archive"
  touch "$DIR/archive/.keep"
  local f n w h
  n="$(sed_esc "$NAME")"; w="$(sed_esc "$WORKDIR")"; h="$(sed_esc "$HOSTV")"
  for f in charter plan state journal decisions; do
    sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{NAME}}|$n|g" -e "s|{{DATE}}|$TODAY|g" \
        -e "s|{{WORKDIR}}|$w|g" -e "s|{{HOST}}|$h|g" -e "s|{{THIS_HOST}}|$THIS_HOST|g" \
      "$TPL/$f.md" > "$DIR/$f.md" || { rm -rf "$DIR"; die "从模板生成 $f.md 失败（名称或 workdir 里有 sed 处理不了的字符？）"; }
  done
  commit_all "$DIR" "new @$THIS_HOST: $NAME" || die "git 提交失败: $DIR"
  render_index
  printf '%s\n' "$SLUG" > "$ROOT/ACTIVE"
  bind_session "$SLUG"

  echo "[project-tracker] 已建档: $DIR  (Host: $HOSTV  Workdir: $WORKDIR)"
  echo "下一步：把用户的回答填进 charter.md（目标/完成标准/不做/约束/验证），再写 plan.md。"
}

# 研究树档案根下的两个小配置：.ignore 让 ripgrep / Grep 跳过 tree.html，.gitattributes 让 git diff 不展开它。
# 缺哪行补哪行，已有的不动、不重复追加；打印新补的文件名
tree_dotfiles() {
  local d="$1" f line
  for f in .ignore .gitattributes; do
    case "$f" in .ignore) line='tree.html' ;; *) line='tree.html -diff' ;; esac
    grep -qxF "$line" "$d/$f" 2>/dev/null && continue
    [ -s "$d/$f" ] && [ -n "$(tail -c1 "$d/$f")" ] && printf '\n' >> "$d/$f"
    printf '%s\n' "$line" >> "$d/$f" && printf ' %s' "$f"
  done
}

cmd_research() {
  local SLUG="${1:-}"; [ -n "$SLUG" ] || die "用法: pt.sh research <slug>"
  local DIR="$ROOT/$SLUG"; [ -f "$DIR/charter.md" ] || die "项目不存在: $SLUG"
  local f added="" name
  for f in verifier experiments; do
    [ -f "$DIR/$f.md" ] && continue
    sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{DATE}}|$TODAY|g" "$TPL/$f.md" > "$DIR/$f.md"; added="$added $f.md"
  done
  # 没有 tree/，或 tree/ 里一个节点文件都没有：补根节点 Q1
  if ! ls "$DIR/tree" 2>/dev/null | grep -qE '^[QH][1-9][0-9]*\.md$'; then
    mkdir -p "$DIR/tree"
    name="$(sed -n '1s/^# *//p' "$DIR/charter.md")"
    sed -e "s|{{NAME}}|$(sed_esc "${name:-$SLUG}")|g" "$TPL/tree-root.md" > "$DIR/tree/Q1.md"; added="$added tree/Q1.md"
  fi
  added="$added$(tree_dotfiles "$DIR")"
  [ -n "$added" ] || { echo "[project-tracker] $SLUG 已有 verifier.md、experiments.md 与 tree/"; return 0; }
  commit_all "$DIR" "research @$THIS_HOST: 加$added" || die "git 提交失败: $DIR"
  local st; st="$(grep -m1 'Status:' "$DIR/verifier.md" | sed 's/.*Status:[[:space:]]*//; s/[（(].*//')"
  case "$st" in 冻结*|已冻结*) st="考官卡已冻结；" ;; *) st="先填 verifier.md（考官卡，用户确认后冻结）；" ;; esac
  echo "[project-tracker] 已加$added → $DIR。${st}实验一行一条记 experiments.md；问题与假设记在 tree/（格式见 tree/Q1.md 的注释，pt tree $SLUG 查看）。"
}

cmd_index() {
  local SLUG="${1:-}" SUMMARY="${2:-}" STATUS="${3:-}"
  [ -n "$SLUG" ] && [ -n "$SUMMARY" ] || die "用法: pt.sh index <slug> \"<一句话>\" [进行中|暂停|已完成|已放弃]（一句话进 state 与 INDEX，不是提交说明）"
  case "$SUMMARY" in *$'\n'*|*$'\r'*) die "一句话不能有换行（它写进 state.md「一句话概括」的一行，也是 INDEX 的一格）" ;; esac
  [ -n "${SUMMARY//[[:space:]]/}" ] || die "一句话不能是空白"
  [ -f "$ROOT/$SLUG/charter.md" ] || die "项目不存在: $SLUG"
  if [ -n "$STATUS" ]; then
    case "$STATUS" in 进行中|暂停|已完成|已放弃) ;; *) die "状态只能是 进行中|暂停|已完成|已放弃: $STATUS" ;; esac
  fi
  if fleet_run_active "$SLUG"; then
    die "派活 $(cat "$ROOT/.fleet/active/$SLUG") 正在改 $SLUG；等它结束（pt.sh runs $SLUG）再 checkpoint，否则会分叉"
  fi
  # 先查冲突再动文件，免得拒绝提交时 state 已经改了一半；tree.html 除外（下面会重新生成）
  local u; u="$(conflict_files "$ROOT/$SLUG" 2>/dev/null | grep -vx tree.html)"
  [ -z "$u" ] || die "$ROOT/$SLUG 有没合完的冲突（文件里还有 <<<<<<< / >>>>>>> 标记），先合并再 checkpoint：$(echo $u)"
  [ -n "$STATUS" ] && sed -i "s/^Status:.*/Status: $STATUS/" "$ROOT/$SLUG/charter.md"
  set_summary "$SLUG" "$SUMMARY" replace
  # 研究树：提交前重渲染 tree.html（派生物，随档案提交）；失败只告警
  if [ -d "$ROOT/$SLUG/tree" ]; then
    tree_dotfiles "$ROOT/$SLUG" >/dev/null
    python3 "$HERE/tree.py" "$ROOT/$SLUG" --render 2>&1 | sed 's/^/[project-tracker] /' ; [ "${PIPESTATUS[0]}" -eq 0 ] \
      || echo "[warn] tree.html 没渲染成（照常提交）：pt.sh tree $SLUG 看原因"
    # 合并冲突里的 tree.html 是派生物，刚重新渲染过，直接算合好了
    [ -n "$(git -C "$ROOT/$SLUG" ls-files -u -- tree.html 2>/dev/null)" ] && git -C "$ROOT/$SLUG" add tree.html
  fi
  commit_all "$ROOT/$SLUG" "checkpoint @$THIS_HOST: $SUMMARY" || die "git 提交失败: $ROOT/$SLUG"
  render_index
  [ -d "$ROOT/$SLUG/tree" ] && render_monitor
  echo "[project-tracker] 已提交: $SLUG | $(field "$SLUG" Status) | $TODAY | $SUMMARY"
}

cmd_migrate() {
  [ -d "$ROOT" ] || die "没有 $ROOT"
  mkdir -p "$ROOT/.backup"
  local bk="$ROOT/.backup/pre-0.4-$(date +%Y%m%d-%H%M%S).tgz"
  tar czf "$bk" -C "$ROOT" --exclude=./.backup . || die "备份失败"
  echo "[project-tracker] 已备份到 $bk"
  local oldindex=""
  [ -f "$ROOT/INDEX.md" ] && ! grep -q '| 主机 |' "$ROOT/INDEX.md" && oldindex="$ROOT/INDEX.md"
  local d s h row isum ist notes
  for d in "$ROOT"/*/; do
    s="$(basename "$d")"
    [ -f "$d/charter.md" ] || continue
    [[ "$s" =~ $SLUG_RE ]] || { echo "  跳过（slug 不合规）: $s"; continue; }
    notes=""
    if ! grep -q '^Host:' "$d/charter.md"; then
      h="$(host_of "$s")"
      [ -n "$h" ] || { h="待定位"; notes+="；Workdir 不在本机，Host 待定位，请手工改"; }
      if grep -q '^Workdir:' "$d/charter.md"; then sed -i "/^Workdir:/a Host: $h" "$d/charter.md"
      else sed -i "/^Slug:/a Host: $h" "$d/charter.md"; fi
    fi
    if [ -n "$oldindex" ]; then
      row="$(grep -F "| $s |" "$oldindex" | head -n1)"
      isum="$(awk -F'|' '{gsub(/^ +| +$/,"",$6); print $6}' <<<"$row")"
      ist="$(awk -F'|' '{gsub(/^ +| +$/,"",$4); print $4}' <<<"$row")"
      [ -n "$isum" ] && [ "$(summary_of "$s")" != "$isum" ] && set_summary "$s" "$isum" insert
      [ -n "$ist" ] && [ "$ist" != "$(field "$s" Status)" ] && notes+="；状态不一致 INDEX=$ist charter=$(field "$s" Status)，以 charter 为准"
    fi
    [ -d "$d/archive" ] || mkdir -p "$d/archive"
    [ -n "$(ls -A "$d/archive")" ] || touch "$d/archive/.keep"
    commit_all "$d" "migrate to 0.4 @$THIS_HOST" || notes+="；git 提交失败"
    echo "  $s: Host=$(field "$s" Host)$notes"
  done
  render_index
  echo "[project-tracker] 迁移完成，INDEX 已重建"
}

case "${1:-}" in
  list)     shift; cmd_list "$@" ;;
  where)    cmd_where ;;
  auto)     cmd_auto ;;
  precompact) cmd_precompact ;;
  brief)    [ -n "${2:-}" ] || die "用法: pt.sh brief <slug>"; cmd_brief "$2" ;;
  new)      shift; cmd_new "$@" ;;
  index)    shift; cmd_index "$@" ;;
  research) shift; cmd_research "$@" ;;
  tree)     shift; cmd_tree "$@" ;;
  migrate)  cmd_migrate ;;
  monitor)  shift; command -v python3 >/dev/null || die "pt monitor 要 python3"; python3 "$HERE/monitor.py" "$ROOT" "$@" ;;
  sync|dispatch|runs)
            is_hub || die "这台机器不是中心机（没有 $ROOT/FLEET）"
            c="$1"; shift; "fleet_$c" "$@" ;;
  *)        sed -n '2,20p' "$0"; exit 1 ;;
esac
