#!/usr/bin/env python3
"""progress.py — 算出来的进度总览。pt list、INDEX.md、research.html 顶部、简报里的 INDEX 行、pt lint 的三项
进度检查都用这里的同一份数据。只读档案；只写 <档案根>/INDEX.md 与缓存 <档案根>/.cache/progress.json。

  progress.py index --root R --host H           重写 <R>/INDEX.md
  progress.py list --root R --host H [--tsv]    打印总览表与各项目的主机、名称、Workdir（--tsv 给代理，一行一个项目）

每列怎么算（算不出来显示「—」，不猜）：
  状态      charter 的 Status（括号前那段）；暂停/已放弃/已完成但研究树还有 active 节点标「⚠矛盾」，进行中但 14 天没活动标「⚠停滞」，
            中心机同步发现与节点分叉标「⚠分叉」
  最近活动  只看档案，取最晚者并注来源：提交（不算 autosync、合并，以及提交说明标明是批量迁移或同步的）、
            journal 非「运维」条目的标题日期、研究树节点 status/verdict 变化（取自 git 历史）
  等用户    state 里标题含「待拍板」「待用户」「等用户」的二级小节：条目都以 [待用户 MM-DD] 开头的给条数与最老天数；
            否则（旧格式）给顶层列表项的条数「N（旧格式，无日期）」；写「无」或为空算 0；没有这种小节显示「—」（正文不猜）
  进度      研究项目 active / 已关节点数；工程项目 plan 勾选 x/y
  在跑      本机 ~/.fleet/jobs 里记了这个 slug、还在跑的 fleet 任务数（fleet run 时会话绑了项目才记）
  现在最信的一条  根节点（研究项目）或 state（工程项目）「## 当前认识」第 1 条，截到一行
排序：等用户（有日期的在前，旧格式无日期的随后）> 进行中但 14 天没活动 > 状态矛盾 > 其余按最近活动。只用标准库。
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree  # noqa: E402
import journal as jmod  # noqa: E402

IDLE_DAYS = 14
BELIEF_WIDTH = 60
STATUS_VALUES = ("进行中", "暂停", "已完成", "已放弃")
# 不算活动的提交：同步、合并、迁移，以及提交说明标明是批量迁移或整理档案格式的（规范主机名、记忆迁入、按 pt 新约定重写 state/tree）
SKIP_COMMIT = re.compile(r"^(autosync @|migrate to |journal-archive @|Merge |规整[：:]|charter: (Host|Workdir)|Workdir 由)"
                         r"|迁入|^(state|tree)[：:].*(新约定|快照|pt v?\d+\.\d+)")
PEND_HEADS = ("待拍板", "待用户", "等用户")
PEND_TAG = re.compile(r"^\[待用户\s*(\d{1,2})-(\d{1,2})\]")
ITEM_MARK = re.compile(r"^(\d+[.)、]|[-*+])\s*")
NONE_LINE = re.compile(r"^[-*]?\s*[（(]?(无|暂无|none|—|-)[）)]?[。.]?\s*$", re.I)
PLAN_DONE = re.compile(r"^\s*[-*]\s*\[[xX✓]")
PLAN_ANY = re.compile(r"^\s*[-*]\s*\[[ xX✓]")
NODE_PATH = re.compile(r"^tree/([QH][1-9][0-9]*)\.md$")
ZERO = re.compile(r"^0+$")
COLS = ("项目", "状态", "最近活动", "距今", "等用户", "进度", "在跑", "现在最信的一条")


def read(path):
    try:
        return tree.read_text(path)
    except (OSError, UnicodeDecodeError):
        return ""


def today():
    t = os.environ.get("PT_TODAY")
    return dt.date.fromisoformat(t) if t else dt.date.today()


def field(text, key):
    m = re.search(rf"^{key}:[ \t]*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def status_of(charter):
    """「进行中 (探索期)」「进行中（…）」都算进行中；与 pt.sh 的 status_of 同口径。"""
    return re.split(r"[\s（(]", field(charter, "Status"), maxsplit=1)[0]


def sections(text):
    """[(标题, [正文行])]，只认 ## 二级标题；代码块里的不算。"""
    secs, cur, fence = [], None, False
    for ln in text.split("\n"):
        if tree.FENCE_RE.match(ln):
            fence = not fence
        if not fence and ln.startswith("## "):
            cur = (ln[3:].strip(), [])
            secs.append(cur)
        elif cur is not None:
            cur[1].append(ln)
    return secs


