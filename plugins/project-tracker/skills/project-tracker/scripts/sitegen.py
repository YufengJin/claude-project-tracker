#!/usr/bin/env python3
"""sitegen.py — 给人看的三层只读页面：全部项目 → 项目 → 节点。只通过 records.load 取数，渲染时不调用模型，只用标准库。

  sitegen.py <档案根> [--out DIR] [--slugs a,b]

写静态站点（默认 <档案根>/site/，pt serve 发在 /site/ 下）：
  index.html             全部项目：等你拍板几件、最近有结论的实验、每个项目一行（现状；研究配判词色条与近两周判完几个，
                         登记了条件的配「条件过 x/y」）
  p/<slug>.html          项目页：现在、下一步、等你拍板、条件表（线没定时显示推荐线与对推荐线差多少）、最近有结论的实验；
                         研究项目按问题分组（问题卡作整支摘要、最近 5 张有卡的实验卡，没卡的旧节点一行一个，可筛）；
                         工程项目放最近的结果（有卡的 journal 结果条目四行卡，其余一行：标题加正文第一句）与决定
  p/<slug>/<编号>.html   节点页：判定徽章与卡；证据（挂着的台账行）、事先定的判据、节点原文；本页编号与术语释义
  p/<slug>/<J编号>.html  journal 条目页（有卡的、条件判定所在的；工程项目是全部带日期的条目）：卡在上，条目原文在下
项目页上编号尽量换成标题（纯编号的括注换成一个「证据」链接），长的原文、判据、台账明细只在节点页。
站点在默认位置时首页页头给「研究总览（旧版）」（→ ../research.html），项目页给「研究树图」；--out 指到别处时都不给。
整站先写进临时目录再整体换上；站点目录里有标记文件 .pt-site，--out 指向已有的别的目录时拒绝覆盖。
取不到的写「未记录」；内网地址、口令类字符串在页面上隐去。
"""
import argparse
import datetime as dt
import fcntl
import html
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import progress  # noqa: E402
import records  # noqa: E402
import tree  # noqa: E402

MARK = ".pt-site"
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RECENT_DAYS = 14
CARDS_PER_Q = 5
RESULT_CARDS = 8      # 工程项目「最近的结果」最多展开几张卡
RESULT_LINES = 12     # 其余一行一个，最多几行
CELL_MAX = 3000
ROWS_MAX = 300
RAW_MAX = 200_000
PAGE_MAX = 1_000_000
CONCL_RECENT = 20     # 项目页超长时，只有最近这么多个没卡的实验给结论首句
TEXT_BUDGET = 22_500  # 项目页的文字量（约 15 屏 × 1500 字）；超了就把已答问题下的实验收成一行一个

SHOWN_CLS = {"成立": "ok", "不成立": "bad", "没定论": "mid", "未跑": "grey", "被取代": "grey", "放弃": "grey",
             "已答": "done", "未答": "live", "在做": "live", "待做": "grey", "搁置": "grey", "结果": "done"}
COND_CLS = {"过": "ok", "不过": "bad", "未测": "grey", "线未定": "mid", "不再适用": "grey"}
FILTER = {"active": "在做", "closed": "已判", "parked": "搁置", "open": "待做"}
VOCAB = {
    "成立": "实验关了，读数支持这个想法。",
    "不成立": "实验关了，读数否定了这个想法。",
    "没定论": "跑了，但读数不够判成立或不成立。",
    "未跑": "没有读数就关了（被别的想法取代、放弃，或判作不必跑）。",
    "被取代": "有读数，但被后来的想法取代，没有判成立与否。",
    "放弃": "中途放弃，没有判成立与否。",
    "已答": "问题关了；答案可能是否定的，看「结果」那一行。",
    "未答": "问题还开着。",
    "搁置": "先放下了，没有判。",
    "原文摘取": "这个节点没有作者写的短卡，卡上各行是程序从原文摘的：标题当目的、判别首句当做法、最后一行台账读数当结果、结论首句当结论。",
    "线未定": "这个条件的及格线还没由用户定，所以不算差距。",
    "未登记": "charter 的完成标准还没按条件行登记，下面原样列出旧写法。",
    "p95": "把样本从小到大排，第 95% 位置上的值，即不算最差 5% 时的最坏值。",
    "中位": "排在正中间的值。",
}
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b|\b[\w-]+(?:\.[\w-]+)*\.ts\.net\b")
SECRET_RE = re.compile(r"\b(?:hf_|sk-|ghp_|gho_|github_pat_|xox[bpa]-|tskey-|glpat-)[A-Za-z0-9_-]{8,}"
                       r"|\b[A-Za-z0-9_-]*(?:token|password|passwd|secret|apikey|api_key)\s*[=:]\s*\S+"
                       r"|\bBearer\s+[A-Za-z0-9._-]{12,}", re.I)
NONE = '<span class="none">未记录</span>'


# ---------- 文字 ----------

def redact(s):
    return SECRET_RE.sub("‹已隐去›", IP_RE.sub("‹内网地址›", s or ""))


def esc(s):
    return html.escape(redact(s or ""), quote=True)


def cut(s, n):
    """压成一行截到 n 个字；不把编号从中间截断。"""
    s = records.clean(s)
    if len(s) <= n:
        return s
    head = s[:n - 1]
    if re.match(r"[A-Za-z0-9_-]", s[n - 1]):
        head = re.sub(r"[A-Za-z0-9_-]+$", "", head)
    return head.rstrip() + "…"


def textlen(h):
    """页面上的字数（含折叠起来的），去标签、压空白。"""
    return len(" ".join(html.unescape(re.sub(r"<[^>]+>", "", h)).split()))


def mmdd(d):
    return d[5:] if d else ""


def badge(word, cls=None):
    return f'<span class="b {cls or SHOWN_CLS.get(word, "grey")}">{esc(word)}</span>'


