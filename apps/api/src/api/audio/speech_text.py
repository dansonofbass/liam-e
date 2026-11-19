"""Project safe CommonMark into spoken text without rendering HTML."""

import re

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark")
_URL = re.compile(r"(?:https?://|mailto:)[^\s<>()]+", re.IGNORECASE)


def speech_text(source: str) -> str:
    blocks = []
    for token in _MARKDOWN.parse(source):
        if token.type == "inline":
            parts = []
            for child in token.children or []:
                if child.type in {"text", "code_inline"}:
                    parts.append(child.content)
                elif child.type in {"softbreak", "hardbreak"}:
                    parts.append(" ")
            blocks.append("".join(parts))
        elif token.type in {"fence", "code_block"}:
            blocks.append(token.content)
    return " ".join(_URL.sub("", " ".join(blocks)).split())
