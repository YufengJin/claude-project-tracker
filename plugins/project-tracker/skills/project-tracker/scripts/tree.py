#!/usr/bin/env python3
"""tree.py — 研究树：读 <档案>/tree/*.md 与 experiments.md，打印上下文并重写 <档案>/tree.html。

  tree.py <档案目录>                 活跃根节点「当前认识/约束/教训」（搁置/已关的根只给指引）、进行中节点（带祖先链）、open/parked 标题、一致性告警
  tree.py <档案目录> --all           再加已关分支索引（ID、verdict、结论首句）
  tree.py <档案目录> --ctx ID        给一个节点干活用的上下文：根的约束/认识/教训、祖先链、兄弟、本节点全文、台账行
  tree.py <档案目录> --ctx ID --blind  只给本节点判别、根约束、考官的指标与判定依据（不给认识与兄弟）
  tree.py <档案目录> --next Q|H      下一个可用 ID
  --no-html 不写 tree.html；--render 只写 tree.html，打印一行摘要

只用标准库。节点格式见 SKILL.md「研究树」。
"""
import html
import json
import os
import re
import sys

STATUSES = ("open", "active", "parked", "closed")
VERDICTS = ("supported", "refuted", "inconclusive", "superseded")
ROOT_SECTIONS = ("当前认识", "约束", "教训")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


# ---------- 解析 ----------

def strip_comments(text):
    return COMMENT_RE.sub("", text)


def parse_node(path):
    raw = open(path, encoding="utf-8").read()
    node = {"id": os.path.splitext(os.path.basename(path))[0], "raw": raw, "meta": {},
            "sections": [], "fm": False}
    body = raw
    lines = raw.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                node["fm"] = True
                for ln in lines[1:i]:
                    m = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$", ln)
                    if m:
                        v = m.group(2).strip()
                        if m.group(1).lower() != "title":
                            v = "" if v.startswith("#") else re.sub(r"\s+#.*$", "", v)
                        node["meta"][m.group(1).lower()] = v.strip("'\"")
                body = "\n".join(lines[i + 1:])
                break
    node["body"] = body
    cur = None
    for ln in body.split("\n"):
        m = re.match(r"^##\s+(.*?)\s*$", ln)
        if m and not ln.startswith("###"):
            cur = [m.group(1), []]
            node["sections"].append(cur)
        elif cur is not None:
            cur[1].append(ln)
    node["sections"] = [(h, "\n".join(b).strip("\n")) for h, b in node["sections"]]
    meta = node["meta"]
    node["title"] = meta.get("title", "")
    node["parent"] = meta.get("parent", "")
    node["status"] = meta.get("status", "").lower()
    node["verdict"] = meta.get("verdict", "").lower()
    node["by"] = [x for x in re.split(r"[,，\s]+", meta.get("by", "")) if x]
    return node


def section(node, name):
    """第一个标题以 name 开头的节（如「判别（事后整理）」也算判别），去掉 HTML 注释。"""
    for h, b in node["sections"]:
        if h.startswith(name):
            return strip_comments(b).strip()
    return ""


def first_para(text):
    out = []
    for ln in text.split("\n"):
        if not ln.strip():
            if out:
                break
            continue
        out.append(ln)
    return "\n".join(out)


def first_sentence(text):
    t = " ".join(first_para(text).split())
    t = re.sub(r"^[-*]\s+", "", t)
    m = re.search(r"[。！？!?；;]|\.\s", t)
    if m:
        t = t[:m.end()].strip()
    return t[:160] + ("…" if len(t) > 160 else "")


