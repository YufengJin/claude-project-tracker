#!/usr/bin/env python3
"""records.py — 一个项目的全部结构化内容：短卡、条件与状态、节点、台账行、ADR、journal 标题、目录 index.tsv。
简报、pt get / find / conditions、lint 与页面生成器都只通过这里取数。只读档案；只写 <档案>/index.tsv
（并把它记进 <档案>/.git/info/exclude，不进提交）和 <档案根>/.cache/index-<slug>.sig。只用标准库。

load(d) 返回（字段缺就是空串、空表或 None，不猜）：
{
  "slug", "dir", "name": charter 标题, "status": charter Status, "status_short": 进行中|暂停|已完成|已放弃|其他原文,
  "kind": "research"（有 tree/）| "engineering",
  "state": {"fixed": state 是否合格的固定小节, "summary": 一句话, "focus": [节点 ID], "sections": [(标题, 正文)]},
  "pending": [state 里标题含待拍板 / 待用户 / 等用户的小节的条目（一行一条，条数与 pt list 的「等用户」同口径）],
  "activity": {"date": 最近活动 YYYY-MM-DD 或 "", "src": 提交|journal|节点|"", "days": 距今天数或 None}（与 pt list 同一算法）,
  "terms": {术语: 释义}（charter 里标题以「术语」开头的小节，一行一条「- 词：释义」；没有就空）,
  "conditions": {
      "registered": charter「完成标准」里有没有 G 行,
      "items": [{"id": "G1", "text": 陈述, "line": 线（原文）, "line_set": 线定了没有, "ruler": 尺, "source": 来源,
                 "status": 过|不过|未测|线未定|不再适用, "direction": "min"|"max"|"",
                 "latest": 判定|None, "best": 判定|None, "judgments": [判定，旧→新], "lineno": charter 行号,
                 "target": 线里的数（线定了且有方向时）或 None, "gap": 最好值离线还差多少（≥0，0 = 已到线；算不出 None）,
                 "bad": 写不成格式时的原因（空串 = 合格）}],
      "legacy": [没登记时「完成标准」原样的行],
      判定 = {"verdict": 过|不过, "value": 数或 None, "eid": 证据编号, "date": YYYY-MM-DD 或 "", "where": "experiments.md:12" 等}},
  "nodes": {ID: {"id", "kind": "Q"|"H", "title", "status": open|active|parked|closed, "verdict", "by": [ID],
                 "shown": 显示状态（问题：已答|未答；假设：在做|待做|搁置|成立|不成立|没定论|被取代|放弃|未跑）,
                 "parent", "children": [ID], "card": {"目的", "怎么做", "结果", "结论"}（问题只有目的、结果；没有的键不出现）,
                 "card_src": "card"（作者写的卡）| "extract"（原文摘取）, "corrected": 卡或摘取取自「更正」,
                 "date", "date_src": 结论|入档|改动|未提交, "rows": [台账行 key], "file": "tree/H4.md"}},
  "rows": {key: {"key", "id", "nodes": [ID], "question", "reading", "concl", "raw"（格数与表头不符时的整行）, "status",
                 "date", "judgments": [判定], "where": "experiments.md:12", "header": [表头], "cells": [格], "line": 原行}},
  "row_order": [key]（台账从上到下）,
  "measurements": {问题 ID: [key]}（只挂在问题节点上、不挂假设的台账行）,
  "conditions" 里另有 "orphans": [点名了 charter 里没有的条件的判定],
  "tree": tree.Tree（研究项目）| None（给要原文的调用者，例如取「当前认识」）,
  "recent": [{"id", "kind", "date", "title", "line"}]（有结论的，新→旧：研究项目是已关节点，工程项目是 journal「结果」「决定」条目）,
  "adrs": [{"id", "title", "date", "status", "where", "lineno"}],
  "journal": [{"id": "J2026-11-16.1", "date", "category", "title", "where", "lineno"}],
  "glossary": {编号: 标题}（节点、台账行、ADR、条件）,
}
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal as jmod  # noqa: E402
import lint  # noqa: E402
import progress  # noqa: E402
import tree  # noqa: E402

CARD_MAX = 600
H_SHOWN = {"supported": "成立", "refuted": "不成立", "inconclusive": "没定论", "superseded": "被取代", "abandoned": "放弃"}
OPEN_SHOWN = {"active": "在做", "open": "待做", "parked": "搁置"}
COND_HEAD = "完成标准"
COND_LINE = re.compile(r"^\s*[-*+]\s+(?:\[[ xX✓]\]\s*)?\**(G\d+[a-z]?)\**(?![\w-])[\s:：.、]*(.*)$")
LINE_UNSET = re.compile(r"^\s*(|待.*|未定.*|推荐待定.*|<.*>|tbd|\?|？|—|-|–)\s*$", re.I)
NUM = r"[-+−]?\d+(?:\.\d+)?"
JUDGE_LEDGER = re.compile(rf"^(不过|过)\s*(G\d+[a-z]?)(?![\w-])(?:\s*[=＝]\s*({NUM}))?")
JUDGE_JOURNAL = re.compile(rf"^\s*(?:[-*+]\s+)?\**(?:(G\d+[a-z]?)\s*(不过|过)|(不过|过)\s*(G\d+[a-z]?))(?![\w-])\**"
                           rf"(?:\s*[=＝]?\s*({NUM}))?\s*(.*)$")
JUDGE_SEP = re.compile(r"^[\s,，、;；/]+")
MIN_WORDS = ("≤", "<=", "<", "不超过", "以内", "以下", "至多", "不大于", "小于")
MAX_WORDS = ("≥", ">=", ">", "不低于", "至少", "以上", "不小于", "大于")
CORR_PARA = re.compile(r"^\**[^\s：:，,。]{0,6}更正[^：:\n]{0,60}?[：:]\**\s*")
ID_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])((?:ADR-\d+)|[QHEG]\d+[a-z]?)(?![A-Za-z0-9_])")
INDEX_COLS = ("编号", "类型", "状态", "日期", "标题", "一行结果", "位置")
STATE_KEEP = (("一句话",), ("焦点", "研究树", "现在在哪", "进行中"), ("下一步",), ("待拍板", "等用户", "待用户"))


# ---------- 小工具 ----------

def clean(s):
    """去粗体、[[ID]] → ID、压空白。"""
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s or "").replace("**", "")
    return " ".join(s.split())


def lead(text, cap=200, short=20):
    """一段文字的头一句（太短就带上第二句），去列表记号与粗体，截到 cap 个字。"""
    p = clean(tree.first_para(text))
    p = re.sub(r"^(?:[-*+]|\d+[.)、])\s+", "", p)
    out, rest = "", p
    while rest:
        m = re.search(r"[。！？!?；;]|\.\s", rest)
        sent, rest = (rest[:m.end()], rest[m.end():].lstrip()) if m else (rest, "")
        out += sent
        if len(out) >= short:
            break
    out = out.strip()
    return out if len(out) <= cap else out[:cap - 1] + "…"


def cut(s, n):
    return progress.cut(clean(s), n) if s else ""


def num(s):
    try:
        return float(s.replace("−", "-"))
    except (TypeError, ValueError):
        return None


def norm_num(x):
    """7.50 与 7.5 当同一个数。"""
    v = num(x)
    return x if v is None else ("%g" % v)


# ---------- 节点 ----------

def correction(n):
    """节点里「更正」之后的说法：(文本, 出处)；没有给 ("", "")。结论节之外标题含「更正」的节取最后一个；
    否则结论与非固定节里以「…更正…：」开头的段落取最后一段。"""
    secs = [(h, b) for h, b in n["sections"] if "更正" in h and tree.sec_name(h) != "结论"]
    if secs and lead(secs[-1][1]):
        return lead(secs[-1][1]), f"「## {secs[-1][0]}」"
    hit = ("", "")
    for h, b in n["sections"]:
        if tree.sec_name(h) not in (None, "结论"):
            continue
        for para in re.split(r"\n\s*\n", b):
            p = para.strip()
            m = CORR_PARA.match(p)
            if m and lead(p[m.end():]):
                hit = (lead(p[m.end():]), f"「{clean(p[:m.end()]).rstrip('：:')}」")
    return hit


def method_of(n):
    """原文摘取的「怎么做」：判别里「命题 / 做法 / 方法 / 怎么做：」那一行（冒号后空着就取下面几行），
    没有就跳过「来源 / 来由 / 为什么」行取首句。"""
    body = tree.section(n, "判别")
    lines = [ln for ln in body.split("\n") if ln.strip()]
    for k, ln in enumerate(lines):
        m = re.match(r"^\s*(?:[-*+]\s+)?\**(命题|做法|方法|怎么做|设计)\**\s*[：:]\s*(.*)$", ln)
        if m and m.group(2).strip():
            return lead(m.group(2))
        if m:
            nxt = "\n".join(lines[k + 1:k + 4])
            if lead(nxt):
                return lead(nxt)
    keep = [ln for ln in lines if not re.match(r"^\s*(?:[-*+]\s+)?\**(来源|来由|为什么做|为什么|背景|出处)\**\s*[：:]", ln)]
    return lead("\n".join(keep)) if keep else ""


def has_reading(r):
    """台账行有真读数：读数格不空、不是「（待回）」「待跑」「—」这类占位。"""
    x = clean(r["reading"] or r["raw"]).strip("（）() ")
    return bool(x) and not tree.is_blank(x) and not re.match(r"^(待|未跑|未测|未回|—|-)", x)


def verdict_of(n):
    """frontmatter 的 verdict 规范到五个值之一（「supported（下限对照成立…）」取前缀）。"""
    v = n["verdict"]
    return next((x for x in tree.VERDICTS if v.startswith(x)), v)


def node_card(n, rows):
    """(卡, 出处, 是否取自更正)。有作者写的卡就用它；否则原文摘取：标题作目的、判别首句作做法、
    台账读数（没有就结论首句）作结果、结论首句作结论，有「更正」取更正后的说法。"""
    c = tree.card(n)
    if c:
        if n["id"].startswith("Q"):
            c = {k: v for k, v in c.items() if k in ("目的", "结果")} or c
        return c, "card", any("更正" in v for v in c.values())
    concl = tree.section(n, "结论")
    fix, _src = correction(n)
    out = {"目的": clean(n["title"])}
    if n["id"].startswith("H"):
        m = method_of(n)
        if m:
            out["怎么做"] = m
        last = next((r for r in reversed(rows) if has_reading(r)), None)
        res = ""
        if last:
            res = f"[{last['id']}] " + cut(last["reading"] or last["raw"], 200)
        elif concl:
            res = lead(concl)
        if res:
            out["结果"] = res
        if fix:
            out["结论"] = "（更正）" + fix
        elif concl:
            out["结论"] = lead(concl)
    else:
        res = fix and "（更正）" + fix or (lead(concl) if concl else
                                          cut(progress.first_item(tree.section(n, "当前认识")), 200))
        if res:
            out["结果"] = res
    return out, "extract", bool(fix)


def shown(n, rows):
    if n["id"].startswith("Q"):
        return "已答" if n["status"] == "closed" else "未答"
    if n["status"] != "closed":
        return OPEN_SHOWN.get(n["status"], n["status"] or "?")
    concl, v = tree.section(n, "结论"), verdict_of(n)
    if not any(has_reading(r) for r in rows) and (v in ("superseded", "abandoned") or "未跑" in concl[:200]
                     or any("未跑" in h for h, _ in n["sections"] if tree.sec_name(h) == "结论")):
        return "未跑"
    return H_SHOWN.get(v, v or "?")


def node_date(n, filed, changed, today):
    """(日期, 出处)。已关：结论标题或结论首段里写明的日期（不晚于入档次日）→ 入档日期 → 未提交；没关：最近一次改动。"""
    if n["status"] != "closed":
        return (changed, "改动") if changed else ("", "未提交")
    fd = dt.date.fromisoformat(filed) if filed else None
    ref = fd or today
    heads = " ".join(h for h, _ in n["sections"] if tree.sec_name(h) == "结论")
    said = [x for x in lint.dates_in(heads + " " + tree.first_para(tree.section(n, "结论")), ref)
            if x <= ref + dt.timedelta(days=1)]
    if said:
        return max(said).isoformat(), "结论"
    if fd:
        return filed, "入档"
    return "", "未提交"


def node_changes(d):
    """各节点文件最近一次改动的提交日期（newest-first 日志里第一次出现）。"""
    out = {}
    for date, _subj, ch in progress.tree_log(d):
        for nid, _a, _b in ch:
            out.setdefault(nid, date)
    return out


# ---------- 台账 ----------

def ledger_dates(d, ids):
    """台账各行最近一次被改的提交日期：git log -p 新→旧，加号行第一、二格是已知 id 的就记下。"""
    out, date = {}, ""
    if not ids:
        return out
    log = progress.git(d, "log", "-p", "-U0", "--no-renames", "--no-color", "--format=%x01%as", "--", "experiments.md")
    for ln in log.split("\n"):
        if ln.startswith("\x01"):
            date = ln[1:11]
        elif ln.startswith("+") and not ln.startswith("+++") and "|" in ln:
            for c in tree.split_row(ln[1:])[:2]:
                k = re.sub(r"[*`]", "", c).strip()
                if k in ids and k not in out:
                    out[k] = date
                    break
    return out


def judgments_in_cell(text):
    """台账结论格开头的判定：「过 G2」「不过 G2=15.3」，可连写几个（逗号、分号隔开）。"""
    s, out = clean(text), []
    while True:
        m = JUDGE_LEDGER.match(s)
        if not m:
            return out
        out.append({"verdict": m.group(1), "cid": m.group(2), "value": num(m.group(3)) if m.group(3) else None})
        s = JUDGE_SEP.sub("", s[m.end():])


def ledger(t, d, today):
    import results  # noqa: E402  延迟导入：results 依赖 lint，lint 延迟依赖本模块
    rows, order, seen = {}, [], {}
    ids = {r["id"] for r in t.rows if r["id"]}
    dates = ledger_dates(d, ids)
    for r in t.rows:
        rid = r["id"] or "?"
        seen[rid] = seen.get(rid, 0) + 1
        key = rid if seen[rid] == 1 else f"{rid}#{seen[rid]}"
        reading, concl, raw = results.ledger_fields(r)
        question = results.ledger_cell(r, ("问题", "对照", "question")) if not raw else ""
        if not question and len(r["cells"]) > 2 and not raw:
            question = " ".join(tree.cell(r["cells"][2]).split())
        js = judgments_in_cell(concl)
        if raw and not js:  # 格数对不上：在各格里找以判定开头的
            for c in r["cells"][1:]:
                js = judgments_in_cell(tree.cell(c))
                if js:
                    break
        date = dates.get(rid, "")
        if not date:
            said = [x for x in lint.dates_in(r["line"], today) if x <= today]
            date = max(said).isoformat() if said else ""
        where = f"experiments.md:{r.get('no', '')}"
        for j in js:
            j.update(eid=rid, date=date, where=where)
        status = ("、".join(f"{j['verdict']} {j['cid']}" for j in js) if js
                  else "有读数" if (reading or raw) else "占行")
        rows[key] = {"key": key, "id": rid, "nodes": r["nodes"], "question": question, "reading": reading,
                     "concl": concl, "raw": raw, "status": status, "date": date, "judgments": js, "where": where,
                     "header": [tree.cell(h) for h in r["table"]["header"]], "cells": [tree.cell(c) for c in r["cells"]],
                     "line": r["line"]}
        order.append(key)
    return rows, order


# ---------- 条件 ----------

def cond_sections(charter):
    """charter 里标题以「完成标准」开头的二级小节：[(起始行号, [行])]（注释去掉，行号保住）。"""
    text = tree.strip_comments(charter, keep_lines=True)
    out, cur, fence = [], None, False
    for k, ln in enumerate(text.split("\n"), 1):
        if tree.FENCE_RE.match(ln):
            fence = not fence
        if not fence and ln.startswith("## "):
            cur = (k, []) if ln[3:].strip().startswith(COND_HEAD) else None
            if cur:
                out.append(cur)
            continue
        if cur is not None:
            cur[1].append((k, ln))
    return out


def direction(line):
    if any(w in line for w in MIN_WORDS):
        return "min"
    if any(w in line for w in MAX_WORDS):
        return "max"
    return ""


def parse_conditions(charter):
    items, legacy = [], []
    for _k, lines in cond_sections(charter):
        for no, ln in lines:
            m = COND_LINE.match(ln)
            if not m:
                if ln.strip():
                    legacy.append(ln.rstrip())
                continue
            cid, rest = m.group(1), m.group(2)
            parts = [p.strip() for p in tree.split_row(rest)] if "|" in rest else [rest.strip()]
            text, fields, bad = tree.cell(parts[0]), {}, []
            for p in parts[1:]:
                f = re.match(r"^(线|尺|来源)\s*[:：]\s*(.*)$", tree.cell(p))
                if f:
                    fields[f.group(1)] = f.group(2).strip()
                elif p:
                    bad.append(f"看不懂的一格「{cut(p, 20)}」")
            for k in ("线", "尺", "来源"):
                if k not in fields:
                    bad.append(f"缺「{k}:」")
            line = fields.get("线", "")
            retired = "不再适用" in ln or text.startswith("~~")
            items.append({"id": cid, "text": clean(text.strip("~")), "line": line,
                          "line_set": not LINE_UNSET.match(line), "ruler": fields.get("尺", ""),
                          "source": fields.get("来源", ""), "retired": retired, "direction": direction(line),
                          "status": "", "latest": None, "best": None, "judgments": [], "lineno": no,
                          "target": None, "gap": None,
                          "bad": "；".join(bad)})
    return items, legacy


def journal_judgments(entries):
    """journal「结果」条目（旧格式没有类别的也算）里以「G3 过 …」或「过 G3 …」开头的行。"""
    out = []
    for e in entries:
        cat = e["category"]
        if cat not in ("结果", None):
            continue
        for k, ln in enumerate(e["text"].split("\n")[1:], 1):
            m = JUDGE_JOURNAL.match(ln)
            if not m:
                continue
            cid, verdict = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            rest = m.group(6) or ""
            refs = [x for x in ID_TOKEN.findall(rest) if x != cid]
            out.append({"verdict": verdict, "cid": cid, "value": num(m.group(5)) if m.group(5) else None,
                        "eid": refs[0] if refs else e["id"], "date": e["date"],
                        "where": f"journal.md:{e['lineno'] + k}", "note": cut(rest, 80)})
    return out


def settle(items, judgments):
    by = {}
    for j in judgments:
        by.setdefault(j["cid"], []).append(j)
    for c in items:
        js = sorted(by.get(c["id"], []), key=lambda j: j["date"] or "0000")  # 稳定排序：同日按出现先后
        c["judgments"] = js
        c["latest"] = js[-1] if js else None
        vals = [j for j in js if j["value"] is not None]
        if vals and c["direction"]:
            pick = min if c["direction"] == "min" else max
            c["best"] = pick(vals, key=lambda j: j["value"])
        else:
            passed = [j for j in js if j["verdict"] == "过"]
            c["best"] = passed[-1] if passed else None
        m = re.search(NUM, c["line"]) if c["line_set"] and c["direction"] else None
        c["target"] = num(m.group(0)) if m else None
        b = c["best"]
        if c["target"] is not None and b and b["value"] is not None:
            g = b["value"] - c["target"] if c["direction"] == "min" else c["target"] - b["value"]
            c["gap"] = max(g, 0.0)
        if c["retired"]:
            c["status"] = "不再适用"
        elif not c["line_set"]:
            c["status"] = "线未定"
        elif not js:
            c["status"] = "未测"
        else:
            c["status"] = js[-1]["verdict"]
    return [j for j in judgments if j["cid"] not in {c["id"] for c in items}]


# ---------- journal 与 ADR ----------

def journal_entries(d):
    pre, entries = jmod.split(jmod.read_raw(os.path.join(d, "journal.md")))
    out, line, per = [], pre.count("\n") + 1, {}
    for e in entries:
        h = jmod.head(e)
        m = re.match(r"^## \[?(\d{4}-\d{2}-\d{2})\]?", h)
        anyd = m or lint.FULL_DATE.search(h)
        date = (m.group(1) if m else anyd.group(0)) if anyd else ""
        per[date] = per.get(date, 0) + 1
        jid = f"J{date}.{per[date]}" if date else f"J#{len(out) + 1}"
        nm = jmod.NEW_HEAD.match(h)
        if nm:
            parts = h.split(" | ", 2)
            title = " | ".join(parts[1:])
        else:
            title = re.sub(r"^## \[?\d{4}-\d{2}-\d{2}\]?\s*[·:：-]?\s*", "", h) if m else h[3:]
        out.append({"id": jid, "date": date, "category": jmod.category(e), "title": clean(title),
                    "where": f"journal.md:{line}", "lineno": line, "text": e})
        line += e.count("\n")
    return out


def adr_list(d):
    raw = lint.read(os.path.join(d, "decisions.md"))
    lines = tree.strip_comments(raw, keep_lines=True).split("\n")
    out, cur = [], None
    for k, ln in enumerate(lines, 1):
        m = re.match(r"^## (ADR-\d+)\b\s*[:：·.\-—]?\s*(.*)$", ln)
        if m:
            title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[·:：]\s*", "", m.group(2).strip())
            said = lint.FULL_DATE.search(m.group(2))
            cur = {"id": m.group(1), "title": clean(title), "date": said.group(0) if said else "", "status": "",
                   "where": f"decisions.md:{k}", "lineno": k, "end": len(lines)}
            if out:
                out[-1]["end"] = k - 1
            out.append(cur)
        elif ln.startswith("## ") and cur:
            cur["end"] = k - 1
            cur = None
        elif cur:
            f = re.match(r"^(Date|Status|日期|状态)\s*[:：]\s*(.*)$", ln)
            if f and f.group(1) in ("Date", "日期") and not cur["date"]:
                said = lint.FULL_DATE.search(f.group(2))
                cur["date"] = said.group(0) if said else ""
            elif f and not cur["status"]:
                cur["status"] = f.group(2).strip()
    return out


# ---------- state ----------

def state_info(d, has_tree):
    raw = lint.read(os.path.join(d, "state.md"))
    secs = [(h[3:].strip(), "\n".join(b).strip("\n")) for h, b in lint.sections(tree.strip_comments(raw))]
    summary = next((lead(b, 300) for h, b in secs if h.startswith("一句话")), "")
    return {"fixed": lint.state_ok(raw, has_tree), "summary": summary,
            "focus": tree.state_focus(d), "sections": secs, "raw": raw}


def pending_items(state_raw):
    """state 里待拍板类小节的条目；与 progress.pending 同口径：条目都带 [待用户 MM-DD] 就全算，否则只算顶层列表项（没有列表就算顶格行）。"""
    secs = [b for h, b in progress.sections(tree.strip_comments(state_raw)) if any(k in h for k in progress.PEND_HEADS)]
    ents = [e for b in secs for e in progress.entries(b)]
    if ents and not all(progress.PEND_TAG.match(progress.ITEM_MARK.sub("", e, count=1)) for e in ents):
        ents = [e for e in ents if progress.ITEM_MARK.match(e)] or ents
    return [clean(progress.ITEM_MARK.sub("", e, count=1)) for e in ents]


def activity(d, today):
    try:
        r = progress.project_row(d, ref=today)
        return {"date": r["act"], "src": r["act_src"], "days": r["days"]}
    except Exception:  # 算不出不拖垮取数
        return {"date": "", "src": "", "days": None}


def terms_of(charter):
    out = {}
    for h, body in lint.sections(tree.strip_comments(charter)):
        if not h[3:].strip().startswith("术语"):
            continue
        for ln in body:
            m = re.match(r"^\s*[-*+]\s+\**([^：:*]{1,30}?)\**\s*[：:]\s*(.+)$", ln)
            if m:
                out[clean(m.group(1))] = clean(m.group(2))
    return out


# ---------- 汇总 ----------

def load(d, today=None):
    d = os.path.abspath(d)
    today = today or progress.today()
    charter = lint.read(os.path.join(d, "charter.md"))
    title = next((ln[2:].strip() for ln in charter.split("\n") if ln.startswith("# ")), "")
    research = os.path.isdir(os.path.join(d, "tree"))
    rec = {"slug": os.path.basename(d), "dir": d, "name": title, "status": lint.field(charter, "Status"),
           "status_short": progress.status_of(charter),
           "kind": "research" if research else "engineering", "state": state_info(d, research),
           "nodes": {}, "rows": {}, "row_order": [], "measurements": {}, "recent": [], "glossary": {}}
    t = tree.Tree(d) if research else None
    rec["tree"] = t
    if t is not None:
        rows, order = ledger(t, d, today)
    elif os.path.isfile(os.path.join(d, "experiments.md")):
        tables, rws, _w = tree.parse_ledger(os.path.join(d, "experiments.md"))
        fake = type("T", (), {"rows": rws})()
        rows, order = ledger(fake, d, today)
    else:
        rows, order = {}, []
    rec["rows"], rec["row_order"] = rows, order
    by_id = {}
    for k in order:
        by_id.setdefault(rows[k]["id"], []).append(k)
    if t is not None:
        ids_closed = [i for i, n in t.nodes.items() if n["status"] == "closed"]
        filed = progress.closed_dates(d, ids_closed)
        changed = node_changes(d)
        for i in sorted(t.nodes, key=tree.id_key):
            n = t.nodes[i]
            keys = []
            for r in t.rows_of.get(i, []):
                for k in by_id.get(r["id"] or "?", []):
                    if rows[k]["line"] == r["line"] and k not in keys:
                        keys.append(k)
            nr = [rows[k] for k in keys]
            card, src, corr = node_card(n, nr)
            date, how = node_date(n, filed.get(i, ""), changed.get(i, ""), today)
            rec["nodes"][i] = {"id": i, "kind": i[0], "title": clean(n["title"]), "status": n["status"],
                               "verdict": verdict_of(n), "by": n["by"], "shown": shown(n, nr), "parent": n["parent"],
                               "children": list(t.children.get(i, [])), "card": card, "card_src": src,
                               "corrected": corr, "date": date, "date_src": how, "rows": keys, "file": f"tree/{i}.md"}
        for k in order:
            r = rows[k]
            live = [x for x in r["nodes"] if x in t.nodes]
            if live and not any(x.startswith("H") for x in live):
                for x in live:
                    rec["measurements"].setdefault(x, []).append(k)
    items, legacy = parse_conditions(charter)
    entries = journal_entries(d)
    js = [j for k in order for j in rows[k]["judgments"]] + journal_judgments(entries)
    orphan = settle(items, js)
    rec["conditions"] = {"registered": bool(items), "items": items, "legacy": [] if items else legacy,
                         "orphans": orphan}
    rec["adrs"] = adr_list(d)
    rec["pending"] = pending_items(rec["state"]["raw"])
    rec["activity"] = activity(d, today)
    rec["terms"] = terms_of(charter)
    rec["journal"] = [{k: v for k, v in e.items() if k != "text"} for e in entries]
    if t is not None:
        closed = [x for x in rec["nodes"].values() if x["status"] == "closed"]
        closed.sort(key=lambda x: tree.id_key(x["id"]), reverse=True)
        closed.sort(key=lambda x: x["date"] or "9999", reverse=True)
        rec["recent"] = [{"id": x["id"], "kind": x["kind"], "date": x["date"], "title": x["title"],
                          "line": x["card"].get("结论") or x["card"].get("结果", ""), "shown": x["shown"],
                          "card_src": x["card_src"]} for x in closed]
    else:
        pick = [e for e in rec["journal"] if e["category"] in ("结果", "决定", None)]  # None = 旧格式标题
        rec["recent"] = [{"id": e["id"], "kind": "J", "date": e["date"], "title": e["title"], "line": e["title"],
                          "shown": e["category"] or "", "card_src": ""} for e in reversed(pick)]
    g = rec["glossary"]
    for i, n in rec["nodes"].items():
        g[i] = n["title"]
    for k in order:
        g.setdefault(rows[k]["id"], cut(rows[k]["question"] or rows[k]["reading"] or rows[k]["raw"], 80))
    for a in rec["adrs"]:
        g.setdefault(a["id"], a["title"])
    for c in items:
        g.setdefault(c["id"], c["text"])
    return rec


# ---------- 目录 index.tsv ----------

def tsv_cell(s):
    return " ".join(str(s or "").replace("\t", " ").split())


def index_rows(rec):
    out = []
    for i, n in rec["nodes"].items():
        c = n["card"]
        res = c.get("结果") or c.get("结论") or ""
        if n["card_src"] == "extract" and res:
            res = "（原文摘取）" + res
        out.append((i, "问题" if n["kind"] == "Q" else "假设", n["shown"], n["date"], n["title"], cut(res, 120), n["file"]))
    for k in rec["row_order"]:
        r = rec["rows"][k]
        out.append((k, "台账", r["status"], r["date"], cut(r["question"] or r["raw"], 100),
                    cut(r["reading"] or r["raw"], 120), r["where"]))
    for c in rec["conditions"]["items"]:
        lt = c["latest"]
        res = f"最近 {lt['verdict']}" + (f"={lt['value']:g}" if lt and lt["value"] is not None else "") + \
              f"（{lt['eid']}）" if lt else ""
        out.append((c["id"], "条件", c["status"], lt["date"] if lt else "", c["text"], res, f"charter.md:{c['lineno']}"))
    for a in rec["adrs"]:
        out.append((a["id"], "ADR", a["status"], a["date"], a["title"], "", a["where"]))
    for e in rec["journal"]:
        out.append((e["id"], "journal", e["category"] or "", e["date"], e["title"], "", e["where"]))
    return out


def index_text(rec):
    return "\n".join("\t".join(tsv_cell(x) for x in row) for row in [INDEX_COLS] + index_rows(rec)) + "\n"


def sources_sig(d):
    parts = [progress.head_sha(d)]
    names = ["charter.md", "state.md", "journal.md", "decisions.md", "experiments.md"]
    tdir = os.path.join(d, "tree")
    if os.path.isdir(tdir):
        names += ["tree/" + f for f in sorted(os.listdir(tdir)) if tree.NODE_FILE_RE.match(f)]
    for f in names:
        try:
            st = os.stat(os.path.join(d, f))
            parts.append(f"{f}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            pass
    parts.append(os.path.getmtime(os.path.abspath(__file__)).__repr__())
    return "|".join(parts)


def sig_path(d):
    d = os.path.abspath(d)
    return os.path.join(os.path.dirname(d), ".cache", f"index-{os.path.basename(d)}.sig")


def exclude_index(d):
    """index.tsv 是生成物：记进 .git/info/exclude（本机），不进提交、不进同步。"""
    p = os.path.join(d, ".git", "info", "exclude")
    if not os.path.isdir(os.path.join(d, ".git")):
        return
    try:
        cur = lint.read(p)
        if "index.tsv" not in cur.split("\n"):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(("" if not cur or cur.endswith("\n") else "\n") + "index.tsv\n")
    except OSError:
        pass


def write_index(d, rec=None):
    rec = rec or load(d)
    text = index_text(rec)
    p = os.path.join(d, "index.tsv")
    exclude_index(d)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)
    try:
        os.makedirs(os.path.dirname(sig_path(d)), exist_ok=True)
        with open(sig_path(d), "w", encoding="utf-8") as f:
            f.write(sources_sig(d))
    except OSError:
        pass
    return text


def ensure_index(d):
    """目录过期（源文件或 HEAD 变了）就重算；返回 index.tsv 路径。"""
    p = os.path.join(d, "index.tsv")
    if not os.path.isfile(p) or lint.read(sig_path(d)) != sources_sig(d):
        write_index(d)
    return p


def read_index(d):
    p = ensure_index(d)
    lines = lint.read(p).rstrip("\n").split("\n")
    return [ln.split("\t") for ln in lines[1:] if ln]
