"""EDINET のテキストブロック(HTML断片)を、素のテキストに落とすだけの簡易変換。

見出し・段落・表を最低限それらしく整形する。完全な Markdown 化は目的にしない。
"""
from __future__ import annotations

from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "table"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.parts.append("\t")
            self._in_cell = True
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_cell:
            text = data.strip()
            if text:
                self.parts.append(text)
            return
        # 有報のプレーンテキストは全角スペース (U+3000) で段落を区切る慣習がある。
        # HTML 断片にタグが無いケースが多いので、ここで段落 = 空行 に変換しておく。
        text = data.replace("　", "\n\n").strip()
        if text:
            self.parts.append(text + " ")


def html_to_text(html: str) -> str:
    parser = _Extractor()
    parser.feed(html or "")
    raw = "".join(parser.parts)

    lines = [ln.rstrip() for ln in raw.splitlines()]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(ln.strip())
    return "\n".join(out).strip() + "\n"
