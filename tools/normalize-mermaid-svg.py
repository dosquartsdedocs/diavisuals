#!/usr/bin/env python3
"""Normalize Mermaid SVG text for renderers that trim tspan whitespace."""

from __future__ import annotations

import re
import sys
from pathlib import Path


LEADING_TSPAN_SPACE_RE = re.compile(
    r"<tspan\b(?P<attributes>[^>]*)>(?P<spaces>[ \u00a0]+)"
)
XML_SPACE_RE = re.compile(r"\bxml:space\s*=")


def preserve_tspan_space(match: re.Match[str]) -> str:
    attributes = match.group("attributes")
    if not XML_SPACE_RE.search(attributes):
        attributes += ' xml:space="preserve"'
    spaces = match.group("spaces").replace("\u00a0", " ")
    return f"<tspan{attributes}>{spaces}"


def normalize(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    normalized = LEADING_TSPAN_SPACE_RE.sub(preserve_tspan_space, source)
    path.write_text(normalized, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: normalize-mermaid-svg.py <svg>")
    normalize(Path(sys.argv[1]))
