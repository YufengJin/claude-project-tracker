#!/usr/bin/env python3
"""journal.py — journal.md 的条目切分与按月归档。只用标准库。

  journal.py archive <档案目录> [--today YYYY-MM-DD] [--limit 字节]

archive：journal.md 超过 100 KB 时，把当月和上月之外的整月条目原样搬到 archive/journal-YYYY-MM.md
（已有的文件往后追加）；标题里认不出日期的旧条目按原顺序归到 archive/journal-early.md。条目内容一字不改，
搬之前核对搬移前后条目的总字节数与条数一致，对不上就什么都不写。journal.md 顶部留一行说明归档在哪。
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree  # noqa: E402

LIMIT = 100 * 1024
# 新格式标题：## [YYYY-MM-DD] 类别 | 节点或线程 | 一句话
NEW_HEAD = re.compile(r"^## \[(\d{4})-(\d{2})-(\d{2})\] (\S+) \| ")
CATEGORIES = ("结果", "决定", "方向", "运维", "评审")
# 认日期：新格式 [YYYY-MM-DD] 与旧格式 ## YYYY-MM-DD · session N
HEAD_DATE = re.compile(r"^## \[?(\d{4})-(\d{2})-\d{2}")
NOTE = "> 归档：更早的条目按月原样搬到 archive/journal-YYYY-MM.md（标题认不出日期的在 archive/journal-early.md），由 pt journal-archive 生成。\n"


def read_raw(path):
    """原样读（不改换行），读不了返回空串。"""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def split(text):
    """(前言, [条目])。条目从「## 」行开始，到下一个条目前为止；代码块里的 ## 不算。前言 + 条目拼回去与原文逐字相同。"""
    pre, entries, fence = [], [], False
    for ln in re.findall(r"[^\n]*\n|[^\n]+\Z", text):
        if tree.FENCE_RE.match(ln):
            fence = not fence
        if not fence and ln.startswith("## "):
            entries.append([ln])
        else:
            (entries[-1] if entries else pre).append(ln)
    return "".join(pre), ["".join(e) for e in entries]


def head(entry):
    return entry.split("\n", 1)[0].rstrip("\r")


def month(entry):
    m = HEAD_DATE.match(entry)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def category(entry):
    m = NEW_HEAD.match(entry)
    return m.group(4) if m else None


def plan(entries, today):
    """(留下的条目, {归档名: [条目]})。当月与上月（及更晚）的留下；更早的按月归档；认不出日期的：
    在第一条留下的条目之前就归 early，之后的留下（那是新近写坏的标题，不算旧条目）。"""
    first = dt.date(today.year, today.month, 1)
    prev = (first - dt.timedelta(days=1)).strftime("%Y-%m")
    keep_from = next((k for k, e in enumerate(entries) if (month(e) or "") >= prev), len(entries))
    kept, moved = [], {}
    for k, e in enumerate(entries):
        m = month(e)
        if (m and m >= prev) or (m is None and k > keep_from):
            kept.append(e)
        else:
            moved.setdefault(m or "early", []).append(e)
    return kept, moved


def archive(d, today, limit=LIMIT):
    jp = os.path.join(d, "journal.md")
    if not os.path.isfile(jp):
        print(f"journal.py: 没有 {jp}", file=sys.stderr)
        return 1
    size = os.path.getsize(jp)
    if size <= limit:
        print(f"journal.md {size} 字节，不到 {limit} 字节，不用搬")
        return 0
    raw = read_raw(jp)
    pre, entries = split(raw)
    kept, moved = plan(entries, today)
    nmoved = sum(len(v) for v in moved.values())
    if not nmoved:
        print(f"journal.md {size} 字节，但没有上月之前的条目可搬（全在当月与上月）")
        return 0
    # 核对：条目一字不改，总条数与总字节数守恒
    after = kept + [e for v in moved.values() for e in v]
    if len(after) != len(entries) or sum(len(e.encode()) for e in after) != sum(len(e.encode()) for e in entries) \
            or sorted(after) != sorted(entries):
        print("journal.py: 核对没过（条目数或字节数对不上），什么都没写", file=sys.stderr)
        return 1
    if NOTE not in pre:
        lines = pre.split("\n", 1)
        pre = (lines[0] + "\n" + NOTE + (lines[1] if len(lines) > 1 else "")) if lines[0].startswith("# ") else NOTE + pre
    adir = os.path.join(d, "archive")
    os.makedirs(adir, exist_ok=True)
    for name, ents in moved.items():
        with open(os.path.join(adir, f"journal-{name}.md"), "a", encoding="utf-8", newline="") as f:
            f.write("".join(ents))
    tmp = jp + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(pre + "".join(kept))
    os.replace(tmp, jp)
    names = "、".join(f"archive/journal-{n}.md（{len(v)} 条）" for n, v in moved.items())
    print(f"搬走 {nmoved} 条（{sum(len(e.encode()) for v in moved.values() for e in v)} 字节）到 {names}；"
          f"journal.md 留 {len(kept)} 条，{size} → {os.path.getsize(jp)} 字节")
    return 0


def main(argv):
    if len(argv) < 2 or argv[0] != "archive":
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    today, limit = dt.date.today(), LIMIT
    if "--today" in argv:
        today = dt.date.fromisoformat(argv[argv.index("--today") + 1])
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    return archive(argv[1], today, limit)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
