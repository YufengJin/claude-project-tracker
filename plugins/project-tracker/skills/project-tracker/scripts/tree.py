#!/usr/bin/env python3
"""tree.py — 研究树：读 <档案>/tree/*.md 与 experiments.md，打印上下文并重写 <档案>/tree.html。

  tree.py <档案目录>                 活跃根节点「当前认识/约束/教训」（搁置/已关的根只给指引）、进行中节点（带祖先链）、open/parked 标题、一致性告警
  tree.py <档案目录> --all           再加已关分支索引（ID、verdict、结论首句）
  tree.py <档案目录> --ctx ID        给一个节点干活用的上下文：根的约束/认识/教训、祖先链、兄弟、本节点全文、台账行
  tree.py <档案目录> --ctx ID --blind  只给本节点判别（[[ID]] 隐去）、根约束、考官的指标与判定依据（不给认识与兄弟）
  tree.py <档案目录> --next Q|H      下一个可用 ID
  --no-html 不写 tree.html；--render 只写 tree.html，打印一行摘要

只用标准库。节点格式见 SKILL.md「研究树」。
"""
import html
import json
import os
import re
import sys
import tempfile

STATUSES = ("open", "active", "parked", "closed")
VERDICTS = ("supported", "refuted", "inconclusive", "superseded", "abandoned")
ROOT_SECTIONS = ("当前认识", "约束", "教训")
SEC_NAMES = ("判别", "结论") + ROOT_SECTIONS
SEC_SEP = "（(：:［[【 \t-—"
KNOWN_KEYS = ("title", "parent", "status", "verdict", "by")
NODE_FILE_RE = re.compile(r"^[QH][1-9][0-9]*\.md$")
REF_RE = re.compile(r"\[\[([A-Za-z][A-Za-z0-9_-]*)\]\]")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
CONFLICT_RE = re.compile(r"^(<<<<<<<|>>>>>>>)( |$)", re.M)
HEAD_RE = re.compile(r"^(#{2,3})[ \t]*([^#\s].*?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
NODE_HEADS = ("node", "nodes", "节点", "节点id", "nodeid")
PLACEHOLDERS = {"无", "todo", "待写", "待补", "待定", "tbd", "-", "—", "–", "n/a", "na", "none", "?", "？"}
OPEN_LIMIT = 50


# ---------- 解析 ----------

def read_text(path):
    """读 UTF-8（带不带 BOM 都行），统一成 \\n 换行。非 UTF-8 抛 UnicodeDecodeError。"""
    with open(path, encoding="utf-8-sig") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def strip_comments(text, warn=None, where="", keep_lines=False):
    """去掉 <!-- --> 注释。未闭合的 <!-- 去到文末；keep_lines 时注释换成同样多的空行（保住行号）。"""
    sub = (lambda m: "\n" * m.group(0).count("\n")) if keep_lines else ""
    out = COMMENT_RE.sub(sub, text)
    k = out.find("<!--")
    if k >= 0:
        if warn is not None:
            warn.append(f"{where}注释 <!-- 没闭合，后面的内容都当注释忽略了")
        out = out[:k] + ("\n" * out[k:].count("\n") if keep_lines else "")
    elif warn is not None and "-->" in out:
        warn.append(f"{where}多出一个 -->（注释不能嵌套）")
    return out


def sec_name(h):
    """标题对应的固定节名：「结论」「结论（更正）」「结论: …」都算结论，「结论性实验」不算。"""
    for name in SEC_NAMES:
        if h == name or (h.startswith(name) and h[len(name)] in SEC_SEP):
            return name
    return None


def ids_of(v):
    """frontmatter 里的 ID 列表：去 [[ ]] 与 [ ]，按逗号、顿号、空白拆。"""
    v = re.sub(r"\[\[|\]\]", "", v).strip().strip("[]")
    return [x for x in re.split(r"[,，、\s]+", v) if x]


def is_blank(text):
    """空，或只写了「无 / TODO / 待写 / TBD / -」这类占位。"""
    t = re.sub(r"^[-*+]\s+", "", text.strip())
    t = t.strip(" \t\n。.!！:：*_`").lower()
    return not t or t in PLACEHOLDERS


def parse_fm(lines, node):
    meta, w = node["meta"], node["warn"]
    last, listed = None, set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$", s)
        if not m:
            if s.startswith("- ") and last and not meta.get(last):
                if last not in listed:
                    listed.add(last)
                    w.append(f"frontmatter 的 {last} 写成了块列表，只认同一行的值（{last}: X）")
            elif re.match(r"^[A-Za-z_]+\s*：", s):
                w.append(f"frontmatter 用了全角冒号，没读：{s[:60]}")
            else:
                w.append(f"frontmatter 看不懂的行，没读：{s[:60]}")
            continue
        k, v = m.group(1).lower(), m.group(2).strip()
        last = k
        q = re.match(r"^([\"'])(.*?)\1(\s+#.*)?$", v)
        if q:
            v = q.group(2)
        elif k != "title":
            v = "" if v.startswith("#") else re.sub(r"\s+#.*$", "", v)
        if k not in KNOWN_KEYS:
            w.append(f"frontmatter 未知键 {m.group(1)}（只认 {'/'.join(KNOWN_KEYS)}）")
        if k in meta:
            w.append(f"frontmatter 重复的键 {k}（取最后一个）")
        meta[k] = v.strip().strip("'\"")


def parse_node(path):
    return parse_node_text(read_text(path), os.path.basename(path)[:-3])


def parse_node_text(raw, nid):
    """解析一个节点文件的文本（monitor 也用它读 git 历史里的旧版本）。"""
    node = {"id": nid, "raw": raw, "meta": {}, "sections": [],
            "fm": False, "warn": []}
    w = node["warn"]
    if CONFLICT_RE.search(raw):
        w.append("含合并冲突标记（<<<<<<< / >>>>>>>），先合并再用")
    lines = raw.split("\n")
    first = next((k for k, ln in enumerate(lines) if ln.strip()), 0)  # 容忍开头的空行
    start = 0
    if lines[first].strip() == "---":
        end = cut = None
        for i in range(first + 1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
            if HEAD_RE.match(lines[i]):
                cut = i
                break
        node["fm"] = True
        if end is None:
            end = cut if cut is not None else len(lines)
            w.append("frontmatter 没闭合（缺结尾的 ---）" + ("，在第一个 ## 标题前截断" if cut is not None else ""))
            start = end
        else:
            start = end + 1
        parse_fm(lines[first + 1:end], node)
    node["body"] = "\n".join(lines[start:])
    # 先去注释、跳过代码块，再切节；### 写成的固定节名也当一节（免得结论混进判别）
    cur, fence = None, False
    for ln in strip_comments(node["body"], w).split("\n"):
        if FENCE_RE.match(ln):
            fence = not fence
        m = None if fence else HEAD_RE.match(ln)
        if m and (len(m.group(1)) == 2 or sec_name(m.group(2))):
            if len(m.group(1)) == 3:
                w.append(f"「### {m.group(2)}」当成一节处理（固定节写 ## 二级标题）")
            cur = [m.group(2), []]
            node["sections"].append(cur)
        elif cur is not None:
            cur[1].append(ln)
    node["sections"] = [(h, "\n".join(b).strip("\n")) for h, b in node["sections"]]
    names = [sec_name(h) for h, _ in node["sections"]]
    for nm in SEC_NAMES:
        if names.count(nm) > 1:
            w.append(f"有 {names.count(nm)} 个「## {nm}」，取最后一个")
    meta = node["meta"]
    node["title"] = meta.get("title", "")
    par = ids_of(meta.get("parent", ""))
    node["parent"] = par[0] if par else ""
    if len(par) > 1:
        w.append(f"parent 只能一个（写了 {', '.join(par)}），按 {par[0]} 算")
    node["status"] = meta.get("status", "").lower()
    node["verdict"] = meta.get("verdict", "").lower()
    node["by"] = ids_of(meta.get("by", ""))
    return node


def section(node, name):
    """名为 name 的节（「判别（事后整理）」也算判别）；有两个时取最后一个（后补的更正优先）。注释已去掉。"""
    hit = ""
    for h, b in node["sections"]:
        if sec_name(h) == name:
            hit = b.strip()
    return hit


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
    return "|" in line and bool(re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", line))


def norm_head(h):
    h = re.sub(r"[*`]", "", cell(h)).strip().lower()
    return re.sub(r"\s+", "", re.sub(r"\(s\)$", "", h))


def node_cells(c):
    """台账 node 单元格 → 节点 ID 列表：去格式与括号注，按逗号、斜杠、「和」等拆，占位当空，去重。"""
    c = cell(c)
    c = re.sub(r"\[\[([^\]]*)\]\]", r" \1 ", c)
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)
    c = re.sub(r"<[^>]*>|[`*]", " ", c)
    c = re.sub(r"[（(][^）)]*[）)]", " ", c)
    c = re.sub(r"\bN/A\b", " ", c, flags=re.I)
    out = []
    for x in re.split(r"[,，、;；/+&＆\s]+|和|\band\b", c):
        x = x.strip("[]")
        if x and x.lower() not in PLACEHOLDERS and not re.fullmatch(r"[-—–]+", x) and x not in out:
            out.append(x)
    return out


def parse_ledger(path):
    """返回 (tables, rows, warns)。table: {section, header, header_line, node_col, id_col}；row: {table, cells, line, nodes, id}。"""
    tables, rows, warns = [], [], []
    if not os.path.isfile(path):
        return tables, rows, warns
    try:
        text = read_text(path)
    except (UnicodeDecodeError, OSError) as e:
        warns.append(f"experiments.md 读不了（{'不是 UTF-8' if isinstance(e, UnicodeDecodeError) else e.strerror}），台账按空算")
        return tables, rows, warns
    if CONFLICT_RE.search(text):
        warns.append("experiments.md 含合并冲突标记（<<<<<<< / >>>>>>>），先合并再用")
    lines = strip_comments(text, warns, "experiments.md ", keep_lines=True).split("\n")
    raw = text.split("\n")
    sec, cur, fence, i = "", None, False, 0
    while i < len(lines):
        ln, no = lines[i], i + 1
        if not ln.strip() and i < len(raw) and raw[i].strip():  # 整行在注释里：跳过，不打断表
            i += 1
            continue
        if FENCE_RE.match(ln):
            fence, cur = not fence, None
        elif fence:
            pass
        elif ln.startswith("## "):
            sec, cur = ln[3:].strip(), None
        elif "|" in ln and ln.strip():
            if i + 1 < len(lines) and is_sep(lines[i + 1]) and not is_sep(ln):  # 新表头（也可能紧贴上一张表）
                header = split_row(ln)
                low = [norm_head(h) for h in header]
                cur = {"section": sec, "header": header, "header_line": ln.rstrip(),
                       "node_col": next((k for k, h in enumerate(low) if h in NODE_HEADS), None),
                       "id_col": low.index("id") if "id" in low else 0, "n": len(tables)}
                tables.append(cur)
                i += 2
                continue
            if cur is None:
                if ln.lstrip().startswith("|"):
                    warns.append(f"experiments.md 第 {no} 行：表外的行（前面没有表头与分隔行），未计入")
            else:
                cells = split_row(ln)
                if len(cells) != len(cur["header"]):
                    warns.append(f"experiments.md 第 {no} 行：{len(cells)} 列，表头 {len(cur['header'])} 列")
                nodes = []
                if cur["node_col"] is not None and cur["node_col"] < len(cells):
                    nodes = node_cells(cells[cur["node_col"]])
                rid = cells[cur["id_col"]] if cur["id_col"] < len(cells) else ""
                rows.append({"table": cur, "cells": cells, "line": ln.rstrip(), "nodes": nodes,
                             "id": re.sub(r"[*`]", "", rid).strip()})
        else:
            cur = None
        i += 1
    return tables, rows, warns


def parse_verifier(path):
    out = {"exists": os.path.isfile(path), "status": "", "sections": {}}
    if not out["exists"]:
        return out
    try:
        text = read_text(path)
    except (UnicodeDecodeError, OSError):
        return out
    cur = None
    for ln in text.split("\n"):
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
        self.ignored = []
        tdir = os.path.join(d, "tree")
        self.has_tree = os.path.isdir(tdir)
        if self.has_tree:
            for f in sorted(os.listdir(tdir)):
                if f.startswith("."):
                    continue
                p = os.path.join(tdir, f)
                if not NODE_FILE_RE.match(f) or not os.path.isfile(p):
                    why = ("是目录" if os.path.isdir(p) else "坏软链" if os.path.islink(p) and not os.path.exists(p)
                           else "文件名不是 Q<n>.md / H<n>.md")
                    self.ignored.append(f"tree/{f}: 忽略的文件（{why}），不当节点")
                    continue
                try:
                    n = parse_node(p)
                except UnicodeDecodeError:
                    self.ignored.append(f"tree/{f}: 不是 UTF-8，跳过")
                    continue
                except OSError as e:
                    self.ignored.append(f"tree/{f}: 读不了（{e.strerror}），跳过")
                    continue
                self.nodes[n["id"]] = n
        self.tables, self.rows, self.ledger_warn = parse_ledger(os.path.join(d, "experiments.md"))
        self.verifier = parse_verifier(os.path.join(d, "verifier.md"))
        self.children = {i: [] for i in self.nodes}
        for n in self.nodes.values():
            if n["parent"] in self.nodes and n["parent"] != n["id"]:
                self.children[n["parent"]].append(n["id"])
        for k in self.children:
            self.children[k].sort(key=id_key)
        self.rows_of = {i: [] for i in self.nodes}
        for r in self.rows:
            for x in r["nodes"]:
                if x in self.rows_of:
                    self.rows_of[x].append(r)
        self.warnings = self.check()
        # 顶层 = 根 + parent 悬空的 + 环上没有根可达的
        reach = set()
        def walk(i):
            stack = [i]
            while stack:
                x = stack.pop()
                if x not in reach:
                    reach.add(x)
                    stack.extend(self.children[x])
        self.tops = sorted([i for i, n in self.nodes.items() if not n["parent"] or n["parent"] not in self.nodes],
                           key=id_key)
        for x in self.tops:
            walk(x)
        for i in sorted(self.nodes, key=id_key):
            if i not in reach:
                self.tops.append(i)
                walk(i)

    def check(self):
        w = list(self.ignored)
        for i in sorted(self.nodes, key=id_key):
            n = self.nodes[i]
            w.extend(f"{i}: {x}" for x in n["warn"])
            if not n["fm"]:
                w.append(f"{i}: 没有 frontmatter（--- 包起来的 title/parent/status）")
            if not n["title"]:
                w.append(f"{i}: 缺 title")
            if n["parent"] == i:
                w.append(f"{i}: parent 指向自己")
            elif n["parent"] and n["parent"] not in self.nodes:
                w.append(f"{i}: parent {n['parent']} 不存在")
            if n["status"] not in STATUSES:
                w.append(f"{i}: status「{n['status'] or '空'}」不是 {'|'.join(STATUSES)}")
            if n["verdict"] and n["verdict"] not in VERDICTS:
                w.append(f"{i}: verdict「{n['verdict']}」不是 {'|'.join(VERDICTS)}")
            if n["status"] == "closed":
                if not n["verdict"]:
                    w.append(f"{i}: closed 但没有 verdict")
                if is_blank(section(n, "结论")):
                    w.append(f"{i}: closed 但结论为空")
            elif n["verdict"]:
                w.append(f"{i}: verdict 只用于 closed（现在 status={n['status'] or '空'}）")
            if n["status"] == "active" and i.startswith("H") and is_blank(section(n, "判别")):
                w.append(f"{i}: 假设 active 但判别为空（跑之前先写预测与什么算错）")
            p = self.nodes.get(n["parent"])
            if p and n["status"] in ("open", "active") and p["status"] == "closed":
                w.append(f"{i}: {n['status']}，但父 {p['id']} 已 closed（关掉它，或把它挂到还开着的问题下）")
            if n["verdict"] == "superseded" and not n["by"]:
                w.append(f"{i}: superseded 但没写 by")
            if n["by"] and n["verdict"] != "superseded":
                w.append(f"{i}: 写了 by 但 verdict 不是 superseded")
            for b in n["by"]:
                if b == i:
                    w.append(f"{i}: by 指向自己")
                elif b not in self.nodes:
                    w.append(f"{i}: by {b} 不存在")
        seen_cycles = set()
        for i in self.nodes:
            path, on, cur = [], set(), i
            while cur in self.nodes and cur not in on:
                path.append(cur)
                on.add(cur)
                cur = self.nodes[cur]["parent"]
            if cur in on and cur != self.nodes[cur]["parent"]:
                cyc = path[path.index(cur):]
                key = frozenset(cyc)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    w.append("成环: " + " → ".join(cyc + [cur]))
        w.extend(self.ledger_warn)
        for r in self.rows:
            for x in r["nodes"]:
                if x not in self.nodes:
                    where = f"（{r['table']['section']}）" if r["table"]["section"] else ""
                    w.append(f"台账 {r['id'] or '?'}{where}: node {x} 不存在")
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
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
            stack.extend(self.children[c])
        return out

    def constraints(self, rid):
        """根 rid 的约束，加上约束里 [[ID]] 引用到的其他根的约束（递归、去重）。返回 [(根 ID, 文本, 引用者)]。"""
        out, seen, todo = [], {rid}, [(rid, None)]
        while todo:
            r, by = todo.pop(0)
            c = section(self.nodes[r], "约束")
            if c or by is None:
                out.append((r, c, by))
            for x in REF_RE.findall(c):
                if x in self.nodes and not self.nodes[x]["parent"] and x not in seen:
                    seen.add(x)
                    todo.append((x, r))
        return out


def id_key(i):
    m = re.match(r"^([A-Za-z_-]*?)(\d+)$", i)
    return (m.group(1), int(m.group(2)), "") if m else (i, 0, i)


def tag(n):
    s = n["status"] or "?"
    return f"{s}/{n['verdict']}" if n["verdict"] else s


# ---------- 文字输出 ----------

def short_chain(ch, keep=6):
    """深链只留根和最近 keep 代，中间用 None 占位（显示成 …）。"""
    return ch if len(ch) <= keep + 2 else ch[:1] + [None] + ch[-keep:]


def par_note(t, n):
    """父节点不是 open/active 时注一句，免得在搁置或已关的问题下照常干活。"""
    p = t.nodes.get(n["parent"])
    if p and p["status"] not in ("open", "active"):
        return f"父 {p['id']} {p['status'] or '无 status'}"
    return ""


def text_default(t, show_all):
    o = []
    cnt = {s: 0 for s in STATUSES}
    other = 0
    for n in t.nodes.values():
        if n["status"] in cnt:
            cnt[n["status"]] += 1
        else:
            other += 1
    o.append(f"研究树 {t.slug}：{len(t.nodes)} 节点（" + "，".join(f"{s} {cnt[s]}" for s in STATUSES)
             + (f"，其他 {other}" if other else "")
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
        note = par_note(t, n)
        o.append(f"- {i} {n['title']}" + (f"（{note}）" if note else ""))
        ch = t.chain(i)
        if ch:
            o.append("  链: " + " > ".join("…" if c is None else f"{c} {t.nodes[c]['title']}" for c in short_chain(ch)))
        rows = t.rows_of.get(i, [])
        if rows:
            o.append("  台账: " + ", ".join(r["id"] or "?" for r in rows))
        kids = t.children.get(i, [])
        if kids and all(t.nodes[k]["status"] == "closed" for k in kids):
            o.append("  子假设全关：决定答完（写结论）或新提假设")
    rest = [i for i in sorted(t.nodes, key=id_key) if t.nodes[i]["status"] in ("open", "parked")]
    quiet = {}  # 搁置或已关的根下的 open/parked 只计数
    o.append("\n## open / parked")
    shown = []
    for i in rest:
        r = t.root_of(i)
        if r != i and not t.nodes[r]["parent"] and t.nodes[r]["status"] in ("parked", "closed") and not show_all:
            quiet[r] = quiet.get(r, 0) + 1
            continue
        shown.append(i)
    for i in (shown if show_all else shown[:OPEN_LIMIT]):
        n = t.nodes[i]
        note = par_note(t, n)
        p = f"（{n['parent']} 下" + (f"，{note}" if note else "") + "）" if n["parent"] else "（根）"
        o.append(f"- {i} [{n['status']}] {n['title']}{p}")
    if not show_all and len(shown) > OPEN_LIMIT:
        o.append(f"- …另有 {len(shown) - OPEN_LIMIT} 个，见 pt tree {t.slug} --all 或 tree.html")
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
    cons = t.constraints(root["id"])
    o = []
    if blind:
        d = section(n, "判别")
        refs = sorted(set(REF_RE.findall(d)), key=id_key)
        if refs:
            o.append(f"[warn] 判别引用了 {len(refs)} 个节点（下面已换成 [[…]]）：盲出前确认判别里没写候选或排名")
        o.append(f"# {i} {n['title']}（盲：只给问题、约束与考官）")
        o.append(f"\n## 判别\n{REF_RE.sub('[[…]]', d) or '(空)'}")
        for r, c, by in cons:
            o.append(f"\n## 约束（根 {r}" + (f"，{by} 的约束引用" if by else "") + f"）\n{c or '(无)'}")
        v = t.verifier
        if not v["exists"]:
            o.append("\n## 考官\n无考官卡（没有 verifier.md）")
        else:
            o.append(f"\n## 考官\n{v['status'] or '(考官卡没有 Status 行)'}")
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
    for r, c, by in cons:
        if by:
            o.append(f"\n## 根 {r} · 约束（{by} 的约束引用）\n{c}")
    ch = t.chain(i)
    if ch:
        o.append("\n## 祖先链（根 → 父）")
        for c in short_chain(ch, 10):
            if c is None:
                o.append(f"\n（中间省略 {len(ch) - 11} 代，--ctx 那些节点看）")
                continue
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
    order = {id(r): k for k, r in enumerate(t.rows)}
    rows.sort(key=lambda r: order[id(r)])
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
    """转义后再做行内标记：`code`、[[ID]]、[文字](链接)、**粗体**。
    代码、引用、链接先换成私有区占位符，粗体只在剩下的文字上做，跨不进 URL 也打不碎标签。"""
    keep = []
    def hold(h):
        keep.append(h)
        return f"{len(keep) - 1}"
    s = s.replace("", "").replace("", "")
    s = re.sub(r"`([^`]+)`", lambda m: hold(f"<code>{esc(m.group(1))}</code>"), s)
    s = esc(s)
    def ref(m):
        i = m.group(1)
        if i in t.nodes:
            return hold(f'<a class="ref" href="#{esc(i)}">{esc(i)}</a>')
        return hold(f'<span class="ref dangling" title="不存在">{esc(i)}</span>')
    s = REF_RE.sub(ref, s)
    def link(m):
        txt, url = m.group(1), html.unescape(m.group(2))
        if SAFE_URL.match(url) and "\ue000" not in url:
            return hold(f'<a href="{esc(url)}">{bold(txt)}</a>')
        return m.group(0)
    s = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", link, s)
    s = bold(s)
    for _ in range(4):  # 链接文字里可能还套着代码占位
        s2 = re.sub("(\\d+)", lambda m: keep[int(m.group(1))], s)
        if s2 == s:
            break
        s = s2
    return s


def bold(s):
    return re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", s)


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


def st_cls(n):
    """class 只取白名单值：status 不认识的归「其他」(s-unknown)，verdict 不认识的 v-unknown。"""
    s = n["status"] if n["status"] in STATUSES else "unknown"
    v = (n["verdict"] if n["verdict"] in VERDICTS else "unknown") if n["verdict"] else ""
    return s, v


def badge(n):
    s, v = st_cls(n)
    b = f'<span class="b s-{s}">{esc(n["status"] or "?")}</span>'
    if v:
        b += f' <span class="b v-{v}">{esc(n["verdict"])}</span>'
    return b


def tree_ul(t, tops):
    """左侧树。用显式栈，深链几千层也不爆递归。"""
    out, seen, stack = [], set(), []
    for top in tops:
        stack.append(top)
        while stack:
            i = stack.pop()
            if i is None:
                out.append("</ul></li>")
                continue
            if i in seen:
                continue
            seen.add(i)
            n = t.nodes[i]
            kids = [c for c in t.children[i] if c not in seen]
            s, v = st_cls(n)
            cls = f"s-{s}" + (f" v-{v}" if v else "")
            caret = '<button class="caret" aria-label="折叠"></button>' if kids else '<span class="caret none"></span>'
            out.append(f'<li data-id="{esc(i)}" data-status="{s if s != "unknown" else "other"}">{caret}'
                       f'<a class="n {cls}" href="#{esc(i)}" title="{esc(i)} {esc(n["title"])}"><span class="dot"></span>'
                       f'<b>{esc(i)}</b> {esc(n["title"])}</a>')
            if kids:
                out.append("<ul>")
                stack.append(None)
                stack.extend(reversed(kids))
            else:
                out.append("</li>")
    return "".join(out)


def graph_data(t):
    """总览图的数据：节点按左侧树的先序排（后代在 [i+1, i+size) 一段里），p 是显示用的父（下标，-1 为顶层）。
    文本只走 JSON + textContent；JSON 里的 < > & 换成 \\u 转义，script 里关不掉、注释也开不了。"""
    order, idx = [], {}
    for top in t.tops:
        stack = [(top, -1)]
        while stack:
            i, p = stack.pop()
            if i in idx:
                continue
            idx[i] = len(order)
            order.append((i, p))
            stack.extend((c, idx[i]) for c in reversed(t.children[i]) if c not in idx)
    nodes = []
    for i, p in order:
        n = t.nodes[i]
        s, v = st_cls(n)
        near = {i, n["parent"], *t.children[i]}
        refs = sorted({x for x in REF_RE.findall(strip_comments(n["body"])) if x in t.nodes and x not in near}, key=id_key)
        nodes.append({"i": i, "t": n["title"][:300], "p": p, "s": s, "v": v, "S": n["status"][:40], "V": n["verdict"][:40],
                      "n": len(t.rows_of[i]), "b": [b for b in n["by"] if b in t.nodes and b != i], "r": refs})
    doc = json.dumps({"slug": t.slug, "nodes": nodes}, ensure_ascii=False, separators=(",", ":"))
    return doc.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# 配色取自 dataviz 参考调色板：表面与墨色、分类色前三槽（蓝 active、绿 supported、红 refuted，--pairs all 两种模式都过），
# 其余 verdict 用中性灰并靠图标区分（✓ ✗ ? → –），颜色不单独承担信息。深色用各自的色阶。
# PALETTE 由 tree.html 与 research.html（monitor.py）共用
PALETTE = """:root{--bg:#f9f9f7;--panel:#fcfcfb;--fg:#0b0b0b;--mut:#52514e;--faint:#898781;--line:#e1e0d9;--edge:#c3c2b7;--hl:#f0efec;--link:#256abf;--warnc:#d03b3b;
--open:#52514e;--active:#2a78d6;--parked:#898781;--closed:#898781;--on:#ffffff;--on-inc:#ffffff;
--supported:#008300;--refuted:#e34948;--inconclusive:#52514e;--superseded:#898781;--abandoned:#898781;--other:#898781;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d0d;--panel:#1a1a19;--fg:#f0efec;--mut:#c3c2b7;--faint:#898781;--line:#2c2c2a;--edge:#55544f;--hl:#2c2c2a;--link:#6da7ec;--warnc:#e66767;
--open:#c3c2b7;--active:#3987e5;--parked:#898781;--closed:#898781;--on:#ffffff;--on-inc:#1a1a19;
--supported:#008300;--refuted:#e66767;--inconclusive:#c3c2b7;--superseded:#898781;--abandoned:#898781;--other:#898781;color-scheme:dark}}
"""

CSS = PALETTE + """
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
.v-abandoned .dot{background:none;border-color:var(--abandoned);border-style:dotted}.s-unknown .dot{border-color:var(--other)}
li.dim>a.n{opacity:.45}li.hide{display:none}
.b{display:inline-block;font-size:12px;padding:0 7px;border-radius:10px;border:1.5px solid var(--line);color:var(--fg)}
.b.s-open{border-color:var(--open)}.b.s-active{border-color:var(--active)}.b.s-parked{border-color:var(--parked);border-style:dashed}.b.s-closed{border-color:var(--closed)}
.b.v-supported{border-color:var(--supported)}.b.v-refuted{border-color:var(--refuted)}.b.v-inconclusive{border-color:var(--inconclusive)}.b.v-superseded{border-color:var(--superseded)}
.b.v-abandoned{border-color:var(--abandoned);border-style:dotted}.b.s-unknown,.b.v-unknown{border-color:var(--other);border-style:dashed}
article h2{font-size:19px;margin:0 0 6px}article h3{font-size:15px;margin:18px 0 6px;padding-bottom:3px;border-bottom:1px solid var(--line)}
article h4,article h5,article h6{font-size:14px;margin:12px 0 4px}.meta{color:var(--mut);margin-bottom:10px}
a{color:var(--link)}a.ref{font-family:ui-monospace,monospace;font-size:13px}.dangling{color:var(--warnc);text-decoration:line-through}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:var(--hl);padding:0 3px;border-radius:3px;word-break:break-all}
.tw{overflow-x:auto;margin:6px 0}table{border-collapse:collapse;font-size:13px}th,td{border:1px solid var(--line);padding:3px 6px;vertical-align:top;text-align:left}
th{background:var(--hl)}td{min-width:3em;max-width:36em}article,td{overflow-wrap:anywhere}
.warn{color:var(--warnc)}ul.plain{padding-left:18px}
@media (max-width:720px){.wrap{flex-direction:column}nav{width:auto;max-width:none;max-height:42vh;border-right:0;border-bottom:1px solid var(--line)}main{padding:12px 16px 40px}}
header button{font:inherit;font-size:13px;padding:2px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);cursor:pointer}
.vsw{display:inline-flex}.vsw button{border-radius:0}.vsw button:first-child{border-radius:6px 0 0 6px}.vsw button:last-child{border-radius:0 6px 6px 0;border-left:0}
.vsw button[aria-pressed=true]{background:var(--fg);color:var(--panel);border-color:var(--fg)}
#graph,#dbar{display:none}body.vg nav,body.vg main{display:none}
body.vg #graph{display:flex;flex-direction:column;flex:1;min-width:0;position:relative;background:var(--panel)}
body.vg.dopen main{display:block;flex:0 0 clamp(320px,38%,560px);border-left:1px solid var(--line);background:var(--bg);padding-top:0}
body.vg #dbar{display:flex;position:sticky;top:0;z-index:1;background:var(--bg);margin:0 -22px 10px;padding:7px 22px;border-bottom:1px solid var(--line)}
#dbar button{font:inherit;font-size:13px;flex:1;min-width:0;display:flex;gap:8px;text-align:left;border:0;background:none;color:var(--fg);padding:2px 0;cursor:pointer}
#dlab{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}#dbar .x{color:var(--mut)}
#gsvg{flex:1;min-height:0;width:100%;display:block;touch-action:none;cursor:grab;user-select:none;-webkit-user-select:none;outline:none}
#gsvg.drag{cursor:grabbing}
.gbar{position:absolute;top:8px;right:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:flex-end;z-index:2}
.gbar button,.gbar label{font:inherit;font-size:12.5px;padding:2px 9px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);cursor:pointer;white-space:nowrap}
#glegend{display:flex;flex-wrap:wrap;gap:3px 14px;align-items:center;padding:6px 12px;border-top:1px solid var(--line);font-size:12px;color:var(--mut)}
#glegend span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}#glegend svg{overflow:visible}#glegend i{font-style:normal;color:var(--fg)}
#gtip{position:absolute;z-index:3;pointer-events:none;max-width:320px;padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);font-size:12.5px;line-height:1.45;box-shadow:0 2px 8px rgba(11,11,11,.12);overflow-wrap:anywhere}
#gtip b{font-weight:600}#gtip .m{color:var(--mut)}
.ed{fill:none;stroke:var(--edge);stroke-width:1.4}.ed.hl{stroke:var(--fg);stroke-width:2}
.by{fill:none;stroke:var(--mut);stroke-width:1.3;stroke-dasharray:5 3}.byh{fill:var(--mut)}
.rf{fill:none;stroke:var(--faint);stroke-width:1.1;stroke-dasharray:1 3;stroke-linecap:round;opacity:.8}
.mk .sh{fill:var(--panel);stroke:var(--open);stroke-width:1.7}
.mk.s-active .sh{fill:var(--active);stroke:var(--active)}.mk .ring{fill:none;stroke:var(--active);stroke-width:1.4}
.mk.s-parked .sh{stroke:var(--parked);stroke-dasharray:2.6 2}.mk.s-unknown .sh{stroke:var(--other);stroke-dasharray:1.5 1.5}
.mk.s-closed .sh{fill:var(--closed);stroke:var(--closed);stroke-width:1.2}
.mk.v-supported .sh{fill:var(--supported);stroke:var(--supported)}.mk.v-refuted .sh{fill:var(--refuted);stroke:var(--refuted)}
.mk.v-inconclusive .sh{fill:var(--inconclusive);stroke:var(--inconclusive)}.mk.v-superseded .sh{fill:var(--superseded);stroke:var(--superseded)}
.mk.v-abandoned .sh{fill:var(--panel);stroke:var(--abandoned);stroke-width:1.5}
.gl{font-size:10px;font-weight:700;fill:var(--on);text-anchor:middle;dominant-baseline:central}
.v-inconclusive .gl{fill:var(--on-inc)}.v-abandoned .gl,.s-unknown .gl,.v-unknown .gl{fill:var(--mut)}
.nd,.stub{cursor:pointer;outline:none}.nd .bg,.stub .bg{fill:transparent;stroke:none}
.nd:hover .bg,.nd.hl .bg,.nd:focus .bg,.stub:hover .bg,.stub:focus .bg{fill:var(--hl)}
.nd.sel .bg{fill:var(--hl);stroke:var(--active);stroke-width:1.5}.nd:focus-visible .bg{stroke:var(--fg);stroke-width:1.5}
.lb{font-size:12.5px;fill:var(--fg);dominant-baseline:central}.lb .id{font-weight:600}
.nd.cl{opacity:.62}.nd.cl .lb{fill:var(--mut)}.nd.cl:hover,.nd.cl.hl,.nd.cl.sel,.nd.cl:focus{opacity:1}
.nd.dim,.stub.dim{opacity:.18}.nd.dim:hover{opacity:.7}
.bd rect{fill:var(--panel);stroke:var(--mut);stroke-width:.9}.bd text{font-size:8.5px;fill:var(--fg);text-anchor:middle;dominant-baseline:central;font-weight:600}
.fd rect{fill:var(--panel);stroke:var(--edge);stroke-width:1}.fd text{font-size:11px;fill:var(--mut);text-anchor:middle;dominant-baseline:central}
.fd:hover rect{stroke:var(--fg)}.fd.hit rect{stroke:var(--active);stroke-width:1.6}.fd.hit text{fill:var(--fg)}
.stub rect.p{fill:var(--panel);stroke:var(--faint);stroke-dasharray:3 2}.stub text{font-size:12px;fill:var(--mut);dominant-baseline:central}
@media (max-width:720px){body.vg .wrap{flex-direction:column}body.vg #graph{margin-bottom:46px}
body.vg main,body.vg.dopen main{display:block;position:fixed;left:0;right:0;bottom:0;z-index:5;max-height:46px;overflow:hidden;border-left:0;border-top:1px solid var(--line);padding-top:0;box-shadow:0 -2px 10px rgba(11,11,11,.12)}
body.vg.dopen main{max-height:58vh;overflow:auto}
body.vg #dbar{margin:0 -16px 8px;padding:7px 16px}
.gbar{top:6px;right:6px}#glegend{gap:2px 10px;font-size:11.5px;padding:5px 10px}#glegend .hint{display:none}}
"""

JS = r"""
(function(){
var $=function(id){return document.getElementById(id);};
var DATA=JSON.parse($('gdata').textContent),KEY='pt-tree:'+DATA.slug+':';
function sget(k){try{return localStorage.getItem(KEY+k);}catch(e){return null;}}
function sset(k,v){try{localStorage.setItem(KEY+k,v);}catch(e){}}
var nav=document.querySelector('nav'),main=document.querySelector('main'),q=$('q'),hc=$('hideclosed');
var boxes=[].slice.call(document.querySelectorAll('input[data-st]'));
var arts={};[].forEach.call(document.querySelectorAll('article'),function(a){arts[a.id]=a;});
var ids={};[].forEach.call(nav.querySelectorAll('li[data-id]'),function(l){var i=l.getAttribute('data-id');ids[i.toLowerCase()]=i;});
var texts={};function txt(id){if(!(id in texts)){var a=arts['n-'+id],h=a&&a.querySelector('h2'),b=a&&a.querySelector('.body');texts[id]=((h?h.textContent:'')+' '+(b?b.textContent:'')).toLowerCase();}return texts[id];}
var view=sget('view')==='list'?'list':'graph',G=null,fromGraph=false;
nav.addEventListener('click',function(e){if(e.target.classList.contains('caret')){e.target.parentNode.classList.toggle('fold');}});
$('fold').addEventListener('click',function(){if(view==='graph')return G.foldAll();[].forEach.call(nav.querySelectorAll('li'),function(l){if(l.querySelector('ul'))l.classList.add('fold');});});
$('unfold').addEventListener('click',function(){if(view==='graph')return G.unfoldAll();[].forEach.call(nav.querySelectorAll('li.fold'),function(l){l.classList.remove('fold');});});
function pred(){
 var on={};boxes.forEach(function(b){on[b.getAttribute('data-st')]=b.checked;});
 var s=q.value.trim().toLowerCase(),ex=ids[s],any=!!s||boxes.some(function(b){return !b.checked;});
 return {any:any,s:s,f:function(id,st){return (on[st]!==false)&&(ex?id===ex:(!s||txt(id).indexOf(s)>=0));}};
}
function filt(){
 var P=pred(),hide=hc.checked;
 function visit(li){
  var st=li.getAttribute('data-status'),id=li.getAttribute('data-id');
  var self=P.f(id,st)&&!(hide&&st==='closed');
  var kid=false,ul=li.querySelector(':scope>ul');
  if(ul)[].forEach.call(ul.children,function(c){if(visit(c))kid=true;});
  li.classList.toggle('hide',!self&&!kid);li.classList.toggle('dim',!self&&kid);
  if(P.s&&kid)li.classList.remove('fold');
  return self||kid;}
 [].forEach.call(nav.querySelector('ul').children,visit);
 sset('hc',hide?'1':'0');
 if(G){G.setAlive(hide);G.setFilter(P.any?P.f:null);}
}
boxes.forEach(function(b){b.addEventListener('change',filt);});q.addEventListener('input',filt);hc.addEventListener('change',filt);
q.addEventListener('keydown',function(e){if(e.key!=='Enter')return;e.preventDefault();
 var P=pred();if(!P.s)return;var N=DATA.nodes,cur=location.hash.slice(1),k0=-1,k;
 for(k=0;k<N.length;k++)if(N[k].i===cur)k0=k;
 for(k=1;k<=N.length;k++){var n=N[(k0+k+N.length)%N.length];if(P.f(n.i,n.s==='unknown'?'other':n.s)){if(n.i===cur)show();else location.hash=n.i;return;}}});
if(sget('hc')==='1')hc.checked=true;
function show(){
 var id=location.hash.slice(1);try{id=decodeURIComponent(id);}catch(e){}
 var a=arts['n-'+id]||arts['overview'],miss=$('miss');
 miss.hidden=!(id&&!arts['n-'+id]);miss.textContent=miss.hidden?'':'没有节点 '+id;
 for(var k in arts)arts[k].hidden=(arts[k]!==a);
 [].forEach.call(nav.querySelectorAll('a.cur'),function(x){x.classList.remove('cur');});
 var l=nav.querySelector('li[data-id="'+(window.CSS&&CSS.escape?CSS.escape(id):id)+'"]');
 if(l){var p=l.parentNode;while(p&&p!==nav){if(p.tagName==='LI')p.classList.remove('fold');p=p.parentNode;}
  var n=l.querySelector(':scope>a.n')||l.querySelector('a.n');if(n){n.classList.add('cur');if(view==='list')n.scrollIntoView({block:'nearest'});}}
 main.scrollTop=0;$('dlab').textContent=a.id==='overview'?'总览':(a.querySelector('h2')||{}).textContent||'';
 document.body.classList.toggle('dopen',a.id!=='overview');
 if(G)G.select(l?id:null,!fromGraph);fromGraph=false;
}
function deselect(){if(!location.hash)return;history.pushState(null,'',location.pathname+location.search);show();}
$('dtog').addEventListener('click',function(){document.body.classList.toggle('dopen');});
$('gpan').addEventListener('click',function(){document.body.classList.toggle('dopen');});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){if(G)G.hideTip();deselect();}});
function setView(v){view=v;sset('view',v);document.body.classList.toggle('vg',v==='graph');
 $('vg').setAttribute('aria-pressed',v==='graph');$('vl').setAttribute('aria-pressed',v==='list');
 if(v==='graph'){if(!G){G=graph();filt();}G.shown();}show();}
$('vg').addEventListener('click',function(){setView('graph');});$('vl').addEventListener('click',function(){setView('list');});
window.addEventListener('hashchange',show);

function graph(){
 var host=$('graph'),svg=$('gsvg'),NS=svg.namespaceURI,vp=$('gvp'),LE=$('ge'),LB=$('gb'),LR=$('gr'),LN=$('gn'),tip=$('gtip');
 var N=DATA.nodes,n=N.length,kids=[],size=new Int32Array(n),allc=new Uint8Array(n),col=new Uint8Array(n),id2={},i,k;
 for(i=0;i<n;i++){kids.push([]);id2[N[i].i]=i;}
 for(i=0;i<n;i++)if(N[i].p>=0)kids[N[i].p].push(i);
 for(i=n-1;i>=0;i--){var sz=1,ac=N[i].s==='closed';for(k=0;k<kids[i].length;k++){sz+=size[kids[i][k]];if(!allc[kids[i][k]])ac=false;}size[i]=sz;allc[i]=ac?1:0;col[i]=kids[i].length&&ac?1:0;}
 var tops=[];for(i=0;i<n;i++)if(N[i].p<0)tops.push(i);
 var alive=false,stubOpen={},showRefs=false,filter=null,sel=-1,items=[],pos=new Int32Array(n),nodeEl=[],edgeEl=[],ext=null;
 var tx=0,ty=0,sc=1,moved=false,fitted=false;
 var FS=12.5,MAXT=18*FS,ROW=25,GAP=40,GLY={supported:'✓',refuted:'✗',inconclusive:'?',superseded:'→',abandoned:'–'};
 var cv=document.createElement('canvas').getContext('2d'),FAM=getComputedStyle(document.body).fontFamily,labs=[];
 function mw(s,b){cv.font=(b?'600 ':'')+FS+'px '+FAM;return cv.measureText(s).width;}
 function trunc(s){if(mw(s)<=MAXT)return s;var a=Array.from(s),lo=0,hi=a.length;while(lo<hi){var m=(lo+hi+1)>>1;if(mw(a.slice(0,m).join('')+'…')<=MAXT)lo=m;else hi=m-1;}return a.slice(0,lo).join('')+'…';}
 function lab(i){if(!labs[i]){var t=trunc(N[i].t||''),iw=mw(N[i].i,1),tw=t?mw(t):0;labs[i]={t:t,w:iw+(t?4+tw:0)};}return labs[i];}
 function el(tag,at,par){var e=document.createElementNS(NS,tag);for(var a in at)e.setAttribute(a,at[a]);if(par)par.appendChild(e);return e;}
 function tx_(par,x,y,cls,s){var t=el('text',{x:x,y:y,'class':cls},par);t.textContent=s;return t;}
 function mark(par,s,v,q){
  var g=el('g',{'class':'mk s-'+s+(v?' v-'+v:'')},par);
  if(s==='active'){if(q)el('rect',{'class':'ring',x:-11,y:-11,width:22,height:22,rx:6},g);else el('circle',{'class':'ring',r:11},g);}
  if(q)el('rect',{'class':'sh',x:-7,y:-7,width:14,height:14,rx:3},g);else el('circle',{'class':'sh',r:7.5},g);
  var gl=s==='closed'?(GLY[v]||'!'):s==='unknown'?'!':'';if(gl)tx_(g,0,0.5,'gl',gl);return g;}
 function badge(par,c){var s=String(c),w=Math.max(10,s.length*5.4+5),g=el('g',{'class':'bd',transform:'translate(4,4)'},par);
  el('rect',{x:0,y:0,width:w,height:10,rx:5},g);tx_(g,w/2,5.3,'',s);return g;}
 function isQ(i){return N[i].i.charAt(0)==='Q';}
 function stubKids(p,list){if(!alive||stubOpen[p])return [list,null];var a=[],h=[],c=0;
  list.forEach(function(x){if(allc[x]){h.push(x);c+=size[x];}else a.push(x);});return [a,h.length?{h:h,c:c}:null];}
 function build(){
  items=[];pos.fill(-1);var st=[];
  function push(p,list,d,par){var r=stubKids(p,list),e=[];r[0].forEach(function(x){e.push({i:x,d:d,par:par});});
   if(r[1])e.push({stub:r[1],sp:p,d:d,par:par});for(var k=e.length-1;k>=0;k--)st.push(e[k]);}
  push(-1,tops,0,-1);
  while(st.length){var e=st.pop(),ix=items.length;e.kids=[];items.push(e);if(e.par>=0)items[e.par].kids.push(ix);
   if(e.stub)continue;pos[e.i]=ix;if(!col[e.i]&&kids[e.i].length)push(e.i,kids[e.i],e.d+1,ix);}
 }
 function layout(){
  var mx=[],it,k,j;
  for(k=0;k<items.length;k++){it=items[k];
   if(it.stub){it.lt='已关 '+it.stub.c+' 个';it.R=mw(it.lt+' \u25b8')+6;}
   else{var L=lab(it.i);it.R=13+L.w;if(kids[it.i].length){it.ft=col[it.i]?'+'+(size[it.i]-1):'−';it.fw=col[it.i]?mw(it.ft)+10:16;it.R+=6+it.fw;}}
   it.w=8+it.R;mx[it.d]=Math.max(mx[it.d]||0,it.w);}
  var cx=[0];for(k=1;k<mx.length;k++)cx[k]=cx[k-1]+mx[k-1]+GAP;
  var row=0,first=true;
  for(k=0;k<items.length;k++){it=items[k];it.x=cx[it.d]+8;it.gx=cx[it.d]+mx[it.d]+4;
   if(it.par<0){if(!first)row+=0.6;first=false;}
   if(!it.kids.length){it.y=row*ROW;row++;}}
  for(k=items.length-1;k>=0;k--){it=items[k];if(it.kids.length)it.y=(items[it.kids[0]].y+items[it.kids[it.kids.length-1]].y)/2;}
  var W=0;for(k=0;k<items.length;k++)W=Math.max(W,items[k].x+items[k].R);
  ext={x0:-16,y0:-18,x1:W+16,y1:Math.max(0,row-1)*ROW+18};
 }
 function curve(a,b,bend){var dx=b[0]-a[0],dy=b[1]-a[1],L=Math.sqrt(dx*dx+dy*dy)||1,ux=dx/L,uy=dy/L,o=Math.min(60,L*0.22)*bend;
  var c=[(a[0]+b[0])/2-uy*o,(a[1]+b[1])/2+ux*o];return {c:c,d:'M'+a[0]+','+a[1]+'Q'+c[0]+','+c[1]+' '+b[0]+','+b[1]};}
 function draw(){
  [LE,LB,LR,LN].forEach(function(g){while(g.firstChild)g.removeChild(g.firstChild);});
  nodeEl=[];edgeEl=[];var fe=document.createDocumentFragment(),fn=document.createDocumentFragment(),k,it,g,p;
  for(k=0;k<items.length;k++){it=items[k];
   if(it.par>=0){p=items[it.par];var sx=p.x+p.R+2,ex=it.x-(it.stub?9:N[it.i].s==='active'?13:10),m=(p.gx+ex)/2;
    edgeEl[k]=el('path',{'class':'ed',d:'M'+sx+','+p.y+'H'+p.gx+'C'+m+','+p.y+' '+m+','+it.y+' '+ex+','+it.y},fe);}
   g=el('g',{'data-k':k,tabindex:0,transform:'translate('+it.x+','+it.y+')'},fn);nodeEl[k]=g;
   if(it.stub){g.setAttribute('class','stub');g.setAttribute('role','button');g.setAttribute('aria-label',it.lt+'，展开');
    el('rect',{'class':'bg',x:-11,y:-12,width:it.R+14,height:24,rx:6},g);el('rect',{'class':'p',x:-8,y:-9,width:it.R+8,height:18,rx:9},g);tx_(g,0,0.5,'',it.lt+' ▸');continue;}
   var i=it.i,nd=N[i],L=lab(i);
   g.setAttribute('class','nd'+(nd.s==='closed'?' cl':'')+(i===sel?' sel':''));g.setAttribute('role','button');
   g.setAttribute('aria-label',nd.i+' '+nd.t+'，'+nd.S+(nd.V?' / '+nd.V:''));
   el('rect',{'class':'bg',x:-12,y:-12,width:it.R+(kids[i].length?-it.fw-6:0)+16,height:24,rx:6},g);
   mark(g,nd.s,nd.v,isQ(i));if(nd.n)badge(g,nd.n);
   var t=el('text',{x:13,y:0.5,'class':'lb'},g),s1=el('tspan',{'class':'id'},t);s1.textContent=nd.i;
   if(L.t){var s2=el('tspan',{dx:4},t);s2.textContent=L.t;}
   if(kids[i].length){var f=el('g',{'class':'fd',transform:'translate('+(it.R-it.fw)+',0)'},g);
    el('rect',{x:0,y:-8,width:it.fw,height:16,rx:8},f);tx_(f,it.fw/2,0.5,'',it.ft);it.fdEl=f;}
  }
  LE.appendChild(fe);LN.appendChild(fn);
  var fb=document.createDocumentFragment();
  for(k=0;k<items.length;k++){it=items[k];if(it.stub)continue;
   N[it.i].b.forEach(function(b){var j=pos[id2[b]];if(j<0)return;var B=items[j],a=[it.x,it.y],z=[B.x,B.y],dx=z[0]-a[0],dy=z[1]-a[1],L=Math.sqrt(dx*dx+dy*dy);if(L<30)return;
    a=[a[0]+dx/L*11,a[1]+dy/L*11];z=[z[0]-dx/L*14,z[1]-dy/L*14];var c=curve(a,z,1);el('path',{'class':'by',d:c.d},fb);
    var hx=z[0]-c.c[0],hy=z[1]-c.c[1],hl=Math.sqrt(hx*hx+hy*hy)||1;hx/=hl;hy/=hl;
    el('path',{'class':'byh',d:'M'+z[0]+','+z[1]+'L'+(z[0]-hx*7-hy*3.5)+','+(z[1]-hy*7+hx*3.5)+'L'+(z[0]-hx*7+hy*3.5)+','+(z[1]-hy*7-hx*3.5)+'Z'},fb);});}
  LB.appendChild(fb);
  if(showRefs){var fr=document.createDocumentFragment(),seen={};
   for(k=0;k<items.length;k++){it=items[k];if(it.stub)continue;
    N[it.i].r.forEach(function(r){var j=pos[id2[r]],key=Math.min(k,j)+':'+Math.max(k,j);if(j<0||seen[key])return;seen[key]=1;var B=items[j];
     el('path',{'class':'rf',d:curve([it.x,it.y],[B.x,B.y],-1).d},fr);});}
   LR.appendChild(fr);}
  dim();
 }
 function render(){build();layout();draw();}
 function hiddenHit(a,b){for(var j=a;j<b;j++)if(filter(N[j].i,N[j].s==='unknown'?'other':N[j].s))return true;return false;}
 function dim(){for(var k=0;k<items.length;k++){var it=items[k],g=nodeEl[k],d=false,h=false;
  if(filter){if(it.stub){d=!it.stub.h.some(function(x){return hiddenHit(x,x+size[x]);});}
   else{var nd=N[it.i];d=!filter(nd.i,nd.s==='unknown'?'other':nd.s);if(col[it.i])h=hiddenHit(it.i+1,it.i+size[it.i]);}}
  g.classList.toggle('dim',d);if(it.fdEl)it.fdEl.classList.toggle('hit',h);}}
 function apply(){vp.setAttribute('transform','translate('+tx+','+ty+') scale('+sc+')');}
 function box(){var r=svg.getBoundingClientRect(),o={left:r.left,top:r.top,width:r.width,height:r.height};
  if(getComputedStyle(main).position==='fixed'){var mt=main.getBoundingClientRect().top;if(mt>r.top+60)o.height=Math.min(r.height,mt-r.top);}return o;}
 function fit(){var r=box();if(!r.width||!r.height||!ext)return;var bw=ext.x1-ext.x0,bh=ext.y1-ext.y0;
  sc=Math.min(r.width/bw,r.height/bh,1.25);tx=(r.width-bw*sc)/2-ext.x0*sc;ty=(r.height-bh*sc)/2-ext.y0*sc;
  if(r.width<720&&sc<0.5){sc=0.5;tx=-ext.x0*sc;ty=(r.height-(ext.y1+ext.y0)*sc)/2;}moved=false;fitted=true;apply();}
 function zoomAt(px,py,f){var nk=Math.max(0.04,Math.min(4,sc*f));tx=px-(px-tx)*nk/sc;ty=py-(py-ty)*nk/sc;sc=nk;moved=true;apply();}
 function center(i){var j=pos[i];if(j<0)return;var it=items[j],r=box();if(!r.width)return;if(sc<0.55)sc=0.9;
  tx=r.width/2-(it.x+Math.min(it.R/2,140))*sc;ty=r.height/2-it.y*sc;moved=true;apply();}
 function anchor(i,fnc){var j=pos[i],x0=j>=0?tx+items[j].x*sc:0,y0=j>=0?ty+items[j].y*sc:0;fnc();var j2=pos[i];
  if(j>=0&&j2>=0){tx+=x0-(tx+items[j2].x*sc);ty+=y0-(ty+items[j2].y*sc);moved=true;apply();}}
 function reveal(i){var ch=false,x=i,path=[];while(x>=0){path.push(x);x=N[x].p;}
  for(var k=0;k<path.length;k++){var y=path[k];if(k>0&&col[y]){col[y]=0;ch=true;}if(alive&&allc[y]&&!stubOpen[N[y].p]){stubOpen[N[y].p]=1;ch=true;}}return ch;}
 function toggle(i){anchor(i,function(){col[i]=col[i]?0:1;render();});}
 function chain(k,on){for(;k>=0;k=items[k].par){nodeEl[k].classList.toggle('hl',on);if(edgeEl[k])edgeEl[k].classList.toggle('hl',on);}}
 var hov=-1;
 function tipFor(k,cx,cy){var it=items[k];tip.textContent='';
  if(it.stub){tip.appendChild(document.createTextNode(it.lt+'（全部 closed 的子树），点开展开'));}
  else{var nd=N[it.i],b=document.createElement('b');b.textContent=nd.i;tip.appendChild(b);tip.appendChild(document.createTextNode(' '+nd.t));
   var m=document.createElement('div');m.className='m';m.textContent=(nd.S||'?')+(nd.V?' / '+nd.V:'')+' · 台账 '+nd.n+' 行'+(kids[it.i].length?' · 子节点 '+kids[it.i].length:'')+(col[it.i]?'（已收起 '+(size[it.i]-1)+' 个）':'');tip.appendChild(m);}
  tip.hidden=false;var hr=host.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight,x=cx-hr.left+14,y=cy-hr.top+16;
  if(x+w>hr.width-6)x=Math.max(6,cx-hr.left-w-14);if(y+h>hr.height-6)y=Math.max(6,cy-hr.top-h-12);tip.style.left=x+'px';tip.style.top=y+'px';}
 function hideTip(){tip.hidden=true;if(hov>=0&&nodeEl[hov])chain(hov,false);hov=-1;}
 function hover(k,cx,cy){if(hov!==k){hideTip();hov=k;if(!items[k].stub)chain(k,true);}tipFor(k,cx,cy);}
 function kOf(t){var g=t&&t.closest?t.closest('[data-k]'):null;return g?+g.getAttribute('data-k'):-1;}
 function activate(k,onFold){var it=items[k];hideTip();if(it.stub){stubOpen[it.sp]=1;var a=it.sp;if(a>=0)anchor(a,render);else{render();}return;}
  if(onFold)return toggle(it.i);fromGraph=true;if(location.hash.slice(1)===N[it.i].i){fromGraph=false;show();}else location.hash=N[it.i].i;}
 var pts={},np=0,drag=null,pinch=null;
 function two(){var a=[];for(var p in pts)a.push(pts[p]);return a;}
 svg.addEventListener('pointerdown',function(e){if(e.pointerType==='mouse'&&e.button!==0)return;pts[e.pointerId]={x:e.clientX,y:e.clientY};np++;
  if(np===1){drag={x:e.clientX,y:e.clientY,tx:tx,ty:ty,id:e.pointerId,on:false};}
  else if(np===2){var a=two(),r=box();pinch={d:Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y)||1,k:sc,mx:(a[0].x+a[1].x)/2-r.left,my:(a[0].y+a[1].y)/2-r.top,tx:tx,ty:ty};if(drag)drag.on=true;}});
 svg.addEventListener('pointermove',function(e){
  if(pts[e.pointerId]){pts[e.pointerId]={x:e.clientX,y:e.clientY};
   if(pinch&&np>=2){var a=two(),d=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y)||1,nk=Math.max(0.04,Math.min(4,pinch.k*d/pinch.d)),r=box(),mx=(a[0].x+a[1].x)/2-r.left,my=(a[0].y+a[1].y)/2-r.top;
    tx=mx-(pinch.mx-pinch.tx)*nk/pinch.k;ty=my-(pinch.my-pinch.ty)*nk/pinch.k;sc=nk;moved=true;apply();return;}
   if(drag){var dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(!drag.on&&dx*dx+dy*dy>16){drag.on=true;svg.classList.add('drag');hideTip();try{svg.setPointerCapture(e.pointerId);}catch(_){}}
    if(drag.on){tx=drag.tx+dx;ty=drag.ty+dy;moved=true;apply();return;}}}
  if(e.pointerType==='mouse'){var k=kOf(e.target);if(k>=0)hover(k,e.clientX,e.clientY);else if(hov>=0)hideTip();}});
 function up(e){if(!pts[e.pointerId])return;delete pts[e.pointerId];np=Math.max(0,np-1);svg.classList.remove('drag');
  if(np<2)pinch=null;if(np===1){var a=two()[0];drag={x:a.x,y:a.y,tx:tx,ty:ty,on:true};}
  else if(np===0){var was=drag&&drag.on;drag=null;if(!was&&e.type==='pointerup'){var k=kOf(e.target);if(k>=0)activate(k,!!(e.target.closest&&e.target.closest('.fd')));}}}
 svg.addEventListener('pointerup',up);svg.addEventListener('pointercancel',up);
 svg.addEventListener('pointerleave',function(e){if(e.pointerType==='mouse')hideTip();});
 svg.addEventListener('wheel',function(e){e.preventDefault();var r=box();zoomAt(e.clientX-r.left,e.clientY-r.top,Math.exp(-e.deltaY*(e.ctrlKey?0.01:0.0015)));},{passive:false});
 svg.addEventListener('focusin',function(e){var k=kOf(e.target);if(k<0)return;var b=nodeEl[k].getBoundingClientRect();hover(k,b.left+12,b.bottom-4);});
 svg.addEventListener('focusout',function(){hideTip();});
 svg.addEventListener('keydown',function(e){var k=kOf(e.target);if(k<0)return;var it=items[k];
  if(e.key==='Enter'||e.key===' '){e.preventDefault();activate(k,false);}
  else if(!it.stub&&kids[it.i].length&&((e.key==='ArrowRight'&&col[it.i])||(e.key==='ArrowLeft'&&!col[it.i]))){e.preventDefault();toggle(it.i);var j=pos[it.i];if(j>=0)nodeEl[j].focus();}});
 $('gfit').addEventListener('click',fit);
 $('gzi').addEventListener('click',function(){var r=box();zoomAt(r.width/2,r.height/2,1.25);});
 $('gzo').addEventListener('click',function(){var r=box();zoomAt(r.width/2,r.height/2,0.8);});
 $('grefs').addEventListener('change',function(e){showRefs=e.target.checked;draw();});
 if(window.ResizeObserver)new ResizeObserver(function(){if(!moved)fit();}).observe(svg);
 (function legend(){var L=$('glegend');
  function sw(w,h,f){var s=el('svg',{width:w,height:h,viewBox:(-w/2)+' '+(-h/2)+' '+w+' '+h});f(s);return s;}
  function item(s,label,strong){var sp=document.createElement('span');sp.appendChild(s);var t=document.createElement(strong?'i':'span');t.textContent=label;sp.appendChild(t);L.appendChild(sp);}
  item(sw(16,16,function(s){mark(s,'open','',true);}),'问题 Q',1);item(sw(16,16,function(s){mark(s,'open','',false);}),'假设 H',1);
  item(sw(24,24,function(s){mark(s,'active','',false);}),'active');item(sw(16,16,function(s){mark(s,'open','',false);}),'open');
  item(sw(16,16,function(s){mark(s,'parked','',false);}),'parked');
  ['supported','refuted','inconclusive','superseded','abandoned'].forEach(function(v){item(sw(16,16,function(s){mark(s,'closed',v,false);}),v);});
  item(sw(26,10,function(s){el('path',{'class':'ed',d:'M-12,0H12'},s);}),'父子');
  item(sw(26,10,function(s){el('path',{'class':'by',d:'M-12,0H6'},s);el('path',{'class':'byh',d:'M12,0L5,-3.5L5,3.5Z'},s);}),'取代 by');
  item(sw(26,10,function(s){el('path',{'class':'rf',d:'M-12,0H12'},s);}),'引用 [[ID]]');
  item(sw(18,14,function(s){badge(s,3).setAttribute('transform','translate(-7,-5)');}),'台账行数');
  item(sw(18,16,function(s){var f=el('g',{'class':'fd'},s);el('rect',{x:-9,y:-8,width:18,height:16,rx:8},f);tx_(f,0,0.5,'','+4');}),'收起的子树');
  var t=document.createElement('span');t.className='hint';t.textContent='closed 的节点减淡；滚轮缩放、拖动平移，Esc 取消选中';L.appendChild(t);})();
 render();
 return {
  shown:function(){if(!fitted)fit();},
  hideTip:hideTip,
  select:function(id,doCenter){var i=id!=null&&id in id2?id2[id]:-1,prev=sel;sel=i;if(i>=0)moved=true;
   if(i>=0&&reveal(i)){if(pos[i]>=0&&!doCenter)anchor(i,render);else render();}
   if(prev>=0&&pos[prev]>=0)nodeEl[pos[prev]].classList.remove('sel');
   if(i>=0&&pos[i]>=0){nodeEl[pos[i]].classList.add('sel');var it=items[pos[i]],r=box(),sx=tx+it.x*sc,sy=ty+it.y*sc;
    if(doCenter||sx<8||sx+Math.min(it.R,200)*sc>r.width||sy<8||sy>r.height-8)center(i);}},
  setFilter:function(f){filter=f;dim();},
  setAlive:function(v){if(v===alive)return;alive=v;stubOpen={};if(sel>=0)reveal(sel);render();if(!moved)fit();},
  foldAll:function(){for(var i=0;i<n;i++)col[i]=kids[i].length?1:0;render();fit();},
  unfoldAll:function(){col.fill(0);render();fit();}
 };
}
setView(view);if(view!=='graph')filt();
})();
"""


def render_html(t):
    sts = STATUSES
    cnt = {s: sum(1 for n in t.nodes.values() if n["status"] == s) for s in sts}
    other = len(t.nodes) - sum(cnt.values())
    tree = tree_ul(t, t.tops)
    arts = []
    # 总览
    ov = ['<p id=miss class=warn hidden></p>', f"<h2>研究树 · {esc(t.slug)}</h2><div class=meta>{len(t.nodes)} 个节点；台账 {len(t.rows)} 行"
          f"（{len(t.tables)} 张表），挂到节点的 {sum(1 for r in t.rows if r['nodes'])} 行。点图上或列表里的节点看详情。</div>"
          "<div class=meta>颜色：<span class=s-open><span class=dot></span>open</span> "
          "<span class=s-active><span class=dot></span>active</span> <span class=s-parked><span class=dot></span>parked</span>；"
          "closed 按 verdict：<span class=v-supported><span class=dot></span>supported</span> "
          "<span class=v-refuted><span class=dot></span>refuted</span> <span class=v-inconclusive><span class=dot></span>inconclusive</span> "
          "<span class=v-superseded><span class=dot></span>superseded</span> "
          "<span class=v-abandoned><span class=dot></span>abandoned</span></div>"]
    if t.warnings:
        ov.append("<h3 class=warn id=warns>一致性告警</h3><ul class=plain>" + "".join(f"<li>{inline(w, t)}</li>" for w in t.warnings) + "</ul>")
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
            + (" <span class=meta>← " + " ← ".join(esc(t.nodes[c]["title"]) for c in t.chain(i)[::-1][:6]) + "</span>" if t.chain(i) else "")
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
        body = []
        ch = t.chain(i)
        if ch:
            a.append(" · 链 " + " › ".join("…" if c is None else f'<a class=ref href="#{esc(c)}">{esc(c)}</a>'
                                            for c in short_chain(ch)))  # 深链只给根与最近几代，免得 html 随深度平方变大
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
            body.append(f"<h3>{inline(h, t)}</h3>{md(b, t)}")
        rows = t.rows_of[i]
        if rows:
            body.append(f"<h3>台账（{len(rows)} 行）</h3>" + ledger_html(t, rows))
        arts.append(f'<article id="n-{esc(i)}" hidden>' + "".join(a) + "<div class=body>" + "".join(body) + "</div></article>")
    boxes = "".join(f'<label><input type=checkbox data-st="{s}" checked> {s} {cnt[s]}</label>' for s in sts)
    if other:
        boxes += f'<label><input type=checkbox data-st="other" checked> 其他 {other}</label>'
    if t.warnings:
        boxes += f'<a class=warn href="#" title="见总览的一致性告警">告警 {len(t.warnings)}</a>' 
    return (f"<!doctype html>\n<html lang=zh-CN><head><meta charset=utf-8>"
            f"<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>研究树 · {esc(t.slug)}</title><style>{CSS}</style></head><body>\n"
            f"<header><h1><a href=\"#\" style=\"color:inherit;text-decoration:none\">研究树 · {esc(t.slug)}</a></h1>"
            f"<span class=vsw role=group aria-label=视图><button id=vg type=button aria-pressed=true>图</button>"
            f"<button id=vl type=button aria-pressed=false>列表</button></span>{boxes}"
            f"<label title=\"图上把全关的子树收成一个桩；列表里隐藏已关节点\"><input type=checkbox id=hideclosed> 只看活着</label>"
            f"<input type=search id=q placeholder=\"搜索 ID、标题、正文（回车定位）\">"
            f"<button id=fold type=button>全折叠</button><button id=unfold type=button>全展开</button></header>\n"
            f"<div class=wrap><nav><ul>{tree}</ul></nav>"
            f"<section id=graph aria-label=研究树总览图><div class=gbar><button id=gpan type=button>总览 / 详情</button><button id=gfit type=button>适应窗口</button>"
            f"<button id=gzi type=button aria-label=放大>＋</button><button id=gzo type=button aria-label=缩小>－</button>"
            f"<label><input type=checkbox id=grefs> 引用线</label></div>"
            f"<svg id=gsvg aria-label=\"研究树总览图：点节点看详情，点节点右侧的钮收起或展开子树\"><g id=gvp><g id=ge></g><g id=gr></g><g id=gb></g><g id=gn></g></g></svg>"
            f"<div id=gtip hidden></div><div id=glegend></div></section>"
            f"<main><div id=dbar><button id=dtog type=button><span id=dlab>总览</span><span class=x>收起 ✕</span></button></div>\n" + "\n".join(arts)
            + f"\n</main></div><script type=application/json id=gdata>{graph_data(t)}</script><script>{JS}</script></body></html>\n")


def write_html(t):
    """先写同目录的唯一临时文件再换名：并发渲染互不踩，崩了也不留半截文件给 git 提交。"""
    p = os.path.join(t.dir, "tree.html")
    doc = render_html(t)
    fd, tmp = tempfile.mkstemp(dir=t.dir, prefix=".tree.html.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(doc)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
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
