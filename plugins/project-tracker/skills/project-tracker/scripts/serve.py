#!/usr/bin/env python3
"""serve.py — 只读地把研究监控页 research.html 与各项目 tree.html 发到 tailnet 内（经 tailscale serve）。

  serve.py --root R [run] [--allow-local] [--port N]   前台起服务：只监听 127.0.0.1
  serve.py --root R install                            写并启用 systemd 用户单元 pt-serve.service，再配 tailscale serve
  serve.py --root R status                             服务、tailscale serve 状态与访问地址
  serve.py --root R uninstall                          撤掉 tailscale serve 配置与单元

配置是档案根下的 .serve.conf（本机文件，不进任何仓库），没有就拒绝启动：
  port=18443           本地监听端口（只在 127.0.0.1 上）
  https_port=8443      tailnet 内 HTTPS 端口（tailscale serve --https=）
  allow=a@x.com,b@y.com   允许的 Tailscale 登录名（tailscale serve 附加的 Tailscale-User-Login 头）

只服务 /、/research.html、/<slug>/tree.html（slug 是档案根下真实目录、含 tree/、不是符号链接、文件不逃出档案根），
其余 404；只允许 GET / HEAD。请求必须带白名单内的 Tailscale-User-Login 头，否则 403；
--allow-local 只给本机调试：没有身份头的请求也放行。只用标准库。
"""
import argparse
import http.server
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PATH_RE = re.compile(r"^/(?:(research\.html)|([a-z0-9]+(?:-[a-z0-9]+)*)/tree\.html)?$")
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
UNIT = "pt-serve.service"
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SEC_HEADERS = (("Cache-Control", "no-cache"), ("X-Content-Type-Options", "nosniff"),
               ("Content-Security-Policy", CSP), ("Referrer-Policy", "no-referrer"),
               ("X-Frame-Options", "DENY"))


def die(msg, code=2):
    print(f"pt serve: {msg}", file=sys.stderr)
    sys.exit(code)


def load_conf(root):
    path = os.path.join(root, ".serve.conf")
    if not os.path.isfile(path):
        die(f"没有 {path}，拒绝启动。先写这个本机文件（不进任何仓库），例如：\n"
            "  port=18443\n  https_port=8443\n  allow=you@example.com")
    conf = {"port": 18443, "https_port": 8443, "allow": set()}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, sep, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if not sep or k not in conf:
                die(f"{path}:{n} 看不懂：{line}（只认 port= https_port= allow=）")
            if k == "allow":
                conf["allow"] |= {a.strip().lower() for a in v.split(",") if a.strip()}
            else:
                if not v.isdigit() or not 0 < int(v) < 65536:
                    die(f"{path}:{n} 端口不对：{v}")
                conf[k] = int(v)
    return conf


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "pt-serve"
    sys_version = ""
    root = ""
    allow = frozenset()
    allow_local = False

    def end_headers(self):
        for k, v in SEC_HEADERS:
            self.send_header(k, v)
        super().end_headers()

    def log_message(self, fmt, *args):
        who = self.headers.get("Tailscale-User-Login", "-") if getattr(self, "headers", None) else "-"
        sys.stderr.write(f"{who} {fmt % args}\n")

    def _identity_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if host not in LOCAL_HOSTS and not host.endswith(".ts.net"):
            return False  # 防 DNS rebinding：只认本机名与 tailnet 名
        login = self.headers.get("Tailscale-User-Login")
        if login is None:
            return self.allow_local
        return login.strip().lower() in self.allow

    def _resolve(self):
        """把请求路径映射到档案根里的文件；不合规返回 None（→404）。不做任何 URL 解码。"""
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        m = PATH_RE.match(path)
        if not m:
            return None
        root = os.path.realpath(self.root)
        slug = m.group(2)
        if slug is None:
            want = os.path.join(root, "research.html")
        else:
            d = os.path.join(root, slug)
            if os.path.islink(d) or not os.path.isdir(d) or not os.path.isdir(os.path.join(d, "tree")):
                return None
            want = os.path.join(d, "tree.html")
        real = os.path.realpath(want)
        if real != want or not os.path.isfile(real):
            return None  # 符号链接（逃逸或不逃逸都不跟）
        return real

    def _serve(self, body):
        if not self._identity_ok():
            return self.send_error(403)
        f = self._resolve()
        if f is None:
            return self.send_error(404)
        try:
            with open(f, "rb") as fh:
                data = fh.read()
        except OSError:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def _not_allowed(self):
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _not_allowed


def cmd_run(root, conf, args):
    if not conf["allow"] and not args.allow_local:
        die(".serve.conf 的 allow= 是空的，没有人能访问；写上允许的登录名（或本机调试加 --allow-local）")
    Handler.root, Handler.allow, Handler.allow_local = root, frozenset(conf["allow"]), args.allow_local
    port = conf["port"] if args.port is None else args.port
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"listening on 127.0.0.1:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def sh(*cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: 没装"
    return p.returncode, (p.stdout + p.stderr).strip()


def unit_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user", UNIT)


