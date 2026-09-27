#!/usr/bin/env bash
# pt.sh — project-tracker 的入口脚本。档案根目录：${PROJECT_TRACKER_ROOT:-~/.claude/project}
#
#   pt.sh list [--no-sync]                     打印索引（中心机先同步全机队）
#   pt.sh where                                当前目录命中的、Host=本机的进行中项目（slug 一行一个）
#   pt.sh auto                                 SessionStart hook 用：命中 1 个→brief；多个→提示；0 个→静默
#   pt.sh brief <slug>                         按恢复顺序输出简报，并把 ACTIVE 设为该 slug
#   pt.sh new <slug> "<名称>" [--host H] [workdir ...]   建档（git 仓 + 首次提交）；workdir 默认当前目录
#   pt.sh index <slug> "<一句话>" [状态]       写一句话与状态、提交这次 checkpoint、重建 INDEX
#   pt.sh migrate                              把 0.3 及以前的档案升级到 0.4（先备份；幂等）
#   pt.sh sync [-q] [别名 ...]                 中心机：与节点同步（只快进；分叉只报告不合并）
#   pt.sh dispatch <slug> "<任务>" [--wait]    中心机：派项目 Host 上的 Claude 去干
#   pt.sh runs [slug | --wait <run>]           中心机：派活状态 / 等某次派活结束
#
# 隔离原则：任何子命令只读写一个 <slug>/ 目录；list 只读各项目 charter 字段与 state 的一句话。
set -u

ROOT="${PROJECT_TRACKER_ROOT:-$HOME/.claude/project}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="$HERE/../reference/templates"
CWD="$(cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null && pwd -P)"
TODAY="$(date +%F)"
THIS_HOST="${PT_HOSTNAME:-$(hostname -s)}"
SLUG_RE='^[a-z0-9]+(-[a-z0-9]+)*$'

die() { echo "pt.sh: $*" >&2; exit 1; }
section() { printf '\n===== %s =====\n' "$1"; }

# 读 charter 里的字段：field <slug> <Key>
field() { sed -n "s/^$2:[[:space:]]*//p" "$ROOT/$1/charter.md" 2>/dev/null | head -n1; }

# 档案 git 用固定身份，不依赖各机的 git 配置
g() { local d=$1; shift; git -C "$d" -c user.name=project-tracker -c user.email="pt@$THIS_HOST" -c commit.gpgsign=false "$@"; }

repo_init() {
  if [ ! -d "$1/.git" ]; then
    git init -q "$1" && git -C "$1" symbolic-ref HEAD refs/heads/main
  fi
  git -C "$1" config receive.denyCurrentBranch updateInstead
}

# commit_all <dir> <message>：有改动才提交
commit_all() {
  repo_init "$1" || return 1
  g "$1" add -A || return 1
  g "$1" diff --cached --quiet && return 0
  g "$1" commit -q -m "$2"
}

# 项目的 Host。旧档案没有这个字段：Workdir 在本机存在就算本机，否则为空（待定位）
host_of() {
  local h p; h="$(field "$1" Host)"
  if [ -n "$h" ]; then echo "$h"; return; fi
  for p in $(field "$1" Workdir); do
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
  alias_of_host "$h" || echo "$h"
}

# 某 slug 的 Workdir 是否包含当前目录
hits_cwd() {
  local p
  for p in $(field "$1" Workdir); do
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
      upd="$(git -C "$d" log -1 --format=%cs 2>/dev/null)"
      [ -n "$upd" ] || upd="$(date -r "$d/state.md" +%F 2>/dev/null)"
      sum="$(summary_of "$s")"; sum="${sum//|/／}"
      flag=""; [ -f "$ROOT/.fleet/forked/$s" ] && flag="⚠分叉 "
      printf '%s\t%s\t| %s | %s | %s | %s | %s | %s%s |\n' "$(status_rank "$st")" "$upd" \
        "$s" "$(sed -n '1s/^# *//p' "$d/charter.md")" "$st" "$(host_label "$s")" "$upd" "$flag" "$sum"
    done | sort -t$'\t' -k1,1n -k2,2r | cut -f3-
  } > "$tmp" && mv "$tmp" "$ROOT/INDEX.md"
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
    [ "$(field "$s" Status)" = "进行中" ] || continue
    [ "$(host_of "$s")" = "$THIS_HOST" ] || continue
    hits_cwd "$s" && echo "$s"
  done
  return 0
}

