#!/usr/bin/env python3
"""results.py — 一个项目「得到了什么」：pt results 的文本与 tree.html「结果」页用同一份数据。只读档案，只用标准库。

  results.py <档案目录> [--all]      默认不超过 4 KB，--all 给全量

研究项目：「当前认识」第 1 条 → 已关节点按日期倒序（日期 ID verdict 结论首句 [台账 id]；日期取结论首句里写的，
没写取入档日期，即这个节点在 git 里变成 closed 的那次提交）→ 挂在未关节点上的台账行（结论列，没有就读数列）。
工程项目：state「当前认识」第 1 条 → plan 已勾项 → state「线程」里的 [已推送 <commit>]。
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree  # noqa: E402
import progress  # noqa: E402
import lint  # noqa: E402

LIMIT = 4 * 1024
PUSHED = re.compile(r"^\[已推送[ \t]")


def ledger_cell(row, names):
    """台账行里第一个有内容的指定列（按表头名）。"""
    head = [tree.norm_head(h) for h in row["table"]["header"]]
    for name in names:
        for k, h in enumerate(head):
            if h.startswith(name) and k < len(row["cells"]) and tree.cell(row["cells"][k]).strip():
                return " ".join(tree.cell(row["cells"][k]).split())
    return ""


def data(d, ref=None):
    """{kind, belief, belief_src, closed: [...], open_rows: [...], plan_done, plan_total, pushed}。"""
    ref = ref or progress.today()
    state = progress.read(os.path.join(d, "state.md"))
    research = os.path.isdir(os.path.join(d, "tree"))
    t = tree.Tree(d) if research else None
    belief, src = progress.belief_of(d, t, state)
    out = {"slug": os.path.basename(os.path.abspath(d)), "kind": "research" if research else "engineering",
           "belief": belief, "belief_src": src, "closed": [], "open_rows": [], "plan_done": [], "plan_total": 0,
           "pushed": []}
    if research:
        ids = [i for i, n in t.nodes.items() if n["status"] == "closed"]
        filed = progress.closed_dates(d, ids)
        for i in ids:
            n = t.nodes[i]
            first = tree.first_sentence(tree.section(n, "结论"))
            fd = dt.date.fromisoformat(filed[i]) if filed.get(i) else None
            said = [x for x in lint.dates_in(first, fd or ref) if x <= (fd or ref) + dt.timedelta(days=1)]
            if said:
                date, how = max(said), "结论"
            elif fd:
                date, how = fd, "入档"
            else:
                date, how = None, "未提交"
            out["closed"].append({"id": i, "title": n["title"], "verdict": n["verdict"] or "?", "first": first,
                                  "date": date.isoformat() if date else "", "how": how,
                                  "ledger": [r["id"] for r in t.rows_of.get(i, []) if r["id"]]})
        # 日期新的在前；未提交的（刚关、还没进 git）最前；同一天按 ID 倒序
        out["closed"].sort(key=lambda c: tree.id_key(c["id"]), reverse=True)
        out["closed"].sort(key=lambda c: c["date"] or "9999", reverse=True)
        for r in t.rows:
            live = [x for x in r["nodes"] if x in t.nodes and t.nodes[x]["status"] != "closed"]
            if live:
                out["open_rows"].append({"id": r["id"] or "?", "nodes": [(x, t.nodes[x]["status"]) for x in live],
                                         "text": ledger_cell(r, ("结论", "conclusion", "读数", "result"))})
        out["open_rows"].reverse()  # 台账往下追加：后写的在前
    else:
        plan = tree.strip_comments(progress.read(os.path.join(d, "plan.md")))
        lines = plan.split("\n")
        out["plan_done"] = [" ".join(x.split()) for x in lines if progress.PLAN_DONE.match(x)]
        out["plan_total"] = sum(1 for x in lines if progress.PLAN_ANY.match(x))
    th = progress.state_section(state, "线程") or []
    out["pushed"] = [e for e in progress.entries(th) if PUSHED.match(progress.ITEM_MARK.sub("", e, count=1))]
    return out


def fit(title, items, budget, s):
    """一节：标题 + 条目；放不下的条目换成一行去处。"""
    out, used = [title], len(title.encode()) + 1
    for k, ln in enumerate(items):
        n = len(ln.encode()) + 1
        if used + n > budget - 80:
            out.append(f"…本节另有 {len(items) - k} 条未列：pt results {s} --all")
            break
        out.append(ln)
        used += n
    return out


def text(d, full=False):
    r = data(d)
    s = r["slug"]
    head = [f"结果 · {s}（{'研究' if r['kind'] == 'research' else '工程'}项目；默认只给 4 KB，全量 pt results {s} --all）"]
    head.append(f"现在最信的一条（{r['belief_src']}）：{r['belief']}" if r["belief"] else
                "现在最信的一条：—（" + ("根节点没有「当前认识」" if r["kind"] == "research" else "state 没有「## 当前认识」") + "）")
    secs = []  # (标题, 条目, 预算份额)
    if r["kind"] == "research":
        rows = []
        for c in r["closed"]:
            date = {"结论": c["date"], "入档": f"入档 {c['date']}", "未提交": "未提交"}[c["how"]]
            led = f" [{', '.join(c['ledger'])}]" if c["ledger"] else ""
            rows.append(f"{date} {c['id']} {c['verdict']} {c['first'].replace('**', '') or '(无结论)'}{led}")
        secs.append((f"\n已关节点 {len(r['closed'])} 个（日期新→旧；日期取结论首句里写的，没写的标「入档」= 这个节点在 git 里变成 closed 的那次提交）：",
                     rows, 0.6))
        rows = [f"{o['id']} {','.join(f'{x}[{st}]' for x, st in o['nodes'])} {progress.cut(o['text'], 160) or '(结论与读数都空)'}"
                for o in r["open_rows"]]
        secs.append((f"\n挂在未关节点上的台账行 {len(r['open_rows'])} 行（后写的在前；结论列，空的给读数列）：", rows, 0.3))
    else:
        secs.append((f"\nplan 已勾 {len(r['plan_done'])}/{r['plan_total']}：", r["plan_done"] or ["(无)"], 0.6))
    if r["pushed"] or r["kind"] == "engineering":
        secs.append((f"\n已推送（state「线程」）{len(r['pushed'])} 条：", r["pushed"] or ["(无)"], 0.3))
    if full:
        return "\n".join(head + [x for t, items, _ in secs for x in [t] + items])
    left = LIMIT - sum(len(x.encode()) + 1 for x in head)
    out = list(head)
    for k, (t, items, share) in enumerate(secs):
        # 前面的节用不完的预算留给后面
        b = left if k == len(secs) - 1 else int(left * share / sum(x[2] for x in secs[k:]))
        part = fit(t, items, b, s)
        out += part
        left -= sum(len(x.encode()) + 1 for x in part)
    return "\n".join(out)


def main(argv):
    args = [a for a in argv if a != "--all"]
    if len(args) != 1 or not os.path.isfile(os.path.join(args[0], "charter.md")):
        print("用法: results.py <档案目录> [--all]", file=sys.stderr)
        return 2
    print(text(args[0], "--all" in argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
