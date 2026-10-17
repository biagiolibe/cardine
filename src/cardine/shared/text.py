"""Shared text bindings extracted from the legacy CLI."""

from __future__ import annotations

import re


def read_task_field(text: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


HEADING_LINE = re.compile(r"^(#{1,6})[ \t]+(.*)$", re.MULTILINE)


def extract_heading_block(text: str, matches_title) -> tuple[str, str] | None:
    """Return `(excerpt, heading title)` for the first heading satisfying
    `matches_title(title)`, bounded by the next heading at the same or a
    shallower level, or EOF. Shared by ADR-log, spec, and task-Authority
    lookups so heading-range extraction is written exactly once.
    """
    headings = [
        (match.start(), len(match.group(1)), match.group(2).strip())
        for match in HEADING_LINE.finditer(text)
    ]
    for index, (start, level, title) in enumerate(headings):
        if not matches_title(title):
            continue
        end = len(text)
        for later_start, later_level, _ in headings[index + 1:]:
            if later_level <= level:
                end = later_start
                break
        return text[start:end].rstrip("\n") + "\n", title
    return None
