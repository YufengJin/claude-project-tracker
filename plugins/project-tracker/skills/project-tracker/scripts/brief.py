#!/usr/bin/env python3
"""brief.py — 简报正文，由 pt brief 调用。所有项目都走这里（brief.py 出错时 pt.sh 才退回 0.6.10 的排版）。只用标准库。

  brief.py --check <state.md>      state 合格（固定小节）退出 0，否则 1
  brief.py --root R --host H --templates T --state-max-bytes N --state-max-lines N --slug S --budget B

各块定长，不随档案变大（数据都来自 records.load）：
  lint 告警 ≤5 行 → state（合格的整段，≤3 KB；不合格的只取一句话、焦点 / 现在在哪 / 进行中、下一步、待拍板四类小节，
  共 ≤3 KB，其余给去处）→ 焦点问题的当前认识 ≤2 KB（离焦点最近的问题先放，按条放，放不下的给 pt get）→ 条件 ≤8 行
  → 最近 5 张卡各一行（工程项目：journal 最近 5 条标题）→ 前沿：各状态计数加 ≤10 个标题 → journal 最近 3 条标题（研究项目）
  → 去哪找。总量超出预算时只让当前认识让位（按条），其余块本来就定长。
"""
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal  # noqa: E402
import lint  # noqa: E402
import records  # noqa: E402
import tree  # noqa: E402

LINT_LINES = 3
LINT_WIDTH = 56
STATE_MAX = 3 * 1024
KNOW_MAX = 2 * 1024
KNOW_MIN = 400          # 当前认识至少留这么多（放不下时其余块退一档）
# 定长块的两档：(条件行数, 最近卡数, 前沿标题数, 标题宽, 结论宽)。第一档放不下当前认识的最低份额时退到第二档
LEVELS = ((8, 5, 10, 18, 44), (5, 3, 5, 14, 34))
ITEM = re.compile(r"^(\d+[.)、]|[-*+])\s")
PENDING = re.compile(r"^\s*(?:[-*+]|\d+[.)、])?\s*\**(待拍板|待用户|等用户)")
BOX = re.compile(r"^\s*[-*+]\s*(\[[ xX✓]\]\s*)?")


def nb(s):
    return len(s.encode())


def block(title, lines):
    return [f"\n===== {title} ====="] + lines


def size(lines):
    return sum(nb(x) + 1 for x in lines)


def cut(s, n):
    return records.cut(s, n)


# ---------- state ----------

def cut_lines(lines, room, path):
    """一节按字节放进 room：整行放得下就放，第一行放不下就截断这一行；余下给去处。"""
    out, used = [], 0
    for k, ln in enumerate(lines):
        if used + nb(ln) + 1 <= room:
            out.append(ln)
            used += nb(ln) + 1
            continue
        if not out[1:] and room - used > 80:  # 标题之后一行都放不下：截这一行
            b = ln.encode()[:room - used - 60].decode("utf-8", "ignore")
            out.append(b + "…")
        out.append(f"（本节余下 {len(lines) - k} 行未展开：cat {path}）")
        break
    return out