cmd_brief() {
  local SLUG="$1" DIR="$ROOT/$1" h a=""
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
    echo "  冲突按语义合（journal 两边条目都保留、state 重写成合并后的现状），提交后 pt.sh sync $a。"
  fi
  [ -f "$ROOT/.fleet/active/$SLUG" ] && echo "派活 $(cat "$ROOT/.fleet/active/$SLUG") 正在改这个项目：结束前不要 checkpoint（pt.sh runs $SLUG）。"

  section "INDEX 行"; grep -F "| $SLUG |" "$ROOT/INDEX.md" || echo "(INDEX 中没有此 slug)"
  section "charter.md"; cat "$DIR/charter.md" 2>/dev/null || echo "(缺失)"
  section "state.md";   cat "$DIR/state.md"   2>/dev/null || echo "(缺失)"

  section "journal.md 最后 3 条"
  if [ -f "$DIR/journal.md" ]; then
    local TOTAL START
    TOTAL=$(grep -c '^## ' "$DIR/journal.md")
    START=$(grep -n '^## ' "$DIR/journal.md" | tail -n 3 | head -n 1 | cut -d: -f1)
    echo "(共 $TOTAL 条，本会话 session 号 = $((TOTAL + 1))，标题写 @$THIS_HOST)"
    [ -n "$START" ] && tail -n +"$START" "$DIR/journal.md"
  else
    echo "(缺失)"
  fi

  section "decisions.md 标题"
  grep -E '^## ADR-' "$DIR/decisions.md" 2>/dev/null || echo "(无 ADR)"

  section "plan.md"; cat "$DIR/plan.md" 2>/dev/null || echo "(缺失)"

  if [ -f "$DIR/state.md" ]; then
    local LINES; LINES=$(wc -l < "$DIR/state.md")
    [ "$LINES" -gt 100 ] && printf '\n[warn] state.md %s 行，超过 100 行上限，checkpoint 时压缩进 archive/\n' "$LINES"
  fi
  printf '\n[project-tracker] 读完给用户 ≤5 行汇报：在哪 / 上次做了什么 / 下一步 / 卡在哪 / 待拍板项。\n'
}

cmd_auto() {
  [ -d "$ROOT" ] || exit 0
  local hits active
  hits="$(cmd_where)"
  [ -z "$hits" ] && exit 0
  active="$(head -n1 "$ROOT/ACTIVE" 2>/dev/null | tr -d '[:space:]')"
  if [ "$(printf '%s\n' "$hits" | wc -l)" -eq 1 ]; then
    cmd_brief "$hits"
  elif [ -n "$active" ] && printf '%s\n' "$hits" | grep -qx "$active"; then
    cmd_brief "$active"
  else
    echo "[project-tracker] 当前目录有多个进行中项目：$(printf '%s' "$hits" | tr '\n' ' ')"
    echo "未加载任何档案。用户说\"继续 <slug>\"后再跑 pt.sh brief <slug>。"
  fi
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

  mkdir -p "$DIR/archive"
  touch "$DIR/archive/.keep"
  local f
  for f in charter plan state journal decisions; do
    sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{NAME}}|$NAME|g" -e "s|{{DATE}}|$TODAY|g" \
        -e "s|{{WORKDIR}}|$WORKDIR|g" -e "s|{{HOST}}|$HOSTV|g" -e "s|{{THIS_HOST}}|$THIS_HOST|g" \
      "$TPL/$f.md" > "$DIR/$f.md"
  done
  commit_all "$DIR" "new @$THIS_HOST: $NAME" || die "git 提交失败: $DIR"
  render_index
  printf '%s\n' "$SLUG" > "$ROOT/ACTIVE"

  echo "[project-tracker] 已建档: $DIR  (Host: $HOSTV  Workdir: $WORKDIR)"
  echo "下一步：把用户的回答填进 charter.md（目标/完成标准/不做/约束/验证），再写 plan.md。"
}

cmd_index() {
  local SLUG="${1:-}" SUMMARY="${2:-}" STATUS="${3:-}"
  [ -n "$SLUG" ] && [ -n "$SUMMARY" ] || die "用法: pt.sh index <slug> \"<一句话>\" [进行中|暂停|已完成|已放弃]"
  [ -f "$ROOT/$SLUG/charter.md" ] || die "项目不存在: $SLUG"
  if [ -n "$STATUS" ]; then
    case "$STATUS" in 进行中|暂停|已完成|已放弃) ;; *) die "状态只能是 进行中|暂停|已完成|已放弃: $STATUS" ;; esac
  fi
  if fleet_run_active "$SLUG"; then
    die "派活 $(cat "$ROOT/.fleet/active/$SLUG") 正在改 $SLUG；等它结束（pt.sh runs $SLUG）再 checkpoint，否则会分叉"
  fi
  [ -n "$STATUS" ] && sed -i "s/^Status:.*/Status: $STATUS/" "$ROOT/$SLUG/charter.md"
  set_summary "$SLUG" "$SUMMARY" replace
  commit_all "$ROOT/$SLUG" "checkpoint @$THIS_HOST: $SUMMARY" || die "git 提交失败: $ROOT/$SLUG"
  render_index
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
  brief)    [ -n "${2:-}" ] || die "用法: pt.sh brief <slug>"; cmd_brief "$2" ;;
  new)      shift; cmd_new "$@" ;;
  index)    shift; cmd_index "$@" ;;
  migrate)  cmd_migrate ;;
  sync|dispatch|runs)
            is_hub || die "这台机器不是中心机（没有 $ROOT/FLEET）"
            c="$1"; shift; "fleet_$c" "$@" ;;
  *)        sed -n '2,15p' "$0"; exit 1 ;;
esac
