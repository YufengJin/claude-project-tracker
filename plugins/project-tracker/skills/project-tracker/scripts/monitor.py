#!/usr/bin/env python3
"""monitor.py — 全局研究监控：汇总档案根下所有有 tree/ 的项目，写 <档案根>/research.html。

  monitor.py <档案根>                 写 <档案根>/research.html（各项目 tree.html 的入口 + 跨项目最近动态）
  monitor.py <档案根> --out PATH      写到别处；指向各项目 tree.html 的链接按相对路径改写
  monitor.py <档案根> --events        不写页面，把最近动态按 TSV 打到 stdout（时间戳 slug ID 类别 变化 机器）
  --days N                            最近动态看几天（默认 14）

最近动态取自各项目 git 历史：比较每个提交里 tree/<ID>.md 前后的 frontmatter，
得出新增、status 变化、verdict 变化、换父、删除。只用标准库。
"""
import html
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree  # noqa: E402

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PATH_RE = re.compile(r"^tree/([QH][1-9][0-9]*)\.md$")
ZERO = re.compile(r"^0+$")
MAX_EVENTS = 100
PER_COMMIT = 6
FOCUS_MAX = 5
# 节点计数的类别：顺序即条与图例的顺序。closed 按 verdict 细分，图标与 tree.html 的图一致
CATS = (("active", "active", "s-active", ""), ("open", "open", "s-open", ""), ("parked", "parked", "s-parked", ""),
        ("supported", "supported", "s-closed v-supported", "✓"), ("refuted", "refuted", "s-closed v-refuted", "✗"),
        ("inconclusive", "inconclusive", "s-closed v-inconclusive", "?"),
        ("superseded", "superseded", "s-closed v-superseded", "→"), ("abandoned", "abandoned", "s-closed v-abandoned", "–"),
        ("closed", "closed（无 verdict）", "s-closed v-unknown", "!"), ("unknown", "status 不认识", "s-unknown", "!"))
KIND_LABEL = {"add": "新增", "status": "状态", "verdict": "结论", "parent": "换父", "del": "删除"}

esc = tree.esc


# ---------- 采集 ----------

def git(d, *args, data=None):
    try:
        r = subprocess.run(["git", "-C", d, *args], input=data, capture_output=True, check=False)
    except OSError:
        return b""
    return r.stdout if r.returncode == 0 else b""


def cat_blobs(d, shas):
    """一次 git cat-file --batch 取回所有 blob 文本。"""
    out = {}
    if not shas:
        return out
    buf = git(d, "cat-file", "--batch", data=("\n".join(shas) + "\n").encode())
    k = 0
    while k < len(buf):
        e = buf.find(b"\n", k)
        if e < 0:
            break
        head = buf[k:e].split()
        k = e + 1
        if len(head) == 3 and head[1] == b"blob":
            n = int(head[2])
            out[head[0].decode()] = buf[k:k + n].decode("utf-8", "replace")
            k += n + 1
    return out


def host_of_commit(email, subject):
    """档案提交用固定身份 pt@<主机>；别的作者看提交说明里的 @<主机>；都没有就空。"""
    if email.startswith("pt@") and len(email) > 3:
        return email[3:]
    m = re.search(r"(?:^|\s)@([A-Za-z0-9][\w.-]*?)(?=[:：\s(（]|$)", subject)
    return m.group(1) if m else ""


def meta_of(raw, nid):
    n = tree.parse_node_text(raw.replace("\r\n", "\n").lstrip("﻿"), nid)
    return n