def state_block(rec, d):
    st = rec["state"]
    path = os.path.join(d, "state.md")
    if st["fixed"]:
        return block("state.md（固定小节，去掉了 <!-- --> 注释）", [tree.strip_comments(st["raw"]).strip("\n")])
    secs = st["sections"]
    pre = [ln for ln in tree.strip_comments(st["raw"]).split("\n")[:4] if ln.startswith(("# ", "Updated"))]
    pick = []  # 四类小节各取第一个命中的，按文件顺序输出
    for group in records.STATE_KEEP:  # 组内按名字的先后挑（焦点 > 研究树 > 现在在哪 > 进行中）
        k = next((k for g in group for k, (h, _b) in enumerate(secs) if k not in pick and h.startswith(g)), None)
        if k is not None:
            pick.append(k)
    text = {k: [f"## {secs[k][0]}"] + secs[k][1].rstrip("\n").split("\n") for k in pick}
    # 没有待拍板小节、但别的小节里有「待拍板 / 待用户」条目的（旧格式常见）：把这些条目摘出来单列，免得被截掉
    if not any(any(secs[k][0].startswith(g) for g in records.STATE_KEEP[-1]) for k in pick):
        moved = []
        for k, (h, b) in enumerate(secs):
            if h.startswith("一句话"):
                continue
            its = items_of(b)
            hit = [it for it in its if PENDING.search(it.split("\n")[0])]
            if hit:
                moved += hit
                if k in text:
                    text[k] = [text[k][0]] + [x for it in its if it not in hit for x in it.split("\n")]
        if moved:
            k = len(secs)  # 排在最后
            pick.append(k)
            text[k] = ["## 待拍板（摘自其他小节）"] + [x for it in moved for x in it.split("\n")]
    # 按需分预算：小的节整节放，大的平分剩下的（不让「进行中」挤掉「下一步」）
    avail, alloc = STATE_MAX - size(pre) - 260, {}
    for k in sorted(pick, key=lambda k: size(text[k])):
        share = avail // (len(pick) - len(alloc))
        alloc[k] = min(size(text[k]), share)
        avail -= alloc[k]
    out = pre + [x for k in sorted(pick) for x in cut_lines(text[k], alloc[k], path)]
    rest = [h for k, (h, _b) in enumerate(secs) if k not in pick]
    if not pick:
        out.append("（state 里没有一句话 / 焦点 / 下一步 / 待拍板这几类小节）")
    if rest:
        out.append(f"（其余小节未展开：{cut('、'.join(rest), 60)}；全文 cat {path}）")
    if rec["kind"] == "research" and any(h.startswith(("当前认识", "别再试")) and not tree.is_blank(b) for h, b in secs):
        out.append("[warn] state.md 还有「当前认识」或「别再试」：研究项目这两节应在根节点（tree/ 根的 ## 当前认识 / ## 教训），state 不复写")
    return block("state.md（旧格式：只取一句话、焦点或进行中、下一步、待拍板）", out)


# ---------- 当前认识 ----------

def items_of(text):
    """当前认识按顶格条目切开（续行、子条目并进上一条）；条目前的说明算一条。"""
    out = []
    for ln in text.split("\n"):
        if not ln.strip():
            continue
        if not out or (ITEM.match(ln) and ln[0] not in " \t") or ln.startswith("#"):
            out.append(ln)
        else:
            out[-1] += "\n" + ln
    return out


def know_block(rec, slug, budget):
    t = rec["tree"]
    if t is None:
        return []
    ids, src, ks = tree.chain_knowledge(t, active_only=True)
    if not ks:
        return block(f"焦点问题的当前认识（焦点 {', '.join(ids) or '无'}）", ["(焦点链上 active 的问题节点都没写当前认识)"])
    lines, used, left = [], 0, []
    for x, body in reversed(ks):  # 离焦点最近的问题先放
        n = t.nodes[x]
        head = f"### {x} [{tree.tag(n)}] {cut(n['title'], 40)}"
        its = items_of(body)
        if used + nb(head) + 1 + 120 > budget:
            left.append(f"{x}（{len(its)} 条）")
            continue
        part, used = [head], used + nb(head) + 1
        for k, it in enumerate(its):
            if k == 0 and used + nb(it) + 1 + 120 > budget:  # 第一条就放不下：截这一条
                room = budget - used - 120
                if room > 120:
                    it = it.encode()[:room].decode("utf-8", "ignore") + "…"
            if used + nb(it) + 1 + 120 > budget:
                part.append(f"（{x} 余下 {len(its) - k} 条：pt get {slug} {x}）")
                used += 60
                break
            part.append(it)
            used += nb(it) + 1
        lines += part
    if left:
        lines.append(f"（没放下的问题：{'、'.join(left)}；pt get {slug} <编号>）")
    return block(f"焦点问题的当前认识（焦点 {', '.join(ids) or '无'}，取自{src}；≤{KNOW_MAX // 1024} KB）", lines)