class Ref:
    """把正文里的编号变成链接。
    mode="id"（节点页）：显示编号，悬停看标题，记下本页出现过的，页尾给释义。
    mode="human"（项目页、总览）：问题与实验换成「短标题」，ADR 换成「决定「…」」，条件换成「条件「…」」；
    台账编号换成一个「证据」链接（悬停看编号与问题）；连着写的几个编号（[E30, E31]、E11/E12、E95–E100）
    只给一个「证据」；只有问题与实验编号的连写逐个换成短标题。"""

    def __init__(self, rec, here, mode):
        self.rec, self.mode, self.seen = rec, mode, {}
        slug = rec["slug"]
        self.node_base = {"index": f"p/{slug}/", "project": f"{slug}/", "node": ""}[here]
        self.proj = {"index": f"p/{slug}.html", "project": "", "node": f"../{slug}.html"}[here]
        self.host_of = {}
        nodes = rec["nodes"]
        for k in rec["row_order"]:
            r = rec["rows"][k]
            live = [x for x in r["nodes"] if x in nodes]
            host = next((x for x in live if x.startswith("H")), live[0] if live else "")
            self.host_of.setdefault(r["id"], (host, k))
        self.adr = {a["id"]: a["title"] for a in rec["adrs"]}
        self.cond = {c["id"]: c["text"] for c in rec["conditions"]["items"]}
        pages = entry_pages(rec)
        self.jmap = {i: i for i in pages}  # 正文里的 journal 编号（含旧写法）→ 有页面的条目
        self.jmap.update({a: i for a, i in rec.get("jalias", {}).items() if i in pages})
        toks = set(nodes) | set(self.host_of) | set(self.adr) | set(self.cond) | set(self.jmap)
        toks = sorted((t for t in toks if t and t != "?"), key=len, reverse=True)
        self.rx = self.tok = None
        if toks:
            one = "(?:" + "|".join(map(re.escape, toks)) + ")"
            b, e = r"(?<![A-Za-z0-9_/.#-])", r"(?![A-Za-z0-9_])"
            sep = r"\s*(?:[,，、;；/+~–—-]|和|与|及|到|至)\s*"
            seq = rf"{b}{one}{e}(?:{sep}{one}{e})*"
            self.rx = re.compile(rf"(?P<g>[\[（(]\s*{seq}\s*[\]）)])|(?P<s>{seq})")
            self.tok = re.compile(rf"{one}{e}")

    def gloss(self, t):
        if t in self.rec["nodes"]:
            return self.rec["nodes"][t]["title"]
        if t in self.jmap:
            return self.rec["glossary"].get(self.jmap[t], "")
        if t in self.adr:
            return self.adr[t]
        if t in self.cond:
            return self.cond[t]
        return self.rec["glossary"].get(t, "")

    def href(self, t):
        if t in self.rec["nodes"]:
            return f"{self.node_base}{t}.html"
        if t in self.cond:
            return f"{self.proj}#cond-{t}"
        if t in self.jmap:
            return f"{self.node_base}{self.jmap[t]}.html"
        if t in self.host_of:
            host, key = self.host_of[t]
            return f"{self.node_base}{host}.html#row-{key}" if host else ""
        return ""

    def link(self, t, text=None, cls="ref"):
        g = self.gloss(t)
        if self.mode == "id":
            self.seen[self.jmap.get(t, t)] = g
        h = self.href(t)
        title = esc(f"{t}：{cut(g, 140)}" if g else t)
        body = esc(t) if text is None else text
        return f'<a class="{cls}" href="{h}" title="{title}">{body}</a>' if h else \
            f'<span class="{cls}" title="{title}">{body}</span>'

    def short(self, t):
        """问题与实验的短标题（去掉标题里的编号）。"""
        s = self.tok.sub("", self.rec["nodes"][t]["title"]) if self.tok else self.rec["nodes"][t]["title"]
        return cut(re.sub(r"^[\s:：,，、·]+", "", s), 16) or t

    def human(self, t):
        if t in self.rec["nodes"]:
            return self.link(t, "「" + esc(self.short(t)) + "」")
        if t in self.adr:
            return self.link(t, "决定「" + esc(cut(self.adr[t], 14)) + "」")
        if t in self.cond:
            return self.link(t, "条件「" + esc(cut(self.cond[t], 12)) + "」")
        if t in self.jmap:
            return self.link(t, "记录 " + esc(jdate(self.jmap[t])), "ev")
        return self.link(t, "证据", "ev")

    def evidence(self, ids, host):
        h = f"{self.node_base}{host}.html#evidence" if host else self.href(ids[0])
        title = esc("；".join(f"{t}：{cut(self.gloss(t), 60)}" for t in ids))
        return f'<a class="ev" href="{h}" title="{title}">证据</a>' if h else f'<span class="ev" title="{title}">证据</span>'

    def sub(self, m, host):
        text = m.group(0)
        if self.mode == "id":
            return self.tok.sub(lambda x: self.link(x.group(0)), text)
        ids = self.tok.findall(text)
        if all(t in self.rec["nodes"] for t in ids):
            return self.tok.sub(lambda x: self.human(x.group(0)), text)
        if len(ids) == 1 and not m.group("g"):
            return self.human(ids[0])
        return self.evidence(ids, host if any(t in self.host_of for t in ids) else None)

    def text(self, escaped, host=None):
        """已转义的文字里换编号；host = 这段文字属于哪个节点（「证据」链接指向它的证据节）。"""
        if not self.rx:
            return escaped
        return self.rx.sub(lambda m: self.sub(m, host), escaped)

    def plain(self, s, n):
        """放进链接文字里的标题：问题与实验编号换成「短标题」（不再套链接），其他编号去掉；截短、转义。"""
        if self.tok and self.mode == "human":
            def one(m):
                ids = self.tok.findall(m.group(0))
                if all(t in self.rec["nodes"] for t in ids):
                    return self.tok.sub(lambda x: "「" + self.short(x.group(0)) + "」", m.group(0))
                return ""
            s = self.rx.sub(one, records.clean(s))
        return esc(cut(s, n))


def inline(s, R=None, host=None):
    s = redact((s or "").replace("[[", "").replace("]]", ""))
    out = []
    for k, part in enumerate(re.split(r"(`[^`\n]*`)", s)):
        if k % 2:
            out.append("<code>" + html.escape(part[1:-1]) + "</code>")
            continue
        e = html.escape(part, quote=True)
        e = re.sub(r"\[([^\]\n]+)\]\((?:https?://|\.{0,2}/)?[^)\s]*\)", r"\1", e)
        e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
        out.append(R.text(e, host) if R else e)
    return "".join(out)


