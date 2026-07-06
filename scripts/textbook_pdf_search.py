"""Search downloaded ChinaTextbook PDFs for textbook examples."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEXTBOOK_DIR = ROOT_DIR / "external" / "ChinaTextbook"


@dataclass
class PdfHit:
    source: str
    page: int
    textbook_page: int | None
    score: int
    excerpt: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Search ChinaTextbook PDFs.")
    parser.add_argument("query", nargs="+", help="Search words, for example: 圆锥摆 例题")
    parser.add_argument("--root", type=Path, default=DEFAULT_TEXTBOOK_DIR)
    parser.add_argument("--glob", default="高中/物理/人教版-人民教育出版社/*.pdf")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    hits = search_pdfs(args.root, args.glob, args.query, args.limit)
    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
        return

    if not hits:
        print("No PDF text hits found.")
        return

    for hit in hits:
        print(f"## {hit.source} · PDF page {hit.page} · score {hit.score}")
        print(hit.excerpt)
        print()


def search_pdfs(root: Path, glob_pattern: str, query_words: list[str], limit: int = 8) -> list[PdfHit]:
    query_words = [word.strip() for word in query_words if word.strip()]
    if not query_words:
        return []

    hits: list[PdfHit] = []
    for pdf_path in sorted(root.glob(glob_pattern)):
        hits.extend(_search_pdf(root, pdf_path, query_words))
    return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


def _search_pdf(root: Path, pdf_path: Path, query_words: list[str]) -> list[PdfHit]:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        print(f"skip {pdf_path}: {exc}", file=sys.stderr)
        return []

    hits: list[PdfHit] = []
    page_texts: list[str] = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")
    for page_index, text in enumerate(page_texts, start=1):
        normalized = _normalize_text(text)
        score = _score(normalized, query_words)
        if score <= 0:
            continue
        next_page = _normalize_text(page_texts[page_index]) if page_index < len(page_texts) else ""
        combined = _normalize_text(f"{normalized}\n{next_page}") if next_page else normalized
        hits.append(
            PdfHit(
                source=str(pdf_path.relative_to(root)),
                page=page_index,
                textbook_page=_textbook_page_from_text(normalized),
                score=score,
                excerpt=_example_block_excerpt(combined, query_words),
            )
        )
    return hits


def _score(text: str, query_words: list[str]) -> int:
    score = 0
    for word in query_words:
        score += text.count(word) * max(2, len(word))
    if _has_real_example_marker(text):
        score += 25
    elif "例题" in text:
        score += 3
    if any(marker in text for marker in ("分析", "解 ", "解\n", "分析与解答")) and _has_real_example_marker(text):
        score += 8
    if re.search(r"(上述例题|例题中|例题的|本章第\s*\d+\s*节\s*例题)", text):
        score -= 12
    if "圆周运动" in text:
        score += 2
    return score


def _excerpt(text: str, query_words: list[str], radius: int = 360) -> str:
    example_position = _real_example_marker_position(text)
    positions = [example_position] if example_position >= 0 else []
    positions.extend(text.find(word) for word in query_words if text.find(word) >= 0)
    start = max(0, min(positions) - radius) if positions else 0
    end = min(len(text), start + radius * 2)
    return text[start:end].strip()


def _example_block_excerpt(text: str, query_words: list[str], limit: int = 8000) -> str:
    """Return a complete textbook example block, not a tiny keyword window."""
    start = _example_block_start(text, query_words)
    block = text[start:]
    end = _example_block_end(block)
    if end > 0:
        block = block[:end]
    block = block.strip()
    if len(block) < 240:
        block = _excerpt(text, query_words, radius=900)
    return block[:limit].strip()


def _example_block_start(text: str, query_words: list[str]) -> int:
    marker = _real_example_marker_position(text)
    if marker >= 0:
        return marker
    positions = [text.find(word) for word in query_words if text.find(word) >= 0]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return 0
    position = min(positions)
    line_start = text.rfind("\n", 0, position)
    sentence_start = max(text.rfind("。", 0, position), text.rfind("？", 0, position), text.rfind("！", 0, position))
    return max(line_start, sentence_start, 0)


def _example_block_end(block: str) -> int:
    boundary_patterns = [
        r"\n\s*【例题(?:\s*\d+)?】",
        r"\n\s*例题(?:\s*\d+)?\s*(?:\n|$)",
        r"\n\s*(?:练习与应用|复习与提高|本章小结|习题|课后练习|思考与讨论|科学漫步|做一做)\b",
        r"\n\s*第[一二三四五六七八九十\d]+节\b",
        r"\n\s*\d+\.\d+\s+[\u4e00-\u9fff]",
        r"\n\s*\d+[\.．]\s+[\u4e00-\u9fff]",
        r"\n\s*\d+\s*\n\s*高中[\u4e00-\u9fff]+",
    ]
    starts: list[int] = []
    for pattern in boundary_patterns:
        for match in re.finditer(pattern, block):
            if match.start() > 160:
                starts.append(match.start())
    return min(starts) if starts else -1


def _has_real_example_marker(text: str) -> bool:
    return _real_example_marker_position(text) >= 0


def _real_example_marker_position(text: str) -> int:
    patterns = [
        r"【\s*例题\s*\d*\s*】",
        r"(?:^|\n)\s*例题\s*\d*\s*(?:\n|$)",
    ]
    positions = [match.start() for pattern in patterns for match in re.finditer(pattern, text)]
    return min(positions) if positions else -1


def _normalize_text(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _textbook_page_from_text(text: str) -> int | None:
    for raw_line in text.splitlines()[:8]:
        line = raw_line.strip()
        if not re.fullmatch(r"\d{1,3}", line):
            continue
        page = int(line)
        if page > 0:
            return page
    return None


if __name__ == "__main__":
    main()
