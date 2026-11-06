#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".venv", "data", "__pycache__", ".pytest_cache", ".git"}
EXCLUDED_FILES = {
    Path("docs/notes/WRITING_GUIDE.md"),
    Path("scripts/style_check.py"),
}

EM_DASH = "\u2014"
EN_DASH = "\u2013"
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF]"
)

BANNED_PHRASES = [
    "in today's fast-paced world",
    "in an era where",
    "it is important to note",
    "it is worth noting",
    "needless to say",
    "at the end of the day",
    "when it comes to",
    "the future of",
    "more than just a",
    "not just",
    "this isn't about",
    "a testament to",
    "whether you're a",
    "let's dive in",
    "dive into",
    "embark on a journey",
    "navigate the landscape",
    "unlock the power",
    "elevate",
    "empower",
    "foster",
    "leverage",
    "delve",
    "seamless",
    "robust",
    "cutting edge",
    "revolutionary",
    "transformative",
    "game changer",
    "holistic",
    "synergy",
    "comprehensive",
    "meticulous",
    "pivotal",
    "crucial",
    "vital role",
    "underscore",
    "showcase",
    "myriad",
    "plethora",
    "tapestry",
    "realm",
    "in conclusion",
    "to sum up",
    "imagine a world where",
]


def text_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        if relative in EXCLUDED_FILES:
            continue
        if path.suffix.lower() not in {".md", ".py", ".tf", ".yml", ".yaml", ".txt", ".html", ".css", ".js"}:
            continue
        paths.append(path)
    return sorted(paths)


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return problems

    for number, line in enumerate(text.splitlines(), start=1):
        if EM_DASH in line:
            problems.append(f"{path.relative_to(ROOT)}:{number}: em dash found")
        if EN_DASH in line:
            problems.append(f"{path.relative_to(ROOT)}:{number}: en dash found")
        if EMOJI_RE.search(line):
            problems.append(f"{path.relative_to(ROOT)}:{number}: emoji or symbol found")
        if path.suffix.lower() == ".md":
            lowered = line.lower()
            for phrase in BANNED_PHRASES:
                if phrase in lowered:
                    problems.append(f"{path.relative_to(ROOT)}:{number}: banned phrase: {phrase}")
    return problems


def main() -> int:
    paths = text_files()
    problems: list[str] = []
    for path in paths:
        problems.extend(check_file(path))

    if problems:
        for problem in problems:
            print(problem)
        print(f"\n{len(problems)} style issue(s) in {len(paths)} files")
        return 1

    print(f"Style check passed: {len(paths)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