def named(h, name):
    return h == name or (h.startswith(name) and h[len(name)] in tree.SEC_SEP)


def state_section(state, name):
    for h, body in sections(tree.strip_comments(state)):
        if named(h, name):
            return body
    return None


def entries(lines):
    """小节里的顶格条目（缩进的续行并进上一条），空行与「无」不算。"""
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        if ln[0] in " \t" and out:
            out[-1] += " " + ln.strip()
        elif not ln.lstrip().startswith("#"):
            out.append(ln.strip())
    return [e for e in out if not NONE_LINE.match(e)]


def first_item(text):
    """「当前认识」第 1 条：第一个顶格列表条目（续行并入；没有列表就取第一段），去掉列表记号与粗体，压成一行。"""
    lines = text.split("\n")
    k = next((k for k, ln in enumerate(lines) if ITEM_MARK.match(ln) and not NONE_LINE.match(ln)), None)
    if k is not None:
        lines = lines[k:]
    item = []
    for ln in lines:
        if not ln.strip():
            if item:
                break
            continue
        if ln.lstrip().startswith("#"):
            continue
        if item and (ITEM_MARK.match(ln) and ln[0] not in " \t"):
            break
        item.append(ln.strip())
    s = " ".join(" ".join(item).split())
    s = ITEM_MARK.sub("", s, count=1)
    return s.replace("**", "").strip()


def cut(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


def year_of(m, d, ref):
    """MM-DD 补年份：不晚于 ref 次日的最近一个（跨年时取上一年）。"""
    for y in (ref.year, ref.year - 1):
        try:
            x = dt.date(y, m, d)
        except ValueError:
            return None
        if x <= ref + dt.timedelta(days=1):
            return x
    return None


# ---------- git ----------

def git(d, *args):
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, check=False)
    except OSError:
        return ""
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def head_sha(d):
    """HEAD 的提交号，直接读 .git（不起进程）；读不出来退回 git rev-parse。"""
    g = os.path.join(d, ".git")
    h = read(os.path.join(g, "HEAD")).strip()
    if h and not h.startswith("ref: "):
        return h
    if h:
        ref = h[5:]
        x = read(os.path.join(g, ref)).strip()
        if x:
            return x
        for ln in read(os.path.join(g, "packed-refs")).split("\n"):
            if ln.rstrip().endswith(" " + ref):
                return ln.split()[0]
    return git(d, "rev-parse", "-q", "--verify", "HEAD").strip()