def exec_start(root):
    me = os.path.realpath(__file__)
    cache = os.path.realpath(os.path.expanduser("~/.claude/plugins/cache/project-tracker/project-tracker"))
    r = shlex.quote(root)
    if me.startswith(cache + os.sep):
        # 插件更新后路径会变：每次启动取缓存里最新版本（与 pt-sync.service 同法）
        glob = "%h/.claude/plugins/cache/project-tracker/project-tracker/*/skills/project-tracker/scripts/serve.py"
        return f"/bin/bash -c 'exec python3 \"$(ls -d {glob} | sort -V | tail -n1)\" --root {r} run'"
    return f"{shutil.which('python3') or '/usr/bin/python3'} {shlex.quote(me)} --root {r} run"


def ts_url(https_port):
    rc, out = sh("tailscale", "status", "--self", "--json")
    try:
        name = json.loads(out)["Self"]["DNSName"].rstrip(".") if rc == 0 else ""
    except (ValueError, KeyError):
        name = ""
    return f"https://{name}:{https_port}/" if name else f"https://<本机 MagicDNS 名>:{https_port}/"


def linger_hint():
    user = os.environ.get("USER") or ""
    rc, out = sh("loginctl", "show-user", user, "-p", "Linger")
    if rc == 0 and out.strip() == "Linger=no":
        print(f"[提示] 没开 linger：没登录时用户单元不跑、开机不自启。需要的话执行：sudo loginctl enable-linger {user}")


def cmd_install(root, conf):
    if not conf["allow"]:
        die(".serve.conf 的 allow= 是空的，装了也没人能访问")
    os.makedirs(os.path.dirname(unit_path()), exist_ok=True)
    with open(unit_path(), "w", encoding="utf-8") as f:
        f.write("[Unit]\nDescription=project-tracker: 只读研究监控页（127.0.0.1，经 tailscale serve）\n\n"
                f"[Service]\nExecStart={exec_start(root)}\nRestart=on-failure\nRestartSec=5\n\n"
                "[Install]\nWantedBy=default.target\n")
    for cmd in (("systemctl", "--user", "daemon-reload"), ("systemctl", "--user", "enable", UNIT),
                ("systemctl", "--user", "restart", UNIT)):
        rc, out = sh(*cmd)
        if rc:
            die(f"{' '.join(cmd)} 失败：{out}")
    print(f"[ok] {UNIT} 已启用并启动（127.0.0.1:{conf['port']}）")
    target = f"http://127.0.0.1:{conf['port']}"
    rc, out = sh("tailscale", "serve", "--bg", f"--https={conf['https_port']}", target)
    if rc:
        low = out.lower()
        if "denied" in low or "permission" in low or "operator" in low:
            user = os.environ.get("USER") or "$USER"
            die(f"tailscale serve 被拒（权限）：{out}\n请执行：sudo tailscale set --operator={user}\n然后重跑：pt serve install", 3)
        die(f"tailscale serve 失败：{out}", 3)
    print(f"[ok] tailscale serve --https={conf['https_port']} → {target}")
    print(f"访问地址（只在 tailnet 内）：{ts_url(conf['https_port'])}")
    linger_hint()


def cmd_status(root, conf):
    rc, act = sh("systemctl", "--user", "is-active", UNIT)
    _, en = sh("systemctl", "--user", "is-enabled", UNIT)
    print(f"{UNIT}: {act or '-'}（{en or '-'}），本地 127.0.0.1:{conf['port']}，允许 {len(conf['allow'])} 个登录名")
    rc, out = sh("tailscale", "serve", "status")
    print("tailscale serve:\n  " + (out or "-").replace("\n", "\n  "))
    print(f"访问地址：{ts_url(conf['https_port'])}")
    linger_hint()


def cmd_uninstall(root, conf):
    rc, out = sh("tailscale", "serve", f"--https={conf['https_port']}", "off")
    print(f"[{'ok' if rc == 0 else 'warn'}] tailscale serve --https={conf['https_port']} off" + ("" if rc == 0 else f"：{out}"))
    sh("systemctl", "--user", "disable", "--now", UNIT)
    if os.path.exists(unit_path()):
        os.remove(unit_path())
    sh("systemctl", "--user", "daemon-reload")
    print(f"[ok] {UNIT} 已停用并删除")


def main(argv):
    ap = argparse.ArgumentParser(prog="pt serve", description="只读发布 research.html 与 tree.html（tailnet 内）")
    ap.add_argument("--root", default=os.environ.get("PROJECT_TRACKER_ROOT") or os.path.expanduser("~/.claude/project"))
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "install", "status", "uninstall"))
    ap.add_argument("--allow-local", action="store_true", help="本机调试：没有 Tailscale-User-Login 头的请求也放行")
    ap.add_argument("--port", type=int, help="覆盖本地端口（0 = 随机，测试用）")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        die(f"没有档案根 {root}")
    conf = load_conf(root)
    if args.cmd == "run":
        return cmd_run(root, conf, args)
    if args.allow_local or args.port is not None:
        die("--allow-local / --port 只用于 run（常驻服务按 .serve.conf 跑）")
    {"install": cmd_install, "status": cmd_status, "uninstall": cmd_uninstall}[args.cmd](root, conf)


if __name__ == "__main__":
    main(sys.argv[1:])
