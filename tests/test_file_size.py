from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("src", "tests", "scripts", "frontend/src")
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".css"}
MAX_LINES = 250


def test_maintained_code_files_stay_under_line_limit():
    violations = []
    for relative_root in SOURCE_ROOTS:
        for path in (ROOT / relative_root).rglob("*"):
            if path.is_file() and path.suffix in CODE_SUFFIXES:
                line_count = len(path.read_text(encoding="utf-8").splitlines())
                if line_count > MAX_LINES:
                    violations.append(f"{path.relative_to(ROOT)}: {line_count} lines")

    assert not violations, "Files exceed the 250-line limit:\n" + "\n".join(violations)
