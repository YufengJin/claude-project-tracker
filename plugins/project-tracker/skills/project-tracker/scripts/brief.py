#!/usr/bin/env python3
"""brief.py — state 合格（固定小节）的项目的简报正文，由 pt brief 调用。只用标准库。

  brief.py --check <state.md>      state 合格退出 0，否则 1（不合格的项目 pt brief 走 0.6.10 的排版）
  brief.py --root R --host H --templates T --state-max-bytes N --state-max-lines N --slug S --budget B

正文依次是：lint 告警（最多 5 行）→ state 全文 →（有研究树时）焦点链上 active 问题节点的当前认识 → 前沿标题
→ journal 最近 8 条标题（跳过「运维」）→ 最近 3 条 ADR 标题 →「要找什么去哪」。charter、plan、考官卡、
journal 正文只给去处。超出预算时依次截前沿、journal 标题、当前认识，截掉的给去处。
"""
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal  # noqa: E402
import lint  # noqa: E402
import tree  # noqa: E402

LINT_LINES = 5
JOURNAL_HEADS = 8
ADR_LAST = 3


def nb(s):
    return len(s.encode())


def block(title, lines):
    return [f"\n===== {title} ====="] + lines


def size(lines):
    return sum(nb(x) + 1 for x in lines)


def trim(lines, budget, ptr):
    """块的前几行放得下就留，余下换成一行去处；标题行总留。"""
    if size(lines) <= budget:
        return lines
    keep, used = lines[:1], nb(lines[0]) + 1
    for k, ln in enumerate(lines[1:], 1):
        p = f"（余下 {len(lines) - k} 行未展开；全文：{ptr}）"
        if used + nb(ln) + 1 + nb(p) + 1 > budget:
            return keep + [p]
        keep.append(ln)
        used += nb(ln) + 1
    return keep


def frontier(t, slug):
    out = []
    for i in sorted(t.nodes, key=tree.id_key):
        n = t.nodes[i]
        if n["status"] not in ("active", "open"):
            continue
        r = t.root_of(i)
        if r != i and t.nodes[r]["status"] in ("parked", "closed"):
            continue
        where = f"（{n['parent']} 下）" if n["parent"] else "（根）"
        out.append(f"- {i} [{n['status']}] {n['title']}{where}")
    if not out:
        out.append("(无 active / open 节点)")
    if t.warnings:
        out.append(f"研究树告警 {len(t.warnings)} 条：pt tree {slug}")
    return out


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

    found = lint.lint_one(slug, d, ctx)
    ll = [f"{c}: {m}" for c, m in found]
    if len(ll) > LINT_LINES:
        ll = ll[:LINT_LINES - 1] + [f"…另有 {len(ll) - LINT_LINES + 1} 条：pt lint {slug}"]
    b_lint = block(f"lint 告警（{len(found)} 条，只报不拦；pt lint {slug}）", ll or ["(无)"])

    b_state = block("state.md（去掉了 <!-- --> 注释）", [tree.strip_comments(lint.read(os.path.join(d, "state.md"))).strip("\n")])

    b_know, b_front = [], []
    if os.path.isdir(os.path.join(d, "tree")):
        t = tree.Tree(d)
        ids, src, ks = tree.chain_knowledge(t, active_only=True)
        kl = []
        for x, b in ks:
            n = t.nodes[x]
            kl += [f"### {x} [{tree.tag(n)}] {n['title']}", b]
        b_know = block(f"焦点链的当前认识（焦点 {', '.join(ids) or '无'}，取自{src}；pt tree {slug}）",
                       "\n".join(kl).split("\n") if kl else ["(焦点链上 active 的问题节点都没写当前认识)"])
        b_front = block(f"前沿（active / open；节点上下文 pt tree {slug} --ctx ID）", frontier(t, slug))

    jp = os.path.join(d, "journal.md")
    entries = journal.split(journal.read_raw(jp))[1]
    heads = [journal.head(e) for e in entries if journal.category(e) != "运维"][-JOURNAL_HEADS:]
    b_journal = block(f"journal 最近 {JOURNAL_HEADS} 条标题（跳过运维；共 {len(entries)} 条，正文 {jp}）",
                      (heads or ["(无)"]) + ["新条目标题：## [YYYY-MM-DD] 类别 | 节点或线程 | 一句话（类别：" +
                                             "、".join(journal.CATEGORIES) + "）"])

    adrs = [ln for ln in tree.strip_comments(lint.read(os.path.join(d, "decisions.md"))).split("\n")
            if re.match(r"^## ADR-", ln)]
    b_adr = block(f"最近 {ADR_LAST} 条 ADR（共 {len(adrs)} 条；正文 {d}/decisions.md）", adrs[-ADR_LAST:] or ["(无 ADR)"])

    rows = []
    if os.path.isfile(os.path.join(d, "experiments.md")):
        rows.append(("数字、读数", f"台账 {d}/experiments.md（读数只在这里）"))
    if os.path.isdir(os.path.join(d, "tree")):
        rows.append(("某条分支为何关", f"节点的「## 结论」：pt tree {slug} --ctx ID；已关索引 pt tree {slug} --all"))
        rows.append(("现在信什么", f"上面焦点链的当前认识；全树 pt tree {slug}"))
    rows.append(("为何转向", f"ADR 正文 {d}/decisions.md"))
    rows.append(("过程、证据路径", f"journal 正文 {jp}" + ("（更早的在 archive/journal-*.md）"
                                                     if glob.glob(os.path.join(d, "archive", "journal-*.md")) else "")))
    rows.append(("目标、边界、完成标准", f"{d}/charter.md"))
    if os.path.isfile(os.path.join(d, "verifier.md")):
        rows.append(("考官（拿什么判对错）", f"{d}/verifier.md"))
    if os.path.isfile(os.path.join(d, "plan.md")) and not lint.plan_is_template(d, ctx["placeholders"]["plan"]):
        rows.append(("计划清单", f"{d}/plan.md"))
    b_ptr = block("要找什么去哪（正文不在简报里，用到再读）", ["| 要找 | 去哪 |", "|---|---|"] +
                  [f"| {a} | {b} |" for a, b in rows])

    budget = int(opts["--budget"])
    fixed = size(b_lint) + size(b_state) + size(b_adr) + size(b_ptr)
    # 截的顺序：前沿 → journal 标题 → 当前认识；当前认识先拿（剩余减去另两块各自的保底）
    left = budget - fixed
    floor_j, floor_f = min(size(b_journal), 1200), min(size(b_front), 600)
    b_know = trim(b_know, max(left - floor_j - floor_f, 0), f"pt tree {slug}") if b_know else b_know
    left -= size(b_know)
    b_journal = trim(b_journal, max(left - floor_f, 0), f"grep '^## ' {jp}")
    left -= size(b_journal)
    b_front = trim(b_front, max(left, 0), f"pt tree {slug}") if b_front else b_front
    out = b_lint + b_state + b_know + b_front + b_journal + b_adr + b_ptr
    return "\n".join(out)


def main(argv):
    if argv[:1] == ["--check"]:
        return 0 if len(argv) > 1 and os.path.isfile(argv[1]) and lint.state_ok(lint.read(argv[1])) else 1
    opts, i = {}, 0
    while i + 1 < len(argv):
        opts[argv[i]] = argv[i + 1]
        i += 2
    print(body(opts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
