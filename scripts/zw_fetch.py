"""Zimbabwe: list and download Acts and the Constitution from Veritas Zimbabwe
(https://www.veritaszim.net, content licensed CC BY-NC-SA 4.0).

  /acts?page=N          -> /node/<n>  (Acts: principal Acts in successive versions, amendment Acts)
  /constitution         -> /node/<n>  (Constitution 2013 consolidated, older constitutions)
Each node page links one or more attachments (.doc/.docx/.pdf) under /sites/veritas_d/files/.

robots.txt Crawl-delay: 10 is obeyed (one request per 10 s). Cached in _raw/zw/.
Usage: python zw_fetch.py
"""
import html
import json
import os
import re
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zw_text import fetch, sniff, pdf_ok  # noqa: E402

BASE = "https://www.veritaszim.net"
RAW = os.environ.get("ZW_RAW", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_raw", "zw"))
DELAY = 10.0


def get(path, name):
    p = fetch(BASE + path, os.path.join(RAW, "html", name), delay=DELAY)
    return open(p, encoding="utf-8", errors="replace").read() if p else ""


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def rows(h):
    i = h.find('class="view-content"')
    if i < 0:
        return []
    j = h.find('<ul class="pager', i)
    j = j if j > 0 else h.find("Search form", i)
    return [(n, text(t)) for n, t in re.findall(r'href="/node/(\d+)">(.*?)</a>', h[i:j], re.S)]


def list_all():
    items = {}
    for n, t in rows(get("/constitution", "constitution.html")):
        items[n] = {"node": n, "title": t, "collection": "constitution"}
    pg = 0
    while True:
        r = rows(get("/acts?page=%d" % pg, "acts-%d.html" % pg))
        if not r:
            break
        for n, t in r:
            items.setdefault(n, {"node": n, "title": t, "collection": "acts"})
        pg += 1
    json.dump(items, open(os.path.join(RAW, "index.json"), "w"), indent=1)
    print("listed", len(items))
    return items


def details(items):
    for k, it in sorted(items.items(), key=lambda kv: int(kv[0])):
        if "files" in it:
            continue
        h = get("/node/%s" % k, "node-%s.html" % k)
        i = h.find("<h1")
        j = h.find("Search form", i)
        body = h[i:j]
        files = re.findall(r'href="(https?://www\.veritaszim\.net/sites/veritas_d/files/[^"]+)"', body)
        it["files"] = list(dict.fromkeys(html.unescape(u) for u in files))
        m = re.search(r'field-name-body.*?<div class="field-item even"[^>]*>(.*?)</div>', body, re.S)
        it["summary"] = text(m.group(1))[:2000] if m else ""
        it["tags"] = [text(t) for t in re.findall(r'href="/taxonomy/term/\d+"[^>]*>(.*?)</a>', body)]
        json.dump(items, open(os.path.join(RAW, "index.json"), "w"), indent=1)


def pick(files):
    """Prefer a Word document (better text) over a PDF; ignore other attachments."""
    def ext(u):
        return os.path.splitext(unquote(u))[1].lower()
    docs = [u for u in files if ext(u) in (".doc", ".docx", ".rtf")]
    pdfs = [u for u in files if ext(u) == ".pdf"]
    return (docs or pdfs)[:1]


def download(items):
    for k, it in sorted(items.items(), key=lambda kv: int(kv[0])):
        for u in pick(it.get("files", [])):
            dest = os.path.join(RAW, "files", k + os.path.splitext(unquote(u))[1].lower())
            if os.path.exists(dest) and (sniff(dest) != "pdf" or pdf_ok(dest)):
                continue
            ok = fetch(u, dest, delay=DELAY, timeout=300, check_pdf=dest.endswith(".pdf"))
            if not ok:
                print("FAILED", k, u)


if __name__ == "__main__":
    os.makedirs(RAW, exist_ok=True)
    idx = os.path.join(RAW, "index.json")
    items = json.load(open(idx)) if os.path.exists(idx) and "--relist" not in sys.argv else list_all()
    details(items)
    download(items)
