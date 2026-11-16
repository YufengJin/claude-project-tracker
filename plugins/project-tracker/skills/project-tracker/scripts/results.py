#!/usr/bin/env python3
"""results.py — 一个项目「得到了什么」：pt results 的文本与 tree.html「结果」页用同一份数据。只读档案，只用标准库。

  results.py <档案目录> [--all]      默认不超过 4 KB，--all 给全量

有 verifier.md 的先给「考官与门槛」：标题含门槛/指标/主分的小节摘几行（共 ≤600 字节，提到门槛/过线/放行/硬门/主分的行先保），
不解析数值、不判过没过；摘不到给一行指针。
研究项目：「当前认识」第 1 条 → 已关节点按日期倒序（日期 ID verdict 标题 — 结论首句 [台账 id]；日期取结论首句里写的，
没写取入档日期，即这个节点在 git 里变成 closed 的那次提交）→ 挂在未关节点上的台账行（读数列与结论列都给、各带列名；
这一行的格数与表头对不上时按列名取不准，原样给整行）。
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
TITLE_WIDTH = 40
FIELD_WIDTH = 80
GATE_BYTES = 600
GATE_LINE_BYTES = 160
GATE_HEADS = ("门槛", "指标", "主分")
GATE_WORDS = ("门槛", "过线", "放行", "硬门", "主分")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def ledger_cell(row, names):
    """台账行里按表头名取的那一格（第一个名字对上的列）；没有这列或为空给空串。"""
    head = [tree.norm_head(h) for h in row["table"]["header"]]
    for name in names:
        for k, h in enumerate(head):
            if h.startswith(name) and k < len(row["cells"]):
                return " ".join(tree.cell(row["cells"][k]).split())
    return ""


def ledger_fields(row):
    """(读数, 结论, 原样)。格数与表头对不上（作者漏格或单元格里有没转义的竖线）时按列名取不准：只给原样整行（去掉 id 格）。"""
    if len(row["cells"]) != len(row["table"]["header"]):
        return "", "", " | ".join(" ".join(tree.cell(c).split()) for c in row["cells"][1:])
    return ledger_cell(row, ("读数", "result")), ledger_cell(row, ("结论", "conclusion")), ""


def ledger_text(o, width=None):
    """台账行的显示文本：读数与结论各带列名（列名照表头，作者在结论列写的「预测：…」也原样，读的人自己看得出）。"""
    c = (lambda x: progress.cut(x, width)) if width else (lambda x: x)
    if o["raw"]:
        return "（格数与表头不符，原样）" + c(o["raw"])
    parts = [f"读数：{c(o['reading'])}" if o["reading"] else "", f"结论：{c(o['concl'])}" if o["concl"] else ""]
    return " ｜ ".join(x for x in parts if x)


def cut_bytes(s, n):
    if len(s.encode()) <= n:
        return s
    b = s.encode()[:max(n - 3, 0)].decode("utf-8", "ignore")
    return b + "…"


def gate(d):
    """verifier.md 里标题含门槛/指标/主分的小节摘几行：(小节标题列表, 行列表)；没有 verifier.md 给 None。
    先保提到门槛/过线/放行/硬门/主分的行（每行 ≤160 字节），再按原顺序补别的行，总共 ≤600 字节，按原顺序输出。不解析数值。"""
    raw = tree.strip_comments(progress.read(os.path.join(d, "verifier.md")))
    if not raw.strip():
        return None
    heads, lines, take, fence = [], [], False, False
    for ln in raw.replace("\r\n", "\n").split("\n"):
        if tree.FENCE_RE.match(ln):
            fence = not fence
            continue
        m = None if fence else HEADING.match(ln)
        if m:
            take = any(w in m.group(2) for w in GATE_HEADS)
            if take:
                heads.append(m.group(2).strip())
            continue
        if take and ln.strip() and not re.match(r"^\s*<.*>\s*$", ln):  # 模板占位 <…> 不算
            lines.append(" ".join(ln.split()).replace("**", ""))
    keep, used = {}, 0
    for pick in (lambda x: any(w in x for w in GATE_WORDS), lambda x: True):
        for k, ln in enumerate(lines):
            if k in keep or not pick(ln):
                continue
            room = min(GATE_LINE_BYTES, GATE_BYTES - used)
            if room < 80:
                break
            keep[k] = cut_bytes(ln, room)
            used += len(keep[k].encode()) + 1
    return heads, [keep[k] for k in sorted(keep)]


def data(d, ref=None):
    """{kind, belief, belief_src, closed: [...], open_rows: [...], plan_done, plan_total, pushed}。"""
    ref = ref or progress.today()
    state = progress.read(os.path.join(d, "state.md"))
    research = os.path.isdir(os.path.join(d, "tree"))
    t = tree.Tree(d) if research else None
    belief, src = progress.belief_of(d, t, state)
    out = {"slug": os.path.basename(os.path.abspath(d)), "kind": "research" if research else "engineering",
           "belief": belief, "belief_src": src, "closed": [], "open_rows": [], "plan_done": [], "plan_total": 0,
           "pushed": [], "gate": gate(d)}
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
                reading, concl, raw = ledger_fields(r)
                out["open_rows"].append({"id": r["id"] or "?", "nodes": [(x, t.nodes[x]["status"]) for x in live],
                                         "reading": reading, "concl": concl, "raw": raw})
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
    if r["gate"] is not None:
        heads, lines = r["gate"]
        if lines:
            head.append(f"考官与门槛（摘自 verifier.md「{'」「'.join(heads)}」，只摘不判；全文与判定依据见 verifier.md）：")
            head += [f"  {x}" for x in lines]
        else:
            head.append("考官与门槛：见 verifier.md（没有标题含门槛 / 指标 / 主分的小节可摘）")
    head.append(f"现在最信的一条（{r['belief_src']}）：{r['belief']}" if r["belief"] else
                "现在最信的一条：—（" + ("根节点没有「当前认识」" if r["kind"] == "research" else "state 没有「## 当前认识」") + "）")
    secs = []  # (标题, 条目, 预算份额)
    if r["kind"] == "research":
        rows = []
        for c in r["closed"]:
            date = {"结论": c["date"], "入档": f"入档 {c['date']}", "未提交": "未提交"}[c["how"]]
            led = f" [{', '.join(c['ledger'])}]" if c["ledger"] else ""
            title = progress.cut(c["title"].replace("**", ""), TITLE_WIDTH) or "(无标题)"
            rows.append(f"{date} {c['id']} {c['verdict']} {title} — {c['first'].replace('**', '') or '(无结论)'}{led}")
        secs.append((f"\n已关节点 {len(r['closed'])} 个（日期 ID verdict 标题 — 结论首句；日期新→旧，取结论首句里写的，没写的标「入档」= 这个节点在 git 里变成 closed 的那次提交）：",
                     rows, 0.6))
        rows = [f"{o['id']} {','.join(f'{x}[{st}]' for x, st in o['nodes'])} {ledger_text(o, FIELD_WIDTH) or '(结论与读数都空)'}"
                for o in r["open_rows"]]
        secs.append((f"\n挂在未关节点上的台账行 {len(r['open_rows'])} 行（后写的在前；读数列与结论列照表头列名给出）：", rows, 0.3))
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
