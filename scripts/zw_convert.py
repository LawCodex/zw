"""Zimbabwe: convert the Veritas downloads (Word or PDF) to Markdown.
Usage: python zw_convert.py <repo_dir>

* Word (.doc/.docx/.rtf) files: textutil (.doc -> .docx) + pandoc (see zw_docx.py);
* PDF files: poppler pdftotext (scans without a text layer are skipped; no OCR).
Acts are kept in every version Veritas publishes (the version/date is part of the title and file name).
Constitution: the current consolidated text, the 2013 Constitution as adopted, and the last consolidated text of
the 1979 (Lancaster House) Constitution, plus the constitutional amendment Acts; older intermediate consolidations
and the 2013 draft are not converted."""
import datetime
import json
import os
import re
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zw_docx import docx_markdown  # noqa: E402
from zw_text import pdf_text, clean_pages, structure, write_md, slug, text_quality, sniff  # noqa: E402

RAW = os.environ.get("ZW_RAW", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_raw", "zw"))
TODAY = datetime.date.today().isoformat()
CONSTITUTION_KEEP = {
    "8104": ("constitution-of-zimbabwe-2013-consolidated.md", "Constitution of Zimbabwe (2013), consolidated", "in_force"),
    "1170": ("constitution-of-zimbabwe-2013-as-adopted.md", "Constitution of Zimbabwe (2013) — Constitution of Zimbabwe Amendment (No. 20) Act, 2013", "unknown"),
    "97": ("constitution-of-zimbabwe-1979-as-amended-to-2009.md", "Constitution of Zimbabwe (1979) as amended by Amendment (No. 19) Act, 2009", "repealed"),
    "94": ("constitution-of-zimbabwe-amendment-no-19-act-2009.md", "Constitution of Zimbabwe Amendment (No. 19) Act, 2009", "unknown"),
    "93": ("constitution-of-zimbabwe-amendment-no-18-act-2007.md", "Constitution of Zimbabwe Amendment (No. 18) Act, 2007", "unknown"),
    "92": ("constitution-of-zimbabwe-amendment-no-13-act-1993.md", "Constitution of Zimbabwe Amendment (No. 13) Act, 1993", "unknown"),
}


EXCLUDE = re.compile(r"(?i)^Acts of \d{4}|\bBill\b|\bH\.?B\.? ?\d|Departmental Draft|Draft Constitution|Extract from|"
                     r"Court Application|Opposition Papers")
TRANSLATIONS = {"nambya": "nmq", "kalanga": "kck", "chewa": "ny", "shona": "sn", "ndebele": "nd", "koisan": "khi",
                "ndau": "ndc", "venda": "ve", "tonga": "toi", "shangani": "ts", "sotho": "st", "tswana": "tn", "xhosa": "xh"}


def file_for(k, it):
    exts = [os.path.splitext(unquote(u))[1].lower() for u in it.get("files", [])]
    for ext in (".doc", ".docx", ".rtf", ".pdf"):
        p = os.path.join(RAW, "files", k + ext)
        if ext in exts and os.path.exists(p):
            return p
    return None


def convert(path):
    kind = sniff(path)
    if kind in ("doc", "docx", "rtf"):
        src = path
        if kind == "doc" and not path.endswith(".doc"):
            src = path + ".doc"
            if not os.path.exists(src):
                os.link(path, src)
        md = docx_markdown(src)
        return md.splitlines() if md and len(md) > 300 else None
    if kind == "pdf":
        pages, _ = pdf_text(path)
        full = "\n".join(pages)
        if len(re.sub(r"\s", "", full)) < 500 or text_quality(full) < 0.75:
            return None
        return structure(clean_pages(pages), "en")
    return None


def main(repo):
    items = json.load(open(os.path.join(RAW, "index.json")))
    n = skipped = 0
    seen = set()
    for k, it in sorted(items.items(), key=lambda kv: int(kv[0])):
        if it["collection"] == "constitution" and k not in CONSTITUTION_KEEP:
            continue
        if EXCLUDE.search(it["title"]):
            continue
        f = file_for(k, it)
        if not f:
            skipped += 1
            print("no file", k, it["title"])
            continue
        body = convert(f)
        if not body:
            skipped += 1
            print("SKIP (no usable text)", k, it["title"])
            continue
        title = re.sub(r"\s*\((PDF|MS Word|WORD)[^)]*\)\s*$", "", it["title"], flags=re.I).strip()
        cap = re.search(r"\[\s*Chapter\s+(\d+:\d+)\s*\]", title, re.I)
        tr = re.match(r"(?i)^Constitution of Zimbabwe 2013 \(PDF Format\)\s+(\w+)$", it["title"])
        lang = "en"
        if tr and tr.group(1).lower() in TRANSLATIONS:
            lang = TRANSLATIONS[tr.group(1).lower()]
            name = tr.group(1).capitalize()
            title = "Constitution of Zimbabwe (2013) — %s translation" % name
            path = os.path.join(repo, "constitution", "translations", "constitution-2013-%s.md" % name.lower())
            typ, status = "constitution", "unknown"
        elif k in CONSTITUTION_KEEP or it["collection"] == "constitution":
            fname, title, status = CONSTITUTION_KEEP[k]
            path = os.path.join(repo, "constitution", fname)
            typ = "act" if title.startswith("Constitution of Zimbabwe Amendment") else "constitution"
        else:
            status = "unknown"
            typ = "statutory_instrument" if re.search(r"(?i)^SI\b|\bS\.I\.|statutory instrument|regulations|\bnotice\b|\bfees\b|scale of fines", title) \
                and not re.search(r"\bAct\b", title) else "act"
            path = os.path.join(repo, "acts", slug(title)[:95] + ".md")
            if path in seen:
                path = path[:-3] + "-%s.md" % k
        seen.add(path)
        year = re.search(r"\b(19[2-9]\d|20[0-2]\d)\b", title)
        meta = {"title": title, "identifier": ("Chapter " + cap.group(1)) if cap else "", "type": typ,
                "jurisdiction": "zw", "language": lang, "year": year.group(1) if year else "", "status": status,
                "source": "https://www.veritaszim.net/node/%s" % k,
                "file": [u for u in it["files"] if os.path.splitext(unquote(u))[1].lower() == os.path.splitext(f)[1].lower()][:1][0]
                if it.get("files") else "",
                "retrieved": TODAY, "note": "Text published by Veritas Zimbabwe (veritaszim.net), CC BY-NC-SA 4.0"}
        if it.get("summary"):
            meta["summary"] = it["summary"][:500]
        if lang != "en":  # translations: drop the line numbers printed in the margin
            body = [x for x in body if not re.match(r"^\d{1,3}$", x.strip())]
        write_md(path, meta, title, body)
        n += 1
    print("written", n, "skipped", skipped)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