def history(d, days):
    """最近 days 天里 tree/ 节点 frontmatter 的变化。返回 (事件列表（新→旧）, 最近一次提交时间或 None)。"""
    log = git(d, "log", f"--since={days}.days", "-n", "3000", "--no-renames", "--raw", "--no-abbrev",
              "--format=%x01%H%x00%ct%x00%ae%x00%s", "--", "tree/").decode("utf-8", "replace")
    commits = []
    for chunk in log.split("\x01")[1:]:
        lines = chunk.split("\n")
        h = lines[0].split("\x00")
        if len(h) < 4:
            continue
        ch = []
        for ln in lines[1:]:
            if not ln.startswith(":") or "\t" not in ln:
                continue
            info, path = ln.split("\t", 1)
            m = PATH_RE.match(path)
            f = info.split()
            if not m or len(f) < 5:
                continue
            ch.append((m.group(1), f[2], f[3], f[4][:1]))
        commits.append({"sha": h[0], "ts": int(h[1] or 0), "host": host_of_commit(h[2], h[3]), "ch": ch})
    shas = sorted({s for c in commits for _, a, b, _ in c["ch"] for s in (a, b) if not ZERO.match(s)})
    blobs = cat_blobs(d, shas)
    parsed = {}

    def node(sha, nid):
        if ZERO.match(sha) or sha not in blobs:
            return None
        if sha not in parsed:
            parsed[sha] = meta_of(blobs[sha], nid)
        return parsed[sha]

    events = []
    for c in commits:
        for nid, a, b, st in sorted(c["ch"], key=lambda x: tree.id_key(x[0])):
            o, n = node(a, nid), node(b, nid)
            chg = []
            if o is None and n is not None:
                chg.append(("add", tree.tag(n)))
            elif n is None and o is not None:
                chg.append(("del", tree.tag(o)))
            elif o is not None:
                if (o["status"], o["verdict"]) != (n["status"], n["verdict"]):
                    chg.append(("status" if o["status"] != n["status"] else "verdict", f"{tree.tag(o)} → {tree.tag(n)}"))
                if o["parent"] != n["parent"]:
                    chg.append(("parent", f"{o['parent'] or '（根）'} → {n['parent'] or '（根）'}"))
            if not chg:
                continue
            cur = n or o
            events.append({"ts": c["ts"], "sha": c["sha"], "host": c["host"], "id": nid,
                           "title": cur["title"], "new": n, "old": o, "chg": chg})
    last = commits[0]["ts"] if commits else None
    return events, last


def index_rows(root):
    """INDEX.md 各行：slug → (名称, 状态, 主机, 一句话)。"""
    rows = {}
    try:
        text = tree.read_text(os.path.join(root, "INDEX.md"))
    except (OSError, UnicodeDecodeError):
        return rows
    for ln in text.split("\n"):
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if ln.startswith("| ") and len(c) >= 6 and SLUG_RE.match(c[0]):
            rows[c[0]] = (c[1], c[2], c[3], c[5])
    return rows


def charter_field(d, key):
    try:
        for ln in tree.read_text(os.path.join(d, "charter.md")).split("\n"):
            if ln.startswith(key + ":"):
                return ln[len(key) + 1:].strip()
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def charter_name(d):
    try:
        first = tree.read_text(os.path.join(d, "charter.md")).split("\n", 1)[0]
    except (OSError, UnicodeDecodeError):
        return ""
    return re.sub(r"^#\s*", "", first).strip()


def host_aliases(root):
    """中心机上 sync 学到的 hostname → FLEET 别名。"""
    out = {}
    hd = os.path.join(root, ".fleet", "hosts")
    for a in sorted(os.listdir(hd)) if os.path.isdir(hd) else []:
        try:
            with open(os.path.join(hd, a, "hostname"), encoding="utf-8") as f:
                h = f.read().strip()
        except OSError:
            continue
        if h:
            out[h] = a
    return out


def sync_state(root):
    """FLEET 里各节点的上次同步：(最近一次同步的时间戳, 在线台数, 总台数)；不是中心机返回 None。"""
    try:
        with open(os.path.join(root, "FLEET"), encoding="utf-8") as f:
            aliases = [ln.split("#", 1)[0].split()[0] for ln in f if ln.split("#", 1)[0].strip()]
    except OSError:
        return None

    def rd(a, k):
        try:
            with open(os.path.join(root, ".fleet", "hosts", a, k), encoding="utf-8") as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0
    tries = [rd(a, "last_try") for a in aliases]
    up = sum(1 for a in aliases if rd(a, "last_try") and rd(a, "last_try") == rd(a, "last_ok"))
    return (max(tries) if tries else 0, up, len(aliases))


def cat_of(n):
    s, v = n["status"], n["verdict"]
    if s == "closed":
        return v if v in tree.VERDICTS else "closed"
    return s if s in tree.STATUSES else "unknown"


