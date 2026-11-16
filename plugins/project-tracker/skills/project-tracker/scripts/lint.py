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
import journal as jmod  # noqa: E402  journal 条目切分与 journal-archive 同一套
import progress  # noqa: E402  最近活动、进度与 pt list 同一套

CHECKS = ("state-stale", "pending-stale", "template", "journal-size", "state-size",
          "host", "workdir-missing", "no-focus", "tree-root-size", "tree-node-size",
          "state-format", "tree-know", "journal-entry", "status", "plan-template",
          "status-tree", "idle", "plan-open",
          "card-missing", "card-format", "card-ref", "card-number", "cond-format")
STATE_LAG_DAYS = 2          # state 的 Updated 比 journal 最新条目早这么多天及以上
PENDING_DAYS = 7            # 待拍板 / 等用户 里的日期超过这么多天
RESULT_CARD_DAYS = 14       # 这么多天内新写的「结果」条目没有卡：提示
COND_FIRST = re.compile(r"^\s*(?:[-*+]\s+)?\**(?:不过|过)?\s*G\d")  # 第一段里有条件判定行的「结果」条目（判定条目）不要卡
JOURNAL_MAX = 100 * 1024
ROOT_KNOW_MAX = 6 * 1024    # 根节点「当前认识」+「教训」
NODE_MAX = 5 * 1024
PENDING_HEAD = re.compile(r"^##\s.*(待拍板|等用户|待用户)")
FOCUS_HEAD = re.compile(r"^##\s.*(焦点|研究树|现在在哪)")
NEXT_HEAD = re.compile(r"^##\s.*下一步")
FULL_DATE = re.compile(r"(20\d\d)-(\d{1,2})-(\d{1,2})")
SHORT_DATE = re.compile(r"(?<![\d./-])(0[1-9]|1[0-2])-([0-2]\d|3[01])(?![\d])")
PLACEHOLDER = re.compile(r"<[^<>\n{}!]{2,}>")
TEMPLATED = ("charter", "state", "decisions")
# state 的固定小节（按此顺序）；合格 = 有「焦点」与「下一步」、没有名单外的二级小节、全文不超过 STATE_FIXED_MAX。
# 「当前认识」只给没有研究树的项目（研究项目的在树的根节点）
STATE_SECTIONS = ("一句话概括", "焦点", "下一步", "待拍板", "线程", "入口与产物", "快速启动", "别再试", "当前认识")
STATE_REQUIRED = ("焦点", "下一步")
STATE_FIXED_MAX = 3 * 1024
KNOW_MAX = 3 * 1024         # 任一问题节点的「当前认识」
JOURNAL_ENTRY_MAX = 3 * 1024  # 新格式 journal 条目单条
STATUS_VALUES = ("进行中", "暂停", "已完成", "已放弃")
APPEND_HEAD = re.compile(r"更新|历史|已过时")
# 0.6.10 及以前的 plan 模板占位：旧项目的 plan 没填也认得出
LEGACY_PLAN_PLACEHOLDERS = ("<一段：整体思路和顺序为什么这样排>", "<当前步骤>", "<可能翻车的地方和预案>")
LEGACY_CHARTER_PLACEHOLDERS = ("<可判定的条件。打勾必须对应 journal 里的证据条目>",)


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


def state_name(head):
    """「## 焦点」「## 待拍板（2 项）」→ 固定小节名；名单外的返回 None。"""
    h = head[3:].strip()
    for n in STATE_SECTIONS:
        if h == n or (h.startswith(n) and h[len(n)] in tree.SEC_SEP):
            return n
    return None


def state_check(raw, has_tree=False):
    """state.md 按固定小节的体检：(缺的必需节, 名单外的节, 超出 3 KB 的字节数)。三者都空才合格。"""
    heads = [h for h, _ in sections(tree.strip_comments(raw))]
    names = [state_name(h) for h in heads]
    if has_tree:
        names = [None if n == "当前认识" else n for n in names]
    missing = [n for n in STATE_REQUIRED if n not in names]
    extra = [h[3:].strip() for h, n in zip(heads, names) if n is None]
    return missing, extra, max(0, len(raw.encode()) - STATE_FIXED_MAX)


def state_ok(raw, has_tree=False):
    missing, extra, over = state_check(raw, has_tree)
    return not missing and not extra and not over


def plan_placeholders(tpl_dir):
    raw = read(os.path.join(tpl_dir, "plan.md"))
    cur = [p for p in dict.fromkeys(PLACEHOLDER.findall(raw)) if re.search(r"\w", p)]
    return cur + list(LEGACY_PLAN_PLACEHOLDERS)