def md(text, R=None, host=None):
    """最小 markdown：段落、列表、表格、代码块、标题（降成 h4）。"""
    lines, out, para, i = (text or "").split("\n"), [], [], 0

    def flush():
        if para:
            out.append("<p>" + "<br>".join(inline(x, R, host) for x in para) + "</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]
        if tree.FENCE_RE.match(ln):
            flush()
            j = i + 1
            while j < len(lines) and not tree.FENCE_RE.match(lines[j]):
                j += 1
            out.append("<pre>" + esc("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        if "|" in ln and i + 1 < len(lines) and tree.is_sep(lines[i + 1]):
            flush()
            head = tree.split_row(ln)
            rows, j = [], i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(tree.split_row(lines[j]))
                j += 1
            t = "<tr>" + "".join(f"<th>{inline(tree.cell(c), R, host)}</th>" for c in head) + "</tr>"
            for r in rows:
                t += "<tr>" + "".join(f"<td>{inline(tree.cell(c), R, host)}</td>" for c in r) + "</tr>"
            out.append(f'<div class="tw"><table>{t}</table></div>')
            i = j
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            flush()
            out.append(f"<h4>{inline(m.group(2), R, host)}</h4>")
        elif re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                depth = min((len(lines[i]) - len(lines[i].lstrip())) // 2, 4)
                body = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() and \
                        not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                    body += " " + lines[i].strip()
                    i += 1
                box = re.match(r"^\[([ xX✓])\]\s*", body)
                mark = ("☑ " if box.group(1) != " " else "☐ ") if box else ""
                body = body[box.end():] if box else body
                items.append(f'<li style="margin-left:{depth}em">{mark}{inline(body, R, host)}</li>')
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif not ln.strip():
            flush()
        else:
            para.append(ln)
        i += 1
    flush()
    return "\n".join(out)


# ---------- 页面骨架 ----------

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#66655f;--line:#e3e0d8;--card:#fff;--acc:#2f5fa7;--code:#f2f0ea;
--ok:#1f7a3f;--okb:#e3f3e8;--bad:#a8322a;--badb:#f8e4e1;--mid:#8a5a00;--midb:#f8edd5;--live:#2f5fa7;--liveb:#e3ebf8;
--grey:#66655f;--greyb:#eceae4;--done:#38596b;--doneb:#e1ebf0;--bar0:#d9d6cc;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#e8e6e1;--mut:#a3a19b;--line:#33343a;
--card:#202124;--acc:#8fb4ff;--code:#2a2b2f;--ok:#7fd49a;--okb:#1f3a29;--bad:#ff9b8f;--badb:#45231f;--mid:#f0c36a;--midb:#3d3119;
--live:#9cc0ff;--liveb:#1f2c45;--grey:#a3a19b;--greyb:#2c2d31;--done:#a9c7d6;--doneb:#22323b;--bar0:#3a3b40;color-scheme:dark}}
:root[data-theme=dark]{--bg:#17181a;--fg:#e8e6e1;--mut:#a3a19b;--line:#33343a;--card:#202124;--acc:#8fb4ff;--code:#2a2b2f;
--ok:#7fd49a;--okb:#1f3a29;--bad:#ff9b8f;--badb:#45231f;--mid:#f0c36a;--midb:#3d3119;--live:#9cc0ff;--liveb:#1f2c45;
--grey:#a3a19b;--greyb:#2c2d31;--done:#a9c7d6;--doneb:#22323b;--bar0:#3a3b40;color-scheme:dark}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
main{max-width:880px;margin:0 auto;padding:12px 16px 64px}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:21px;line-height:1.4;margin:6px 0 4px}h2{font-size:17px;margin:26px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:0 0 4px}h4{font-size:14px;margin:12px 0 4px}
.crumb{font-size:13px;color:var(--mut);overflow-wrap:anywhere}.muted{color:var(--mut);font-size:13px}
.meta{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;font-size:13px;color:var(--mut);margin:2px 0}
.lead{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:8px;padding:8px 12px;margin:10px 0;overflow-wrap:anywhere}
.lead p{margin:0}
.card,.grp,.proj{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0;overflow-wrap:anywhere}
.grp{padding:10px 12px}.grp>.card{margin:8px 0 0;border-style:dashed}
.ch{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:13px;color:var(--mut)}
.ct{display:block;font-weight:600;margin:2px 0 4px;color:var(--fg)}
.ct a{color:var(--fg)}
.nid{font-size:11px;color:var(--mut);font-weight:400;white-space:nowrap;font-family:ui-monospace,monospace}
.t2{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.ex{display:block;font-size:13.5px;color:var(--mut)}
dl.f{display:grid;grid-template-columns:3.6em 1fr;gap:2px 8px;margin:4px 0 0}dl.f dt{color:var(--mut);font-size:13px;padding-top:1px}
dl.f dd{margin:0;min-width:0;overflow-wrap:anywhere}
.b{display:inline-block;border-radius:999px;padding:0 8px;font-size:12px;line-height:20px;white-space:nowrap}
.b.ok{background:var(--okb);color:var(--ok)}.b.bad{background:var(--badb);color:var(--bad)}.b.mid{background:var(--midb);color:var(--mid)}
.b.live{background:var(--liveb);color:var(--live)}.b.grey{background:var(--greyb);color:var(--grey)}.b.done{background:var(--doneb);color:var(--done)}
.none{color:var(--mut);font-style:italic;font-size:13px}
.ev{font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 3px;margin:0 1px;white-space:nowrap}
.ref{border-bottom:1px dotted var(--mut)}
ul.ls{list-style:none;padding:0;margin:4px 0}ul.ls li{padding:4px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}
ul.ls li:first-child{border-top:0}
ul{margin:4px 0;padding-left:1.2em}p{margin:4px 0}
code{background:var(--code);border-radius:4px;padding:0 4px;font-size:.88em;overflow-wrap:anywhere}
pre{background:var(--code);padding:8px;border-radius:6px;overflow-x:auto;font-size:12.5px;white-space:pre-wrap;overflow-wrap:anywhere}
.tw{overflow-x:auto;max-width:100%}table{border-collapse:collapse;font-size:13px;margin:6px 0;width:100%}
th,td{border:1px solid var(--line);padding:3px 6px;vertical-align:top;text-align:left;overflow-wrap:anywhere}th{background:var(--code);font-weight:600}
tr:target td{background:var(--midb)}table.evt{min-width:720px}table.evt td.k{white-space:nowrap}
details{margin:8px 0}summary{cursor:pointer;color:var(--acc)}
.flt{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0;position:sticky;top:0;background:var(--bg);padding:6px 0;z-index:2}
.flt button,.tbtn{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:2px 10px;cursor:pointer}
.flt button.on{border-color:var(--acc);color:var(--acc)}
.tbtn{float:right;color:var(--mut);margin-left:8px}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--bar0);margin:6px 0 2px;max-width:420px}
.bar i{display:block;height:100%}.bar .ok{background:var(--ok)}.bar .bad{background:var(--bad)}.bar .mid{background:var(--mid)}
.bar .grey{background:var(--grey);opacity:.55}.bar .dim{background:var(--grey);opacity:.25}
.proj .pn{font-weight:600}.proj .now{margin:2px 0}
table.cond td.st,table.cond th,table.cond td[data-l="日期"]{white-space:nowrap}.evn{display:inline-block;max-width:14em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}
@media (max-width:640px){table.cond,table.cond tbody,table.cond tr,table.cond td{display:block;width:100%}
table.cond thead{display:none}table.cond tr{border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:4px 8px;background:var(--card)}
table.cond td{border:0;padding:1px 0}table.cond td.e{display:none}table.cond td.st{display:inline-block;margin-top:2px}table.cond td[data-l]::before{content:attr(data-l) "：";color:var(--mut)}
dl.f{grid-template-columns:3.2em 1fr}}
dl.gl dt{font-weight:600;font-size:13px}dl.gl dd{margin:0 0 6px 0;font-size:13px;color:var(--mut)}
.foot{margin-top:36px;font-size:12px;color:var(--mut)}
"""

HEAD_JS = """<script>(function(){var r=document.documentElement,q=(location.search.match(/[?&]theme=(light|dark)/)||[])[1];
try{var t=q||localStorage.getItem('pt-theme');if(t)r.dataset.theme=t}catch(e){if(q)r.dataset.theme=q}})();</script>"""

JS = """<script>(function(){var r=document.documentElement;
document.addEventListener('click',function(e){var b=e.target.closest('.tbtn');
if(b){var cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
r.dataset.theme=cur==='dark'?'light':'dark';try{localStorage.setItem('pt-theme',r.dataset.theme)}catch(_){}return}
var f=e.target.closest('.flt button');if(!f)return;var v=f.dataset.f,box=document.getElementById('groups');if(!box)return;
f.parentNode.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===f)});
box.querySelectorAll('[data-s]:not(.grp)').forEach(function(x){x.hidden=v!=='all'&&x.dataset.s!==v});
box.querySelectorAll('.grp').forEach(function(g){g.hidden=v!=='all'&&g.dataset.s!==v&&!g.querySelector('[data-s]:not(.grp):not([hidden])')})});
})();</script>"""


def page(title, body, note):
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>'
            f'{HEAD_JS}<style>{CSS}</style></head><body><main><button class="tbtn" type="button">亮 / 暗</button>'
            f'{body}<p class="foot">{esc(note)}</p></main>{JS}</body></html>')


# ---------- 小块 ----------

def state_sec(rec, *names):
    for h, b in rec["state"]["sections"]:
        if any(h.startswith(n) for n in names):
            return b
    return ""


def first_entry(body):
    return progress.first_item(body) if body else ""


def vbar(rec):
    """研究项目的判词色条：假设节点的显示状态计数。"""
    hs = [n for n in rec["nodes"].values() if n["kind"] == "H"]
    if not hs:
        return '<span class="muted">还没有实验</span>'
    cnt = {}
    for n in hs:
        cnt[n["shown"]] = cnt.get(n["shown"], 0) + 1
    other = cnt.get("被取代", 0) + cnt.get("放弃", 0)
    segs = [(cnt.get("成立", 0), "ok", "成立"), (cnt.get("不成立", 0), "bad", "不成立"),
            (cnt.get("没定论", 0), "mid", "没定论"), (cnt.get("未跑", 0), "grey", "未跑"), (other, "dim", "取代或放弃")]
    live = sum(cnt.get(k, 0) for k in ("在做", "待做", "搁置"))
    bar = "".join(f'<i class="{c}" style="width:{100 * k / len(hs):.1f}%" title="{w} {k}"></i>' for k, c, w in segs if k)
    legend = " · ".join(f"{w} {k}" for k, _c, w in segs if k)
    legend += f" · 没判 {live}" if live else ""
    return f'<div class="bar" role="img" aria-label="{esc(legend)}">{bar}</div><div class="muted">实验 {len(hs)} 个：{esc(legend)}</div>'


def recent_closed(rec, today, days=RECENT_DAYS):
    lo = (today - dt.timedelta(days=days)).isoformat()
    return [n for n in rec["nodes"].values() if n["kind"] == "H" and n["status"] == "closed" and n["date"] >= lo]


def cond_counts(rec):
    items = [c for c in rec["conditions"]["items"] if c["status"] != "不再适用"]
    return sum(1 for c in items if c["status"] == "过"), len(items)


def jval(j):
    """最近 / 最好两列只写数；没有数的判定（过 / 不过写在状态列）写「—」。"""
    return f"{j['value']:g}" if j and j["value"] is not None else "—"


def jdate(jid):
    """J260927-3 → 09-27。"""
    m = re.match(r"^J\d{2}(\d{2})(\d{2})-", jid)
    return f"{m.group(1)}-{m.group(2)}" if m else jid


def ev_link(rec, R, j):
    """证据格：台账行给链接；journal 判定给证据原文（一行，点进条目页）。"""
    if not j:
        return "—"
    note, entry = j.get("note") or "", j.get("entry") or ""
    if entry:
        text = R.plain(note, 28) if note else "记录 " + esc(jdate(entry))
        href = f"{R.node_base}{entry}.html" if entry in entry_pages(rec) else ""
        tip = esc(f"{entry}：{note}" if note else entry)
        return f'<a class="evn" href="{href}" title="{tip}">{text}</a>' if href else f'<span class="evn" title="{tip}">{text}</span>'
    return R.human(j["eid"]) if j["eid"] else "—"


def line_cell(x):
    if x["line_set"]:
        return esc(x["line"])
    if x["rec"]:
        return badge("线未定", "mid") + f' <span title="{esc(x["line"])}">待用户定，推荐 {esc(cut(x["rec"], 40))}</span>'
    return badge("线未定", "mid")


def gap_cell(x):
    if x["line_set"]:
        return "—" if x["gap"] is None else ("已到线" if x["gap"] == 0 else f"差 {x['gap']:g}")
    if x["rec_gap"] is not None:
        return "已到推荐线" if x["rec_gap"] == 0 else f"对推荐线差 {x['rec_gap']:g}"
    return "—"


def cond_table(rec, R):
    c = rec["conditions"]
    if not c["registered"]:
        out = ['<p>' + badge("未登记", "grey") + ' <span class="muted">完成标准还没按条件行登记，下面原样列出旧写法；'
               '没勾的不等于没做到。</span></p>']
        out.append(md("\n".join(c["legacy"]), R) if c["legacy"] else '<p class="none">charter 里没有完成标准</p>')
        return "".join(out)
    rows = []
    for x in c["items"]:
        lt, best = x["latest"], x["best"]
        line, gap = line_cell(x), gap_cell(x)
        tip = esc(f"{x['id']}；尺：{x['ruler'] or '未记录'}；来源：{x['source'] or '未记录'}" + (f"；格式：{x['bad']}" if x["bad"] else ""))
        cells = [("最近", esc(jval(lt))), ("最好", esc(jval(best))), ("线", line), ("差多少", esc(gap)),
                 ("证据", ev_link(rec, R, lt)),
                 ("日期", esc(mmdd(lt["date"])) if lt and lt["date"] else "—")]
        rows.append(f'<tr id="cond-{esc(x["id"])}"><td title="{tip}">{inline(x["text"])}</td>'
                    f'<td class="st">{badge(x["status"], COND_CLS.get(x["status"]))}</td>' +
                    "".join(f'<td data-l="{k}"{" class=e" if v == "—" else ""}>{v}</td>' for k, v in cells) + "</tr>")
    ok, n = cond_counts(rec)
    return (f'<p class="muted">过 {ok}/{n}。状态只从点名该条件的判定里算；最近、最好两列是判定里的数，最好值按线的方向取；'
            '线没定时差多少只对推荐线算，状态仍是「线未定」。</p>'
            '<div class="tw"><table class="cond"><thead><tr><th>条件</th><th>状态</th><th>最近</th><th>最好</th><th>线</th>'
            '<th>差多少</th><th>证据</th><th>日期</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def date_note(n):
    if n["status"] == "closed":
        return f"判于 {n['date']}" if n["date"] else "判定日期未记录"
    return f"最近改动 {n['date']}" if n["date"] else "日期未记录"


# ---------- 项目页 ----------

def card_rows(n, R, host, ext_cut=90, full=False):
    labels = ("目的", "结果") if n["kind"] == "Q" else ("目的", "怎么做", "结果", "结论")
    ext = n["card_src"] == "extract"
    out = []
    for lab in labels:
        v = n["card"].get(lab, "")
        if lab == "目的" and ext and records.clean(v) == n["title"] and not full:
            continue  # 摘取的目的就是标题，标题已在卡头
        if not v:
            val = '<span class="none">还没判</span>' if lab in ("结论", "结果") and n["status"] != "closed" else NONE
        else:
            val = inline(v if full or not ext else cut(v, ext_cut), R, host)
        out.append(f"<dt>{lab}</dt><dd>{val}</dd>")
    return '<dl class="f">' + "".join(out) + "</dl>"


def flags(n):
    s = ""
    if n["card_src"] == "extract":
        s += badge("原文摘取", "grey")
    if n["corrected"]:
        s += badge("已更正", "mid")
    return s


def h_card(n, R):
    i = n["id"]
    return (f'<article class="card" data-s="{FILTER.get(n["status"], "")}"><div class="ch">{badge(n["shown"])}'
            f'<span>{esc(mmdd(n["date"]))}</span>{flags(n)}</div>'
            f'<span class="ct"><a href="{R.node_base}{i}.html" title="{esc(i)}">{R.plain(n["title"], 60)}</a>{nid(i)}</span>'
            f'{card_rows(n, R, i)}</article>')


def q_summary(q, R):
    """问题分组最上面的整支摘要：有卡给目的、结果两行；没卡给一行原文摘取的结果。"""
    if q["card_src"] == "card":
        return f'<div class="card">{card_rows(q, R, q["id"])}</div>'
    res = q["card"].get("结果", "")
    if not res:
        return ""
    return (f'<p class="muted">结果（原文摘取）：{inline(cut(res, 110), R, q["id"])}</p>')


def nid(i):
    """链接文字后的小字编号：人能对上号，也能按编号直接开页。只放在卡的标题行与列表行。"""
    return f' <small class="nid">{esc(i)}</small>'


def h_line(n, R, concl=True):
    """一行一个的实验。带卡的照旧（标题截短）；没卡的给完整标题（最多两行）、判定，concl 时再给程序摘的结论首句。"""
    i = n["id"]
    li = f'<li data-s="{FILTER.get(n["status"], "")}">'
    if n["card_src"] == "card":
        return (f'{li}{badge(n["shown"])} <a href="{R.node_base}{i}.html" title="{esc(i)}">'
                f'{R.plain(n["title"], 46)}</a>{nid(i)} <span class="muted">{esc(mmdd(n["date"]))}</span></li>')
    head = (f'<span class="t2">{badge(n["shown"])} <a href="{R.node_base}{i}.html" title="{esc(i)}">'
            f'{R.plain(n["title"], 10 ** 4)}</a></span>')  # 标题过长最多两行；编号与日期放下一行开头，不被截掉
    c = n["card"].get("结论", "") if n["status"] == "closed" and concl else ""
    tail = f' · {inline(cut(c, 120), R, i)} {badge("原文摘取", "grey")}' if c else ""
    return f'{li}{head}<span class="ex">{nid(i).strip()} {esc(mmdd(n["date"]))}{tail}</span></li>'


def h_order(ns):
    ns = sorted(ns, key=lambda n: tree.id_key(n["id"]), reverse=True)
    ns.sort(key=lambda n: n["date"] or "", reverse=True)
    ns.sort(key=lambda n: n["status"] != "active")
    return ns


def q_rank(n):
    return {"active": 0, "open": 1, "parked": 2}.get(n["status"], 3)


def groups_html(rec, R, expand_answered=True, concl=None):
    """concl：哪些没卡的节点给结论首句（None = 全给）。"""
    nodes = rec["nodes"]
    qs = [n for n in nodes.values() if n["kind"] == "Q"]
    order = {}
    t = rec["tree"]

    def walk(i):
        stack = [i]
        while stack:
            x = stack.pop()
            if x in order or x not in nodes:
                continue
            order[x] = len(order)
            stack.extend(reversed(nodes[x]["children"]))
    for top in (t.tops if t else []):
        walk(top)
    qs.sort(key=lambda n: (q_rank(n), order.get(n["id"], 10 ** 6)))
    out = []
    for q in qs:
        i = q["id"]
        hs = h_order([nodes[k] for k in q["children"] if k.startswith("H") and k in nodes])
        subq = [nodes[k] for k in q["children"] if k.startswith("Q") and k in nodes]
        par = nodes.get(q["parent"])
        cnt = {}
        for n in hs:
            cnt[n["shown"]] = cnt.get(n["shown"], 0) + 1
        s = [f'<section class="grp" id="g-{esc(i)}" data-s="{FILTER.get(q["status"], "")}">'
             f'<div class="ch">{badge(q["shown"])}{flags(q)}<span>{esc(date_note(q))}</span></div>'
             f'<h3><a href="{R.node_base}{i}.html" title="{esc(i)}">{R.plain(q["title"], 90)}</a>{nid(i)}</h3>']
        if par:
            s.append(f'<div class="muted">属于：<a href="#g-{esc(par["id"])}">{R.plain(par["title"], 30)}</a></div>')
        s.append(q_summary(q, R))
        if hs:
            s.append('<div class="muted" style="margin-top:6px">实验 ' + str(len(hs)) + " 个：" +
                     esc("、".join(f"{k} {v}" for k, v in cnt.items())) + "</div>")
            k = CARDS_PER_Q if expand_answered or q["status"] != "closed" else 0
            full = [n for n in hs if n["card_src"] == "card"][:k]  # 有卡的最近几张展开；没卡的旧节点只占一行
            s.extend(h_card(n, R) for n in full)
            rest = [n for n in hs if n not in full]
            if rest:
                s.append('<ul class="ls">' + "".join(h_line(n, R, concl is None or n["id"] in concl) for n in rest) + "</ul>")
        if subq:
            s.append('<div class="muted" style="margin-top:6px">子问题：' + "、".join(
                f'<a href="#g-{esc(x["id"])}" title="{esc(x["id"])}">{R.plain(x["title"], 24)}</a>（{esc(x["shown"])}）'
                for x in subq) + "</div>")
        meas = rec["measurements"].get(i, [])
        if meas:
            s.append(f'<div class="muted">直接挂在这个问题上的测量 {len(meas)} 行，见'
                     f'<a href="{R.node_base}{i}.html#evidence">问题页</a></div>')
        s.append("</section>")
        out.append("".join(s))
    loose = h_order([n for n in nodes.values() if n["kind"] == "H" and n["parent"] not in nodes])
    if loose:
        full = [n for n in loose if n["card_src"] == "card"][:CARDS_PER_Q]
        rest = [n for n in loose if n not in full]
        out.append('<section class="grp" data-s=""><h3>没挂在问题下的实验</h3>' + "".join(h_card(n, R) for n in full) +
                   ('<ul class="ls">' + "".join(h_line(n, R, concl is None or n["id"] in concl) for n in rest) + "</ul>"
                    if rest else "") + "</section>")
    return "".join(out)


def project_page(rec, today, tree_href, note, pid=""):
    R = Ref(rec, "project", "human")
    research = rec["kind"] == "research"
    act = rec["activity"]
    s = [f'<div class="crumb"><a href="../index.html">全部项目</a> › {esc(rec["slug"])}</div>',
         f'<h1>{esc(rec["name"] or rec["slug"])}{nid(pid) if pid else ""}</h1>']
    meta = ["研究项目" if research else "工程项目", rec["status"] or "状态未写"]
    meta.append(f"最近活动 {act['date']}（{act['days']} 天前）" if act["date"] else "最近活动未记录")
    links = f'<a href="{tree_href}">研究树图</a>' if tree_href else ""
    s.append('<div class="meta">' + "".join(f"<span>{esc(x)}</span>" for x in meta) + links + "</div>")
    summ = rec["state"]["summary"]
    s.append(f'<div class="lead"><b>现在：</b>{inline(cut(summ, 300), R) if summ else NONE}</div>')
    nxt = first_entry(state_sec(rec, "下一步"))
    s.append(f'<p><b>下一步：</b>{inline(cut(nxt, 200), R) if nxt else NONE}</p>')
    pend = rec["pending"]
    s.append(f'<h2 id="pending">等你拍板（{len(pend)}）</h2>')
    if pend:
        s.append('<ul class="ls">' + "".join(f"<li>{inline(cut(x, 160), R)}</li>" for x in pend[:8]) + "</ul>")
        if len(pend) > 8:
            s.append(f'<p class="muted">另 {len(pend) - 8} 条在 state.md 的待拍板小节。</p>')
    else:
        s.append('<p class="muted">state 里没有待拍板的条目。</p>')
    s.append("<h2>条件</h2>" + cond_table(rec, R))
    if research:
        rc = [x for x in rec["recent"] if x["kind"] in ("H", "J")][:5]
        s.append("<h2>最近有结论的实验</h2>")
        if rc:  # 标题加卡的结论行；没卡的只给标题。节点编号在下面分组里给过，这里不重复（一页一个编号只出现一次）
            s.append('<ul class="ls">' + "".join(
                f'<li>{badge(x["shown"])} <span class="muted">{esc(mmdd(x["date"]))}</span> '
                f'<a href="{R.node_base}{x["id"]}.html" title="{esc(x["id"])}">{R.plain(x["title"], 36)}</a>{nid(x["id"]) if x["kind"] == "J" else ""}'
                f'{"：" + inline(cut(x["line"], 90), R, x["id"]) if x["line"] and x["card_src"] == "card" else ""}</li>'
                for x in rc) + "</ul>")
        else:
            s.append('<p class="muted">还没有关闭的实验。</p>')
        s.append('<h2>按问题看</h2><div class="flt"><button class="on" data-f="all">全部</button>'
                 '<button data-f="在做">在做</button><button data-f="已判">已判</button><button data-f="搁置">搁置</button>'
                 '<button data-f="待做">待做</button></div>')
        head = textlen("\n".join(s))
        g = groups_html(rec, R)
        if head + textlen(g) > TEXT_BUDGET:  # 太长：没卡的节点只有最近 CONCL_RECENT 个给结论首句，更早的只给标题
            bare = [n for n in rec["nodes"].values() if n["kind"] == "H" and n["card_src"] != "card" and n["status"] == "closed"]
            bare.sort(key=lambda n: (n["date"] or "", tree.id_key(n["id"])), reverse=True)
            keep = {n["id"] for n in bare[:CONCL_RECENT]}
            g = groups_html(rec, R, concl=keep)
            if head + textlen(g) > TEXT_BUDGET:  # 还太长：已答的问题下实验一行一个（问题卡就是子树的摘要）
                g = ('<p class="muted">实验多，已答的问题下的实验一行一个；问题卡上的「结果」是那一支的摘要。</p>'
                     + groups_html(rec, R, expand_answered=False, concl=keep))
        s.append(f'<div id="groups">{g}</div>')
        loose = [k for k in rec["row_order"] if not any(x in rec["nodes"] for x in rec["rows"][k]["nodes"])]
        if loose:
            s.append(f'<p class="muted">台账里另有 {len(loose)} 行没挂到节点（见 experiments.md）。</p>')
    else:
        s.append("<h2>最近的结果</h2>" + results_html(rec, R))
        dec = [(a["date"], a["lineno"], a["title"], "") for a in rec["adrs"]]
        dec += [(e["date"], e["lineno"], e["title"], "journal") for e in rec["journal"] if e["category"] == "决定"]
        dec.sort(key=lambda x: (x[0] or "", x[1]), reverse=True)
        s.append("<h2>最近的决定</h2>")
        s.append('<ul class="ls">' + "".join(f'<li><span class="muted">{esc(mmdd(d) or "日期未记录")}</span> '
                                             f'{inline(cut(t, 90), R)}</li>' for d, _n, t, _k in dec[:5]) + "</ul>"
                 if dec else '<p class="none">还没有记下的决定</p>')
    return page(rec["name"] or rec["slug"], "\n".join(s), note)


def results_html(rec, R):
    """工程项目「最近的结果」：journal「结果」与旧格式条目按结果日期新→旧；有卡的前 RESULT_CARDS 条四行卡，
    其余一行一个（标题加正文第一句），共 RESULT_LINES 行，每条链到自己的条目页。"""
    order = {e["id"]: k for k, e in enumerate(rec["journal"])}
    res = [e for e in rec["journal"] if e["category"] in ("结果", None) and e["date"]]
    res.sort(key=lambda e: (e["date"], order[e["id"]]), reverse=True)
    if not res:
        return '<p class="none">journal 里没有结果类条目</p>'
    pages = entry_pages(rec)
    cards = [e for e in res if e["card"]][:RESULT_CARDS]
    out = [j_card(e, R) for e in cards]
    rest = [e for e in res if e not in cards]
    lines = []
    for e in rest[:RESULT_LINES]:
        title = e["headline"] if e["category"] else e["title"]
        body = f'<a href="{R.node_base}{e["id"]}.html" title="{esc(e["id"])}">{inline(cut(title, 60))}</a>{nid(e["id"])}' \
            if e["id"] in pages else inline(cut(title, 60))
        first = (e["card"] or {}).get("结论") or e["first"]
        more = f'：{inline(cut(first, 90), R)}' if first and first != title else ""
        cov = f' <span class="muted">（已补卡 {len(e["covered_by"])} 张）</span>' if e["covered_by"] else ""
        lines.append(f'<li><span class="muted">{esc(mmdd(e["date"]))}</span> {body}{more}{cov}</li>')
    if lines:
        out.append('<ul class="ls">' + "".join(lines) + "</ul>")
    if len(rest) > RESULT_LINES:
        out.append(f'<p class="muted">更早的 {len(rest) - RESULT_LINES} 条见 journal.md（pt get &lt;J编号&gt;）。</p>')
    return "".join(out)


def j_card(e, R):
    return (f'<article class="card"><div class="ch">{badge("结果", "done")}<span>{esc(mmdd(e["date"]))}</span>'
            f'{badge("补记", "grey") if e["thread"] == "补记" else ""}</div>'
            f'<span class="ct"><a href="{R.node_base}{e["id"]}.html" title="{esc(e["id"])}">{inline(cut(e["headline"], 60))}</a>'
            f'{nid(e["id"])}</span>'
            f'{j_rows(e, R)}</article>')


def j_rows(e, R):
    return '<dl class="f">' + "".join(f"<dt>{lab}</dt><dd>{inline(e['card'].get(lab, ''), R) or NONE}</dd>"
                                      for lab in tree.CARD_LABELS) + "</dl>"


def entry_pages(rec):
    """有自己页面的 journal 条目：有卡的、条件判定所在的；工程项目另加全部带日期的条目。"""
    if "_jpages" not in rec:
        eng = rec["kind"] != "research"
        judged = {j.get("entry") for c in rec["conditions"]["items"] for j in c["judgments"]}
        rec["_jpages"] = {e["id"] for e in rec["journal"] if e["date"] and (eng or e["card"] or e["id"] in judged)}
    return rec["_jpages"]


def entry_page(rec, e, note):
    """journal 条目页：卡在上，条目原文在下。"""
    R = Ref(rec, "node", "id")
    s = [f'<div class="crumb"><a href="../../index.html">全部项目</a> › <a href="../{rec["slug"]}.html">'
         f'{esc(cut(rec["name"] or rec["slug"], 24))}</a> › journal</div>',
         f'<h1>{esc(e["headline"]) or NONE}</h1>',
         f'<div class="meta">{badge(e["category"] or "旧格式", "done" if e["category"] == "结果" else "grey")}'
         f'<span>记录 {esc(e["id"])}</span><span>{esc(e["date"] or "日期未记录")}</span>'
         f'<span>{esc(e["where"])}</span></div>']
    if e["card"]:
        s.append(f'<div class="card">{j_rows(e, R)}</div>')
    rel = []
    if e["covers"]:
        rel.append("补记自：" + "、".join(R.link(x) for x in e["covers"]))
    elif e["orig"]:
        rel.append("原始记录：" + inline(e["orig"], R))
    if e["covered_by"]:
        rel.append("这条的补记卡：" + "、".join(R.link(x) for x in e["covered_by"]))
    js = [j for c in rec["conditions"]["items"] for j in c["judgments"] if j.get("entry") == e["id"]]
    if js:
        rel.append("判定的条件：" + "、".join(f'{esc(j["verdict"])} {R.link(j["cid"])}' +
                                          (f"={j['value']:g}" if j["value"] is not None else "") for j in js))
    if rel:
        s.append('<p class="muted">' + "<br>".join(rel) + "</p>")
    body = e["text"].split("\n", 1)[1] if "\n" in e["text"] else ""
    cutnote = ""
    if len(body) > RAW_MAX:
        body, cutnote = body[:RAW_MAX], '<p class="muted">原文太长，只给前面一部分；全文见档案。</p>'
    s.append(f'<h2>条目原文</h2>{md(tree.strip_comments(body), R)}{cutnote}')
    main = "\n".join(s)
    gl = [f"<dt>{esc(k)}</dt><dd>{esc(cut(v, 160)) or '未记录'}</dd>" for k, v in sorted(R.seen.items())]
    voc = [f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in vocab_html(rec, main)]
    foot = ""
    if gl or voc:
        foot = "<h2>本页编号与术语</h2>" + (f'<dl class="gl">{"".join(gl)}</dl>' if gl else "") + \
            (f'<dl class="gl">{"".join(voc)}</dl>' if voc else "")
    return page(f"{e['id']} · {cut(e['headline'], 30)}", main + foot, note)


# ---------- 节点页 ----------

def evidence_html(rec, keys, R, host):
    if not keys:
        return '<p class="none">没有挂到这里的台账行</p>'
    out, cur, buf = [], None, []
    extra = len(keys) - ROWS_MAX

    def flush():
        if not buf:
            return
        head = "<tr>" + "".join(f"<th>{inline(h)}</th>" for h in cur) + "</tr>"
        out.append(f'<div class="tw"><table class="evt">{head}{"".join(buf)}</table></div>')
        buf.clear()
    for k in keys[:ROWS_MAX]:
        r = rec["rows"][k]
        hd = tuple(r["header"])
        if hd != cur:
            flush()
            cur = hd
        if r["raw"]:
            buf.append(f'<tr id="row-{esc(k)}"><td colspan="{max(len(hd), 1)}"><span class="muted">这一行格数和表头对不上，原样给出：</span>'
                       f'<pre>{esc(r["line"][:CELL_MAX])}</pre></td></tr>')
            continue
        cells = [c if len(c) <= CELL_MAX else c[:CELL_MAX] + "…（太长，截断）" for c in r["cells"]]
        short = {n for n, h in enumerate(hd) if tree.norm_head(h) in ("id",) + tree.NODE_HEADS}
        buf.append(f'<tr id="row-{esc(k)}">' + "".join(f'<td{" class=k" if n in short else ""}>{inline(c, R, host)}</td>'
                                                       for n, c in enumerate(cells)) + "</tr>")
    flush()
    if extra > 0:
        out.append(f'<p class="muted">另有 {extra} 行没列出（见 experiments.md）。</p>')
    js = [j for k in keys for j in rec["rows"][k]["judgments"]]
    if js:
        out.append('<p class="muted">判定的条件：' + "、".join(
            f'{esc(j["verdict"])} {R.link(j["cid"])}' + (f"={j['value']:g}" if j["value"] is not None else "") for j in js) + "</p>")
    return "".join(out)


def vocab_html(rec, body):
    text = re.sub(r"<[^>]+>", "", body)
    terms = dict(VOCAB)
    terms.update(rec["terms"])
    hit = [(k, v) for k, v in terms.items() if k in text]
    return hit


def node_page(rec, i, note):
    n = rec["nodes"][i]
    raw = rec["tree"].nodes[i] if rec["tree"] is not None and i in rec["tree"].nodes else {"sections": [], "raw": ""}
    R = Ref(rec, "node", "id")
    nodes = rec["nodes"]
    chain, x, seen = [], n["parent"], set()
    while x in nodes and x not in seen:
        seen.add(x)
        chain.append(x)
        x = nodes[x]["parent"]
    crumbs = "".join(f' › <a href="{c}.html" title="{esc(c)}">{esc(cut(nodes[c]["title"], 14))}</a>' for c in reversed(chain))
    kind = "探索" if n["kind"] == "Q" else "实验"
    s = [f'<div class="crumb"><a href="../../index.html">全部项目</a> › <a href="../{rec["slug"]}.html">'
         f'{esc(cut(rec["name"] or rec["slug"], 24))}</a>{crumbs}</div>',
         f'<h1>{esc(n["title"]) or NONE}</h1>',
         f'<div class="meta">{badge(n["shown"])}{flags(n)}<span>{kind} {esc(i)}</span><span>{esc(date_note(n))}</span></div>']
    s.append(f'<div class="card">{card_rows(n, R, i, full=True)}</div>')
    if n["card_src"] == "extract":
        s.append('<p class="muted">原文摘取：这个节点还没有作者写的短卡，上面各行由程序从原文摘出'
                 + ("；结论取自原文里的「更正」" if n["corrected"] else "") + "。</p>")
    rel = []
    if n["parent"] in nodes:
        p = nodes[n["parent"]]
        rel.append(f'上级问题：<a href="{p["id"]}.html">{esc(cut(p["title"], 50))}</a>（{esc(p["shown"])}）')
    if n["by"]:
        rel.append("取代它的：" + "、".join(R.link(b) for b in n["by"]))
    if rel:
        s.append('<p class="muted">' + "<br>".join(rel) + "</p>")
    if n["children"]:
        s.append("<h2>下面的节点</h2><ul class=\"ls\">" + "".join(
            f'<li>{badge(nodes[k]["shown"])} {R.link(k)} {esc(cut(nodes[k]["title"], 70))}</li>'
            for k in n["children"] if k in nodes) + "</ul>")
    s.append(f'<h2 id="evidence">证据（{len(n["rows"])} 行台账）</h2>' + evidence_html(rec, n["rows"], R, i))
    judge = tree.section(raw, "判别") if raw["sections"] else ""
    s.append("<h2>事先定的判据</h2>" + (md(judge, R, i) if judge else NONE))
    body = [(h, b) for h, b in raw["sections"] if tree.sec_name(h) != "判别" and b.strip()]
    src = "\n".join(f"### {h}\n{b}" for h, b in body)
    cutnote = ""
    if len(src) > RAW_MAX:
        src, cutnote = src[:RAW_MAX], '<p class="muted">原文太长，只给前面一部分；全文见档案。</p>'
    s.append(f'<details><summary>节点原文（{esc(n["file"])}，判别以外的各节）</summary>{md(src, R, i)}{cutnote}</details>'
             if body else '<p class="muted">节点原文除判别外没有别的节。</p>')
    main = "\n".join(s)
    gl = [f"<dt>{esc(k)}</dt><dd>{esc(cut(v, 160)) or '未记录'}</dd>" for k, v in sorted(R.seen.items(), key=lambda kv: (kv[0][:1], len(kv[0]), kv[0]))]
    voc = [f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in vocab_html(rec, main)]
    foot = ""
    if gl or voc:
        foot = "<h2>本页编号与术语</h2>" + (f'<dl class="gl">{"".join(gl)}</dl>' if gl else "") + \
            (f'<dl class="gl">{"".join(voc)}</dl>' if voc else "")
    return page(f"{i} · {cut(n['title'], 30)}", main + foot, note)


# ---------- 全部项目 ----------

def overview(recs, fails, today, research_href, note, ids=None):
    ids = ids or {}
    allp = len(recs) + len(fails)
    pend = [(r, len(r["pending"])) for r in recs.values() if r["pending"]]
    pend.sort(key=lambda x: -x[1])
    s = ["<h1>全部项目</h1>",
         f'<div class="meta"><span>{allp} 个项目</span>' +
         (f'<a href="{research_href}">研究总览（旧版）</a>' if research_href else "") + "</div>"]
    total = sum(k for _r, k in pend)
    s.append(f'<div class="lead"><b>等你拍板 {total} 件</b>' +
             (f'（{len(pend)} 个项目）：' + "、".join(
                 f'<a href="p/{r["slug"]}.html#pending">{esc(cut(r["name"] or r["slug"], 16))}</a> {k}' for r, k in pend)
              if pend else "") + "</div>")
    rc = []
    for r in recs.values():
        for x in r["recent"]:
            if x["date"] and (x["kind"] == "H" or (x["kind"] == "J" and x["card_src"] == "card")):
                rc.append((x["date"], r, x))
    rc.sort(key=lambda z: z[0], reverse=True)
    per, keep = {}, []
    for z in rc:  # 每个项目至多 3 条，免得一个项目占满
        per[z[1]["slug"]] = per.get(z[1]["slug"], 0) + 1
        if per[z[1]["slug"]] <= 3:
            keep.append(z)
    rc = keep
    if rc:
        s.append("<h2>最近有结论的实验</h2><ul class=\"ls\">" + "".join(
            f'<li>{badge(x["shown"])} <span class="muted">{esc(mmdd(d))} · {esc(cut(r["name"] or r["slug"], 14))}</span> '
            f'<a href="p/{r["slug"]}/{x["id"]}.html" title="{esc(x["id"])}">{Ref(r, "index", "human").plain(x["title"], 40)}</a>'
            f'{nid(x["id"])}</li>'
            for d, r, x in rc[:10]) + "</ul>")
    groups = (("进行中", ("进行中",)), ("暂停", ("暂停",)), ("结束了", ("已完成", "已放弃")))
    used = set()
    for title, sts in groups + (("其他", None),):
        rs = [r for r in recs.values() if (r["status_short"] in sts if sts else r["slug"] not in used)]
        used.update(r["slug"] for r in rs)
        if not rs:
            continue
        rs.sort(key=lambda r: r["slug"])
        rs.sort(key=lambda r: r["activity"]["date"] or "", reverse=True)
        rs.sort(key=lambda r: not r["pending"])
        rows = []
        for r in rs:
            m = ["研究" if r["kind"] == "research" else "工程"]
            act = r["activity"]
            m.append(f"{act['days']} 天前有活动" if act["date"] else "活动时间未记录")
            tags = badge(f"等你拍板 {len(r['pending'])}", "mid") if r["pending"] else ""
            prog = ""
            if r["kind"] == "research":
                k = len(recent_closed(r, today))
                prog += vbar(r) + f'<div class="muted">近两周判完 {k} 个</div>'
            if r["conditions"]["registered"]:
                ok, n = cond_counts(r)
                prog += f'<div class="muted">条件过 {ok}/{n}</div>'
            elif r["kind"] != "research":
                prog += '<div class="muted">条件未登记</div>'
            summ = r["state"]["summary"]
            pid = nid(ids[r["slug"]]) if r["slug"] in ids else ""  # 项目编号（pt rm / pt id 认它）
            rows.append(f'<div class="proj"><a class="pn" href="p/{r["slug"]}.html">{esc(r["name"] or r["slug"])}</a>{pid}'
                        f'<div class="meta">{"".join(f"<span>{esc(x)}</span>" for x in m)}{tags}</div>'
                        f'<div class="now">{inline(cut(summ, 110), Ref(r, "index", "human")) if summ else NONE}</div>{prog}</div>')
        body = "".join(rows)
        if title == "结束了":
            body = f"<details><summary>展开</summary>{body}</details>"
        s.append(f"<h2>{title}（{len(rs)}）</h2>{body}")
    for slug, why in sorted(fails.items()):
        s.append(f'<div class="proj"><b>{esc(slug)}</b><div class="muted">读取失败：{esc(why)}</div></div>')
    return page("全部项目", "\n".join(s), note)


# ---------- 写出 ----------

def projects(root, slugs=None):
    out = []
    for slug in sorted(os.listdir(root)):
        d = os.path.join(root, slug)
        if slug.startswith(".") or not SLUG_RE.match(slug) or os.path.islink(d) or \
                not os.path.isfile(os.path.join(d, "charter.md")):
            continue
        if slugs and slug not in slugs:
            continue
        out.append(slug)
    return out


def rel(target, frm):
    return os.path.relpath(target, frm).replace(os.sep, "/")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return len(text.encode())


def build(root, out=None, slugs=None, today=None):
    """生成整站；返回 {"pages", "projects", "max_bytes", "max_page", "seconds", "failed"}。"""
    t0 = time.time()
    root = os.path.abspath(root)
    out = os.path.abspath(out or os.path.join(root, "site"))
    today = today or progress.today()
    if os.path.isfile(os.path.join(out, "charter.md")):
        raise RuntimeError(f"{out} 是一个项目档案，不能当站点目录")
    if os.path.isdir(out) and os.listdir(out) and not os.path.isfile(os.path.join(out, MARK)):
        raise RuntimeError(f"{out} 已存在且不是 pt 生成的站点（没有 {MARK}），拒绝覆盖")
    parent = os.path.dirname(out)
    os.makedirs(parent, exist_ok=True)
    lock = open(os.path.join(parent, f".{os.path.basename(out)}.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    tmp = f"{out}.tmp-{os.getpid()}"
    try:
        recs, fails = {}, {}
        for slug in projects(root, slugs):
            try:
                recs[slug] = records.load(os.path.join(root, slug), today)
            except Exception as e:  # 坏档案不拖垮整站
                fails[slug] = f"{type(e).__name__}: {e}"
        note = f"由 pt 从档案只读生成于 {dt.datetime.now():%Y-%m-%d %H:%M}，不调用模型。「未记录」= 档案里找不到这一项。"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "p"))
        write(os.path.join(tmp, MARK), "pt sitegen\n")
        sizes = {}
        # 站点在档案根下（默认位置）才链回 research.html 与各 tree.html（pt serve 下是 /research.html、/<slug>/tree.html）；
        # --out 指到别处时这些相对路径既不在 pt serve 里、换台机器也打不开，不给
        home = out == os.path.join(root, "site")
        rh = "../research.html" if home and os.path.isfile(os.path.join(root, "research.html")) else ""
        ids = progress.project_ids(root)
        sizes["index.html"] = write(os.path.join(tmp, "index.html"), overview(recs, fails, today, rh, note, ids))
        for slug, rec in recs.items():
            th = os.path.join(root, slug, "tree.html")
            href = rel(th, os.path.join(out, "p")) if home and rec["kind"] == "research" and os.path.isfile(th) else ""
            try:
                sizes[f"p/{slug}.html"] = write(os.path.join(tmp, "p", f"{slug}.html"), project_page(rec, today, href, note,
                                                                                         ids.get(slug, "")))
                for i in rec["nodes"]:
                    sizes[f"p/{slug}/{i}.html"] = write(os.path.join(tmp, "p", slug, f"{i}.html"), node_page(rec, i, note))
                pages = entry_pages(rec)
                for e in rec["journal"]:
                    if e["id"] in pages:
                        sizes[f"p/{slug}/{e['id']}.html"] = write(os.path.join(tmp, "p", slug, f"{e['id']}.html"),
                                                                  entry_page(rec, e, note))
            except Exception as e:
                fails[slug] = f"渲染失败 {type(e).__name__}: {e}"
        big = max(sizes, key=sizes.get)
        if sizes[big] > PAGE_MAX:
            print(f"[warn] {big} 有 {sizes[big]} 字节，超过 1 MB", file=sys.stderr)
        old = f"{out}.old-{os.getpid()}"
        if os.path.isdir(out):
            os.rename(out, old)
        os.rename(tmp, out)
        shutil.rmtree(old, ignore_errors=True)
        return {"pages": len(sizes), "projects": len(recs), "max_bytes": sizes[big], "max_page": big,
                "seconds": time.time() - t0, "failed": fails, "out": out}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def main(argv):
    ap = argparse.ArgumentParser(prog="pt site", description="从档案生成给人看的只读站点（全部项目 → 项目 → 节点）")
    ap.add_argument("root", help="档案根")
    ap.add_argument("--out", help="站点目录（默认 <档案根>/site，pt serve 发在 /site/ 下）")
    ap.add_argument("--slugs", help="只生成这些项目（逗号分隔）")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        print(f"pt site: 没有档案根 {a.root}", file=sys.stderr)
        return 2
    try:
        st = build(a.root, a.out, set(a.slugs.split(",")) if a.slugs else None)
    except RuntimeError as e:
        print(f"pt site: {e}", file=sys.stderr)
        return 2
    print(f"site：{st['projects']} 个项目，{st['pages']} 页，最大 {st['max_page']} {st['max_bytes'] // 1024} KB，"
          f"{st['seconds']:.2f}s → {st['out']}")
    for slug, why in st["failed"].items():
        print(f"[warn] {slug}：{why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