def collect(root, days):
    me = os.environ.get("PT_HOSTNAME") or os.uname().nodename.split(".")[0]
    alias = host_aliases(root)
    label = lambda h: "" if not h else "本机" if h == me else alias.get(h, h)  # noqa: E731
    idx = index_rows(root)
    projects, events = [], []
    for slug in sorted(os.listdir(root)):
        d = os.path.join(root, slug)
        if not SLUG_RE.match(slug) or not os.path.isdir(os.path.join(d, "tree")) or not os.path.isfile(os.path.join(d, "charter.md")):
            continue
        t = tree.Tree(d)
        evs, last = history(d, days)
        if last is None:
            last = int(git(d, "log", "-1", "--format=%ct", "--", "tree/").strip() or 0) or None
        if last is None:  # 还没提交过 tree/：取节点文件的修改时间
            ms = [os.path.getmtime(os.path.join(d, "tree", f)) for f in os.listdir(os.path.join(d, "tree"))]
            last = int(max(ms)) if ms else 0
        cnt = {}
        for n in t.nodes.values():
            cnt[cat_of(n)] = cnt.get(cat_of(n), 0) + 1
        act = [i for i in sorted(t.nodes, key=tree.id_key) if t.nodes[i]["status"] == "active"]
        leaves = [i for i in act if not any(t.nodes[x]["status"] == "active" for x in t.descendants(i))]
        name, st, host, summ = idx.get(slug, ("", "", "", ""))
        if not name:
            name = charter_name(d)
            st = charter_field(d, "Status")
            host = label(charter_field(d, "Host"))
        for e in evs:
            e["slug"] = slug
            e["host"] = label(e["host"])
        events.extend(evs)
        projects.append({"slug": slug, "name": name or slug, "status": st, "host": host, "summary": summ,
                         "cnt": cnt, "total": len(t.nodes), "focus": [(t.chain(i) + [i]) for i in leaves],
                         "warn": len(t.warnings), "last": last, "nodes": t.nodes})
    projects.sort(key=lambda p: (-(p["last"] or 0), p["slug"]))
    events.sort(key=lambda e: -e["ts"])  # 稳定排序：同一秒内保持各项目 git log 的先后
    return projects, events


# ---------- 页面 ----------

