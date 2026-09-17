from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".venv", "node_modules", "dist"}
LINE_LIMIT_EXEMPT = {".json", ".jsonl", ".md", ".docx", ".csv"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


def check_trailing_whitespace(path: Path, lines: list[str]) -> list[str]:
    errors = []
    for index, line in enumerate(lines, 1):
        body = line.removesuffix("\n")
        if body.rstrip(" \t") != body:
            errors.append(f"{path}:{index}: trailing whitespace")
    return errors


def check_line_count(path: Path, lines: list[str]) -> list[str]:
    if path.suffix.lower() in LINE_LIMIT_EXEMPT:
        return []
    if len(lines) <= 250:
        return []
    return [f"{path}: file has {len(lines)} lines; limit is 250"]


def check_internal_double_spaces(path: Path, lines: list[str]) -> list[str]:
    if path.suffix.lower() not in {".py", ".ts", ".tsx", ".sql"}:
        return []
    errors = []
    marker = " " * 2
    for index, line in enumerate(lines, 1):
        stripped = line.lstrip(" ")
        if marker in stripped.rstrip("\n"):
            errors.append(f"{path}:{index}: double spaces inside code text")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in iter_files():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        errors.extend(check_trailing_whitespace(path, lines))
        errors.extend(check_line_count(path, lines))
        errors.extend(check_internal_double_spaces(path, lines))
    if errors:
        print("\n".join(errors))
        return 1
    print("quality checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
