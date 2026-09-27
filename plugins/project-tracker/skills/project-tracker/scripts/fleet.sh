# fleet.sh — 多机部分，由 pt.sh source。
# 中心机 = 有 $ROOT/FLEET 的机器（每行一个节点的 ssh 别名，# 后为注释）。只有中心机主动 ssh 到节点；
# 节点不需要能连回中心，也不需要新版插件（探测脚本自带）。
# 同步只快进：谁新听谁的；两边都有对方没有的提交（分叉）只标记、不合并，由 agent 按语义合。

FDIR="$ROOT/.fleet"
SSH_CMD="${PT_SSH:-ssh -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=10 -o ServerAliveCountMax=3}"
RROOT="${PT_REMOTE_ROOT:-.claude/project}"   # 节点上的档案根，相对节点 HOME
IDLE="${PT_IDLE:-1800}"                      # 节点未提交改动空闲这么久 → 代为提交
QUIET="${PT_QUIET:-900}"                     # 推给节点前要求它这么久没改过档案
TMUX_CMD="${PT_TMUX:-tmux}"

is_hub() { [ -f "$ROOT/FLEET" ]; }
fleet_aliases() { sed 's/#.*//' "$ROOT/FLEET" | awk 'NF{print $1}'; }
rssh() { local a=$1; shift; timeout "${PT_SSH_TIMEOUT:-90}" $SSH_CMD "$a" "$@"; }
gssh() { timeout 180 env GIT_SSH_COMMAND="${PT_GIT_SSH:-$SSH_CMD}" git "$@"; }
now() { date +%s; }
ago() {
  local t; t="$(cat "$1" 2>/dev/null)" || { echo "从未"; return; }
  t=$(( $(now) - t ))
  if [ $t -lt 120 ]; then echo "刚刚"; elif [ $t -lt 7200 ]; then echo "$((t/60)) 分钟前"
  elif [ $t -lt 172800 ]; then echo "$((t/3600)) 小时前"; else echo "$((t/86400)) 天前"; fi
}
fleet_host_status() {
  local a=$1
  if [ "$(cat "$FDIR/hosts/$a/last_ok" 2>/dev/null)" = "$(cat "$FDIR/hosts/$a/last_try" 2>/dev/null)" ]; then
    echo "$a 在线，$(ago "$FDIR/hosts/$a/last_ok")同步"
  else
    echo "$a 上次不可达；最后一次成功同步 $(ago "$FDIR/hosts/$a/last_ok")"
  fi
}

# 同步一个项目。参数来自探测：别名 slug 节点HEAD 节点未提交 节点空闲秒数 是否有派活在跑
sync_project() {
  local a=$1 s=$2 rh=$3 dirty=$4 age=$5 running=$6 L="$ROOT/$2" U="$1:$RROOT/$2" lh
  if [ "$rh" = none ]; then echo "  $s: $a 上还没有提交（正在写；空闲后会代为提交）"; return; fi
  if [ ! -d "$L" ]; then
    if gssh clone -q -o "$a" "$U" "$L" 2>/dev/null; then
      git -C "$L" config receive.denyCurrentBranch updateInstead
      echo "  $s: ↓ 新导入"
    else
      echo "  $s: 导入失败"
    fi
    return
  fi
  [ -d "$L/.git" ] || { echo "  $s: 中心副本不是 git 仓，先在中心跑 pt.sh migrate"; return; }
  git -C "$L" remote get-url "$a" >/dev/null 2>&1 || git -C "$L" remote add "$a" "$U"
  gssh -C "$L" fetch -q "$a" "+refs/heads/main:refs/remotes/$a/main" 2>/dev/null || { echo "  $s: fetch 失败"; return; }
  lh="$(git -C "$L" rev-parse -q --verify HEAD)"; rh="$(git -C "$L" rev-parse "$a/main")"
  [ "$lh" = "$rh" ] && { rm -f "$FDIR/forked/$s"; return; }
  if [ -z "$lh" ] || git -C "$L" merge-base --is-ancestor "$lh" "$rh"; then
    rm -f "$FDIR/forked/$s"
    if [ -n "$(git -C "$L" status --porcelain)" ]; then echo "  $s: 中心有未提交改动，本轮不快进"; return; fi
    git -C "$L" merge -q --ff-only "$a/main" && echo "  $s: ↓ 快进（$a 有新 checkpoint）" || echo "  $s: 快进失败"
  elif git -C "$L" merge-base --is-ancestor "$rh" "$lh"; then
    rm -f "$FDIR/forked/$s"
    if [ "$running" = 1 ]; then echo "  $s: 派活进行中，下轮再推"
    elif [ "$dirty" = 1 ]; then echo "  $s: $a 上有未提交改动，下轮再推"
    elif [ "$age" -lt "$QUIET" ]; then echo "  $s: $a 上 $((age/60)) 分钟前刚改过，下轮再推"
    elif gssh -C "$L" push -q "$a" HEAD:main 2>/dev/null; then echo "  $s: ↑ 推送到 $a"
    else echo "  $s: 推送被拒（$a 上正在写？），下轮再试"
    fi
  elif git -C "$L" merge-base "$lh" "$rh" >/dev/null; then
    echo "$a" > "$FDIR/forked/$s"
    echo "  $s: ⚠ 与 $a 分叉（两边都有新提交），未合并"
  else
    echo "  $s: ⚠ slug 冲突：$a 上的同名项目与中心副本没有共同历史，跳过"
  fi
}