CSS = tree.PALETTE + """
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,-apple-system,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif}
header{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:17px;margin:0 6px 0 0}header .m{color:var(--mut);font-size:13px}header label{color:var(--mut);font-size:13px;cursor:pointer;white-space:nowrap}
main{max-width:1180px;margin:0 auto;padding:16px 16px 60px}
h2.sec{font-size:15px;margin:22px 0 10px;color:var(--mut);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(330px,100%),1fr));gap:12px}
.card{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;min-width:0}
.card:hover{border-color:var(--edge)}.card:focus-within{border-color:var(--active)}
.card h3{font-size:15px;margin:0;line-height:1.35;overflow-wrap:anywhere}
.card h3 a{color:var(--fg);text-decoration:none}.card h3 a::after{content:"";position:absolute;inset:0;border-radius:10px}
.card h3 a:focus-visible{outline:none}
.card .slug{font:12px ui-monospace,monospace;color:var(--faint)}
.meta{color:var(--mut);font-size:12.5px;margin:2px 0 6px}
.sum{margin:4px 0 8px;font-size:13px;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;gap:1px;background:var(--line);margin:6px 0 4px}
.bar i{display:block;min-width:3px;background:var(--panel);box-shadow:inset 0 0 0 1.5px var(--open)}
.bar i.s-active{background:var(--active);box-shadow:none}.bar i.s-parked{box-shadow:inset 0 0 0 1.5px var(--parked);background:repeating-linear-gradient(90deg,var(--panel) 0 3px,var(--line) 3px 5px)}
.bar i.v-supported{background:var(--supported);box-shadow:none}.bar i.v-refuted{background:var(--refuted);box-shadow:none}
.bar i.v-inconclusive{background:var(--inconclusive);box-shadow:none}.bar i.v-superseded{background:var(--superseded);box-shadow:none}
.bar i.v-abandoned{box-shadow:inset 0 0 0 1.5px var(--abandoned)}.bar i.v-unknown,.bar i.s-unknown{background:var(--other);box-shadow:none}
.cts{display:flex;flex-wrap:wrap;gap:2px 10px;font-size:12px;color:var(--mut)}.cts span{white-space:nowrap}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;border:2px solid var(--open);vertical-align:-1px}
.s-active .dot,.dot.s-active{background:var(--active);border-color:var(--active)}.s-parked .dot{border-color:var(--parked);border-style:dashed}
.s-closed .dot{background:var(--closed);border-color:var(--closed)}
.v-supported .dot{background:var(--supported);border-color:var(--supported)}.v-refuted .dot{background:var(--refuted);border-color:var(--refuted)}
.v-inconclusive .dot{background:var(--inconclusive);border-color:var(--inconclusive)}.v-superseded .dot{background:var(--superseded);border-color:var(--superseded)}
.v-abandoned .dot{background:none;border-color:var(--abandoned);border-style:dotted}.s-unknown .dot,.v-unknown .dot{border-color:var(--other);border-style:dashed;background:none}
.focus{margin:8px 0 0;font-size:12.5px}.focus b{font-weight:600;color:var(--mut);font-size:12px}
.focus ol{list-style:none;margin:2px 0 0;padding:0}.focus li{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.focus a,.tl a{position:relative;z-index:1}
a{color:var(--link)}a.id{font-family:ui-monospace,monospace;font-size:12.5px;text-decoration:none}a.id:hover{text-decoration:underline}
.sep{color:var(--faint);margin:0 2px}.lt{color:var(--mut)}
.foot{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:8px;font-size:12px;color:var(--mut)}.warn{color:var(--warnc)}
.tl{list-style:none;margin:0;padding:0}
.day{font-size:13px;font-weight:600;margin:14px 0 4px;color:var(--fg)}
.cm{display:grid;grid-template-columns:3.4em 1fr;gap:0 10px;padding:6px 0;border-top:1px solid var(--line)}
.cm time{color:var(--mut);font:12.5px ui-monospace,monospace;padding-top:1px}
.cm .h{font-size:12.5px;color:var(--mut)}.cm .h a{font-weight:600;text-decoration:none}.cm .h a:hover{text-decoration:underline}
.cm ul{list-style:none;margin:2px 0 0;padding:0}.cm li{min-width:0;overflow-wrap:anywhere;margin:1px 0}
.cm li .t{color:var(--fg);margin:0 8px 0 6px}.k{font-size:11.5px;color:var(--mut);border:1px solid var(--line);border-radius:4px;padding:0 4px;white-space:nowrap;margin-right:5px}
.chg{font-size:12.5px;white-space:nowrap;margin-right:8px}
.b{display:inline-block;font-size:11.5px;padding:0 6px;border-radius:9px;border:1.5px solid var(--line);color:var(--fg);line-height:1.45}
.b.s-open{border-color:var(--open)}.b.s-active{border-color:var(--active)}.b.s-parked{border-color:var(--parked);border-style:dashed}.b.s-closed{border-color:var(--closed)}
.b.v-supported{border-color:var(--supported)}.b.v-refuted{border-color:var(--refuted)}.b.v-inconclusive{border-color:var(--inconclusive)}.b.v-superseded{border-color:var(--superseded)}
.b.v-abandoned{border-color:var(--abandoned);border-style:dotted}.b.s-unknown,.b.v-unknown{border-color:var(--other);border-style:dashed}
details summary{cursor:pointer;color:var(--mut);font-size:12.5px}
.empty{color:var(--mut);padding:12px 0}
@media (max-width:520px){header{padding:10px 16px}main{padding:12px 16px 40px}.cm{grid-template-columns:3em 1fr;gap:0 8px}}
"""

JS = r"""
(function(){var cb=document.getElementById('ar'),lab=document.getElementById('age'),K='pt-monitor-autorefresh',T=null,gen=+document.body.getAttribute('data-gen')*1000;
try{if(localStorage.getItem(K)==='0')cb.checked=false;}catch(e){}
function arm(){clearTimeout(T);if(cb.checked)T=setTimeout(function(){location.reload();},60000);}
cb.addEventListener('change',function(){try{localStorage.setItem(K,cb.checked?'1':'0');}catch(e){}arm();});
function age(){var m=Math.round((Date.now()-gen)/60000);lab.textContent=m<1?'':m<120?'（'+m+' 分钟前）':'（'+Math.round(m/60)+' 小时前）';}
age();setInterval(age,30000);arm();})();
"""


