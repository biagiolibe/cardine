"""Bridge generated command names and templates until the template rename."""

import re


def normalize_program_word(text: str) -> str:
    # MERIDIAN-TEMPLATE-PROGRAM: remove in 5b
    return re.sub(r'(?<![\w/.-])meridian(?=\s|["\'])', "cardine", text)
