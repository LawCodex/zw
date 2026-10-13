# Zimbabwe (ZW) — legislation as Markdown

Part of [LawCodex](https://github.com/LawCodex): the legislation of every country as plain Markdown in git.

Legislation of Zimbabwe, in **English**, from **Veritas Zimbabwe** (https://www.veritaszim.net), the
non-governmental legal-information trust that has published Zimbabwean legislation online for two decades:
the **Constitution of Zimbabwe (2013) consolidated to 28 July 2026**, earlier constitutional texts, the
Constitution's official translations into 13 other official languages, and the ~360 Acts listed in Veritas's
"Acts" section (principal Acts — many in several successive consolidated versions —, amendment Acts, Finance and
Appropriation Acts, and a few statutory instruments). Veritas is a reputable **non-official** source; the official
sites (Parliament of Zimbabwe, government portals) were unreachable. Retrieved 2026-10-13.

| Category | Files |
|---|---|
| Constitution: 2013 consolidated (current), 2013 as adopted (Amendment No. 20 Act), 1979 Constitution as amended to 2009, Amendment Acts No. 13, 18, 19 | 6 |
| Constitution 2013 — translations (Chewa, Kalanga, Koisan, Nambya, Ndau, Ndebele, Shangani, Shona, Sotho, Tonga, Tswana, Venda, Xhosa) | 13 |
| Acts (344 of them carry a `[Chapter x:yy]` number) | 355 |
| Statutory instruments / notices listed among Acts | 8 |
| **Total** | **382** |

## Structure

```
constitution/constitution-of-zimbabwe-2013-consolidated.md   current text (as amended up to 28 July 2026)
constitution/...                                             historical texts and amendment Acts
constitution/translations/constitution-2013-<language>.md    official translations (language: ISO 639 code)
acts/<slug>.md                                               one file per Veritas document (version in the title)
```

An Act may appear several times, once per consolidated version published by Veritas (e.g. "Access to Information &
Protection of Privacy Act [Chapter 10:27], 2003-10"); the date or "amended …" in the title identifies the version.
Front matter: `identifier` (`Chapter 10:27`), `type` (`constitution`/`act`/`statutory_instrument`), `year` (from
the title), `status` (`unknown` except for the current/historical Constitution), `source` (Veritas page), `file`
(the Word or PDF file converted), `summary` (Veritas's description).

Word documents (.doc/.docx) were converted with macOS `textutil` and `pandoc`; PDFs with poppler `pdftotext`.
PART / CHAPTER become headings and sections `Section N — <title>`. The Veritas cover notice ("Distributed by
Veritas…") at the top of each document is kept.

## Not covered / known gaps

* Not every Act of Zimbabwe: only those in Veritas's "Acts" section (no Acts database of the Parliament or the
  Government Printer was reachable). Statutory instruments in general (Veritas "Statutory Instruments" section) are
  not included.
* Skipped: Veritas lists of Acts per year, Bills and amendments to Bills, drafts (Kariba Draft, departmental
  drafts, the 2013 draft Constitution), court papers, an extract, intermediate consolidations of the Constitution
  (2018, 2021, 2023, 1979-text versions before 2009) and 6 PDFs without a usable text layer (e.g. Securities
  Amendment Act 2013, Microfinance Act 2013, several Appropriation Acts).
* The ZimLII (Zimbabwe Legal Information Institute) site forbids scraping/bulk download and was not used.

## Sources and licence

| Source | URL |
|---|---|
| Veritas Zimbabwe — Acts | https://www.veritaszim.net/acts |
| Veritas Zimbabwe — Constitution | https://www.veritaszim.net/constitution |

**Licence: the Veritas website content is licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0
International (CC BY-NC-SA 4.0)**, http://creativecommons.org/licenses/by-nc-sa/4.0/. The Markdown texts in this
repository derived from it are therefore distributed under the same licence, with attribution to Veritas
Zimbabwe (www.veritaszim.net); non-commercial use only. The robots.txt `Crawl-delay: 10` was obeyed (one request
every 10 seconds) with an identifying User-Agent.

## Regenerate

```
pip install -r scripts/requirements.txt     # plus pandoc, macOS textutil and poppler on PATH
python scripts/zw_fetch.py                  # downloads into ../_raw/zw/ (≈ 2.5 h because of Crawl-delay: 10)
python scripts/zw_convert.py .
```