def hm(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def mdhm(ts):
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def tag_badge(tg):
    """「closed/refuted」这种 tag → 徽标（class 只取白名单值）。"""
    s, _, v = tg.partition("/")
    sc = s if s in tree.STATUSES else "unknown"
    vc = (v if v in tree.VERDICTS else "unknown") if v else ""
    return f'<span class="b s-{sc}' + (f" v-{vc}" if vc else "") + f'">{esc(tg)}</span>'


def node_link(base, slug, nid, nodes=None, cls="id"):
    t = nodes[nid]["title"] if nodes and nid in nodes else ""
    return f'<a class={cls} href="{esc(base)}{slug}/tree.html#{nid}"' + (f' title="{esc(t)}"' if t else "") + f">{esc(nid)}</a>"


def card(p, base):
    s = p["slug"]
    out = [f'<article class=card><h3><a href="{esc(base)}{s}/tree.html">{esc(p["name"])}</a></h3>'
           f'<div class=slug>{esc(s)}</div>']
    meta = [x for x in (f"@{p['host']}" if p["host"] else "", p["status"]) if x]
    out.append(f"<div class=meta>{' · '.join(esc(x) for x in meta)}</div>")
    if p["summary"]:
        out.append(f"<p class=sum>{esc(p['summary'])}</p>")
    cnt = p["cnt"]
    if p["total"]:
        out.append("<div class=bar role=img aria-label=\"" + esc("，".join(f"{lab} {cnt[k]}" for k, lab, _, _ in CATS if cnt.get(k)))
                   + "\">" + "".join(f'<i class="{c}" style="flex-grow:{cnt[k]}"></i>' for k, _, c, _ in CATS if cnt.get(k)) + "</div>")
        chips = []
        for k, lab, c, g in CATS:
            if cnt.get(k):
                txt = f"{g} {cnt[k]}" if g else f"{lab} {cnt[k]}"
                chips.append(f'<span class="{c}" title="{esc(lab)} {cnt[k]}"><i class=dot></i>{esc(txt)}</span>')
        out.append(f"<div class=cts>{''.join(chips)}<span>共 {p['total']}</span></div>")
    else:
        out.append("<div class=meta>还没有节点</div>")
    if p["focus"]:
        items = []
        for ch in p["focus"][:FOCUS_MAX]:
            leaf = ch[-1]
            links = '<span class=sep>›</span>'.join("…" if x is None else node_link(base, s, x, p["nodes"])
                                                    for x in tree.short_chain(ch, keep=4))
            items.append(f"<li>{links} <span class=lt>{esc(p['nodes'][leaf]['title'])}</span></li>")
        more = f"<li class=lt>另 {len(p['focus']) - FOCUS_MAX} 条</li>" if len(p["focus"]) > FOCUS_MAX else ""
        out.append(f"<div class=focus><b>焦点</b><ol>{''.join(items)}{more}</ol></div>")
    else:
        out.append("<div class=focus><b>焦点</b> <span class=lt>没有 active 节点</span></div>")
    foot = [f"最近变动 {mdhm(p['last'])}"]
    if p["warn"]:
        foot.append(f"<span class=warn>⚠ 告警 {p['warn']}</span>")
    else:
        foot.append("告警 0")
    out.append(f"<div class=foot>{''.join(f'<span>{x}</span>' for x in foot)}</div></article>")
    return "".join(out)


def event_li(e, base):
    s, nid = e["slug"], e["id"]
    href = f"{esc(base)}{s}/tree.html" + ("" if e["new"] is None else f"#{nid}")
    parts = []
    for kind, txt in e["chg"]:
        if kind in ("add", "del"):
            body = tag_badge(txt)
        elif kind == "parent":
            body = esc(txt)
        else:
            a, _, b = txt.partition(" → ")
            body = f"{tag_badge(a)} → {tag_badge(b)}"
        parts.append(f'<span class=k>{KIND_LABEL[kind]}</span><span class=chg>{body}</span>')
    return (f'<li><a class=id href="{href}">{esc(nid)}</a><span class=t>{esc(e["title"])}</span>'
            + "".join(parts) + "</li>")


def timeline(events, base):
    shown = events[:MAX_EVENTS]
    groups = []  # 按 (项目, 提交) 归组，组内保持 ID 顺序
    for e in shown:
        if groups and groups[-1][0]["sha"] == e["sha"] and groups[-1][0]["slug"] == e["slug"]:
            groups[-1].append(e)
        else:
            groups.append([e])
    out, day = [], None
    for g in groups:
        e0 = g[0]
        d = time.strftime("%Y-%m-%d", time.localtime(e0["ts"]))
        if d != day:
            if day is not None:
                out.append("</ul>")
            day = d
            out.append(f"<div class=day>{time.strftime('%m 月 %d 日', time.localtime(e0['ts']))}</div><ul class=tl>")
        lis = [event_li(e, base) for e in g]
        body = "".join(lis[:PER_COMMIT])
        if len(lis) > PER_COMMIT:
            body += f"<li><details><summary>另 {len(lis) - PER_COMMIT} 项</summary><ul>{''.join(lis[PER_COMMIT:])}</ul></details></li>"
        host = f" · @{esc(e0['host'])}" if e0["host"] else ""
        out.append(f'<li class=cm><time>{hm(e0["ts"])}</time><div><div class=h><a href="{esc(base)}{e0["slug"]}/tree.html">'
                   f'{esc(e0["slug"])}</a>{host}</div><ul>{body}</ul></div></li>')
    if day is not None:
        out.append("</ul>")
    return "".join(out)


def render(projects, events, sync, days, base, now):
    sy = ""
    if sync and sync[0]:
        sy = f'<span class=m>上次同步 {mdhm(sync[0]) if now - sync[0] > 86400 else hm(sync[0])}（{sync[1]}/{sync[2]} 台在线）</span>'
    head = (f'<header><h1>研究监控</h1><span class=m>生成于 {hm(now)}<span id=age></span></span>{sy}'
            f'<span class=m>{len(projects)} 个研究项目</span>'
            f'<label><input type=checkbox id=ar checked> 每 60 秒刷新</label></header>')
    cards = "".join(card(p, base) for p in projects) or "<p class=empty>档案根下还没有研究项目（有 tree/ 的项目）。</p>"
    n = len(events)
    cap = f"（显示最近 {MAX_EVENTS} 条，共 {n} 条）" if n > MAX_EVENTS else f"（{n} 条）"
    tl = timeline(events, base) or f"<p class=empty>最近 {days} 天没有节点变化。</p>"
    return (f"<!doctype html>\n<html lang=zh-CN><head><meta charset=utf-8>"
            f"<meta name=viewport content=\"width=device-width,initial-scale=1\"><title>研究监控</title>"
            f"<style>{CSS}</style></head><body data-gen=\"{int(now)}\">\n{head}\n<main>"
            f"<h2 class=sec>研究项目（按最近 tree/ 变动排序）</h2><div class=grid>{cards}</div>"
            f"<h2 class=sec>最近动态 · {days} 天{cap}</h2>{tl}</main>"
            f"<script>{JS}</script></body></html>\n")


def write_atomic(path, doc):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".research.html.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(doc)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv):
    args = list(argv)
    out = days = None
    events_only = "--events" in args
    if events_only:
        args.remove("--events")
    for opt in ("--out", "--days"):
        if opt in args:
            k = args.index(opt)
            if k + 1 >= len(args):
                return usage(f"{opt} 后面要跟参数")
            val = args[k + 1]
            del args[k:k + 2]
            if opt == "--out":
                out = val
            else:
                days = val
    if len(args) != 1 or args[0].startswith("-"):
        return usage()
    root = os.path.abspath(args[0])
    if not os.path.isdir(root):
        return usage(f"不是目录: {root}")
    try:
        days = int(days) if days is not None else 14
        assert days > 0
    except (ValueError, AssertionError):
        return usage("--days 要正整数")
    t0 = time.time()
    projects, events = collect(root, days)
    if events_only:
        for e in events:
            for kind, txt in e["chg"]:
                print("\t".join((str(e["ts"]), e["slug"], e["id"], kind, txt, e["host"])))
        return 0
    path = os.path.abspath(out) if out else os.path.join(root, "research.html")
    rel = os.path.relpath(root, os.path.dirname(path))
    base = "" if rel == "." else urllib.parse.quote(rel.replace(os.sep, "/")) + "/"
    write_atomic(path, render(projects, events, sync_state(root), days, base, time.time()))
    print(f"research.html：{len(projects)} 个研究项目，最近 {days} 天 {len(events)} 条动态，"
          f"{time.time() - t0:.2f}s → {path}")
    return 0


def usage(msg=None):
    if msg:
        print("monitor.py: " + msg, file=sys.stderr)
    print("用法: monitor.py <档案根> [--out PATH] [--days N] [--events]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
