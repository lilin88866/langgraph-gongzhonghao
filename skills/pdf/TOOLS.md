# PDF Tool References

## MinerU

Repository: `repos/MinerU`

Use for:

- PDF or image to structured Markdown / JSON.
- Reading-order recovery for complex textbook pages.
- Layout-aware extraction where native `pypdf` text order is poor.
- Formula/table extraction when the PDF page contains mixed content.

Prefer MinerU before raw OCR when the PDF has a real document layout.

## PaddleOCR

Repository: `repos/PaddleOCR`

Use for:

- Scanned textbook pages.
- Chinese OCR when PDF text extraction is empty or garbled.
- Page layout, table, seal, or scene text recognition.
- Producing OCR text for downstream example-problem extraction.

Use PaddleOCR when the input behaves like an image rather than a text PDF.

## LaTeX-OCR

Repository: `repos/LaTeX-OCR`

Use for:

- Formula screenshots or cropped formula images.
- Converting math formula images to LaTeX.
- Recovering formulas that are missing or badly ordered in PDF text/OCR output.

Typical Python usage from the upstream README:

```python
from PIL import Image
from pix2tex.cli import LatexOCR

img = Image.open("formula.png")
model = LatexOCR()
print(model(img))
```

## Integration Guidance

For `langgraph-study` video generation, the parser should return structured data:

```json
{
  "repository": "https://github.com/TapXWorld/ChinaTextbook",
  "pdf": "高中/物理/人教版-人民教育出版社/普通高中教科书·物理必修 第二册.pdf",
  "pdf_page": 37,
  "textbook_page": 32,
  "basis": "第六章“向心力”中的圆锥摆例题...",
  "question": "如图6.3-3所示...",
  "solution_basis": "分析...解..."
}
```

The result page must show `仓库 / PDF / 页码 / 依据` and then the complete original problem and solution process.
