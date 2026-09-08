#!/usr/bin/env bash
# brief.sh [--if-active] [slug]
# 按恢复协议的顺序和裁剪量输出一个项目的简报：
#   INDEX 行 → charter 全文 → state 全文 → journal 最后 3 条 → decisions 标题 → plan 全文
# 无 slug 时读 .claude/project/ACTIVE。--if-active 且 ACTIVE 不存在则静默退出（供 SessionStart hook 用）。
# 传 list 列出 INDEX。
set -u

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/project"
IF_ACTIVE=0
SLUG=""
for a in "$@"; do
  case "$a" in
    --if-active) IF_ACTIVE=1 ;;
    *) SLUG="$a" ;;
  esac
done

if [ "$SLUG" = "list" ]; then
  [ -f "$ROOT/INDEX.md" ] && cat "$ROOT/INDEX.md" || echo "没有 $ROOT/INDEX.md"
  exit 0
fi

if [ -z "$SLUG" ]; then
  if [ -f "$ROOT/ACTIVE" ]; then
    SLUG="$(head -n1 "$ROOT/ACTIVE" | tr -d '[:space:]')"
  else
    [ "$IF_ACTIVE" = 1 ] && exit 0
    echo "用法: brief.sh [--if-active] <slug>|list  （或先写 $ROOT/ACTIVE）"
    exit 1
  fi
fi

DIR="$ROOT/$SLUG"
if [ ! -d "$DIR" ]; then
  [ "$IF_ACTIVE" = 1 ] && exit 0
  echo "项目目录不存在: $DIR"
  [ -f "$ROOT/INDEX.md" ] && { echo; cat "$ROOT/INDEX.md"; }
  exit 1
fi

section() { printf '\n===== %s =====\n' "$1"; }

echo "[project-tracker] 项目简报: $SLUG  ($DIR)"
[ -f "$ROOT/INDEX.md" ] && { section "INDEX 行"; grep -F "| $SLUG |" "$ROOT/INDEX.md" || echo "(INDEX 中没有此 slug)"; }

section "charter.md"; cat "$DIR/charter.md" 2>/dev/null || echo "(缺失)"
section "state.md";   cat "$DIR/state.md"   2>/dev/null || echo "(缺失)"

section "journal.md 最后 3 条"
if [ -f "$DIR/journal.md" ]; then
  TOTAL=$(grep -c '^## ' "$DIR/journal.md")
  START=$(grep -n '^## ' "$DIR/journal.md" | tail -n 3 | head -n 1 | cut -d: -f1)
  echo "(共 $TOTAL 条，下一条 session 号 = $((TOTAL + 1)))"
  [ -n "$START" ] && tail -n +"$START" "$DIR/journal.md"
else
  echo "(缺失)"
fi

section "decisions.md 标题"
grep -E '^## ADR-' "$DIR/decisions.md" 2>/dev/null || echo "(无 ADR)"
grep -E '^Status:' "$DIR/decisions.md" 2>/dev/null | sort | uniq -c | sed 's/^/  /'

section "plan.md"; cat "$DIR/plan.md" 2>/dev/null || echo "(缺失)"

if [ -f "$DIR/state.md" ]; then
  LINES=$(wc -l < "$DIR/state.md")
  [ "$LINES" -gt 100 ] && printf '\n[warn] state.md 有 %s 行，超过 100 行上限，checkpoint 时请压缩进 archive/\n' "$LINES"
fi
printf '\n[project-tracker] 读完后给用户 ≤5 行汇报：在哪 / 上次做了什么 / 下一步 / 卡在哪 / 待拍板项。\n'
