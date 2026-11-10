"""Texts in several languages, for the card and for the reasons the integration computes.

Pure Python, no Home Assistant imports. A language file is a flat JSON object:
    {"_language": "cs", "_name": "Čeština", "reason.heat": "{room} < {target} − {hysteresis} → topit", ...}
Placeholders are {name}. A value can also be an object of plural forms for the card
({"one": ..., "few": ..., "many": ..., "other": ...}, chosen with the language's plural rules).
Keys starting with "_" are metadata. A missing key falls back to English.
"""
from __future__ import annotations

import json
from pathlib import Path

LANG_DIR = Path(__file__).parent / "lang"
BUILTIN = ("en", "cs")
PLURAL_FORMS = ("zero", "one", "two", "few", "many", "other")
MAX_TEXT = 500
MISSING = object()  # "argument not given", where None means "remove"


def load_builtin() -> dict[str, dict]:
    """Reads the language files. Blocking: run it in the executor."""
    return {code: json.loads((LANG_DIR / f"{code}.json").read_text(encoding="utf-8")) for code in BUILTIN}


def _text(value) -> str:
    if isinstance(value, dict):
        return value.get("other") or next(iter(value.values()), "")
    return value


class Translator:
    def __init__(self, strings: dict, english: dict) -> None:
        self.strings = strings
        self.english = english

    def __call__(self, key: str, **params) -> str:
        for source in (self.strings, self.english):
            if key in source:
                try:
                    return _text(source[key]).format(**params)
                except (KeyError, IndexError, ValueError):
                    continue  # a broken placeholder in a translation: use English instead
        return key


def check_custom(data, english: dict) -> tuple[dict, dict]:
    """Validate an uploaded translation. Returns (clean copy, report) or raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("the translation must be a JSON object of \"key\": \"text\"")
    clean: dict = {}
    unknown: list[str] = []
    for key, value in data.items():
        if not isinstance(key, str):
            raise ValueError("keys must be strings")
        if key.startswith("_"):
            if key in ("_language", "_name") and isinstance(value, str) and len(value) <= 40:
                clean[key] = value
            continue
        if key not in english:
            unknown.append(key)
            continue
        if isinstance(value, str):
            ok = len(value) <= MAX_TEXT
        elif isinstance(value, dict):
            ok = bool(value) and all(k in PLURAL_FORMS and isinstance(v, str) and len(v) <= MAX_TEXT
                                     for k, v in value.items())
        else:
            ok = False
        if not ok:
            raise ValueError(f"{key}: the text must be a string (or plural forms) of at most {MAX_TEXT} characters")
        clean[key] = value
    if not any(not k.startswith("_") for k in clean):
        raise ValueError("no known keys; start from the exported English file")
    missing = sorted(k for k in english if not k.startswith("_") and k not in clean)
    return clean, {"unknown": sorted(unknown), "missing": missing}
