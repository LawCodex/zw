"""Word document (.docx, or .doc/.rtf converted with macOS textutil) -> Markdown body, using pandoc
(GitHub-flavoured Markdown), then light structuring for statutes:

* images are dropped (text only);
* in the body of the Act (from the first section "**1.**" backwards over its heading lines),
  PART / CHAPTER / DIVISION / SCHEDULE lines become headings;
* a section "**12.** text" becomes a heading "Section 12 — <bold marginal title>" when the title
  is the preceding bold-only paragraph (South African / Namibian / Zimbabwean drafting style),
  else "Section 12".
"""
import os
import re
import subprocess


def to_docx(path):
    """.doc/.rtf -> .docx next to it (textutil). Returns the .docx path."""
    if path.lower().endswith(".docx"):
        return path
    out = os.path.splitext(path)[0] + ".conv.docx"
    if not os.path.exists(out):
        subprocess.run(["textutil", "-convert", "docx", "-output", out, path], capture_output=True)
    return out if os.path.exists(out) else None


def pandoc_md(path):
    r = subprocess.run(["pandoc", "-f", "docx", "-t", "gfm", "--wrap=none", path], capture_output=True, timeout=600)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


DIV = re.compile(r"^(PART|CHAPTER|DIVISION|SUB-?PART|TITLE)\s+([IVXLC]+[A-Z]?|\d+[A-Z]?|[A-Z])\b\.?\s*[-–—:]?\s*(.*)$", re.I)
SCHED = re.compile(r"^((FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ELEVENTH|TWELFTH)\s+)?SCHEDULE\b.{0,80}$|^ANNEX(URE)?\b.{0,60}$", re.I)
SEC = re.compile(r"^\*\*(\d{1,3}[A-Z]{0,2})\.\*\*\s*(.*)$")
SEC2 = re.compile(r"^\*\*(\d{1,3}[A-Z]{0,2})\.?\s+([^*]{2,200})\*\*\s*$")  # "**1. Short title**" (Zimbabwe style)
ART = re.compile(r"^\*\*(Article|Rule|Regulation)\s+(\d{1,3}[A-Z]{0,2})\.?\s*(.{0,250}?)\*\*\s*$")
SEC4 = re.compile(r"^(\d{1,3}[A-Z]{0,2})\.?\s+\*\*([^*]{2,200})\*\*\s*$")  # "1 **Short title**"
SEC5 = re.compile(r"^(\d{1,3}[A-Z]{0,2})\.?\s+([A-Z][^.;:]{1,150})$")  # "1 Short title" (plain paragraph)
BOLD = re.compile(r"^\*\*([^*]{2,200})\*\*$")


def strip_md(s):
    return re.sub(r"[*_`\\]", "", s).strip()


def is_div(p):
    t = strip_md(p)
    if len(t) > 160:
        return None
    m = DIV.match(t)
    if m and t[:2].isupper():
        return m
    return None


