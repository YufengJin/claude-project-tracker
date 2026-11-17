#!/usr/bin/env python3
"""serve.py — 把研究监控页 research.html 与各项目 tree.html 发到 tailnet 内（经 tailscale serve）。

  serve.py --root R [run] [--allow-local] [--port N]   前台起服务：只监听 127.0.0.1
  serve.py --root R install                            写并启用 systemd 用户单元 pt-serve.service，再配 tailscale serve
  serve.py --root R status                             服务、tailscale serve 状态与访问地址
  serve.py --root R uninstall                          撤掉 tailscale serve 配置与单元

配置是档案根下的 .serve.conf（本机文件，不进任何仓库），没有就拒绝启动：
  port=18443           本地监听端口（只在 127.0.0.1 上）
  https_port=8443      tailnet 内 HTTPS 端口（tailscale serve --https=）
  allow=a@x.com,b@y.com   允许的 Tailscale 登录名（tailscale serve 附加的 Tailscale-User-Login 头）

只服务 /（档案根下有合格的 site/ 时 302 到 /site/，没有时同 /research.html）、/research.html、/<slug>/tree.html（slug 是档案根下真实目录、含 tree/、不是符号链接、文件不逃出档案根），
以及给人看的站点 <档案根>/site/（pt site / pt monitor 生成，目录里要有 .pt-site 标记）：/site/、/site/index.html、
/site/p/<slug>.html（研究与工程项目都有）、/site/p/<slug>/<Q|H 编号或 J 条目编号>.html（slug 同样要是档案根下真实的项目目录，含 charter.md）；
其余 404；读只允许 GET / HEAD。唯一的写入口是 POST /api/rm（站点首页的「删除所选」）：正文 JSON
{"slugs": [...], "env": 是否连同环境与结果, "dry": 是否只预演}，原样转给 pt.sh rm [--env] [--dry-run]，回 {"ok", "out"}；
要求 Content-Type: application/json、头 X-PT: 1、Origin（有的话）与 Host 同名，挡跨站请求。
请求必须带白名单内的 Tailscale-User-Login 头，否则 403；
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
SITE_RE = re.compile(r"^/site/(?:(index\.html)?|p/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\.html|/([QH][1-9][0-9]{0,5}|J[0-9]{6}-[1-9][0-9]{0,3})\.html))$")
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
UNIT = "pt-serve.service"
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; "
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
        root = os.path.realpath(self.root)
        sm = SITE_RE.match(path)
        if sm:
            return self._resolve_site(root, sm)
        m = PATH_RE.match(path)
        if not m:
            return None
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

    @staticmethod
    def _resolve_site(root, m):
        site = os.path.join(root, "site")
        if os.path.islink(site) or not os.path.isfile(os.path.join(site, ".pt-site")):
            return None
        slug, nid = m.group(2), m.group(3)
        if slug is None:
            want = os.path.join(site, "index.html")
        else:
            d = os.path.join(root, slug)
            if os.path.islink(d) or not os.path.isfile(os.path.join(d, "charter.md")):
                return None  # 只发真实存在的项目的页
            want = os.path.join(site, "p", f"{slug}.html") if nid is None else os.path.join(site, "p", slug, f"{nid}.html")
        real = os.path.realpath(want)
        if real != want or not os.path.isfile(real):
            return None
        return real

    def _serve(self, body):
        if not self._identity_ok():
            return self.send_error(403)
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/" and self._resolve_site(os.path.realpath(self.root), SITE_RE.match("/site/")):
            self.send_response(302)  # 首页换成新站点；旧的 research.html 仍在 /research.html
            self.send_header("Location", "/site/")
            self.send_header("Content-Length", "0")
            return self.end_headers()
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

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/rm":
            return self._not_allowed()
        if not self._identity_ok():
            return self.send_error(403)
        origin = self.headers.get("Origin")
        if (self.headers.get("X-PT") != "1" or (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json"
                or (origin is not None and origin.split("://", 1)[-1] != self.headers.get("Host"))):
            return self.send_error(403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n)) if 0 < n <= 65536 else None
            slugs = req["slugs"]
            if not (isinstance(slugs, list) and 0 < len(slugs) <= 200 and all(isinstance(x, str) and SLUG_RE.match(x) for x in slugs)):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self.send_error(400)
        cmd = ["bash", os.path.join(os.path.dirname(os.path.realpath(__file__)), "pt.sh"), "rm"]
        cmd += ["--env"] if req.get("env") is True else []
        cmd += ["--dry-run"] if req.get("dry") is not False else []  # 没明说 dry=false 就只预演
        env = dict(os.environ, PROJECT_TRACKER_ROOT=self.root,
                   PATH=os.path.expanduser("~/.local/bin") + os.pathsep + os.environ.get("PATH", ""))
        try:
            p = subprocess.run(cmd + slugs, capture_output=True, text=True, timeout=900, env=env, stdin=subprocess.DEVNULL)
            ok, out = p.returncode == 0, p.stdout + p.stderr
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, out = False, str(e)
        sys.stderr.write(f"{self.headers.get('Tailscale-User-Login', '-')} rm {' '.join(cmd[3:] + slugs)} → {'ok' if ok else 'fail'}\n")
        self._json(200, {"ok": ok, "out": out})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _not_allowed


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
    ap = argparse.ArgumentParser(prog="pt serve", description="只读发布 research.html、tree.html 与 site/（tailnet 内）")
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