# ---------- 条件、最近、前沿、去哪找（各块按档 L 定长） ----------

def cond_block(rec, slug, L):
    ncond, _nr, _nf, tw, lw = L
    cs = rec["conditions"]
    if not cs["registered"]:
        leg = [x for x in cs["legacy"] if x.strip()]
        lines = ["- " + cut(BOX.sub("", x), lw + 8) for x in leg[:ncond - 1]]
        if len(leg) > ncond - 1:
            lines.append(f"…另有 {len(leg) - ncond + 1} 行：pt conditions {slug}")
        return block(f"条件：未登记（完成标准还是旧写法，原样；pt conditions {slug}）",
                     lines or ["(charter 没有「完成标准」小节)"])
    items = cs["items"]
    cnt = {}
    for c in items:
        cnt[c["status"]] = cnt.get(c["status"], 0) + 1
    lines = []
    for c in items[:ncond]:
        lt = c["latest"]
        s = f"- {c['id']} [{c['status']}] {cut(c['text'], tw + 6)}｜线 {cut(c['line'], 12) or '—'}"
        if lt:
            s += f"｜最近 {lt['verdict']}" + (f" {lt['value']:g}" if lt["value"] is not None else "") + f"（{lt['eid']}）"
        lines.append(s)
    if len(items) > ncond:
        lines[-1] = f"…另有 {len(items) - ncond + 1} 条：pt conditions {slug}"
    return block(f"条件（{'，'.join(f'{k} {v}' for k, v in cnt.items())}；pt conditions {slug}）", lines)


def recent_block(rec, slug, L):
    _nc, nrecent, _nf, tw, lw = L
    rs = rec["recent"][:nrecent]
    if rec["kind"] == "research":
        lines = []
        for r in rs:
            tag = "" if r["card_src"] == "card" else "（摘）"
            lines.append(f"- {r['id']} [{r['shown']}] {r['date'][5:] or '?'} {cut(r['title'], tw)} — {tag}{cut(r['line'], lw)}")
        return block(f"最近有结论的 {len(rs)} 个（新→旧；（摘）= 没写短卡，程序摘的原文）", lines or ["(还没有关闭的节点)"])
    lines = [f"- {r['id']} [{r['shown'] or '旧格式'}] {cut(r['title'], lw + tw)}" for r in rs]
    return block(f"journal 最近 {len(rs)} 条结果 / 决定（新→旧；正文 pt get {slug} <J编号>）", lines or ["(无)"])


def front_block(rec, slug, L):
    if rec["kind"] != "research":
        return []
    _nc, _nr, nfront, tw, _lw = L
    t = rec["tree"]
    cnt = {}
    for n in rec["nodes"].values():
        if n["status"] != "closed":
            k = ("问题" + records.OPEN_SHOWN.get(n["status"], n["status"])) if n["kind"] == "Q" else "假设" + n["shown"]
            cnt[k] = cnt.get(k, 0) + 1
    live = []
    for i in sorted(rec["nodes"], key=tree.id_key):
        n = rec["nodes"][i]
        if n["status"] not in ("active", "open"):
            continue
        r = t.root_of(i)
        if r != i and t.nodes[r]["status"] in ("parked", "closed"):
            continue
        live.append(n)
    live.sort(key=lambda n: 0 if n["status"] == "active" else 1)
    lines = [("计数：" + "，".join(f"{k} {v}" for k, v in sorted(cnt.items()))) if cnt else "计数：没有未关的节点"]
    lines += [f"- {n['id']} [{records.OPEN_SHOWN.get(n['status'])}] {cut(n['title'], tw + 10)}"
              + (f"（{n['parent']} 下）" if n["parent"] else "（根）") for n in live[:nfront]]
    if len(live) > nfront:
        lines.append(f"…另有 {len(live) - nfront} 个：pt find {slug} 在做 / 待做")
    if t.warnings:
        lines.append(f"研究树告警 {len(t.warnings)} 条：pt tree {slug}")
    return block("前沿（在做、待做）", lines)


