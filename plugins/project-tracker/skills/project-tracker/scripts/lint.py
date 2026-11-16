#!/usr/bin/env python3
"""lint.py — 档案体检：只读、只报告，不改任何文件，退出码恒为 0。

  lint.py --root R --host H --state-max-bytes N --state-max-lines N (--all | <slug> ...)

每条发现一行：<slug>: <检查名>: <一句话>；--all 末尾给各检查的计数。只用标准库。
"""
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree  # noqa: E402  研究树节点的解析与 pt tree 同一套

CHECKS = ("state-stale", "pending-stale", "template", "journal-size", "state-size",
          "host", "workdir-missing", "no-focus", "tree-root-size", "tree-node-size")
STATE_LAG_DAYS = 2          # state 的 Updated 比 journal 最新条目早这么多天及以上
PENDING_DAYS = 7            # 待拍板 / 等用户 里的日期超过这么多天
JOURNAL_MAX = 100 * 1024
ROOT_KNOW_MAX = 6 * 1024    # 根节点「当前认识」+「教训」
NODE_MAX = 5 * 1024
PENDING_HEAD = re.compile(r"^##\s.*(待拍板|等用户|待用户)")
FOCUS_HEAD = re.compile(r"^##\s.*(焦点|研究树|现在在哪)")
NEXT_HEAD = re.compile(r"^##\s.*下一步")
FULL_DATE = re.compile(r"(20\d\d)-(\d{1,2})-(\d{1,2})")
SHORT_DATE = re.compile(r"(?<![\d./-])(0[1-9]|1[0-2])-([0-2]\d|3[01])(?![\d])")
PLACEHOLDER = re.compile(r"<[^<>\n{}!]{2,}>")
TEMPLATED = ("charter", "plan", "state", "decisions")


def read(path):
    try:
        return tree.read_text(path)
    except (OSError, UnicodeDecodeError):
        return ""


