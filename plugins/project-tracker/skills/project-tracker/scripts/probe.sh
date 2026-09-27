# probe.sh — 中心机经 ssh 在节点上跑：bash -s -- <档案根(相对 HOME，或绝对路径)> <空闲秒数>
# 中心机也对自己的档案根跑一遍（兜住旧版会话和忘了 checkpoint 的改动）。
# 不依赖节点上的插件版本，只要 git。输出一行一条：
#   H <hostname>
#   P <slug> <HEAD|none> <未提交 0/1> <距最近修改的秒数>
#   R <run id> <slug> <running|done|unknown> <rc|->
# 未提交改动空闲超过阈值（忘了 checkpoint，或旧版插件根本不提交）时代为提交；正在写的不碰。
case "${1:-}" in /*) R="$1" ;; *) R="$HOME/${1:-.claude/project}" ;; esac
IDLE="${2:-1800}"
H="${PT_HOSTNAME:-$(hostname -s)}"
echo "H $H"
[ -d "$R" ] || exit 0
now=$(date +%s)
g() { local d=$1; shift; git -C "$d" -c user.name=project-tracker -c user.email="pt@$H" -c commit.gpgsign=false "$@"; }

for d in "$R"/*/; do
  d="${d%/}"; s="${d##*/}"
  [ -f "$d/charter.md" ] || continue
  [[ "$s" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || continue
  newest=$(find "$d" -path "$d/.git" -prune -o -type f -printf '%T@\n' | sort -n | tail -n1)
  newest=${newest%.*}; age=$(( now - ${newest:-0} ))
  dirty=1
  if [ -d "$d/.git" ]; then
    git -C "$d" config receive.denyCurrentBranch updateInstead
    [ -z "$(git -C "$d" status --porcelain 2>/dev/null)" ] && dirty=0
  fi
  if [ "$dirty" = 1 ] && [ "$age" -ge "$IDLE" ] && [ ! -f "$d/.git/MERGE_HEAD" ]; then
    if [ ! -d "$d/.git" ]; then
      git init -q "$d" && git -C "$d" symbolic-ref HEAD refs/heads/main && git -C "$d" config receive.denyCurrentBranch updateInstead
    fi
    if ! grep -q '^Host:' "$d/charter.md"; then
      for p in $(sed -n 's/^Workdir:[[:space:]]*//p' "$d/charter.md" | head -n1 | tr ' ' '\n' | sed -E 's/(（|\(|；|;|，|,).*//' | grep -E '^[~/]'); do
        p="${p/#\~/$HOME}"
        [ -d "$p" ] && { sed -i "/^Workdir:/a Host: $H" "$d/charter.md"; break; }
      done
    fi
    g "$d" add -A && g "$d" commit -q -m "autosync @$H (idle)" >/dev/null 2>&1
    [ -z "$(git -C "$d" status --porcelain 2>/dev/null)" ] && dirty=0
  fi
  head=$(git -C "$d" rev-parse -q --verify HEAD 2>/dev/null || echo none)
  echo "P $s $head $dirty $age"
done

for f in "$R"/.runs/*/status; do
  [ -f "$f" ] || continue
  id=$(basename "$(dirname "$f")")
  slug=$(sed -n 's/^slug=//p' "$f"); rc=$(sed -n 's/^rc=//p' "$f"); pid=$(sed -n 's/^pid=//p' "$f")
  if [ -n "$rc" ]; then st=done
  elif [ -n "$pid" ] && grep -qs run.sh "/proc/$pid/cmdline"; then st=running
  else st=unknown; fi
  echo "R $id $slug $st ${rc:--}"
done
