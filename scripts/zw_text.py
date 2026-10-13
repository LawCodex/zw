"""Generic helpers: polite HTTP download with cache, PDF verification, text extraction
(poppler pdftotext, tesseract OCR fallback for scanned PDFs) and plain-text -> Markdown
structuring for statutes (English or French)."""
import os
import re
import subprocess
import time
import unicodedata

import requests

UA = "LawCodex/1.0 (+https://github.com/LawCodex)"
_S = requests.Session()
_S.headers["User-Agent"] = UA
_last = [0.0]


def fetch(url, dest, delay=2.0, tries=4, timeout=120, check_pdf=False, verify=True):
    """Download url to dest (cached). Returns dest or None."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        if not check_pdf or pdf_ok(dest):
            return dest
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    for i in range(tries):
        wait = _last[0] + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = _S.get(url, timeout=timeout, verify=verify)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            exp = r.headers.get("content-length")
            if exp and exp.isdigit() and int(exp) != len(r.content) and "gzip" not in r.headers.get("content-encoding", ""):
                raise IOError("truncated %d/%s" % (len(r.content), exp))
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(r.content)
            if check_pdf and not pdf_ok(tmp):
                os.remove(tmp)
                raise IOError("bad pdf")
            os.replace(tmp, dest)
            return dest
        except Exception as e:  # noqa
            print("  retry", i + 1, url, e)
            time.sleep(5 * (i + 1))
    return None


def pdf_pages_count(path):
    r = subprocess.run(["pdfinfo", path], capture_output=True)
    m = re.search(rb"Pages:\s+(\d+)", r.stdout)
    return int(m.group(1)) if m else 0


def pdf_ok(path):
    """Header present, %%EOF near the end, poppler sees pages and can read the last page."""
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
            f.seek(max(0, os.path.getsize(path) - 2048))
            tail = f.read()
    except OSError:
        return False
    if b"%PDF" not in head or b"%%EOF" not in tail:
        return False
    n = pdf_pages_count(path)
    if n <= 0:
        return False
    r = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), path, "-"], capture_output=True)
    return r.returncode == 0


def _ocr_page(path, i, lang, tmpdir):
    base = os.path.join(tmpdir, "ocr_p")
    subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(i), "-l", str(i),
                    "-singlefile", path, base], capture_output=True)
    png = base + ".png"
    if not os.path.exists(png):
        return ""
    env = dict(os.environ)
    td = os.environ.get("LC_TESSDATA")
    if td:
        env["TESSDATA_PREFIX"] = td
    r = subprocess.run(["tesseract", png, "-", "-l", lang, "--psm", os.environ.get("LC_PSM", "6")], capture_output=True, env=env)
    os.remove(png)
    return r.stdout.decode("utf-8", "replace")


GOOD_TOK = re.compile(r"^[(\"'\u201c\u2018\u00ab\[]*([A-Za-z\u00c0-\u00ff][a-z\u00e0-\u00ff'\u2019-]*|[A-Z\u00c0-\u00de][A-Z\u00c0-\u00de'\u2019-]+|\d+([.,]\d+)*(er|e|°)?|[a-z]\)|\(\w{1,4}\))[)\"'\u201d\u2019\u00bb\].,;:!?]*$")


def text_quality(t):
    toks = t.split()
    if len(toks) < 15:
        return 1.0 if len(toks) == 0 else 0.5
    good = sum(1 for x in toks if GOOD_TOK.match(x))
    return good / len(toks)


def pdf_text(path, lang="eng", tmpdir=None, min_chars=200, ocr=False, min_quality=0.7):
    """Return (list_of_page_texts, used_ocr). Cached next to the PDF (<pdf>.text.json)."""
    import json
    cache = path + ".text.json"
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        try:
            pages, used = json.load(open(cache))
            return pages, used
        except ValueError:
            pass
    pages, used = _pdf_text(path, lang, tmpdir, min_chars, ocr, min_quality)
    with open(cache, "w") as f:
        json.dump([pages, used], f)
    return pages, used


def _page_columns(path, i, w, h):
    """If page i is laid out in two columns (almost no word crosses the vertical middle),
    return the text of the left then the right column; else None."""
    r = subprocess.run(["pdftotext", "-bbox", "-f", str(i), "-l", str(i), path, "-"], capture_output=True)
    words = re.findall(rb'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"', r.stdout)
    if len(words) < 80:
        return None
    mid = w / 2.0
    cross = sum(1 for a, b, c, d in words if float(a) < mid - 2 and float(c) > mid + 2)
    left = sum(1 for a, b, c, d in words if float(c) <= mid + 2)
    right = sum(1 for a, b, c, d in words if float(a) >= mid - 2)
    # words spanning the middle are allowed only in full-width headings
    if cross > 0.04 * len(words) or left < 0.2 * len(words) or right < 0.2 * len(words):
        return None
    # full-width header/footer bands: words crossing the middle near the top/bottom of the page
    crossing = [(float(b), float(d)) for a, b, c, d in words if float(a) < mid - 2 and float(c) > mid + 2]
    head = [d for b, d in crossing if b < h * 0.25]
    foot = [b for b, d in crossing if b > h * 0.8]
    top = int(max(head)) + 2 if head else 0
    bottom = int(min(foot)) - 1 if foot else int(h) + 1

    def region(x0, y0, ww, hh):
        if hh <= 0:
            return ""
        return subprocess.run(["pdftotext", "-r", "72", "-f", str(i), "-l", str(i), "-x", str(int(x0)), "-y", str(int(y0)),
                               "-W", str(int(ww)), "-H", str(int(hh)), path, "-"], capture_output=True).stdout.decode("utf-8", "replace")
    out = [region(0, 0, w + 1, top), region(0, top, mid + 1, bottom - top), region(mid, top, mid + 1, bottom - top),
           region(0, bottom, w + 1, h + 1 - bottom)]
    return "\n".join(x.replace("\f", "") for x in out)


def pdf_text_columns(path, lang="fra", tmpdir=None, **kw):
    """Like pdf_text, but splits two-column pages (Journal officiel layout) into columns."""
    import json
    cache = path + ".cols.json"
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        try:
            return tuple(json.load(open(cache)))
        except ValueError:
            pass
    pages, used = pdf_text(path, lang, tmpdir, **kw)
    if not used:
        r = subprocess.run(["pdfinfo", path], capture_output=True).stdout.decode("latin-1")
        m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", r)
        if m:
            w, h = float(m.group(1)), float(m.group(2))
            pages = [(_page_columns(path, i + 1, w, h) or p) for i, p in enumerate(pages)]
    with open(cache, "w") as f:
        json.dump([pages, used], f)
    return pages, used


def _pdf_text(path, lang, tmpdir, min_chars, ocr, min_quality):
    r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True)
    pages = r.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    n = max(1, len(pages))
    total = sum(len(re.sub(r"\s", "", p)) for p in pages)
    bad = [k for k, p in enumerate(pages) if len(re.sub(r"\s", "", p)) < min_chars or text_quality(p) < min_quality]
    if not ocr or (total / n >= min_chars and len(bad) <= max(0, n * 0.1) and not (n <= 3 and bad)):
        return pages, False
    tmpdir = tmpdir or os.path.dirname(path)
    npg = pdf_pages_count(path)
    out = []
    for i in range(1, npg + 1):
        t = pages[i - 1] if i - 1 < len(pages) else ""
        if len(re.sub(r"\s", "", t)) >= min_chars and text_quality(t) >= min_quality:
            out.append(t)
        else:
            o = _ocr_page(path, i, lang, tmpdir)
            out.append(o if text_quality(o) >= text_quality(t) or len(t.strip()) < 20 else t)
    return out, True


# ------------------------------------------------------------------ cleaning
LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}


def norm(s):
    for k, v in LIG.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\xa0", " ").replace("­", "").replace("\t", " ")
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", s)
    return re.sub(r" {2,}", " ", s).strip()


PAGENUM = re.compile(r"^(-\s*)?(page\s*)?[A-Z]?\s?\d{1,4}(\s*-)?$|^\d+\s*/\s*\d+$|^[ivxlc]+$", re.I)


def clean_pages(pages):
    """Normalise, remove page numbers and running headers/footers. Returns list of lines."""
    pl = [[norm(x) for x in p.splitlines()] for p in pages]
    n = len(pl)
    if n >= 4:
        from collections import Counter
        cnt = Counter()
        for p in pl:
            edge = [x for x in p if x][:3] + [x for x in p if x][-3:]
            for x in set(edge):
                key = re.sub(r"\d+", "#", x)
                cnt[key] += 1
        rep = {k for k, c in cnt.items() if c >= max(3, n * 0.4) and len(k) < 120}
    else:
        rep = set()
    out = []
    for p in pl:
        nz = [i for i, x in enumerate(p) if x]
        edges = set(nz[:3] + nz[-3:])
        for i, x in enumerate(p):
            if i in edges and (PAGENUM.match(x) or re.sub(r"\d+", "#", x) in rep):
                continue
            out.append(x)
        out.append("")
    return out


# ------------------------------------------------------------------ structure
EN_LEVELS = [("CHAPTER", r"CHAPTER\s+([IVXLC]+|\d+|[A-Z]+)\b"),
             ("PART", r"PART\s+([IVXLC]+|\d+[A-Z]?|[A-Z]+)\b"),
             ("DIVISION", r"DIVISION\s+([IVXLC]+|\d+)\b")]
EN_SCHED = re.compile(r"^((FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+)?SCHEDULE\b(?!\s+(to|of)\s+the\s+\w+\s+(is|are|shall))", re.I)
FR_LEVELS = [("PARTIE", r"(PREMI[EÈ]RE|DEUXI[EÈ]ME|TROISI[EÈ]ME|QUATRI[EÈ]ME|CINQUI[EÈ]ME|[A-Z]+I[EÈ]ME)\s+PARTIE\b|PARTIE\s+([IVXLC]+|\d+|[A-Z]+)\b"),
             ("LIVRE", r"LIVRE\s+([IVXLC]+|\d+|PR[EÉ]LIMINAIRE|PREMIER|[A-Z]+)\b"),
             ("TITRE", r"TITRE\s+([IVXLC]+|\d+|PR[EÉ]LIMINAIRE|PREMIER|UNIQUE|[A-Z]+)\b"),
             ("CHAPITRE", r"CHAPITRE\s+([IVXLC]+|\d+|PR[EÉ]LIMINAIRE|PREMIER|UNIQUE|[A-Z]+)\b"),
             ("SECTION", r"SECTION\s+([IVXLC]+|\d+|PREMI[EÈ]RE|UNIQUE|[A-Z]+)\b"),
             ("SOUS-SECTION", r"SOUS[- ]SECTION\s+([IVXLC]+|\d+|PREMI[EÈ]RE|UNIQUE)\b"),
             ("PARAGRAPHE", r"PARAGRAPHE\s+([IVXLC]+|\d+|PREMIER|UNIQUE)\b")]
FR_ART = re.compile(r"^(ARTICLE|Article|ART\.|Art\.|Art)\s*(PREMIER|premier|unique|UNIQUE|1er|1 er|\d+(\s?(bis|ter|quater|quinquies|nouveau|\d))?(-\d+)?|[LRD]\.?\s?\d+[\d\-.]*)\b\s*(.*)$")
EN_SEC = re.compile(r"^(\d{1,3}[A-Z]?)\.\s*(.*)$")
NUMWORDS = {"PREMIER": 1, "PREMIERE": 1, "PREMIÈRE": 1, "UNIQUE": 1}


def _title_after(lines, j):
    """Return (title, next_index) if the line after a division heading looks like its title."""
    k = j
    while k < len(lines) and not lines[k]:
        k += 1
    if k < len(lines):
        t = lines[k]
        if 0 < len(t) < 150 and not FR_ART.match(t) and not EN_SEC.match(t) and not re.match(
                r"^(PART|CHAPTER|TITRE|CHAPITRE|SECTION|LIVRE)\b", t, re.I) and not t.endswith((",", ";")):
            return t, k + 1
    return None, j


def _div(line, levels):
    fl = re.I if levels is FR_LEVELS else 0
    for name, pat in levels:
        m = re.match(r"^(" + pat + r")\s*[-–—:.]?\s*(.*)$", line, fl)
        if m:
            if fl and not line[:1].isupper():
                return None
            if fl and len(line) > 120:
                return None
            rest = m.groups()[-1].strip()
            # a heading line is short; avoid cross references ("Part II of this Act shall")
            if len(line) > 160:
                return None
            if rest and (rest[:1].islower() or re.match(r"^(of|to|shall|and|or)\b", rest)):
                return None
            if name in ("SECTION",) and line.lower().startswith("section ") and not line[:7].isupper() and rest[:1].islower():
                return None
            return name, m.group(1).strip(), rest
    return None


def _sec_runs(lines):
    """English sections: find runs of sequential section numbers; return set of line idx in the
    run spanning the most text (the body of the Act)."""
    cands = []
    for i, x in enumerate(lines):
        if x in ("I.", "l.", "1 ."):
            cands.append((i, 1, "1"))
            continue
        m = EN_SEC.match(x)
        if m:
            n = int(re.match(r"\d+", m.group(1)).group(0))
            cands.append((i, n, m.group(1)))
    # MULTI_RUNS: several runs are followed in parallel, so that an inner numbered list ("1.", "2." inside a
    # section) does not cut the run of section numbers in two
    runs = []
    for i, n, lab in cands:
        placed = False
        for cur in runs:
            last = cur[-1][1]
            if n == last + 1 or (n == last and lab != cur[-1][2]) or (last < n <= last + 3 and n != 1):
                cur.append((i, n, lab))
                placed = True
                break
        if not placed and n in (1, 2):
            runs.append([(i, n, lab)])
        if len(runs) > 60:
            runs.sort(key=len, reverse=True)
            del runs[40:]
    if not runs:
        return set()
    best = max(runs, key=lambda r: (r[-1][0] - r[0][0]) * len(r) ** 0.5)
    if len(best) < 2 and len(runs) > 1:
        return set()
    return {i for i, _, _ in best}


def structure(lines, lang="en"):
    """Turn cleaned lines into markdown body lines."""
    levels = FR_LEVELS if lang == "fr" else EN_LEVELS
    secset = _sec_runs(lines) if lang == "en" else set()
    if sum(1 for x in lines if re.match(r"^(Article|Section)\s+\d+[A-Z]?\s*[—–]\s*\S", x)) >= 5:
        secset = set()  # "Section 12—Title." style (Ghana revised editions): numbered lists are tables of contents
    # which division kinds are used
    used = []
    for x in lines:
        d = _div(x, levels)
        if d and d[0] not in used:
            used.append(d[0])
    order = [n for n, _ in levels if n in used]
    lvl = {n: min(2 + k, 5) for k, n in enumerate(order)}
    art_level = min(2 + len(order), 6)
    later_divs = set()
    if secset:
        for k in range(min(secset), len(lines)):
            dd = _div(lines[k], levels)
            if dd:
                later_divs.add((dd[0], dd[1]))
    out = []
    para = []

    def flush():
        if para:
            txt = " ".join(para)
            txt = re.sub(r"^([#>+*-](?=\s|#)|#)", lambda m: "\\" + m.group(0), txt)
            txt = re.sub(r"^(\d+)\.(\s)", r"\1\\.\2", txt)
            txt = re.sub(r"(\w)- (\w)", lambda m: m.group(1) + m.group(2) if m.group(2).islower() else m.group(0), txt)
            out.append(txt)
            out.append("")
            para.clear()

    i = 0
    n = len(lines)
    while i < n:
        x = lines[i]
        if not x:
            flush()
            i += 1
            continue
        d = _div(x, levels)
        if d and secset and i < min(secset) - 8:  # FIRST_SEC_GUARD: table of contents before the body
            d = None
        if d and secset and i < min(secset) and (d[0], d[1]) in later_divs:
            d = None
        if d and (lang == "fr" or x[:4].isupper()):
            flush()
            name, lab, rest = d
            title = rest
            j = i + 1
            if not title:
                t, j = _title_after(lines, i + 1)
                title = t or ""
            lab_txt = lab if lab.isupper() else lab
            out.append("#" * lvl[name] + " " + (lab_txt + (" — " + title if title else "")).strip())
            out.append("")
            i = j
            continue
        if lang == "en" and EN_SCHED.match(x) and len(x) < 100 and x[:3].isupper() and not (secset and i < min(secset)):
            flush()
            top = 2
            out.append("#" * top + " " + x)
            out.append("")
            i += 1
            continue
        if lang == "fr":
            x = re.sub(r"^[|:;.,'‘’_\-–—=•°\s]{1,6}(?=(ARTICLE|Article|ART|Art)\b)", "", x)
            m = FR_ART.match(x)
            if m and (x[:3] in ("ART", "Art")) and not re.match(
                    r"^(de la loi|de l[’']ordonnance|de l[’']acte|du d[ée]cret|de la pr[ée]sente|de la Constitution|des lois|du code|du présent|alinéa|,|et \d|à \d)",
                    (m.group(m.lastindex) or "").strip(), re.I):
                flush()
                lab = m.group(2)
                rest = m.group(m.lastindex).strip() if m.lastindex else ""
                rest = re.sub(r"^[\s.:\-–—°]+", "", rest)
                out.append("#" * art_level + " Article " + lab.replace("1 er", "1er"))
                out.append("")
                if rest:
                    para.append(rest)
                i += 1
                continue
        elif re.match(r"^(Article|Section|Regulation|Rule|Paragraph)\s+(\d+[A-Z]?)\s*[—–]\s*(.{2,200})$", x):
            flush()
            m = re.match(r"^(Article|Section|Regulation|Rule|Paragraph)\s+(\d+[A-Z]?)\s*[—–]\s*(.{2,200})$", x)
            out.append("#" * art_level + " %s %s — %s" % (m.group(1), m.group(2), m.group(3).rstrip(".")))
            out.append("")
            i += 1
            continue
        elif i in secset:
            flush()
            m = EN_SEC.match(x)
            lab = m.group(1) if m else "1"
            j = i + 1  # NEXT_NONEMPTY: the marginal title may follow after blank lines
            while j < n and j <= i + 3 and not lines[j]:
                j += 1
            if m and not m.group(2).strip() and j < n and 2 < len(lines[j]) <= 100 and lines[j][:1].isupper() \
                    and not lines[j].endswith((".", ";", ",", ":")) and not EN_SEC.match(lines[j]) and not _div(lines[j], levels) \
                    and lines[j].count("(") <= lines[j].count(")") and not re.search(  # TITLE_STOP2
                        r"\b(the|of|as|in|this|by|to|and|or|a|an|for|from|with|under|that|which|its)$|\b(is|are|shall|may|be)\b", lines[j]):
                out.append("#" * art_level + " Section " + lab + " — " + lines[j])
                out.append("")
                i = j + 1
                continue
            t2 = (m.group(2) if m else "").strip()
            k2 = i + 1  # NEXT_LOWER: a wrapped sentence continues in lower case on the next line
            while k2 < n and k2 <= i + 3 and not lines[k2]:
                k2 += 1
            wrapped = k2 < n and lines[k2][:1].islower()
            wrapped = wrapped or t2.count("(") > t2.count(")") or bool(re.search(  # TITLE_STOP
                r"\b(the|of|as|in|this|by|to|and|or|a|an|for|from|with|under|that|which|its)$|\b(is|are|shall|may|be)\b", t2))
            if not wrapped and t2 and len(t2) <= 120 and t2[:1].isupper() and not t2.endswith((".", ";", ",", ":", "-", "—", "–")) \
                    and " shall " not in t2:  # SAME_LINE_TITLE: "12. Marginal title"
                out.append("#" * art_level + " Section " + lab + " — " + t2)
                out.append("")
            else:
                out.append("#" * art_level + " Section " + lab)
                out.append("")
                if t2:
                    para.append(t2)
            i += 1
            continue
        # paragraph breaks before enumerations
        if para and re.match(r"^(\(\w{1,5}\)|[a-z]\)|\d+[°º]|[-–•]\s)", x):
            flush()
        para.append(x)
        i += 1
    flush()
    # collapse blank lines
    res = []
    for x in out:
        if x == "" and res and res[-1] == "":
            continue
        res.append(x)
    return res


def yaml_str(s):
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return '"' + s + '"'


def front_matter(meta):
    lines = ["---"]
    for k, v in meta.items():
        if v is None or v == "":
            continue
        if k in ("title", "identifier", "source", "archived_source", "note", "gazette") or isinstance(v, str) and not re.match(r"^\d{4}-\d{2}-\d{2}$|^[a-z_]+$", v):
            lines.append("%s: %s" % (k, yaml_str(str(v))))
        else:
            lines.append("%s: %s" % (k, v))
    lines.append("---")
    return "\n".join(lines)


def slug(s, maxlen=90):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    if len(s) > maxlen:
        s = s[:maxlen].rsplit("-", 1)[0]
    return s or "untitled"


def write_md(path, meta, title, body_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    txt = front_matter(meta) + "\n\n# " + title + "\n\n" + "\n".join(body_lines).strip() + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)


def doc_text(path):
    """Word documents (.doc/.docx/.rtf) -> text via macOS textutil (pages = [text])."""
    r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path], capture_output=True)
    return [r.stdout.decode("utf-8", "replace")] if r.returncode == 0 else []


def sniff(path):
    with open(path, "rb") as f:
        h = f.read(8)
    if h.startswith(b"%PDF"):
        return "pdf"
    if h.startswith(b"PK"):
        return "docx"
    if h.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"
    if h.startswith(b"{\\rtf"):
        return "rtf"
    return "other"


def doc_or_pdf_text(path, lang="eng", tmpdir=None):
    k = sniff(path)
    if k == "pdf":
        return pdf_text(path, lang, tmpdir)
    if k in ("docx", "doc", "rtf"):
        ext = {"docx": ".docx", "doc": ".doc", "rtf": ".rtf"}[k]
        tmp = path + ext
        if not os.path.exists(tmp):
            os.link(path, tmp)
        return doc_text(tmp), False
    return [], False