def where_block(rec, d, ctx):
    s = rec["slug"]
    rows = [("单条", f"pt get {s} <编号>（节点、台账第一列、ADR-xxxx、G1、J日期.序号；卡+台账行+指针，长的分页）"),
            ("按词找", f"pt find {s} <词> …（目录 index.tsv）"), ("条件", f"pt conditions {s}")]
    if rec["kind"] == "research":
        rows.append(("已关按日期 / 全图", f"pt results {s} / pt tree {s}"))
    files = ["experiments.md（读数只在这里）"] if os.path.isfile(os.path.join(d, "experiments.md")) else []
    files += ["journal.md（过程）", "decisions.md（为何转向）", "charter.md（目标、完成标准）"]
    if os.path.isfile(os.path.join(d, "verifier.md")):
        files.append("verifier.md（考官）")
    if os.path.isfile(os.path.join(d, "plan.md")) and not lint.plan_is_template(d, ctx["placeholders"]["plan"]):
        files.append("plan.md（计划）")
    rows.append(("原文", "、".join(files)))
    cold = [x for x in ("archive", "briefs", "reviews", "references", "artifacts", "pages") if os.path.isdir(os.path.join(d, x))]
    if cold:
        rows.append(("冷存储（平时不读）", "、".join(x + "/" for x in cold)))
    rows.append(("journal 新条目", "## [YYYY-MM-DD] 类别 | 节点或线程 | 一句话（" + "、".join(journal.CATEGORIES) + "）"))
    return block(f"去哪找（文件在 {d}/）", [f"- {a}：{b}" for a, b in rows])


def body(opts):
    root, slug = opts["--root"], opts["--slug"]
    d = os.path.join(root, slug)
    hosts = {opts["--host"]}
    for f in glob.glob(os.path.join(root, ".fleet", "hosts", "*", "hostname")):
        hn = lint.read(f).strip()
        if hn:
            hosts.add(hn)
    ctx = {"today": dt.date.today(), "host": opts["--host"], "hosts": hosts,
           "state_max_bytes": int(opts["--state-max-bytes"]), "state_max_lines": int(opts["--state-max-lines"]),
           "placeholders": lint.template_placeholders(opts["--templates"])}
    rec = records.load(d)
    try:
        records.write_index(d, rec)  # 顺手刷新目录，pt find 不用再算
    except OSError:
        pass

    found = lint.lint_one(slug, d, ctx, rec)
    ll = [f"{c}: {cut(m, LINT_WIDTH)}" for c, m in found]
    if len(ll) > LINT_LINES:
        ll = ll[:LINT_LINES - 1] + [f"…另有 {len(ll) - LINT_LINES + 1} 条：pt lint {slug}"]
    b_lint = block(f"lint（{len(found)} 条，只报不拦）", ll or ["(无)"])
    b_state = state_block(rec, d)
    b_where = where_block(rec, d, ctx)
    budget = int(opts["--budget"])
    for L in LEVELS:
        mid = cond_block(rec, slug, L) + recent_block(rec, slug, L) + front_block(rec, slug, L)
        left = budget - size(b_lint) - size(b_state) - size(mid) - size(b_where)
        if left >= KNOW_MIN + 200:
            break
    b_know = know_block(rec, slug, max(min(KNOW_MAX, left - 120), 0))
    return "\n".join(b_lint + b_state + b_know + mid + b_where)


def main(argv):
    if argv[:1] == ["--check"]:
        return 0 if len(argv) > 1 and os.path.isfile(argv[1]) and lint.state_ok(
            lint.read(argv[1]), os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(argv[1])), "tree"))) else 1
    opts, i = {}, 0
    while i + 1 < len(argv):
        opts[argv[i]] = argv[i + 1]
        i += 2
    print(body(opts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