def plan_is_template(d, placeholders):
    """plan.md 还留着模板占位（新旧模板都认）。注释里的不算。"""
    text = tree.strip_comments(read(os.path.join(d, "plan.md")))
    return [p for p in placeholders if p in text]


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
    out["charter"] += list(LEGACY_CHARTER_PLACEHOLDERS)
    out["plan"] = plan_placeholders(tpl_dir)
    return out


NUM_TOKEN = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


def nums(text):
    """两位数及以上的数（7.50 与 7.5 算同一个）。"""
    import records
    return {records.norm_num(x) for x in NUM_TOKEN.findall(text) if sum(ch.isdigit() for ch in x) >= 2}


def card_checks(rec, add):
    """短卡与条件行（只报不拦）：已关节点没有卡；卡的字段不齐或超长；卡里的编号在目录里找不到；
    卡里的数在本节点原文与它的台账行里找不到（只作提示：派生数会误报）；条件行写不成格式、判定点名了没登记的条件。"""
    import records
    nodes = rec["nodes"]
    miss = [n for n in nodes.values() if n["status"] == "closed" and n["card_src"] != "card"]
    if miss:
        miss.sort(key=lambda n: (n["date"] or "9999", tree.id_key(n["id"])), reverse=True)
        add("card-missing", f"已关节点 {len(miss)} 个没有短卡（最近关的：{'、'.join(n['id'] for n in miss[:5])}）："
                            "关节点时在「## 结论」第一段写 目的：/怎么做：/结果：/结论：（问题节点 目的：/结果：）")
    t = rec["tree"]
    for i in sorted(nodes, key=tree.id_key):
        n = nodes[i]
        if n["card_src"] != "card":
            continue
        need = ("目的", "结果") if n["kind"] == "Q" else tree.CARD_LABELS
        lack = [k for k in need if not n["card"].get(k)]
        para = tree.first_para(tree.section(t.nodes[i], "结论"))
        size = len(para.encode())
        why = ([f"缺 {'、'.join(lack)}"] if lack else []) + ([f"{size} 字节，超过 {records.CARD_MAX}"] if size > records.CARD_MAX else [])
        if why:
            add("card-format", f"{i} 的卡：{'；'.join(why)}")
        text = " ".join(n["card"].values())
        refs = set(records.ID_TOKEN.findall(text))
        for br in re.findall(r"\[([^\[\]]+)\]", text):
            refs |= {x.strip() for x in re.split(r"[,，、;；\s]+", br) if x.strip()}
        bad = sorted(x for x in refs if x not in rec["glossary"] and not re.match(r"^\d", x))
        if bad:
            add("card-ref", f"{i} 的卡引用了目录里没有的编号：{short('、'.join(bad), 40)}")
        src = t.nodes[i]["raw"].replace(para, "") + "\n".join(rec["rows"][k]["line"] for k in n["rows"])
        lost = sorted(nums(n["card"].get("结果", "") + " " + n["card"].get("结论", "")) - nums(src))
        if lost:
            add("card-number", f"提示：{i} 的卡里 {short('、'.join(lost), 30)} 在节点原文与它的台账行里没找到（派生数可忽略）")
    # journal「结果」条目的卡：规则同节点；近 RESULT_CARD_DAYS 天新写的没有卡只作提示（只写条件判定的不算）
    lo = (records.progress.today() - dt.timedelta(days=RESULT_CARD_DAYS)).isoformat()
    bare = []
    for e in rec["journal"]:
        if e["category"] != "结果":
            continue
        if e["card"]:
            lack = [k for k in tree.CARD_LABELS if not e["card"].get(k)]
            why = ([f"缺 {'、'.join(lack)}"] if lack else []) + \
                ([f"{e['card_bytes']} 字节，超过 {records.CARD_MAX}"] if e["card_bytes"] > records.CARD_MAX else [])
            if why:
                add("card-format", f"{e['id']}（{e['where']}）的卡：{'；'.join(why)}")
        elif e["date"] >= lo and not any(COND_FIRST.match(ln) for ln in tree.first_para(e["text"].split("\n", 1)[-1]).split("\n")):
            bare.append(e["id"])
    if bare:
        add("card-missing", f"提示：近 {RESULT_CARD_DAYS} 天 {len(bare)} 条「结果」条目没有卡（{'、'.join(bare[-5:])}）："
                            "正文第一段写 目的：/怎么做：/结果：/结论：四行")
    cs = rec["conditions"]
    for c in cs["items"]:
        if c["bad"]:
            add("cond-format", f"条件 {c['id']}（charter.md:{c['lineno']}）：{c['bad']}；写法 - G1 陈述 | 线: … | 尺: … | 来源: …")
        said = [j for j in c["judgments"] if j.get("claimed")]
        if said:
            add("cond-format", f"提示：{c['id']} 的线还没定，判定只能记读数（{short('、'.join(j['where'] for j in said), 60)} "
                               f"写了过 / 不过，按读数显示；线由用户定）")
    for cid in sorted({j["cid"] for j in cs["orphans"]}):
        w = next(j["where"] for j in cs["orphans"] if j["cid"] == cid)
        add("cond-format", f"判定点名了 {cid}（{w}），但 charter「完成标准」里没有这条")