class Blobs:
    """一个 git cat-file --batch 进程，按需取 blob。"""

    def __init__(self, d):
        self.p = subprocess.Popen(["git", "-C", d, "cat-file", "--batch"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def get(self, sha):
        if ZERO.match(sha):
            return None
        self.p.stdin.write((sha + "\n").encode())
        self.p.stdin.flush()
        h = self.p.stdout.readline().split()
        if len(h) != 3:
            return None
        n = int(h[2])
        data = self.p.stdout.read(n)
        self.p.stdout.read(1)
        return data.decode("utf-8", "replace")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.p.kill()


def tree_log(d):
    """tree/ 下节点文件的变化，新→旧：[(日期, 提交说明, [(ID, 旧 blob, 新 blob)])]。合并提交不列 diff。"""
    out = []
    log = git(d, "log", "--no-renames", "--raw", "--no-abbrev", "--format=%x01%as%x00%s", "--", "tree/")
    for chunk in log.split("\x01")[1:]:
        lines = chunk.split("\n")
        h = lines[0].split("\x00")
        if len(h) < 2:
            continue
        ch = []
        for ln in lines[1:]:
            if not ln.startswith(":") or "\t" not in ln:
                continue
            info, path = ln.split("\t", 1)
            m, f = NODE_PATH.match(path), info.split()
            if m and len(f) >= 4:
                ch.append((m.group(1), f[2], f[3]))
        out.append((h[0], h[1], ch))
    return out


def meta(bl, sha, nid, memo):
    if sha not in memo:
        raw = bl.get(sha)
        memo[sha] = None if raw is None else tree.parse_node_text(raw.replace("\r\n", "\n").lstrip("﻿"), nid)
    n = memo[sha]
    return None if n is None else (n["status"], n["verdict"])


def last_node_change(d):
    """最近一次节点 status/verdict 变化（含新增节点）的日期；跳过不算活动的提交。"""
    log = tree_log(d)
    if not log:
        return ""
    bl, memo = Blobs(d), {}
    try:
        for date, subj, ch in log:
            if SKIP_COMMIT.search(subj):
                continue
            for nid, a, b in ch:
                if meta(bl, a, nid, memo) != meta(bl, b, nid, memo) and meta(bl, b, nid, memo) is not None:
                    return date
    finally:
        bl.close()
    return ""


def closed_dates(d, ids):
    """各节点最近一次变成 closed 的提交日期（入档日期）。HEAD 里还不是 closed 的（关了还没提交）给空串。"""
    want, out = set(ids), {}
    log = tree_log(d)
    if not log or not want:
        return out
    bl, memo, seen = Blobs(d), {}, set()
    try:
        for date, _subj, ch in log:
            for nid, a, b in ch:
                if nid not in want or nid in out:
                    continue
                new, old = meta(bl, b, nid, memo), meta(bl, a, nid, memo)
                if nid not in seen:
                    seen.add(nid)
                    if not new or new[0] != "closed":
                        out[nid] = ""
                        continue
                if new and new[0] == "closed" and (not old or old[0] != "closed"):
                    out[nid] = date
            if len(out) == len(want):
                break
    finally:
        bl.close()
    return out


def commit_activity(d):
    for ln in git(d, "log", "--format=%as%x00%s").split("\n"):
        date, _, subj = ln.partition("\x00")
        if date and not SKIP_COMMIT.search(subj):
            return date
    return ""


# ---------- 单个项目 ----------

def journal_dates(d):
    """journal 非「运维」条目标题里的日期（去重、新→旧）。哪天算「将来」要看今天，所以全留，取的时候再挑。"""
    out = set()
    for e in jmod.split(jmod.read_raw(os.path.join(d, "journal.md")))[1]:
        m = re.match(r"^## \[?(\d{4}-\d{2}-\d{2})", e)
        if not m or jmod.category(e) == "运维":
            continue
        try:
            out.add(dt.date.fromisoformat(m.group(1)).isoformat())
        except ValueError:
            pass
    return sorted(out, reverse=True)


def pending(state, ok):
    """([MM-DD…], None)：条目都带 [待用户 MM-DD]；(None, 条数)：旧格式，只数顶层列表项（没有列表就数顶格行）；
    (None, None)：没有标题含待拍板/待用户/等用户的二级小节（合格的 state 没有这节算 0）。只看小节标题，正文不猜。"""
    secs = [body for h, body in sections(tree.strip_comments(state)) if any(k in h for k in PEND_HEADS)]
    if not secs:
        return ([], None) if ok else (None, None)
    ents = [e for body in secs for e in entries(body)]
    tags = [PEND_TAG.match(ITEM_MARK.sub("", e, count=1)) for e in ents]
    if all(tags):
        return [f"{int(m.group(1)):02d}-{int(m.group(2)):02d}" for m in tags], None
    return None, (sum(1 for e in ents if ITEM_MARK.match(e)) or len(ents))


def belief_of(d, t, state):
    """(第 1 条, 出处)；没有就 ("", "")。"""
    if t is not None:
        ids, _src, _seq = tree.focus_chain(t)
        roots = sorted((i for i, n in t.nodes.items() if not n["parent"]), key=tree.id_key)
        first = [t.root_of(i) for i in ids if i in t.nodes]
        alive = [r for r in roots if t.nodes[r]["status"] in ("active", "open")]
        for r in dict.fromkeys(first + alive + roots):
            s = first_item(tree.section(t.nodes[r], "当前认识"))
            if s:
                return s, f"根 {r}「当前认识」第 1 条"
        return "", ""
    body = state_section(state, "当前认识")
    s = first_item("\n".join(body)) if body else ""
    return (s, "state「当前认识」第 1 条") if s else ("", "")


def host_label(charter, d, me, aliases):
    h = field(charter, "Host")
    if not h:
        for p in field(charter, "Workdir").split(" "):
            p = re.split(r"[（(；;，,]", p, maxsplit=1)[0]
            if p.startswith(("/", "~")) and os.path.isdir(os.path.expanduser(p)):
                h = me
                break
    if not h:
        return "待定位"
    return "本机" if h == me else aliases.get(h, h)


def file_sig(d):
    sig = [head_sha(d)]
    for f in ("charter.md", "state.md", "journal.md", "plan.md", "experiments.md"):
        try:
            st = os.stat(os.path.join(d, f))
            sig.append([f, st.st_mtime_ns, st.st_size])
        except OSError:
            sig.append([f])
    tdir = os.path.join(d, "tree")
    if os.path.isdir(tdir):
        with os.scandir(tdir) as it:
            for e in sorted(it, key=lambda e: e.name):
                try:
                    st = e.stat()
                    sig.append([e.name, st.st_mtime_ns, st.st_size])
                except OSError:
                    pass
    return sig


def facts(d):
    """一个项目里不随今天变化的部分（可缓存）。"""
    charter = read(os.path.join(d, "charter.md"))
    state = read(os.path.join(d, "state.md"))
    t = tree.Tree(d) if os.path.isdir(os.path.join(d, "tree")) else None
    import lint  # noqa: E402  延迟导入：lint 也会导入本模块
    ok = bool(state) and lint.state_ok(state, t is not None)
    pend = pending(state, ok)
    belief, bsrc = belief_of(d, t, state)
    f = {"name": re.sub(r"^#\s*", "", charter.split("\n", 1)[0]).strip(),
         "status": status_of(charter), "status_raw": field(charter, "Status"),
         "commit": commit_activity(d), "journal": journal_dates(d),
         "node": last_node_change(d) if t is not None else "",
         "pend": pend[0], "pend_old": pend[1],
         "belief": belief, "belief_src": bsrc,
         "summary": next((x.strip() for x in (state_section(state, "一句话概括") or []) if x.strip()), ""),
         "research": t is not None, "active": [], "closed": 0, "plan": None}
    if t is not None:
        f["active"] = sorted((i for i, n in t.nodes.items() if n["status"] == "active"), key=tree.id_key)
        f["closed"] = sum(1 for n in t.nodes.values() if n["status"] == "closed")
    else:
        plan = tree.strip_comments(read(os.path.join(d, "plan.md")))
        tpl = lint.plan_placeholders(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference", "templates"))
        if plan and not any(p in plan for p in tpl):
            lines = plan.split("\n")
            f["plan"] = [sum(1 for x in lines if PLAN_DONE.match(x)), sum(1 for x in lines if PLAN_ANY.match(x))]
    return f


CACHE_VER = "2"


def cache_key():
    return CACHE_VER + ":" + str(os.path.getmtime(os.path.abspath(__file__)))


def load_cache(root):
    try:
        with open(os.path.join(root, ".cache", "progress.json"), encoding="utf-8") as fh:
            c = json.load(fh)
        return c["projects"] if c.get("key") == cache_key() else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save_cache(root, projects):
    d = os.path.join(root, ".cache")
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".progress.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"key": cache_key(), "projects": projects}, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(d, "progress.json"))
    except OSError:
        pass


def running_counts():
    """本机 fleet 任务里记了 slug 且还在跑的：{slug: 个数}；没有 fleet 任务目录返回 None。"""
    jd = os.environ.get("PT_FLEET_JOBS") or os.path.expanduser("~/.fleet/jobs")
    if not os.path.isdir(jd):
        return None
    cand = []
    for n in sorted(os.listdir(jd)):
        p = os.path.join(jd, n)
        if os.path.exists(os.path.join(p, "exit")) or not os.path.isfile(os.path.join(p, "slug")):
            continue
        s = read(os.path.join(p, "slug")).strip()
        if s:
            cand.append((n, s))
    out = {}
    if not cand:
        return out
    try:
        r = subprocess.run(["systemctl", "--user", "is-active"] + [f"fleet-{n}" for n, _ in cand],
                           capture_output=True, text=True, timeout=10)
        states = r.stdout.split("\n")
    except (OSError, subprocess.TimeoutExpired):
        return None
    for (n, s), st in zip(cand, states):
        if st.strip() in ("active", "activating", "deactivating", "reloading"):
            out[s] = out.get(s, 0) + 1
    return out


def aliases_of(root):
    out = {}
    hd = os.path.join(root, ".fleet", "hosts")
    for a in sorted(os.listdir(hd)) if os.path.isdir(hd) else []:
        h = read(os.path.join(hd, a, "hostname")).strip()
        if h:
            out[h] = a
    return out


def row(slug, d, f, ref, run, me, aliases):
    """把缓存的 facts 加上随今天变化的部分（距今、等用户天数、停滞、在跑）。"""
    r = dict(f, slug=slug)
    # 最近活动：三个来源取最晚；journal 标题里晚于明天的日期（笔误）不算；同一天以更具体的来源为准：节点 > journal > 提交
    soon = (ref + dt.timedelta(days=1)).isoformat()
    src = [(f["commit"], "提交"), (next((x for x in f["journal"] if x <= soon), ""), "journal"), (f["node"], "节点")]
    act = max(src, key=lambda x: (x[0], ("提交", "journal", "节点").index(x[1])))
    r["act"], r["act_src"] = act[0], (act[1] if act[0] else "")
    charter = read(os.path.join(d, "charter.md"))
    r["host"] = host_label(charter, d, me, aliases)
    r["workdir"] = field(charter, "Workdir")
    r["days"] = (ref - dt.date.fromisoformat(r["act"])).days if r["act"] else None
    if f["pend"] is None:
        r["pend_n"], r["pend_days"] = f.get("pend_old"), None
    else:
        ds = [year_of(int(x[:2]), int(x[3:]), ref) for x in f["pend"]]
        ds = [x for x in ds if x]
        r["pend_n"] = len(f["pend"])
        r["pend_days"] = max((ref - x).days for x in ds) if ds else None
    r["contra"] = r["status"] in ("暂停", "已放弃", "已完成") and bool(f["active"])
    r["idle"] = r["status"] == "进行中" and r["days"] is not None and r["days"] >= IDLE_DAYS
    r["plan_open"] = (f["plan"][1] - f["plan"][0]) if f["plan"] else 0
    r["running"] = None if run is None else run.get(slug, 0)
    r["forked"] = os.path.isfile(os.path.join(os.path.dirname(d), ".fleet", "forked", slug))
    return r


def project_row(d, ref=None, me=None, run=None):
    """单个项目的一行（pt lint 用）：用档案根的缓存，但不改写它。"""
    d = os.path.abspath(d)
    root, slug = os.path.dirname(d), os.path.basename(d)
    ref = ref or today()
    c = load_cache(root).get(slug)
    sig = file_sig(d)
    f = c["data"] if c and c.get("sig") == sig else facts(d)
    me = me or os.environ.get("PT_HOSTNAME") or os.uname().nodename.split(".")[0]
    return row(slug, d, f, ref, run, me, aliases_of(root))


def collect(root, me, ref=None):
    """档案根下所有项目的行，按总览的顺序排好。缓存按各项目的 HEAD 与文件 mtime 失效。"""
    ref = ref or today()
    cache, fresh = load_cache(root), {}
    run = running_counts()
    aliases = aliases_of(root)
    rows = []
    for slug in sorted(os.listdir(root)):
        d = os.path.join(root, slug)
        if slug.startswith(".") or not os.path.isfile(os.path.join(d, "charter.md")):
            continue
        sig = file_sig(d)
        c = cache.get(slug)
        f = c["data"] if c and c.get("sig") == sig else facts(d)
        fresh[slug] = {"sig": sig, "data": f}
        rows.append(row(slug, d, f, ref, run, me, aliases))
    if fresh != cache:
        save_cache(root, fresh)
    return order(rows)


def tier(r):
    if r["pend_n"]:
        return 0 if r["pend"] is not None else 1
    if r["idle"]:
        return 2
    if r["contra"]:
        return 3
    return 4


def order(rows):
    """等用户（有日期的最老在前，旧格式无日期的随后）> 停滞 > 矛盾 > 其余；同一档按最近活动从新到旧，算不出的垫底。"""
    rows = sorted(rows, key=lambda r: r["slug"])
    rows.sort(key=lambda r: r["act"] or "", reverse=True)
    rows.sort(key=lambda r: (tier(r), -(r["pend_days"] or 0) if tier(r) == 0 else 0))
    return rows


# ---------- 显示 ----------

def cells(r, width=BELIEF_WIDTH):
    st = r["status"] if r["status"] in STATUS_VALUES else (cut(r["status_raw"], 12) or "—")
    if r["contra"]:
        st += f" ⚠矛盾（树上 {len(r['active'])} 个 active）"
    if r["idle"]:
        st += " ⚠停滞"
    if r["forked"]:
        st += " ⚠分叉"
    act = f"{r['act']} {r['act_src']}" if r["act"] else "—"
    days = "—" if r["days"] is None else f"{r['days']} 天"
    if r["pend_n"] is None:
        pend = "—"
    elif r["pend_n"] == 0:
        pend = "0"
    elif r["pend"] is None:
        pend = f"{r['pend_n']}（旧格式，无日期）"
    else:
        pend = f"{r['pend_n']}（最老 {r['pend_days']} 天）" if r["pend_days"] is not None else str(r["pend_n"])
    if r["research"]:
        prog = f"active {len(r['active'])} / 已关 {r['closed']}"
    elif r["plan"] and r["plan"][1]:
        prog = f"plan {r['plan'][0]}/{r['plan'][1]}"
    else:
        prog = "—"
    run = "—" if r["running"] is None else str(r["running"])
    belief = cut(r["belief"], width) if r["belief"] else "—"
    return [r["slug"], st, act, days, pend, prog, run, belief]


def md_cell(s):
    return s.replace("|", "／").replace("\n", " ")


def index_md(rows):
    out = ["# 项目索引", "",
           "由 pt.sh 从各项目档案算出，不要手改。排序：等用户 > 进行中但 14 天没活动（⚠停滞）> 状态矛盾（⚠矛盾）> 其余按最近活动。",
           "最近活动只看档案：提交（不算 autosync、合并与批量迁移）、journal 非运维条目、研究树节点状态变化，取最晚者；— 表示算不出。",
           "等用户只数 state 里标题含「待拍板 / 待用户 / 等用户」的小节；「—」= 没有这种小节，不等于没在等（正文里写的等用户不算）。", "",
           "| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)]
    for r in rows:
        out.append("| " + " | ".join(md_cell(c) for c in cells(r)) + " |")
    return "\n".join(out) + "\n"


TSV_KEYS = ("slug", "name", "status", "host", "act", "act_src", "days", "pend_n", "pend_days", "progress",
            "running", "flags", "belief", "summary")


def tsv(rows):
    out = ["\t".join(TSV_KEYS)]
    for r in rows:
        c = cells(r, 10 ** 6)
        v = dict(r, progress="" if c[5] == "—" else c[5],
                 flags=",".join(x for x, y in (("等用户" if r["pend"] is not None else "等用户（旧格式）", r["pend_n"]),
                                              ("停滞", r["idle"]), ("矛盾", r["contra"])) if y))
        out.append("\t".join("" if v.get(k) is None else " ".join(str(v[k]).split()) for k in TSV_KEYS))
    return "\n".join(out) + "\n"


def write_index(root, rows):
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".INDEX.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(index_md(rows))
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, os.path.join(root, "INDEX.md"))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv):
    if not argv or argv[0] not in ("index", "list"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    opts, i = {}, 1
    while i < len(argv):
        if argv[i] in ("--root", "--host"):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            opts[argv[i]] = True
            i += 1
    root = opts.get("--root")
    if not root or not os.path.isdir(root):
        print(f"progress.py: 没有档案根 {root}", file=sys.stderr)
        return 1
    me = opts.get("--host") or os.environ.get("PT_HOSTNAME") or os.uname().nodename.split(".")[0]
    rows = collect(root, me)
    if argv[0] == "index":
        write_index(root, rows)
    elif opts.get("--tsv"):
        sys.stdout.write(tsv(rows))
    else:
        # 总览表之后每个项目一行：slug、主机、名称、Workdir（用户叫的可能是别名，对 slug 用）
        sys.stdout.write(index_md(rows) + "\n" + "".join(
            f"  {r['slug']:<24} @{r['host']:<10} {r['name']} ｜ Workdir: {r['workdir']}\n"
            for r in sorted(rows, key=lambda r: r["slug"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
