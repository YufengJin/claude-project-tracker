#!/usr/bin/env bash
# pt.sh — project-tracker 的唯一脚本。档案根目录全局固定：${PROJECT_TRACKER_ROOT:-~/.claude/project}
#
#   pt.sh list                                 打印 INDEX（每行附 Workdir）
#   pt.sh where                                当前目录命中的进行中项目（slug 一行一个）
#   pt.sh auto                                 SessionStart hook 用：命中 1 个→brief；多个→提示；0 个→静默
#   pt.sh brief <slug>                         按恢复顺序输出简报，并把 ACTIVE 设为该 slug
#   pt.sh new <slug> "<名称>" [workdir ...]    从模板建档、INDEX 加行、ACTIVE 指向；workdir 默认当前目录
#   pt.sh index <slug> "<一句话>" [状态]       更新 INDEX 的日期/一句话；给了状态则同步 charter 的 Status
#
# 隔离原则：任何子命令只读写一个 <slug>/ 目录；list 只读 INDEX。
set -u

ROOT="${PROJECT_TRACKER_ROOT:-$HOME/.claude/project}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="$HERE/../reference/templates"
CWD="$(cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null && pwd -P)"
TODAY="$(date +%F)"

die() { echo "pt.sh: $*" >&2; exit 1; }
section() { printf '\n===== %s =====\n' "$1"; }

# 读 charter 里的字段：field <slug> <Key>
field() { sed -n "s/^$2:[[:space:]]*//p" "$ROOT/$1/charter.md" 2>/dev/null | head -n1; }

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

cmd_list() {
  [ -f "$ROOT/INDEX.md" ] || die "没有 $ROOT/INDEX.md（还没有任何项目）"
  cat "$ROOT/INDEX.md"
  echo
  local d s
  for d in "$ROOT"/*/; do
    s="$(basename "$d")"
    [ -f "$d/charter.md" ] && printf '  %-24s Workdir: %s\n' "$s" "$(field "$s" Workdir)"
  done
}

cmd_where() {
  local d s
  for d in "$ROOT"/*/; do
    s="$(basename "$d")"
    [ -f "$d/charter.md" ] || continue
    [ "$(field "$s" Status)" = "进行中" ] || continue
    hits_cwd "$s" && echo "$s"
  done
  return 0
}

cmd_brief() {
  local SLUG="$1" DIR="$ROOT/$1"
  [ -d "$DIR" ] || die "项目不存在: $DIR（先 pt.sh list）"
  printf '%s\n' "$SLUG" > "$ROOT/ACTIVE"

  echo "[project-tracker] 项目简报: $SLUG  ($DIR)"
  echo "只读写这个目录；其他项目的档案与本会话无关，不要打开。"
  [ -f "$ROOT/INDEX.md" ] && { section "INDEX 行"; grep -F "| $SLUG |" "$ROOT/INDEX.md" || echo "(INDEX 中没有此 slug)"; }

  section "charter.md"; cat "$DIR/charter.md" 2>/dev/null || echo "(缺失)"
  section "state.md";   cat "$DIR/state.md"   2>/dev/null || echo "(缺失)"

  section "journal.md 最后 3 条"
  if [ -f "$DIR/journal.md" ]; then
    local TOTAL START
    TOTAL=$(grep -c '^## ' "$DIR/journal.md")
    START=$(grep -n '^## ' "$DIR/journal.md" | tail -n 3 | head -n 1 | cut -d: -f1)
    echo "(共 $TOTAL 条，本会话 session 号 = $((TOTAL + 1)))"
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
  local SLUG="${1:-}" NAME="${2:-}"
  [ -n "$SLUG" ] && [ -n "$NAME" ] || die "用法: pt.sh new <slug> \"<名称>\" [workdir ...]"
  shift 2
  [[ "$SLUG" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || die "slug 只能是小写字母、数字、连字符: $SLUG"
  local DIR="$ROOT/$SLUG"
  [ -e "$DIR" ] && die "已存在: $DIR（改用 pt.sh brief $SLUG）"
  local WORKDIR="${*:-$CWD}"

  mkdir -p "$DIR/archive"
  local f
  for f in charter plan state journal decisions; do
    sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{NAME}}|$NAME|g" -e "s|{{DATE}}|$TODAY|g" -e "s|{{WORKDIR}}|$WORKDIR|g" \
      "$TPL/$f.md" > "$DIR/$f.md"
  done

  if [ ! -f "$ROOT/INDEX.md" ]; then
    printf '# 项目索引\n\n| Slug | 名称 | 状态 | 最后更新 | 一句话 |\n|------|------|------|----------|--------|\n' > "$ROOT/INDEX.md"
  fi
  printf '| %s | %s | 进行中 | %s | 刚立项，charter 待补全 |\n' "$SLUG" "$NAME" "$TODAY" >> "$ROOT/INDEX.md"
  printf '%s\n' "$SLUG" > "$ROOT/ACTIVE"

  echo "[project-tracker] 已建档: $DIR  (Workdir: $WORKDIR)"
  echo "下一步：把用户的回答填进 charter.md（目标/完成标准/不做/约束/验证），再写 plan.md。"
}

cmd_index() {
  local SLUG="${1:-}" SUMMARY="${2:-}" STATUS="${3:-}"
  [ -n "$SLUG" ] && [ -n "$SUMMARY" ] || die "用法: pt.sh index <slug> \"<一句话>\" [进行中|暂停|已完成|已放弃]"
  [ -f "$ROOT/INDEX.md" ] || die "没有 INDEX.md"
  grep -qF "| $SLUG |" "$ROOT/INDEX.md" || die "INDEX 里没有 $SLUG"
  [ -z "$STATUS" ] && STATUS="$(grep -F "| $SLUG |" "$ROOT/INDEX.md" | awk -F'|' '{gsub(/^ +| +$/,"",$4); print $4}')"
  SUMMARY="${SUMMARY//|/／}"
  local NAME; NAME="$(grep -F "| $SLUG |" "$ROOT/INDEX.md" | awk -F'|' '{gsub(/^ +| +$/,"",$3); print $3}')"
  local TMP; TMP="$(mktemp)"
  awk -v s="$SLUG" -v row="| $SLUG | $NAME | $STATUS | $TODAY | $SUMMARY |" \
    -F'|' '{ k=$2; gsub(/^ +| +$/,"",k); if (k==s) print row; else print }' "$ROOT/INDEX.md" > "$TMP" && mv "$TMP" "$ROOT/INDEX.md"
  [ -n "${3:-}" ] && [ -f "$ROOT/$SLUG/charter.md" ] && sed -i "s/^Status:.*/Status: $STATUS/" "$ROOT/$SLUG/charter.md"
  echo "[project-tracker] INDEX 已更新: $SLUG | $STATUS | $TODAY | $SUMMARY"
}

case "${1:-}" in
  list)  cmd_list ;;
  where) cmd_where ;;
  auto)  cmd_auto ;;
  brief) [ -n "${2:-}" ] || die "用法: pt.sh brief <slug>"; cmd_brief "$2" ;;
  new)   shift; cmd_new "$@" ;;
  index) shift; cmd_index "$@" ;;
  *)     sed -n '2,12p' "$0"; exit 1 ;;
esac
