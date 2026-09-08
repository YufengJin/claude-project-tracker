#!/usr/bin/env bash
# eval.sh <run-dir>  — print evidence for one run
R=$1; cd "$R" || exit 1
name=$(basename "$R"); model=${name%%-*}; sc=${name#*-}
echo "################ $name"
if [ "$model" = codex ]; then
  echo "skill loaded : $(grep -c 'project-tracker/SKILL.md' out.jsonl) refs to SKILL.md"
  echo "brief.sh run : $(grep -c 'brief.sh' out.jsonl) refs"
  echo "--- final message"; cat last.md 2>/dev/null | head -40
else
  echo "Skill tool   : $(grep -o '"name":"Skill","input":{[^}]*}' out.jsonl | head -3)"
  echo "SKILL.md read: $(grep -c 'project-tracker/SKILL.md' out.jsonl) refs"
  echo "brief.sh run : $(grep -c 'brief.sh' out.jsonl) refs"
  echo "tools used   : $(grep -o '"name":"[A-Za-z]*","input"' out.jsonl | cut -d'"' -f4 | sort | uniq -c | tr '\n' ' ')"
  echo "--- final message"; python3 - <<'PY'
import json
last=None
for line in open('out.jsonl'):
    try: d=json.loads(line)
    except: continue
    if d.get('type')=='result': last=d
if last: print(last.get('result','')[:3000]); print('[cost]', last.get('total_cost_usd'), 'turns', last.get('num_turns'), 'dur', last.get('duration_ms'))
else: print('(no result event)')
PY
fi
echo "--- git changes"; cat changes.txt
echo "--- untracked files"; git ls-files --others --exclude-standard | head
case $sc in
  checkpoint)
    echo "--- tests now: $(.venv/bin/pytest tests/ -q 2>&1 | tail -1)"
    echo "--- journal entries: $(grep -c '^## ' .claude/project/calc-fix/journal.md); first 2 intact: $(git show HEAD:.claude/project/calc-fix/journal.md | diff - <(head -n $(git show HEAD:.claude/project/calc-fix/journal.md | wc -l) .claude/project/calc-fix/journal.md) >/dev/null && echo yes || echo NO)"
    echo "--- journal new entry:"; awk '/^## /{n++} n>=3' .claude/project/calc-fix/journal.md
    echo "--- state head:"; head -12 .claude/project/calc-fix/state.md
    echo "--- INDEX:"; grep calc-fix .claude/project/INDEX.md
    echo "--- charter checkboxes:"; grep -n '^- \[' .claude/project/calc-fix/charter.md
    echo "--- plan steps:"; grep -n '^- \[' .claude/project/calc-fix/plan.md
    echo "--- decisions diff:"; git diff --stat .claude/project/calc-fix/decisions.md
    ;;
  new)
    echo "--- ACTIVE: $(cat .claude/project/ACTIVE)"; echo "--- INDEX:"; cat .claude/project/INDEX.md
    for d in .claude/project/*/; do [ "$d" != .claude/project/calc-fix/ ] && { echo "--- new dir $d:"; ls "$d"; echo "--- journal:"; cat "$d/journal.md"; echo "--- charter:"; cat "$d/charter.md"; }; done
    ;;
  resume) echo "--- ACTIVE: $(cat .claude/project/ACTIVE)";;
esac
