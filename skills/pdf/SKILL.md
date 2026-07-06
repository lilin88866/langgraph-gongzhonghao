---
name: pdf
description: Parse textbook PDFs, scanned pages, OCR text, tables, and math formulas for K12 video generation. Use when working with ChinaTextbook PDFs, PDF page extraction, scanned textbook OCR, formula recognition, MinerU, PaddleOCR, or LaTeX-OCR.
---

# PDF Textbook Parsing

## Purpose

Use this skill when the video agent needs reliable content from textbook PDFs:

1. Locate the exact PDF and page.
2. Extract the original example problem from the selected textbook page.
3. Preserve source metadata for the result page.
4. OCR scanned pages when text extraction is incomplete.
5. Convert formula images to LaTeX when formulas are not readable from PDF text.

For `/workflow/video/agent`, this skill is required before rendering: use it to obtain textbook content, source metadata, the complete original example problem, and solution evidence.

## Local Repositories

The upstream repositories are vendored under `skills/pdf/repos/`:

- `repos/MinerU`: document parsing engine for PDF/image to structured Markdown or JSON.
- `repos/PaddleOCR`: OCR and document structure toolkit for scanned pages, Chinese text, tables, and layout.
- `repos/LaTeX-OCR`: `pix2tex` formula image recognition for converting formula screenshots to LaTeX.

See `TOOLS.md` for the role of each tool and installation notes.

## Default Workflow

1. Try native PDF text extraction first with the existing project script:
   `scripts/textbook_pdf_search.py`.
2. If the selected page has broken ordering, missing formulas, or no text, use MinerU to parse the PDF/page into Markdown or JSON.
3. If MinerU output still misses Chinese text from scanned pages, use PaddleOCR for OCR.
4. If a formula is only available as an image, crop the formula area and use LaTeX-OCR to convert it to LaTeX.
5. Always produce the video result source in this format:

```text
仓库：https://github.com/TapXWorld/ChinaTextbook
PDF：<relative pdf path>
页码：PDF 第 <n> 页，教材页码第 <m> 页
依据：<one-line textbook evidence summary>
```

## Review Rules

- Never invent a textbook problem when the user asks for an original example.
- If OCR is used, mark the result for human review.
- Keep the full original problem separate from the explanation process.
- Do not put backend tool logs, OCR confidence dumps, or rendering warnings in the user-facing result page.