def lint_one(slug, d, ctx, rec=None):
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
        add("journal-size", f"journal.md {kb(os.path.getsize(jpath))}，超过 {kb(JOURNAL_MAX)}（pt journal-archive {slug} 按月原样搬走）")
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

    # state 固定小节
    if os.path.isfile(os.path.join(d, "state.md")):
        missing, extra, over = state_check(state_raw, os.path.isdir(os.path.join(d, "tree")))
        why = ([f"缺 {'、'.join(missing)}"] if missing else []) + \
              ([f"多了 {short('、'.join(extra), 60)}"] if extra else []) + \
              ([f"超 {kb(STATE_FIXED_MAX)} 上限 {over} 字节"] if over else [])
        if why:
            add("state-format", "state 不合格（固定小节：" + "/".join(STATE_SECTIONS) + "）：" + "；".join(why))

    # journal 新格式条目单条大小
    for e in jmod.split(jmod.read_raw(jpath))[1]:
        n = len(e.encode())
        if jmod.NEW_HEAD.match(e) and n > JOURNAL_ENTRY_MAX:
            add("journal-entry", f"条目「{short(e.split(chr(10), 1)[0][3:], 50)}」{kb(n)}，超过 {kb(JOURNAL_ENTRY_MAX)}：长内容落产物文件，条目只记路径")

    # Status 规范取值
    st = field(charter, "Status")
    if charter and st not in STATUS_VALUES:
        add("status", f"charter Status「{short(st, 30)}」不是规范取值（{'/'.join(STATUS_VALUES)}），备注写到 state")

    # 工程项目的 plan 还是模板
    tdir = os.path.join(d, "tree")
    if not os.path.isdir(tdir) and os.path.isfile(os.path.join(d, "plan.md")):
        left = plan_is_template(d, ctx["placeholders"]["plan"])
        if left:
            add("plan-template", f"plan.md 还是模板（{short('、'.join(left), 40)}）：写成清单 - [ ] 步骤 → 验证：命令或判据")

    # 进度：状态与研究树、活动、plan 对不上（与 pt list 同一份数据）
    if charter:
        r = progress.project_row(d, ref=today, me=host)
        st = r["status"]
        if r["contra"]:
            ids = r["active"]
            add("status-tree", f"状态「{st}」，但研究树还有 {len(ids)} 个 active 节点（{short('、'.join(ids), 40)}）：关掉或 park 它们，或改状态")
        if r["idle"]:
            add("idle", f"进行中，但最近活动 {r['act']}（{r['act_src']}）已过 {r['days']} 天：还在做就 checkpoint，不做了就改状态")
        if st == "已完成" and r["plan_open"]:
            add("plan-open", f"已完成，但 plan.md 还有 {r['plan_open']} 个未勾项（共 {r['plan'][1]} 项）：勾上、删掉或注明不做")

    # 研究树
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
        if nid.startswith("Q"):
            kn = len(tree.section(node, "当前认识").encode())
            if kn > KNOW_MAX:
                add("tree-know", f"{nid} 的「当前认识」{kb(kn)}，超过 {kb(KNOW_MAX)}：重写成不超过 15 条的快照")
            app = [h for h, _ in node["sections"] if not tree.sec_name(h) and APPEND_HEAD.search(h)]
            app += [ln.lstrip("#").strip() for ln in tree.section(node, "当前认识").split("\n")
                    if re.match(r"^#{3,}\s", ln) and APPEND_HEAD.search(ln)]
            if app:
                add("tree-know", f"{nid} 有 {len(app)} 个追加小节（「{short(app[0], 24)}」等）：当前认识每次重写，旧版交给 git 与 journal")
        if node["parent"]:
            continue
        know = len(tree.section(node, "当前认识").encode()) + len(tree.section(node, "教训").encode())
        if know > ROOT_KNOW_MAX:
            add("tree-root-size", f"根 {nid} 的「当前认识」加「教训」{kb(know)}，超过 {kb(ROOT_KNOW_MAX)}")

    # 短卡与条件
    if charter:
        try:
            import records
            card_checks(rec or records.load(d, today), add)
        except Exception as e:  # 解析出错只报一行，不拦别的检查
            add("card-format", f"读不出短卡与条件（{type(e).__name__}: {short(str(e), 60)}）")
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