def field(text, key):
    m = re.search(rf"^{key}:[ \t]*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def workdirs(charter):
    """与 pt.sh 的 workdirs 同口径：按空格拆，在第一个括号/分号/逗号处截断，只留像路径的。"""
    out = []
    for tok in field(charter, "Workdir").split(" "):
        tok = re.split(r"[（(；;，,]", tok, maxsplit=1)[0]
        if tok.startswith(("/", "~")):
            out.append(tok)
    return out


def dates_in(text, today):
    """文本里的日期：YYYY-MM-DD 与 MM-DD（年份取最近的过去，不晚于明天）。"""
    out = []
    for m in FULL_DATE.finditer(text):
        try:
            out.append(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    rest = FULL_DATE.sub(" ", text)
    for m in SHORT_DATE.finditer(rest):
        for y in (today.year, today.year - 1):
            try:
                d = dt.date(y, int(m.group(1)), int(m.group(2)))
            except ValueError:
                break
            if d <= today + dt.timedelta(days=1):
                out.append(d)
                break
    return out


def sections(text):
    """[(标题行, [正文行])]，只认 ## 二级标题；代码块里的不算。"""
    secs, cur, fence = [], None, False
    for ln in text.split("\n"):
        if tree.FENCE_RE.match(ln):
            fence = not fence
        if not fence and ln.startswith("## "):
            cur = (ln, [])
            secs.append(cur)
        elif cur is not None:
            cur[1].append(ln)
    return secs


def short(s, n=40):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def kb(n):
    return f"{n / 1024:.1f} KB"


def template_placeholders(tpl_dir):
    out = {}
    for name in TEMPLATED:
        raw = read(os.path.join(tpl_dir, name + ".md"))
        out[name] = [p for p in dict.fromkeys(PLACEHOLDER.findall(raw)) if re.search(r"\w", p)]
    return out


def lint_one(slug, d, ctx):
    today, host = ctx["today"], ctx["host"]
    found = []

    def add(check, msg):
        found.append((check, msg))

    charter = read(os.path.join(d, "charter.md"))
    state_raw = read(os.path.join(d, "state.md"))
    state = tree.strip_comments(state_raw)
    jpath = os.path.join(d, "journal.md")
    journal = read(jpath)

    # state 落后 journal
    jdates = [x for ln in journal.split("\n") if ln.startswith("## ") for x in dates_in(ln, today)]
    if jdates:
        jlast = max(jdates)
        upd = dates_in(field(state, "Updated"), today)
        if not upd:
            add("state-stale", f"state 没有可读的 Updated 日期，比不了 journal 最新条目 {jlast}")
        elif (jlast - upd[0]).days >= STATE_LAG_DAYS:
            add("state-stale", f"state Updated {upd[0]}，journal 最新条目 {jlast}，落后 {(jlast - upd[0]).days} 天")

    # 待拍板 / 等用户 过期
    for head, body in sections(state):
        if not PENDING_HEAD.match(head):
            continue
        hd = dates_in(head, today)
        if hd and (today - max(hd)).days > PENDING_DAYS:
            add("pending-stale", f"「{short(head[3:], 30)}」标题日期 {max(hd)}，已过 {(today - max(hd)).days} 天")
        entries = []
        for ln in body:
            if not ln.strip():
                continue
            if ln[0] in " \t" and entries:
                entries[-1] += " " + ln.strip()
            else:
                entries.append(ln.strip())
        for e in entries:
            ed = dates_in(e, today)
            if ed and (today - max(ed)).days > PENDING_DAYS:
                add("pending-stale", f"「{short(head[3:], 12)}」里「{short(e)}」最新日期 {max(ed)}，已过 {(today - max(ed)).days} 天")

    # 模板占位没填（注释里的不算）
    for name in TEMPLATED:
        text = tree.strip_comments(read(os.path.join(d, name + ".md")))
        left = [p for p in ctx["placeholders"][name] if p in text]
        if left:
            add("template", f"{name}.md 有 {len(left)} 处模板占位没填：{short('、'.join(left), 60)}")

    # 体积
    if os.path.isfile(jpath) and os.path.getsize(jpath) > JOURNAL_MAX:
        add("journal-size", f"journal.md {kb(os.path.getsize(jpath))}，超过 {kb(JOURNAL_MAX)}")
    nbytes = len(state_raw.encode())
    nlines = state_raw.count("\n") + (0 if state_raw.endswith("\n") or not state_raw else 1)
    if nbytes > ctx["state_max_bytes"] or nlines > ctx["state_max_lines"]:
        add("state-size", f"state.md {nlines} 行 / {nbytes} 字节，超过 {ctx['state_max_lines']} 行或 {ctx['state_max_bytes']} 字节的上限")

    # Host 与 Workdir
    h = field(charter, "Host")
    if not h:
        add("host", "charter 没有 Host 字段")
    elif h not in ctx["hosts"]:
        add("host", f"Host「{short(h)}」不是规范主机名（pt where 按主机名精确比对，永远命中不了）")
    elif h == host:
        wds = workdirs(charter)
        if not wds:
            add("workdir-missing", "Host 是本机，但 Workdir 里认不出路径")
        for p in wds:
            if not os.path.isdir(os.path.expanduser(p)):
                add("workdir-missing", f"Host 是本机，但 Workdir {p} 不存在")

    # 焦点 / 下一步
    heads = [hd for hd, _ in sections(state)]
    if not any(FOCUS_HEAD.match(x) for x in heads) and not any(NEXT_HEAD.match(x) for x in heads):
        add("no-focus", "state 里既没有焦点类小节（焦点、焦点节点、研究树、现在在哪），也没有「下一步」")

    # 研究树
    tdir = os.path.join(d, "tree")
    names = [f for f in os.listdir(tdir) if tree.NODE_FILE_RE.match(f)] if os.path.isdir(tdir) else []
    for nid in sorted((f[:-3] for f in names), key=tree.id_key):
        path = os.path.join(tdir, nid + ".md")
        if not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size > NODE_MAX:
            add("tree-node-size", f"节点 {nid} {kb(size)}，超过 {kb(NODE_MAX)}")
        try:
            node = tree.parse_node(path)
        except (OSError, UnicodeDecodeError):
            continue
        if node["parent"]:
            continue
        know = len(tree.section(node, "当前认识").encode()) + len(tree.section(node, "教训").encode())
        if know > ROOT_KNOW_MAX:
            add("tree-root-size", f"根 {nid} 的「当前认识」加「教训」{kb(know)}，超过 {kb(ROOT_KNOW_MAX)}")
    return found


def main(argv):
    opts, slugs, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--root", "--host", "--state-max-bytes", "--state-max-lines", "--templates"):
            opts[a] = argv[i + 1]
            i += 2
            continue
        if a == "--all":
            opts["--all"] = True
        else:
            slugs.append(a)
        i += 1
    root = opts["--root"]
    if opts.get("--all"):
        slugs = sorted(s for s in os.listdir(root) if os.path.isfile(os.path.join(root, s, "charter.md")))
    host = opts["--host"]
    hosts = {host}
    for f in glob.glob(os.path.join(root, ".fleet", "hosts", "*", "hostname")):
        hn = read(f).strip()
        if hn:
            hosts.add(hn)
    ctx = {"today": dt.date.today(), "host": host, "hosts": hosts,
           "state_max_bytes": int(opts["--state-max-bytes"]), "state_max_lines": int(opts["--state-max-lines"]),
           "placeholders": template_placeholders(opts["--templates"])}
    count = dict.fromkeys(CHECKS, 0)
    for s in slugs:
        d = os.path.join(root, s)
        if not os.path.isfile(os.path.join(d, "charter.md")):
            print(f"{s}: missing: 没有这个项目（{d}/charter.md 不存在）")
            continue
        for check, msg in lint_one(s, d, ctx):
            count[check] += 1
            print(f"{s}: {check}: {msg}")
    if opts.get("--all"):
        print(f"\n共 {len(slugs)} 个项目，{sum(count.values())} 条发现：" + "，".join(f"{k} {v}" for k, v in count.items()))
    return 0


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:  # 体检本身出错也不拦人
        print(f"lint.py: 体检出错（{type(e).__name__}: {e}）", file=sys.stderr)
    sys.exit(0)
