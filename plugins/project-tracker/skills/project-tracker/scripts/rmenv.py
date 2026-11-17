#!/usr/bin/env python3
"""rmenv.py — pt rm --env 的后半：清掉项目在本机的环境与实验结果（档案本身由 pt.sh rm 打包删除）。

  rmenv.py <档案根> plan  <slug> [--gone a,b,c]    只打印会动什么
  rmenv.py <档案根> apply <slug> [--gone a,b,c]    照做

「环境与结果」只认 charter 的 Workdir 里列的目录（代码、worktree、scratch、结果都在里面），外加：
  · 记了这个 slug、还在跑的 fleet 任务：停掉
  · 挂载了这些目录的 docker 容器：docker rm -f（镜像不动）
  · 目录本身：挪进同一层的 .pt-trash/<slug>-<时间>/（同一文件系统，瞬间完成，可原样挪回；腾盘要手工删 .pt-trash）
不动的目录各说一句原因：别的还在的项目也在用（相同或互相包含）、还挂着别的 worktree 的 git 主仓、
家目录或它的上层、挂载点、包着档案根的、不在本机的（Host 不是本机）。--gone 是同一批里一起删的 slug，不算「还在的项目」。
只用标准库。
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

CUT = re.compile(r"(（|\(|；|;|，|,).*")


def field(root, slug, key):
    try:
        with open(os.path.join(root, slug, "charter.md"), encoding="utf-8") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return line[len(key) + 1:].strip()
    except OSError:
        pass
    return ""


def workdirs(root, slug):
    """与 pt.sh 的 workdirs 同法：按空格切，砍掉括注，只留 ~ 或 / 开头的。"""
    out = []
    for tok in field(root, slug, "Workdir").split():
        tok = CUT.sub("", tok)
        if tok[:1] in ("~", "/"):
            p = os.path.realpath(os.path.expanduser(tok))
            if p not in out:
                out.append(p)
    return out


def sh(*cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def inside(a, b):
    """a 等于 b 或在 b 里面。"""
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def why_keep(path, root, others):
    home = os.path.realpath(os.path.expanduser("~"))
    if not os.path.isdir(path):
        return "本机没有这个目录"
    if inside(home, path):
        return "是家目录或它的上层"
    if inside(os.path.realpath(root), path):
        return "包着档案根"
    if os.path.ismount(path):
        return "是挂载点"
    for slug, ps in others.items():
        if any(inside(path, p) or inside(p, path) for p in ps):
            return f"项目 {slug} 也在用"
    if os.path.isdir(os.path.join(path, ".git")):
        rc, out = sh("git", "-C", path, "worktree", "list", "--porcelain")
        if rc == 0 and out.count("\nworktree ") >= 1:
            return "git 主仓，还挂着别的 worktree"
    return ""


def fleet_jobs(slug):
    jd = os.environ.get("PT_FLEET_JOBS") or os.path.expanduser("~/.fleet/jobs")
    out = []
    if not os.path.isdir(jd):
        return out
    for n in sorted(os.listdir(jd)):
        p = os.path.join(jd, n)
        try:
            with open(os.path.join(p, "slug"), encoding="utf-8") as f:
                if f.read().strip() != slug:
                    continue
        except OSError:
            continue
        if os.path.exists(os.path.join(p, "exit")):
            continue
        if sh("systemctl", "--user", "is-active", "-q", f"fleet-{n}")[0] == 0:
            out.append(n)
    return out


def containers(paths):
    """挂载了 paths 里任一目录（或其子目录）的容器：[(名字, 状态)]。没装 docker 就是空。"""
    if not paths or not shutil.which("docker"):
        return []
    rc, ids = sh("docker", "ps", "-aq")
    if rc or not ids:
        return []
    rc, out = sh("docker", "inspect", *ids.split())
    try:
        data = json.loads(out) if rc == 0 else []
    except ValueError:
        data = []
    hit = []
    for c in data:
        srcs = [os.path.realpath(m.get("Source") or "/nonexistent") for m in c.get("Mounts") or []]
        if any(inside(s, p) for s in srcs for p in paths):
            hit.append((c.get("Name", "").lstrip("/"), (c.get("State") or {}).get("Status", "?")))
    return hit


def main(argv):
    if len(argv) < 3 or argv[1] not in ("plan", "apply"):
        sys.exit(__doc__)
    root, mode, slug = os.path.abspath(argv[0]), argv[1], argv[2]
    gone = {slug}
    if "--gone" in argv:
        gone |= set(argv[argv.index("--gone") + 1].split(","))
    do = mode == "apply"
    will = "" if do else "会"
    host = field(root, slug, "Host")
    this = os.environ.get("PT_HOSTNAME") or socket.gethostname().split(".")[0]
    if host and host != this:
        print(f"    环境与结果在 {host} 上，本机不动")
        return 0
    others = {s: workdirs(root, s) for s in sorted(os.listdir(root))
              if s not in gone and os.path.isfile(os.path.join(root, s, "charter.md"))}
    move, rc = [], 0
    for p in workdirs(root, slug):
        w = why_keep(p, root, others)
        if w:
            print(f"    不动 {p}：{w}")
        else:
            move.append(p)
    for n in fleet_jobs(slug):
        if do:
            cmd = ("fleet", "kill", n) if shutil.which("fleet") else ("systemctl", "--user", "stop", f"fleet-{n}")
            r, out = sh(*cmd)
            rc |= r != 0
            print(f"    停任务 {n}" + ("" if r == 0 else f" 失败：{out[-200:]}"))
        else:
            print(f"    会停任务 {n}")
    for name, st in containers(move):
        if do:
            r, out = sh("docker", "rm", "-f", name)
            rc |= r != 0
            print(f"    删容器 {name}" + ("" if r == 0 else f" 失败：{out[-200:]}"))
        else:
            print(f"    会删容器 {name}（{st}）")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for p in move:
        dst = os.path.join(os.path.dirname(p), ".pt-trash", f"{slug}-{stamp}", os.path.basename(p))
        if do:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(p, dst)
                print(f"    已挪走 {p} → {dst}")
            except OSError as e:
                rc = 1
                print(f"    没挪动 {p}：{e}")
        else:
            print(f"    会挪走 {p} → {os.path.dirname(dst)}/")
    if not move:
        print(f"    没有{will}要挪的目录")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