def split_row(line):
    """按未转义的竖线切一行表格；单元格保留原样（含 \\|）。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, buf, i = [], [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("\\|")
            i += 2
            continue
        if c == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def cell(c):
    """显示用：表格里的 \\| 还原成竖线。"""
    return c.replace("\\|", "|")


def is_sep(line):
    return bool(re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", line))


def parse_ledger(path):
    """返回 (tables, rows)。table: {section, header, header_line, node_col, id_col}；row: {table, cells, line, nodes, id}。"""
    tables, rows = [], []
    if not os.path.isfile(path):
        return tables, rows
    lines = open(path, encoding="utf-8").read().split("\n")
    sec, cur, i = "", None, 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            sec, cur = ln[3:].strip(), None
        elif ln.lstrip().startswith("|"):
            if cur is None:
                if i + 1 < len(lines) and is_sep(lines[i + 1]):
                    header = split_row(ln)
                    low = [h.strip().lower() for h in header]
                    cur = {"section": sec, "header": header, "header_line": ln.rstrip(),
                           "node_col": next((k for k, h in enumerate(low) if h in ("node", "nodes", "节点")), None),
                           "id_col": low.index("id") if "id" in low else 0, "n": len(tables)}
                    tables.append(cur)
                    i += 2
                    continue
            else:
                cells = split_row(ln)
                nodes = []
                if cur["node_col"] is not None and cur["node_col"] < len(cells):
                    nodes = [t.strip("[]") for t in re.split(r"[,，、;；\s]+", cells[cur["node_col"]])
                             if t.strip("[]") and t not in ("-", "—", "无")]
                rid = cells[cur["id_col"]] if cur["id_col"] < len(cells) else ""
                rows.append({"table": cur, "cells": cells, "line": ln.rstrip(), "nodes": nodes, "id": rid})
        else:
            cur = None
        i += 1
    return tables, rows


def parse_verifier(path):
    out = {"status": "", "sections": {}}
    if not os.path.isfile(path):
        return out
    cur = None
    for ln in open(path, encoding="utf-8").read().split("\n"):
        if not out["status"] and "Status:" in ln:
            out["status"] = ln.strip()
        m = re.match(r"^##\s+(.*?)\s*$", ln)
        if m:
            cur = m.group(1)
            out["sections"][cur] = []
        elif cur:
            out["sections"][cur].append(ln)
    out["sections"] = {k: strip_comments("\n".join(v)).strip() for k, v in out["sections"].items()}
    return out


def verifier_section(v, prefix):
    for k, b in v["sections"].items():
        if k.startswith(prefix):
            return k, b
    return None, ""


class Tree:
    def __init__(self, d):
        self.dir = d
        self.slug = os.path.basename(os.path.abspath(d))
        self.nodes = {}
        tdir = os.path.join(d, "tree")
        self.has_tree = os.path.isdir(tdir)
        if self.has_tree:
            for f in sorted(os.listdir(tdir)):
                if f.endswith(".md") and ID_RE.match(f[:-3]):
                    n = parse_node(os.path.join(tdir, f))
                    self.nodes[n["id"]] = n
        self.tables, self.rows = parse_ledger(os.path.join(d, "experiments.md"))
        self.verifier = parse_verifier(os.path.join(d, "verifier.md"))
        self.children = {i: [] for i in self.nodes}
        for n in self.nodes.values():
            if n["parent"] in self.nodes:
                self.children[n["parent"]].append(n["id"])
        for k in self.children:
            self.children[k].sort(key=id_key)
        self.rows_of = {i: [] for i in self.nodes}
        for r in self.rows:
            for t in r["nodes"]:
                if t in self.rows_of:
                    self.rows_of[t].append(r)
        self.warnings = self.check()
        # 顶层 = 根 + parent 悬空的 + 环上没有根可达的
        reach = set()
        def walk(i):
            if i in reach:
                return
            reach.add(i)
            for c in self.children[i]:
                walk(c)
        self.tops = sorted([i for i, n in self.nodes.items() if not n["parent"] or n["parent"] not in self.nodes],
                           key=id_key)
        for t in self.tops:
            walk(t)
        for i in sorted(self.nodes, key=id_key):
            if i not in reach:
                self.tops.append(i)
                walk(i)

    def check(self):
        w = []
        for i in sorted(self.nodes, key=id_key):
            n = self.nodes[i]
            if not n["fm"]:
                w.append(f"{i}: 没有 frontmatter（--- 包起来的 title/parent/status）")
            if not n["title"]:
                w.append(f"{i}: 缺 title")
            if n["parent"] and n["parent"] not in self.nodes:
                w.append(f"{i}: parent {n['parent']} 不存在")
            if n["status"] not in STATUSES:
                w.append(f"{i}: status「{n['status'] or '空'}」不是 {'|'.join(STATUSES)}")
            if n["verdict"] and n["verdict"] not in VERDICTS:
                w.append(f"{i}: verdict「{n['verdict']}」不是 {'|'.join(VERDICTS)}")
            if n["status"] == "closed":
                if not n["verdict"]:
                    w.append(f"{i}: closed 但没有 verdict")
                if not section(n, "结论"):
                    w.append(f"{i}: closed 但结论为空")
            elif n["verdict"]:
                w.append(f"{i}: verdict 只用于 closed（现在 status={n['status'] or '空'}）")
            if n["verdict"] == "superseded" and not n["by"]:
                w.append(f"{i}: superseded 但没写 by")
            for b in n["by"]:
                if b not in self.nodes:
                    w.append(f"{i}: by {b} 不存在")
        seen_cycles = set()
        for i in self.nodes:
            path, cur = [], i
            while cur in self.nodes and cur not in path:
                path.append(cur)
                cur = self.nodes[cur]["parent"]
            if cur in path:
                cyc = path[path.index(cur):]
                key = frozenset(cyc)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    w.append("成环: " + " → ".join(cyc + [cur]))
        for r in self.rows:
            for t in r["nodes"]:
                if t not in self.nodes:
                    where = f"（{r['table']['section']}）" if r["table"]["section"] else ""
                    w.append(f"台账 {r['id'] or '?'}{where}: node {t} 不存在")
        return w

    def chain(self, i):
        """祖先链，从根到父（不含自己）。遇环或悬空就停。"""
        out, cur, seen = [], self.nodes[i]["parent"], {i}
        while cur in self.nodes and cur not in seen:
            out.append(cur)
            seen.add(cur)
            cur = self.nodes[cur]["parent"]
        return out[::-1]

    def root_of(self, i):
        ch = self.chain(i)
        return ch[0] if ch else i

    def descendants(self, i):
        out, stack, seen = [], list(self.children[i]), {i}
        while stack:
            c = stack.pop(0)
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
            stack.extend(self.children[c])
        return out


def id_key(i):
    m = re.match(r"^([A-Za-z_-]*?)(\d+)$", i)
    return (m.group(1), int(m.group(2)), "") if m else (i, 0, i)


def tag(n):
    s = n["status"] or "?"
    return f"{s}/{n['verdict']}" if n["verdict"] else s


# ---------- 文字输出 ----------

def text_default(t, show_all):
    o = []
    cnt = {s: 0 for s in STATUSES}
    for n in t.nodes.values():
        if n["status"] in cnt:
            cnt[n["status"]] += 1
    o.append(f"研究树 {t.slug}：{len(t.nodes)} 节点（" + "，".join(f"{s} {cnt[s]}" for s in STATUSES)
             + f"）；台账 {len(t.rows)} 行，挂到节点的 {sum(1 for r in t.rows if r['nodes'])} 行；全图 tree.html")
    for r in sorted([i for i, n in t.nodes.items() if not n["parent"]], key=id_key):
        n = t.nodes[r]
        o.append(f"\n## 根 {r} [{tag(n)}] {n['title']}")
        if n["status"] in ("parked", "closed"):
            # 搁置或已关的根只给指引，全文按需取，免得旧线把简报撑大
            have = [s for s in ROOT_SECTIONS if section(n, s)]
            if have:
                o.append(f"（{'/'.join(have)} 见 pt tree {t.slug} --ctx {r} 或 tree.html）")
            continue
        for s in ROOT_SECTIONS:
            b = section(n, s)
            if b:
                o.append(f"### {s}\n{b}")
    act = [i for i in sorted(t.nodes, key=id_key) if t.nodes[i]["status"] == "active"]
    o.append("\n## 进行中")
    if not act:
        o.append("(无)")
    for i in act:
        n = t.nodes[i]
        o.append(f"- {i} {n['title']}")
        ch = t.chain(i)
        if ch:
            o.append("  链: " + " > ".join(f"{c} {t.nodes[c]['title']}" for c in ch))
        rows = t.rows_of.get(i, [])
        if rows:
            o.append("  台账: " + ", ".join(r["id"] or "?" for r in rows))
    rest = [i for i in sorted(t.nodes, key=id_key) if t.nodes[i]["status"] in ("open", "parked")]
    quiet = {}  # 搁置或已关的根下的 open/parked 只计数
    o.append("\n## open / parked")
    for i in rest:
        n = t.nodes[i]
        r = t.root_of(i)
        if r != i and not t.nodes[r]["parent"] and t.nodes[r]["status"] in ("parked", "closed") and not show_all:
            quiet[r] = quiet.get(r, 0) + 1
            continue
        p = f"（{n['parent']} 下）" if n["parent"] else "（根）"
        o.append(f"- {i} [{n['status']}] {n['title']}{p}")
    for r, k in sorted(quiet.items(), key=lambda x: id_key(x[0])):
        o.append(f"- 根 {r}（{t.nodes[r]['status']}）下另有 {k} 个，见 --all 或 tree.html")
    if not rest:
        o.append("(无)")
    if show_all:
        o.append("\n## 已关分支")
        closed = [i for i in sorted(t.nodes, key=id_key) if t.nodes[i]["status"] == "closed"]
        if not closed:
            o.append("(无)")
        for i in closed:
            n = t.nodes[i]
            by = f" → {','.join(n['by'])}" if n["by"] else ""
            o.append(f"- {i} [{n['verdict'] or '?'}{by}] {n['title']} —— {first_sentence(section(n, '结论')) or '(无结论)'}")
    else:
        nc = sum(1 for n in t.nodes.values() if n["status"] == "closed")
        if nc:
            o.append(f"\n(已关 {nc} 个，索引见 pt tree {t.slug} --all 或 tree.html)")
    o.append(warn_text(t))
    return "\n".join(o)


def warn_text(t):
    if not t.warnings:
        return "\n## 告警\n(无)"
    return "\n## 告警\n" + "\n".join("- " + w for w in t.warnings)


def ledger_text(t, rows):
    o, last = [], None
    for r in rows:
        tb = r["table"]
        if tb is not last:
            o.append(f"\n[{tb['section'] or '台账'}]\n{tb['header_line']}")
            last = tb
        o.append(r["line"])
    return "\n".join(o)


def text_ctx(t, i, blind):
    n = t.nodes[i]
    root = t.nodes[t.root_of(i)]
    o = []
    if blind:
        o.append(f"# {i} {n['title']}（盲：只给问题、约束与考官）")
        o.append(f"\n## 判别\n{section(n, '判别') or '(空)'}")
        c = section(root, "约束")
        o.append(f"\n## 约束（根 {root['id']}）\n{c or '(无)'}")
        v = t.verifier
        if v["status"]:
            o.append(f"\n## 考官\n{v['status']}")
            for p in ("指标", "判定依据"):
                k, b = verifier_section(v, p)
                if k:
                    o.append(f"\n### {k}\n{b}")
        return "\n".join(o)
    o.append(f"# {i} [{tag(n)}] {n['title']}")
    if root["id"] != i:
        for s in ROOT_SECTIONS:
            b = section(root, s)
            if b:
                o.append(f"\n## 根 {root['id']} · {s}\n{b}")
    ch = t.chain(i)
    if ch:
        o.append("\n## 祖先链（根 → 父）")
        for c in ch:
            a = t.nodes[c]
            o.append(f"\n### {c} [{tag(a)}] {a['title']}")
            d = first_para(section(a, "判别"))
            if d:
                o.append(f"判别: {d}")
            r = section(a, "结论")
            if r:
                o.append(f"结论: {r}")
    sib = [s for s in (t.children.get(n["parent"], []) if n["parent"] in t.nodes else
                       [x for x in t.nodes if not t.nodes[x]["parent"]]) if s != i]
    if sib:
        o.append("\n## 兄弟")
        for s in sorted(sib, key=id_key):
            o.append(f"- {s} [{tag(t.nodes[s])}] {t.nodes[s]['title']}")
    kids = t.children.get(i, [])
    if kids:
        o.append("\n## 子节点")
        for s in kids:
            o.append(f"- {s} [{tag(t.nodes[s])}] {t.nodes[s]['title']}")
    o.append(f"\n## 本节点全文（tree/{i}.md）\n{n['raw'].strip()}")
    seen, rows = set(), []
    for x in [i] + kids:
        for r in t.rows_of.get(x, []):
            if id(r) not in seen:
                seen.add(id(r))
                rows.append(r)
    rows.sort(key=lambda r: t.rows.index(r))
    o.append(f"\n## 台账行（本节点与子节点，{len(rows)} 行）" + (ledger_text(t, rows) if rows else "\n(无)"))
    deep = sum(len(t.rows_of.get(x, [])) for x in t.descendants(i) if x not in kids)
    if deep:
        o.append(f"(更深的后代还挂着 {deep} 行，用 --ctx 那些节点看)")
    return "\n".join(o)


def next_id(t, kind):
    nums = [int(m.group(1)) for i in t.nodes for m in [re.match(rf"^{kind}(\d+)$", i)] if m]
    return f"{kind}{max(nums) + 1 if nums else 1}"


# ---------- HTML ----------

def esc(s):
    return html.escape(s, quote=True)


SAFE_URL = re.compile(r"^(https?://|mailto:|#|\.{0,2}/|[\w.~-]+(/|$|\.))", re.I)


def inline(s, t):
    """转义后再做行内标记：`code`、[[ID]]、[文字](链接)、**粗体**。"""
    codes = []
    def keep(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"
    s = re.sub(r"`([^`]+)`", keep, s)
    s = esc(s)
    def ref(m):
        i = m.group(1)
        if i in t.nodes:
            return f'<a class="ref" href="#{esc(i)}">{esc(i)}</a>'
        return f'<span class="ref dangling" title="不存在">{esc(i)}</span>'
    s = re.sub(r"\[\[([A-Za-z][A-Za-z0-9_-]*)\]\]", ref, s)
    def link(m):
        txt, url = m.group(1), html.unescape(m.group(2))
        if SAFE_URL.match(url):
            return f'<a href="{esc(url)}">{txt}</a>'
        return m.group(0)
    s = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{esc(codes[int(m.group(1))])}</code>", s)
    return s


def md(text, t):
    """最小 markdown：标题、列表（按缩进嵌套）、表格、段落、行内标记。"""
    text = strip_comments(text)
    out, para, stack = [], [], []
    def flush():
        if para:
            out.append("<p>" + "<br>".join(inline(p, t) for p in para) + "</p>")
            para.clear()
    def close_lists(level=0):
        while len(stack) > level:
            out.append(f"</li></{stack.pop()[1]}>")
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        m_h = re.match(r"^(#{1,6})\s+(.*)$", ln)
        m_l = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", ln)
        if not ln.strip():
            flush()
            close_lists()
        elif m_h:
            flush(); close_lists()
            lv = min(6, len(m_h.group(1)) + 2)
            out.append(f"<h{lv}>{inline(m_h.group(2), t)}</h{lv}>")
        elif ln.lstrip().startswith("|") and i + 1 < len(lines) and is_sep(lines[i + 1]):
            flush(); close_lists()
            head = split_row(ln)
            out.append("<div class=tw><table><thead><tr>" + "".join(f"<th>{inline(cell(c), t)}</th>" for c in head)
                       + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                out.append("<tr>" + "".join(f"<td>{inline(cell(c), t)}</td>" for c in split_row(lines[i])) + "</tr>")
                i += 1
            out.append("</tbody></table></div>")
            continue
        elif m_l:
            flush()
            ind = len(m_l.group(1).expandtabs(4))
            kind = "ol" if m_l.group(2)[0].isdigit() else "ul"
            while stack and stack[-1][0] > ind:
                out.append(f"</li></{stack.pop()[1]}>")
            if stack and stack[-1][0] == ind:
                out.append("</li><li>")
            else:
                stack.append((ind, kind))
                out.append(f"<{kind}><li>")
            out.append(inline(m_l.group(3), t))
        elif stack:
            out.append("<br>" + inline(ln.strip(), t))
        else:
            para.append(ln)
        i += 1
    flush()
    close_lists()
    return "\n".join(out)


def ledger_html(t, rows, mark_nodes=True):
    out, last = [], None
    for r in rows:
        tb = r["table"]
        if tb is not last:
            if last is not None:
                out.append("</tbody></table></div>")
            out.append(f"<h4>{inline(tb['section'] or '台账', t)}</h4><div class=tw><table><thead><tr>"
                       + "".join(f"<th>{inline(cell(h), t)}</th>" for h in tb["header"]) + "</tr></thead><tbody>")
            last = tb
        cells = r["cells"]
        tds = []
        for k, c in enumerate(cells):
            if mark_nodes and k == tb["node_col"]:
                tds.append("<td>" + " ".join(
                    f'<a class="ref" href="#{esc(x)}">{esc(x)}</a>' if x in t.nodes
                    else f'<span class="ref dangling">{esc(x)}</span>' for x in r["nodes"]) + "</td>")
            else:
                tds.append(f"<td>{inline(cell(c), t)}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    if last is not None:
        out.append("</tbody></table></div>")
    return "\n".join(out)


def badge(n):
    s = n["status"] or "?"
    b = f'<span class="b s-{esc(s)}">{esc(s)}</span>'
    if n["verdict"]:
        b += f' <span class="b v-{esc(n["verdict"])}">{esc(n["verdict"])}</span>'
    return b


def tree_li(t, i, seen):
    n = t.nodes[i]
    seen.add(i)
    kids = [c for c in t.children[i] if c not in seen]
    cls = f"s-{n['status'] or 'none'}" + (f" v-{n['verdict']}" if n["verdict"] else "")
    caret = '<button class="caret" aria-label="折叠"></button>' if kids else '<span class="caret none"></span>'
    sub = ""
    if kids:
        sub = "<ul>" + "".join(tree_li(t, c, seen) for c in kids) + "</ul>"
    return (f'<li data-id="{esc(i)}" data-status="{esc(n["status"] or "none")}">{caret}'
            f'<a class="n {cls}" href="#{esc(i)}"><span class="dot"></span><b>{esc(i)}</b> {esc(n["title"])}</a>{sub}</li>')


CSS = """
:root{--bg:#fbfbfa;--fg:#1f2328;--mut:#6a737d;--line:#d8dee4;--panel:#ffffff;--hl:#eef3fb;
--open:#6a737d;--active:#0969da;--parked:#9a6700;--closed:#57606a;
--supported:#1a7f37;--refuted:#cf222e;--inconclusive:#8250df;--superseded:#bc4c00;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#30363d;--panel:#161b22;--hl:#1c2a3f;
--open:#8b949e;--active:#4493f8;--parked:#d29922;--closed:#8b949e;
--supported:#3fb950;--refuted:#f85149;--inconclusive:#a371f7;--superseded:#db6d28;color-scheme:dark}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,-apple-system,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif;display:flex;flex-direction:column}
header{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:16px;margin:0 8px 0 0}header label{white-space:nowrap;color:var(--mut);cursor:pointer}
header input[type=search]{flex:1 1 180px;min-width:120px;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.wrap{flex:1;display:flex;min-height:0}
nav{width:38%;max-width:520px;min-width:240px;overflow:auto;border-right:1px solid var(--line);padding:8px 6px 40px}
main{flex:1;overflow:auto;padding:16px 22px 60px;min-width:0}
nav ul{list-style:none;margin:0;padding-left:16px}nav>ul{padding-left:0}
nav li{margin:1px 0;white-space:nowrap}
.caret{width:16px;height:16px;border:0;background:none;color:var(--mut);cursor:pointer;padding:0;display:inline-block;vertical-align:middle}
.caret::before{content:"▾"}li.fold>.caret::before{content:"▸"}li.fold>ul{display:none}.caret.none::before{content:""}
a.n{color:var(--fg);text-decoration:none;padding:1px 6px;border-radius:4px;display:inline-block;max-width:calc(100% - 20px);overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
a.n:hover{background:var(--hl)}a.n.cur{background:var(--hl);outline:1px solid var(--active)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;border:2px solid var(--open);vertical-align:0}
.s-active .dot{background:var(--active);border-color:var(--active)}.s-parked .dot{border-color:var(--parked);border-style:dashed}
.s-closed{color:var(--mut)!important}.s-closed .dot{background:var(--closed);border-color:var(--closed)}
.v-supported .dot{background:var(--supported);border-color:var(--supported)}.v-refuted .dot{background:var(--refuted);border-color:var(--refuted)}
.v-inconclusive .dot{background:var(--inconclusive);border-color:var(--inconclusive)}.v-superseded .dot{background:var(--superseded);border-color:var(--superseded)}
li.dim>a.n{opacity:.45}li.hide{display:none}
.b{display:inline-block;font-size:12px;padding:0 7px;border-radius:10px;border:1px solid currentColor}
.b.s-open{color:var(--open)}.b.s-active{color:var(--active)}.b.s-parked{color:var(--parked)}.b.s-closed{color:var(--closed)}
.b.v-supported{color:var(--supported)}.b.v-refuted{color:var(--refuted)}.b.v-inconclusive{color:var(--inconclusive)}.b.v-superseded{color:var(--superseded)}
article h2{font-size:19px;margin:0 0 6px}article h3{font-size:15px;margin:18px 0 6px;padding-bottom:3px;border-bottom:1px solid var(--line)}
article h4,article h5,article h6{font-size:14px;margin:12px 0 4px}.meta{color:var(--mut);margin-bottom:10px}
a{color:var(--active)}a.ref{font-family:ui-monospace,monospace;font-size:13px}.dangling{color:var(--refuted);text-decoration:line-through}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:var(--hl);padding:0 3px;border-radius:3px;word-break:break-all}
.tw{overflow-x:auto;margin:6px 0}table{border-collapse:collapse;font-size:13px}th,td{border:1px solid var(--line);padding:3px 6px;vertical-align:top;text-align:left}
th{background:var(--hl)}td{min-width:3em;max-width:36em}
.warn{color:var(--refuted)}ul.plain{padding-left:18px}
@media (max-width:720px){.wrap{flex-direction:column}nav{width:auto;max-width:none;max-height:42vh;border-right:0;border-bottom:1px solid var(--line)}main{padding:12px 16px 40px}}
"""

JS = """
(function(){
var nav=document.querySelector('nav'),q=document.getElementById('q'),hc=document.getElementById('hideclosed');
var boxes=[].slice.call(document.querySelectorAll('input[data-st]'));
var arts={};[].forEach.call(document.querySelectorAll('article'),function(a){arts[a.id]=a;});
var texts={};function txt(id){var a=arts['n-'+id];if(!(id in texts))texts[id]=a?a.textContent.toLowerCase():'';return texts[id];}
nav.addEventListener('click',function(e){if(e.target.classList.contains('caret')){e.target.parentNode.classList.toggle('fold');}});
document.getElementById('fold').onclick=function(){[].forEach.call(nav.querySelectorAll('li'),function(l){if(l.querySelector('ul'))l.classList.add('fold');});};
document.getElementById('unfold').onclick=function(){[].forEach.call(nav.querySelectorAll('li.fold'),function(l){l.classList.remove('fold');});};
function filt(){
 var on={};boxes.forEach(function(b){on[b.getAttribute('data-st')]=b.checked;});
 var s=q.value.trim().toLowerCase(),hide=hc.checked;
 function visit(li){
  var st=li.getAttribute('data-status'),id=li.getAttribute('data-id');
  var self=(on[st]!==false)&&!(hide&&st==='closed')&&(!s||txt(id).indexOf(s)>=0);
  var kid=false,ul=li.querySelector(':scope>ul');
  if(ul)[].forEach.call(ul.children,function(c){if(visit(c))kid=true;});
  li.classList.toggle('hide',!self&&!kid);li.classList.toggle('dim',!self&&kid);
  if(s&&kid)li.classList.remove('fold');
  return self||kid;}
 [].forEach.call(nav.querySelector('ul').children,visit);
 try{localStorage.setItem('pt-tree-hc',hide?'1':'0');}catch(e){}
}
boxes.forEach(function(b){b.onchange=filt;});q.oninput=filt;hc.onchange=filt;
try{if(localStorage.getItem('pt-tree-hc')==='1')hc.checked=true;}catch(e){}
function show(){
 var id=decodeURIComponent(location.hash.slice(1)),a=arts['n-'+id]||arts['overview'];
 for(var k in arts)arts[k].hidden=(arts[k]!==a);
 [].forEach.call(nav.querySelectorAll('a.cur'),function(x){x.classList.remove('cur');});
 var l=nav.querySelector('li[data-id="'+(window.CSS&&CSS.escape?CSS.escape(id):id)+'"]');
 if(l){var p=l.parentNode;while(p&&p!==nav){if(p.tagName==='LI')p.classList.remove('fold');p=p.parentNode;}
  var n=l.querySelector(':scope>a.n');n.classList.add('cur');n.scrollIntoView({block:'nearest'});}
 document.querySelector('main').scrollTop=0;
}
window.addEventListener('hashchange',show);filt();show();
})();
"""


def render_html(t):
    sts = STATUSES
    cnt = {s: sum(1 for n in t.nodes.values() if n["status"] == s) for s in sts}
    seen = set()
    tree = "".join(tree_li(t, i, seen) for i in t.tops)
    arts = []
    # 总览
    ov = [f"<h2>研究树 · {esc(t.slug)}</h2><div class=meta>{len(t.nodes)} 个节点；台账 {len(t.rows)} 行"
          f"（{len(t.tables)} 张表），挂到节点的 {sum(1 for r in t.rows if r['nodes'])} 行。点左侧节点看详情。</div>"
          "<div class=meta>颜色：<span class=s-open><span class=dot></span>open</span> "
          "<span class=s-active><span class=dot></span>active</span> <span class=s-parked><span class=dot></span>parked</span>；"
          "closed 按 verdict：<span class=v-supported><span class=dot></span>supported</span> "
          "<span class=v-refuted><span class=dot></span>refuted</span> <span class=v-inconclusive><span class=dot></span>inconclusive</span> "
          "<span class=v-superseded><span class=dot></span>superseded</span></div>"]
    if t.warnings:
        ov.append("<h3 class=warn>一致性告警</h3><ul class=plain>" + "".join(f"<li>{inline(w, t)}</li>" for w in t.warnings) + "</ul>")
    for r in sorted([i for i, n in t.nodes.items() if not n["parent"]], key=id_key):
        n = t.nodes[r]
        ov.append(f'<h3>根 <a class=ref href="#{esc(r)}">{esc(r)}</a> {esc(n["title"])} {badge(n)}</h3>')
        for s in ROOT_SECTIONS:
            b = section(n, s)
            if b:
                ov.append(f"<h4>{s}</h4>{md(b, t)}")
    act = [i for i in sorted(t.nodes, key=id_key) if t.nodes[i]["status"] == "active"]
    if act:
        ov.append("<h3>进行中</h3><ul class=plain>" + "".join(
            f'<li><a class=ref href="#{esc(i)}">{esc(i)}</a> {esc(t.nodes[i]["title"])}'
            + (" <span class=meta>← " + " ← ".join(esc(t.nodes[c]["title"]) for c in t.chain(i)[::-1]) + "</span>" if t.chain(i) else "")
            + "</li>" for i in act) + "</ul>")
    loose = [r for r in t.rows if not r["nodes"]]
    if t.rows:
        ov.append(f'<h3>台账</h3><p><a href="#__ledger">全部 {len(t.rows)} 行</a>；未挂到节点的 {len(loose)} 行。</p>')
    arts.append('<article id="overview">' + "\n".join(ov) + "</article>")
    if t.rows:
        arts.append('<article id="n-__ledger" hidden><h2>实验台账（experiments.md）</h2>' + ledger_html(t, t.rows) + "</article>")
    for i in sorted(t.nodes, key=id_key):
        n = t.nodes[i]
        a = [f"<h2>{esc(i)} · {esc(n['title'])}</h2><div class=meta>{badge(n)}"]
        ch = t.chain(i)
        if ch:
            a.append(" · 链 " + " › ".join(f'<a class=ref href="#{esc(c)}">{esc(c)}</a>' for c in ch))
        elif n["parent"]:
            a.append(f' · parent <span class="ref dangling">{esc(n["parent"])}</span>')
        if n["by"]:
            a.append(" · 被取代于 " + " ".join(
                f'<a class=ref href="#{esc(b)}">{esc(b)}</a>' if b in t.nodes else f'<span class="ref dangling">{esc(b)}</span>'
                for b in n["by"]))
        kids = t.children[i]
        if kids:
            a.append(" · 子 " + " ".join(f'<a class=ref href="#{esc(c)}">{esc(c)}</a>' for c in kids))
        a.append(f" · <code>tree/{esc(i)}.md</code></div>")
        for h, b in n["sections"]:
            a.append(f"<h3>{inline(h, t)}</h3>{md(b, t)}")
        rows = t.rows_of[i]
        if rows:
            a.append(f"<h3>台账（{len(rows)} 行）</h3>" + ledger_html(t, rows))
        arts.append(f'<article id="n-{esc(i)}" hidden>' + "".join(a) + "</article>")
    boxes = "".join(f'<label><input type=checkbox data-st="{s}" checked> {s} {cnt[s]}</label>' for s in sts)
    return (f"<!doctype html>\n<html lang=zh-CN><head><meta charset=utf-8>"
            f"<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>研究树 · {esc(t.slug)}</title><style>{CSS}</style></head><body>\n"
            f"<header><h1><a href=\"#\" style=\"color:inherit;text-decoration:none\">研究树 · {esc(t.slug)}</a></h1>{boxes}"
            f"<label><input type=checkbox id=hideclosed> 隐藏已关</label>"
            f"<input type=search id=q placeholder=\"搜索 ID、标题、正文\">"
            f"<button id=fold type=button>全折叠</button><button id=unfold type=button>全展开</button></header>\n"
            f"<div class=wrap><nav><ul>{tree}</ul></nav><main>\n" + "\n".join(arts)
            + f"\n</main></div><script>{JS}</script></body></html>\n")


def write_html(t):
    p = os.path.join(t.dir, "tree.html")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render_html(t))
    os.replace(tmp, p)
    return p


# ---------- 入口 ----------

def main(argv):
    args = list(argv)
    flags = {"--all": False, "--blind": False, "--no-html": False, "--render": False}
    for k in flags:
        if k in args:
            flags[k] = True
            args.remove(k)
    ctx = nxt = None
    for opt in ("--ctx", "--next"):
        if opt in args:
            k = args.index(opt)
            if k + 1 >= len(args):
                return usage(f"{opt} 后面要跟参数")
            val = args[k + 1]
            del args[k:k + 2]
            if opt == "--ctx":
                ctx = val
            else:
                nxt = val
    if len(args) != 1 or args[0].startswith("-"):
        return usage()
    d = args[0]
    if not os.path.isdir(d):
        return usage(f"不是目录: {d}")
    t = Tree(d)
    if nxt is not None:
        if nxt not in ("Q", "H"):
            return usage("--next 只接 Q 或 H")
        print(next_id(t, nxt))
        return 0
    if not t.has_tree:
        print(f"tree.py: {d} 没有 tree/（研究树是可选的；pt research <slug> 会建一个根节点）", file=sys.stderr)
        return 1
    if not flags["--no-html"]:
        write_html(t)
    if flags["--render"]:
        print(f"tree.html：{len(t.nodes)} 节点，告警 {len(t.warnings)} 条" + ("" if not t.warnings else "（pt tree 看）"))
        return 0
    if ctx is not None:
        if ctx not in t.nodes:
            print(f"tree.py: 没有节点 {ctx}", file=sys.stderr)
            return 1
        print(text_ctx(t, ctx, flags["--blind"]))
        if not flags["--blind"]:
            print(warn_text(t))
        return 0
    print(text_default(t, flags["--all"]))
    return 0


def usage(msg=None):
    if msg:
        print("tree.py: " + msg, file=sys.stderr)
    print("用法: tree.py <档案目录> [--all | --ctx ID [--blind] | --next Q|H] [--no-html | --render]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
