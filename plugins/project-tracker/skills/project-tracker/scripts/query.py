#!/usr/bin/env python3
"""query.py — 按锚点取档案：pt get / pt find / pt conditions，以及重算目录 index.tsv。数据都来自 records.load。只用标准库。

  query.py index <档案目录>                    重算 <档案>/index.tsv，打印行数与字节数
  query.py get <档案目录> <编号> [--page N]    取单条：卡、挂着的台账行、指向证据与上级的指针；每页 ≤3 KB，超出给「接着看」的命令
  query.py find <档案目录> <词> [词 ...]       在目录里找（各词都要出现，不分大小写），返回匹配的行
  query.py conditions <档案目录>               条件与状态（charter「完成标准」的 G 行；没登记的原样列出旧完成标准）
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import records  # noqa: E402
import tree  # noqa: E402

PAGE = 3 * 1024
FIND_MAX = 20
TITLE_W = 50


def nb(s):
    return len(s.encode())


def pages(text, size=PAGE, foot=160):
    """按字节切页：尽量在行尾切；一行比一页还长就在字符边界上切开。"""
    room, out, cur = size - foot, [], ""
    for ln in text.split("\n"):
        while nb(ln) > room:
            if cur:
                out.append(cur)
                cur = ""
            b = ln.encode()[:room].decode("utf-8", "ignore")
            out.append(b)
            ln = ln[len(b):]
        if cur and nb(cur) + 1 + nb(ln) > room:
            out.append(cur)
            cur = ln
        else:
            cur = ln if not cur else cur + "\n" + ln
    if cur or not out:
        out.append(cur)
    return out


def cond_line(c, short=False):
    lt, best = c["latest"], c["best"]
    def v(j):
        return f"{j['verdict']}" + (f" {j['value']:g}" if j["value"] is not None else "") + \
            f"（{j['eid']}，{j['date'] or '日期不明'}）"
    bits = [f"线 {c['line'] or '—'}"]
    if lt:
        bits.append("最近 " + v(lt))
    if best and best is not lt:
        bits.append("最好 " + v(best))
    if short:
        return f"{c['id']} [{c['status']}] {records.cut(c['text'], 30)} — " + "；".join(bits)
    return f"{c['id']} [{c['status']}] {c['text']}\n    " + "；".join(bits) + \
        f"\n    尺：{c['ruler'] or '—'}；来源：{c['source'] or '—'}；判定 {len(c['judgments'])} 次"


def conditions_text(rec):
    s, cs = rec["slug"], rec["conditions"]
    out = [f"条件 · {s}（charter「完成标准」；状态只从点名该条件的判定里算：台账结论列以「过 G2」「不过 G2=15.3」开头，"
           "journal「结果」条目里写「G3 过 <证据>」）"]
    if not cs["registered"]:
        out.append("未登记：完成标准还没按「- G1 陈述 | 线: … | 尺: … | 来源: …」写，下面原样列出，状态一律「未登记」。")
        out += [f"  {x}" for x in cs["legacy"]] or ["  (charter 没有「完成标准」小节)"]
        return "\n".join(out)
    n = len(cs["items"])
    cnt = {}
    for c in cs["items"]:
        cnt[c["status"]] = cnt.get(c["status"], 0) + 1
    out.append(f"共 {n} 条：" + "，".join(f"{k} {v}" for k, v in cnt.items()))
    for c in cs["items"]:
        out.append(cond_line(c))
        for j in c["judgments"][-5:]:
            val = f"={j['value']:g}" if j["value"] is not None else ""
            out.append(f"      {j['date'] or '?'} {j['verdict']}{val} {j['eid']}（{j['where']}）")
        if c["bad"]:
            out.append(f"    （格式：{c['bad']}）")
    if cs["orphans"]:
        out.append("点名了没登记的条件：" + "、".join(sorted({j['cid'] for j in cs["orphans"]})))
    return "\n".join(out)


def row_text(rec, k, indent="  "):
    r = rec["rows"][k]
    o = [f"{indent}{r['id']} · {r['status']} · {r['date'] or '日期不明'} · {r['where']}"]
    if r["raw"]:
        o.append(f"{indent}  （格数与表头不符，原样）{r['raw']}")
        return o
    for h, c in zip(r["header"], r["cells"]):
        hn = tree.norm_head(h)
        if hn in ("id",) + tree.NODE_HEADS or not c.strip():
            continue
        o.append(f"{indent}  {h.strip()}：{' '.join(c.split())}")
    return o


def node_ref(rec, i):
    n = rec["nodes"].get(i)
    return f"{i} [{n['shown']}] {records.cut(n['title'], TITLE_W)}" if n else f"{i}（不存在）"


def get_node(rec, i):
    n, s = rec["nodes"][i], rec["slug"]
    kind = "问题" if n["kind"] == "Q" else "假设"
    o = [f"{i} · {kind} · {n['shown']} · {n['date'] or '日期不明'}（{n['date_src']}） · {n['file']}",
         f"标题：{n['title']}"]
    if n["card_src"] == "card":
        o.append("卡" + ("（含更正）" if n["corrected"] else "") + "：")
    else:
        o.append("卡（原文摘取：这个节点还没有短卡，以下由程序从原文摘出" + ("，结论取自「更正」" if n["corrected"] else "") + "）：")
    o += [f"  {k}：{v}" for k, v in n["card"].items()] or ["  (无)"]
    if n["parent"]:
        o.append(f"上级：{node_ref(rec, n['parent'])}")
    if n["by"]:
        o.append("被取代于：" + "；".join(node_ref(rec, b) for b in n["by"]))
    judged = [f"{j['verdict']} {j['cid']}（{j['eid']}）" for k in n["rows"] for j in rec["rows"][k]["judgments"]]
    if judged:
        o.append("判定的条件：" + "、".join(judged))
    if n["kind"] == "Q":
        t = rec["tree"]
        know = tree.section(t.nodes[i], "当前认识") if t else ""
        if know:
            o.append("当前认识：")
            o += [f"  {ln}" for ln in know.split("\n")]
        if n["children"]:
            o.append(f"子节点 {len(n['children'])} 个：")
            o += [f"  {node_ref(rec, c)}" for c in n["children"]]
        meas = rec["measurements"].get(i, [])
        if meas:
            o.append(f"直接挂在这个问题上的测量 {len(meas)} 行（不属于任何假设；详情 pt get {s} <编号>）：")
            o += [f"  {rec['rows'][k]['id']} · {rec['rows'][k]['date'] or '?'} · "
                  f"{records.cut(rec['rows'][k]['reading'] or rec['rows'][k]['raw'], 90)}" for k in meas]
    else:
        if n["children"]:
            o.append("子节点：" + "；".join(node_ref(rec, c) for c in n["children"]))
        if n["rows"]:
            o.append(f"台账 {len(n['rows'])} 行：")
            for k in n["rows"]:
                o += row_text(rec, k)
        else:
            o.append("台账：没有挂在这个节点上的行")
    o.append(f"全文：{rec['dir']}/{n['file']}（判别、结论、教训都在里面）")
    return "\n".join(o)


def get_row(rec, keys):
    o = []
    for k in keys:
        r = rec["rows"][k]
        o.append(f"{r['id']} · 台账行 · {r['status']} · {r['date'] or '日期不明'} · {r['where']}")
        o += row_text(rec, k, "")[1:]
        if r["nodes"]:
            o.append("判的节点：" + "；".join(node_ref(rec, x) for x in r["nodes"]))
            ups = {rec["nodes"][x]["parent"] for x in r["nodes"] if x in rec["nodes"] and rec["nodes"][x]["parent"]}
            if ups - set(r["nodes"]):
                o.append("上级问题：" + "；".join(node_ref(rec, x) for x in sorted(ups - set(r["nodes"]), key=tree.id_key)))
    return "\n".join(o)


def get_cond(rec, c):
    return cond_line(c) + "\n" + "\n".join(
        f"  {j['date'] or '?'} {j['verdict']}" + (f"={j['value']:g}" if j["value"] is not None else "") +
        f" {j['eid']}（{j['where']}）" + (f" {j['note']}" if j.get("note") else "") for j in c["judgments"]) + \
        (f"\n  （格式：{c['bad']}）" if c["bad"] else "") + f"\n  定义：{rec['dir']}/charter.md:{c['lineno']}"


def get_span(rec, path, start, end, head):
    lines = records.lint.read(os.path.join(rec["dir"], path)).split("\n")[start - 1:end]
    while lines and not lines[-1].strip():
        lines.pop()
    return f"{head} · {path}:{start}\n" + "\n".join(lines)


def get_text(rec, want):
    if want in rec["nodes"]:
        return get_node(rec, want)
    keys = [k for k in rec["row_order"] if rec["rows"][k]["id"] == want]
    if keys:
        return get_row(rec, keys)
    for c in rec["conditions"]["items"]:
        if c["id"] == want:
            return get_cond(rec, c)
    for a in rec["adrs"]:
        if a["id"] == want:
            return get_span(rec, "decisions.md", a["lineno"], a["end"], f"{a['id']} · ADR · {a['date'] or '日期不明'}")
    js = rec["journal"]
    for k, e in enumerate(js):
        if e["id"] == want:
            end = js[k + 1]["lineno"] - 1 if k + 1 < len(js) else 10 ** 9
            return get_span(rec, "journal.md", e["lineno"], end, f"{e['id']} · journal · {e['category'] or '旧格式'}")
    return None


def resolve(rec, want):
    """精确编号优先；再试不分大小写。"""
    names = list(rec["nodes"]) + [rec["rows"][k]["id"] for k in rec["row_order"]] + \
        [c["id"] for c in rec["conditions"]["items"]] + [a["id"] for a in rec["adrs"]] + [e["id"] for e in rec["journal"]]
    if want in names:
        return want
    low = [x for x in names if x.lower() == want.lower()]
    return low[0] if low else None


def cmd_get(d, want, page):
    rec = records.load(d)
    s = rec["slug"]
    hit = resolve(rec, want)
    if hit is None:
        print(f"没有编号 {want}。在目录里找：pt find {s} {want}")
        return 1
    ps = pages(get_text(rec, hit))
    page = min(max(page, 1), len(ps))
    print(ps[page - 1])
    if len(ps) > 1:
        nxt = f"；接着看：pt get {s} {hit} --page {page + 1}" if page < len(ps) else "；已是最后一页"
        print(f"（第 {page}/{len(ps)} 页，每页 ≤{PAGE // 1024} KB{nxt}）")
    return 0


def cmd_find(d, words):
    p = records.ensure_index(d)
    lines = records.lint.read(p).rstrip("\n").split("\n")
    ws = [w.lower() for w in words]
    hit = [ln for ln in lines[1:] if all(w in ln.lower() for w in ws)]
    slug = os.path.basename(os.path.abspath(d))
    if not hit:
        print(f"目录里没有同时含「{' '.join(words)}」的行（目录 {p}）。全文找：grep -rn '{words[0]}' {os.path.abspath(d)}")
        return 1
    print(lines[0])
    print("\n".join(hit[:FIND_MAX]))
    if len(hit) > FIND_MAX:
        print(f"（共 {len(hit)} 行，只列前 {FIND_MAX} 行；加词缩小，或 grep -i '{words[0]}' {p}）")
    print(f"（取单条：pt get {slug} <编号>）")
    return 0


def main(argv):
    if len(argv) < 2 or argv[0] not in ("index", "get", "find", "conditions"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, d = argv[0], argv[1]
    if not os.path.isfile(os.path.join(d, "charter.md")):
        print(f"query.py: 不是项目档案目录：{d}", file=sys.stderr)
        return 2
    if cmd == "index":
        text = records.write_index(d)
        print(f"{os.path.join(d, 'index.tsv')}: {text.count(chr(10)) - 1} 行，{nb(text)} 字节")
        return 0
    if cmd == "conditions":
        print(conditions_text(records.load(d)))
        return 0
    if cmd == "find":
        if len(argv) < 3:
            print("用法: query.py find <档案目录> <词> [词 ...]", file=sys.stderr)
            return 2
        return cmd_find(d, argv[2:])
    rest = argv[2:]
    page = 1
    if "--page" in rest:
        k = rest.index("--page")
        try:
            page = int(rest[k + 1])
        except (IndexError, ValueError):
            print("--page 要一个页码", file=sys.stderr)
            return 2
        rest = rest[:k] + rest[k + 2:]
    if len(rest) != 1:
        print("用法: query.py get <档案目录> <编号> [--page N]", file=sys.stderr)
        return 2
    return cmd_get(d, rest[0], page)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