def structure(md):
    paras = [p.strip() for p in re.split(r"\n\s*\n", md)]
    paras = [re.sub(r"!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?|<img [^>]*>", "", p).strip() for p in paras]
    paras = [p for p in paras if p and p != "\\"]
    # Veritas documents put section headings in block quotes, sometimes with a hard line break inside the bold:
    # "> **\\\n> 1 Short title**" -> "**1 Short title**"
    def _norm(p):
        q = re.sub(r"(?m)^>\s?", "", p)
        q = re.sub(r"\\\n", " ", q)
        q = re.sub(r"\*\*\s+", "**", q, count=1)
        return q.strip()
    paras = [_norm(p) if re.match(r"^>\s*\*\*", p) else p for p in paras]
    first = next((i for i, p in enumerate(paras) if SEC.match(p) and SEC.match(p).group(1) in ("1", "1A")), None)
    if first is None:
        first = next((i for i, p in enumerate(paras) if SEC2.match(p) and SEC2.match(p).group(1) == "1"), None)
    if first is None:
        first = next((i for i, p in enumerate(paras) if ART.match(p) and ART.match(p).group(2) == "1"), None)
    if first is None:
        first = next((i for i, p in enumerate(paras) if SEC.match(p) or ART.match(p)), None)
    start = first if first is not None else len(paras)
    while True:
        if start > 1 and is_div(paras[start - 2]) and len(strip_md(paras[start - 1])) < 100 and not is_div(paras[start - 1]):
            start -= 2
        elif start > 0 and (is_div(paras[start - 1]) or BOLD.match(paras[start - 1]) or len(strip_md(paras[start - 1])) < 80 and strip_md(paras[start - 1]).isupper()):
            start -= 1
        else:
            break
    # plain "N Title" / "N **Title**" headings: keep the longest increasing chain of numbers starting at 1
    cand = []
    for i, p in enumerate(paras):
        m = SEC4.match(p) or SEC5.match(p)
        if m:
            cand.append((i, int(re.match(r"\d+", m.group(1)).group(0)), m))
    chains = []
    for i, n, m in cand:
        for ch in chains:
            if ch[-1][1] < n <= ch[-1][1] + 3 or (n == ch[-1][1] and m.group(1) != ch[-1][2].group(1)):
                ch.append((i, n, m))
                break
        else:
            if n == 1:
                chains.append([(i, n, m)])
    best = max(chains, key=len) if chains else []
    bold = any(SEC4.match(paras[i]) for i, _, _ in best)
    plain = {i: m for i, n, m in best} if len(best) >= 3 or (bold and len(best) >= 1) else {}
    if plain and first is None or plain and min(plain) < start:
        start = min(plain)
        while start > 0 and (is_div(paras[start - 1]) or len(strip_md(paras[start - 1])) < 80 and strip_md(paras[start - 1]).isupper()):
            start -= 1
    divs = []
    for p in paras[start:]:
        m = is_div(p)
        if m and m.group(1).upper() not in divs:
            divs.append(m.group(1).upper())
    lvl = {d: min(2 + k, 5) for k, d in enumerate(divs)}
    sec_lvl = min(2 + len(divs), 6)
    out = []
    i = 0
    n = len(paras)
    pending_title = None
    while i < n:
        p = paras[i]
        if i < start:
            out.append(p)
            i += 1
            continue
        m = is_div(p)
        if m:
            kind, lab, rest = m.group(1).upper(), m.group(2), m.group(3).strip()
            if not rest and i + 1 < n and not SEC.match(paras[i + 1]) and not SEC2.match(paras[i + 1]) and not is_div(paras[i + 1]) \
                    and len(strip_md(paras[i + 1])) < 150 and not (i + 2 < n and SEC.match(paras[i + 2]) and BOLD.match(paras[i + 1])):
                rest = strip_md(paras[i + 1])
                i += 1
            out.append("\x00" + "#" * lvl[kind] + " " + kind.title() + " " + lab + (" — " + rest if rest else ""))
            i += 1
            continue
        if SCHED.match(strip_md(p)) and strip_md(p)[:3].isupper():
            out.append("\x00## " + strip_md(p))
            i += 1
            continue
        if i in plain:
            pm = plain[i]
            out.append("\x00" + "#" * sec_lvl + " Section " + pm.group(1) + " — " + strip_md(pm.group(2)).rstrip("."))
            i += 1
            continue
        b = BOLD.match(p)
        if b and i + 1 < n and SEC.match(paras[i + 1]):
            pending_title = strip_md(b.group(1)).rstrip(".")
            i += 1
            continue
        s = SEC.match(p)
        if s:
            out.append("\x00" + "#" * sec_lvl + " Section " + s.group(1) + (" — " + pending_title if pending_title else ""))
            if s.group(2).strip():
                out.append(s.group(2).strip())
            pending_title = None
            i += 1
            continue
        a = ART.match(p)
        if a:
            t = strip_md(a.group(3)).rstrip(".")
            out.append("\x00" + "#" * sec_lvl + " " + a.group(1) + " " + a.group(2) + (" — " + t if t else ""))
            i += 1
            continue
        s = SEC2.match(p)
        if s:
            out.append("\x00" + "#" * sec_lvl + " Section " + s.group(1) + " — " + strip_md(s.group(2)).rstrip("."))
            i += 1
            continue
        out.append(p)
        i += 1
    # escape stray leading '#' in text paragraphs
    res = []
    for p in out:
        if p.startswith("\x00"):
            res.append(p[1:])
        elif p.startswith("#"):
            res.append("\\" + p)
        else:
            res.append(p)
    return "\n\n".join(res)


def docx_markdown(path):
    d = to_docx(path)
    if not d:
        return None
    md = pandoc_md(d)
    if md is None:
        return None
    return structure(md)