# 中心上 Host=该节点、但从没同步过的项目（在中心立项、或档案原本就在中心）→ 在节点建仓并推送
seed_project() {
  local a=$1 s=$2 L="$ROOT/$2"
  [ -d "$L/.git" ] || { echo "  $s: 中心副本不是 git 仓，先在中心跑 pt.sh migrate"; return; }
  rssh "$a" "mkdir -p $RROOT/$s && cd $RROOT/$s && { [ -d .git ] || { git init -q . && git symbolic-ref HEAD refs/heads/main; }; } && git config receive.denyCurrentBranch updateInstead" \
    || { echo "  $s: 在 $a 上建仓失败"; return; }
  git -C "$L" remote add "$a" "$a:$RROOT/$s"
  gssh -C "$L" push -q "$a" HEAD:main 2>/dev/null && echo "  $s: ↑ 首次下发到 $a" || echo "  $s: 首次下发到 $a 失败"
}

# fleet_sync_host <别名> [slug]：探测一台节点并同步它的项目（可只同步一个）。调用方负责加锁
fleet_sync_host() {
  local a=$1 only=${2:-} out hn t s rh dirty age id rs st rc d seen=" " running
  mkdir -p "$FDIR/hosts/$a" "$FDIR/forked" "$FDIR/active" "$FDIR/runs"
  now > "$FDIR/hosts/$a/last_try"
  if ! out="$(rssh "$a" bash -s -- "$RROOT" "$IDLE" < "$HERE/probe.sh" 2>/dev/null)" || ! grep -q '^H ' <<<"$out"; then
    echo "$a: 不可达（最后一次成功同步 $(ago "$FDIR/hosts/$a/last_ok")）"
    return 1
  fi
  cp "$FDIR/hosts/$a/last_try" "$FDIR/hosts/$a/last_ok"
  hn="$(sed -n 's/^H //p' <<<"$out")"
  echo "$hn" > "$FDIR/hosts/$a/hostname"
  grep '^R ' <<<"$out" > "$FDIR/hosts/$a/runs"
  while read -r t id rs st rc; do
    [ "$st" != running ] && [ "$(cat "$FDIR/active/$rs" 2>/dev/null)" = "$id" ] && rm -f "$FDIR/active/$rs"
  done < "$FDIR/hosts/$a/runs"
  echo "$a: 在线（$hn）"
  while read -r t s rh dirty age; do
    [ "$t" = P ] || continue
    seen+="$s "
    [ -n "$only" ] && [ "$s" != "$only" ] && continue
    running=0; grep -q "^R [^ ]* $s running" "$FDIR/hosts/$a/runs" && running=1
    sync_project "$a" "$s" "$rh" "$dirty" "$age" "$running"
  done <<<"$out"
  for d in "$ROOT"/*/; do
    s="$(basename "$d")"
    [ -f "$d/charter.md" ] || continue
    [ -n "$only" ] && [ "$s" != "$only" ] && continue
    [[ "$seen" == *" $s "* ]] && continue
    [ "$(field "$s" Host)" = "$hn" ] || continue
    if git -C "$d" remote get-url "$a" >/dev/null 2>&1; then
      echo "  $s: $a 上已经没有这个项目（曾同步过，不自动重建）"
    else
      seed_project "$a" "$s"
    fi
  done
}

# 输出过滤：-q 只留有变化或有问题的行
_fleet_filter() { if [ "$1" = 1 ]; then grep -v ': 在线（' || true; else cat; fi; }

fleet_sync_one() {   # fleet_sync_one <别名> <slug> [-q]
  mkdir -p "$FDIR"
  exec 9>"$FDIR/sync.lock"
  flock -w 120 9 || { echo "另一个同步在跑，跳过"; return 1; }
  local out rc
  out="$(fleet_sync_host "$1" "$2")"; rc=$?
  _fleet_filter "$([ "${3:-}" = -q ] && echo 1)" <<<"$out"
  flock -u 9
  return $rc
}

fleet_sync() {       # fleet_sync [-q] [--summary] [别名 ...]
  local quiet=0 summary=0 a tmpd n=0 up=0
  while [ $# -gt 0 ]; do
    case "$1" in -q) quiet=1 ;; --summary) summary=1 ;; *) break ;; esac; shift
  done
  local list="$*"; [ -n "$list" ] || list="$(fleet_aliases)"
  mkdir -p "$FDIR"
  exec 9>"$FDIR/sync.lock"
  if ! flock -w "$([ $summary = 1 ] && echo 20 || echo 300)" 9; then
    echo "[project-tracker] 另一个同步在跑，显示的是上次同步的结果"; return 0
  fi
  tmpd="$(mktemp -d)"
  for a in $list; do ( fleet_sync_host "$a" > "$tmpd/$a" 2>&1 ) & done
  wait
  for a in $list; do
    n=$((n+1)); grep -q ': 在线（' "$tmpd/$a" && up=$((up+1))
    _fleet_filter "$quiet" < "$tmpd/$a"
  done
  rm -rf "$tmpd"
  flock -u 9
  render_index
  [ $summary = 1 ] && echo "[project-tracker] 已同步：$up/$n 台节点在线"
  return 0
}

# 派活是否仍在进行（中心上有占用标记且节点上它还没结束）。结束了就顺手清掉标记
fleet_run_active() {
  local f="$FDIR/active/$1" id st
  [ -f "$f" ] || return 1
  id="$(cat "$f")"
  st="$(fleet_run_state "$id")"
  case "$st" in running|unreachable|starting) return 0 ;; esac
  rm -f "$f"; return 1
}

# fleet_run_state <run>：running | starting | done <rc> | unknown | unreachable
fleet_run_state() {
  local id=$1 s a t0 out
  read -r s a t0 < "$FDIR/runs/$id" 2>/dev/null || { echo unknown; return; }
  out="$(rssh "$a" bash -s -- "$RROOT/.runs/$id" 2>/dev/null <<'EOF'
f="$HOME/$1/status"
[ -f "$f" ] || { echo missing; exit 0; }
rc=$(sed -n 's/^rc=//p' "$f"); pid=$(sed -n 's/^pid=//p' "$f")
if [ -n "$rc" ]; then echo "done $rc"
elif [ -n "$pid" ] && grep -qs run.sh "/proc/$pid/cmdline"; then echo running
else echo unknown; fi
EOF
)" || { echo unreachable; return; }
  if [ "$out" = missing ]; then
    [ $(( $(now) - t0 )) -lt 120 ] && echo starting || echo unknown
  else
    echo "$out"
  fi
}

fleet_dispatch() {
  local s="${1:-}" task="${2:-}" wait=0
  [ -n "$s" ] && [ -n "$task" ] || die "用法: pt.sh dispatch <slug> \"<任务>\" [--wait]"
  [ "${3:-}" = --wait ] && wait=1
  local L="$ROOT/$s" h a
  [ -f "$L/charter.md" ] || fleet_sync -q >/dev/null
  [ -f "$L/charter.md" ] || die "项目不存在: $s"
  h="$(field "$s" Host)"
  [ -n "$h" ] && [ "$h" != 待定位 ] || die "$s 的 charter 没有 Host，先写明项目在哪台机器"
  [ "$h" != "$THIS_HOST" ] || die "$s 的 Host 就是本机，直接在这里干，不用派"
  a="$(alias_of_host "$h")" || die "不知道 Host=$h 是 FLEET 里的哪个别名（先 pt.sh sync）"

  fleet_sync_one "$a" "$s" || die "同步 $a 失败，不派"
  [ -f "$FDIR/forked/$s" ] && die "$s 与 $a 分叉，先合并（pt.sh brief $s 有步骤）"
  fleet_run_active "$s" && die "已有派活 $(cat "$FDIR/active/$s") 在改 $s（pt.sh runs $s）"
  [ "$(git -C "$L" rev-parse HEAD)" = "$(git -C "$L" rev-parse "$a/main" 2>/dev/null)" ] \
    || die "$a 上的档案还没和中心一致（见上面的同步信息），稍后再派"

  local wd id rd tmp mode cw
  wd="$(field "$s" Workdir | awk '{print $1}')"
  id="$s-$(date +%Y%m%d-%H%M%S)-$(printf %04x $RANDOM)"
  rd="$RROOT/.runs/$id"
  mode="${PT_DISPATCH_MODE:-bypassPermissions}"
  tmp="$(mktemp -d)"
  cat > "$tmp/prompt.md" <<EOF
你是中心机（$THIS_HOST）派到本机的 agent，无人值守运行，run id: $id。

项目：$s。档案在 ~/$RROOT/$s/（project-tracker 格式）。

1. 先恢复上下文：按 project-tracker skill 的 resume 做（pt.sh brief $s），或依次读 charter.md、state.md、journal.md 最后 3 条、plan.md。
2. 只做这件事：
$task
3. 做完或做不下去时，按 project-tracker 的 checkpoint 写档案：journal 追加一条（标题带 @本机 hostname，Did 里写明 dispatched $id），重写 state，最后运行 pt.sh index $s "<一句话>"（它会提交）。
4. 需要人拍板、或风险超出上面这件事的操作，写进 state 的"下一步"和 charter 的 Open questions 后停止，不要猜。
5. 最后输出不超过三行的结果摘要。
EOF
  cat > "$tmp/run.sh" <<EOF
#!/usr/bin/env bash
RUN="\$(cd "\$(dirname "\$0")" && pwd)"
{ echo "slug=$s"; echo "pid=\$\$"; echo "start=\$(date +%s)"; } > "\$RUN/status"
CL="${PT_CLAUDE:-}"; [ -n "\$CL" ] || CL="\$(command -v claude 2>/dev/null || echo "\$HOME/.local/bin/claude")"
WD="$wd"; WD="\${WD/#\~/\$HOME}"; cd "\$WD" 2>/dev/null || cd "\$HOME"
export PROJECT_TRACKER_ROOT="\$HOME/$RROOT"
"\$CL" -p --permission-mode $mode < "\$RUN/prompt.md" > "\$RUN/out.log" 2> "\$RUN/err.log"
rc=\$?
# agent 没提交的（忘了 pt index，或节点插件太旧）在这里补提交：此刻没人在写
A="\$HOME/$RROOT/$s"
if [ -d "\$A/.git" ] && [ -n "\$(git -C "\$A" status --porcelain)" ]; then
  H=\$(hostname -s); git -C "\$A" add -A
  git -C "\$A" -c user.name=project-tracker -c user.email="pt@\$H" -c commit.gpgsign=false commit -q -m "dispatch $id @\$H: agent 未提交的改动"
fi
{ echo "rc=\$rc"; echo "end=\$(date +%s)"; } >> "\$RUN/status"
EOF

  cw="$(rssh "$a" 'for p in $(pgrep -x claude); do readlink /proc/$p/cwd; done' 2>/dev/null)"
  if [ -n "$wd" ] && [ "${wd#\~}" = "$wd" ] && awk -v w="$wd" 'index($0"/", w"/")==1{f=1} END{exit !f}' <<<"$cw"; then
    echo "[warn] $a 上有 Claude 会话的工作目录在 $wd 里；派出的 agent 会和它改同一份代码"
  fi
  rssh "$a" "mkdir -p $rd && cat > $rd/prompt.md" < "$tmp/prompt.md" \
    && rssh "$a" "cat > $rd/run.sh" < "$tmp/run.sh" || { rm -rf "$tmp"; die "把任务传到 $a 失败"; }
  rm -rf "$tmp"
  printf '%s %s %s\n' "$s" "$a" "$(now)" > "$FDIR/runs/$id"
  echo "$id" > "$FDIR/active/$s"
  rssh "$a" "$TMUX_CMD new-session -d -s pt-$id \"bash \$HOME/$rd/run.sh\"" \
    || { rm -f "$FDIR/active/$s"; die "在 $a 上启动 tmux 失败"; }
  echo "[project-tracker] 已派出 $id → $a:$wd（$mode）"
  echo "查看：pt.sh runs $s    等待：pt.sh runs --wait $id    节点上：tmux attach -t pt-$id"
  if [ $wait = 1 ]; then fleet_wait "$id"; return $?; fi
  return 0
}

fleet_wait() {
  local id=$1 s a t0 st pre deadline
  read -r s a t0 < "$FDIR/runs/$id" 2>/dev/null || die "没有这次派活: $id"
  pre="$(git -C "$ROOT/$s" rev-parse HEAD)"
  deadline=$(( $(now) + ${PT_WAIT_MAX:-43200} ))
  while :; do
    st="$(fleet_run_state "$id")"
    case "$st" in running|starting|unreachable) ;; *) break ;; esac
    [ "$(now)" -ge "$deadline" ] && { echo "[project-tracker] 等待超时，$id 仍在跑（$st）"; return 2; }
    sleep "${PT_WAIT_INTERVAL:-20}"
  done
  [ "$(cat "$FDIR/active/$s" 2>/dev/null)" = "$id" ] && rm -f "$FDIR/active/$s"
  fleet_sync_one "$a" "$s"
  echo "===== 派活 $id：$st ====="
  git -C "$ROOT/$s" log --format='%h %s' "$pre..HEAD"
  echo "--- 新增 journal ---"
  git -C "$ROOT/$s" diff "$pre..HEAD" -- journal.md | sed -n '/^+++/d; s/^+//p'
  echo "--- 输出尾 ---"
  rssh "$a" "tail -n 20 $RROOT/.runs/$id/out.log; tail -n 5 $RROOT/.runs/$id/err.log" 2>/dev/null
  [ "$st" = "done 0" ]
}

fleet_runs() {
  if [ "${1:-}" = --wait ]; then [ -n "${2:-}" ] || die "用法: pt.sh runs --wait <run>"; fleet_wait "$2"; return; fi
  local only=${1:-} id s a t0 st
  mkdir -p "$FDIR/runs"
  ls -t "$FDIR/runs" | head -n 20 | while read -r id; do
    read -r s a t0 < "$FDIR/runs/$id"
    [ -n "$only" ] && [ "$s" != "$only" ] && continue
    st="$(fleet_run_state "$id")"
    printf '%-48s %-10s %-12s %s\n' "$id" "$a" "$st" "$(date -d "@$t0" '+%m-%d %H:%M')"
    case "$st" in running|starting|unreachable) ;; *) [ "$(cat "$FDIR/active/$s" 2>/dev/null)" = "$id" ] && rm -f "$FDIR/active/$s" ;; esac
  done
  return 0
}
