#!/usr/bin/env bash
# run.sh <model: opus|fable|codex>   — runs all scenarios sequentially for one model
set -u
S=$(cd "$(dirname "$0")" && pwd)
source "$S/scenarios.sh"
MODEL=$1
for sc in $SCENARIOS; do
  R="$S/runs/$MODEL-$sc"
  rm -rf "$R"; mkdir -p "$S/runs"; cp -a "$S/fixture" "$R"
  sed -i "s|{{WORKDIR}}|$R|" "$R/.claude/project/calc-fix/charter.md"
  git -C "$R" commit -qam "fixture workdir" 2>/dev/null
  export PROJECT_TRACKER_ROOT="$R/.claude/project"   # 全局根指向夹具，hook 和 pt.sh 都读它
  P="${PROMPT[$sc]}"
  start=$(date +%s)
  case $MODEL in
    opus)  MID=claude-opus-5 ;;
    fable) MID=claude-fable-5-1 ;;
  esac
  if [ "$MODEL" = codex ]; then
    (cd "$R" && timeout 900 codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --json -o "$R/last.md" "$P" > "$R/out.jsonl" 2> "$R/err.log"); rc=$?
  else
    (cd "$R" && timeout 900 claude -p "$P" --model "$MID" --dangerously-skip-permissions --no-session-persistence --output-format stream-json --verbose > "$R/out.jsonl" 2> "$R/err.log"); rc=$?
  fi
  end=$(date +%s)
  (cd "$R" && git status --short > changes.txt && git diff > diff.patch)
  echo "$MODEL $sc rc=$rc $((end-start))s changes=$(wc -l < "$R/changes.txt")" | tee -a "$S/runs/summary.txt"
done
