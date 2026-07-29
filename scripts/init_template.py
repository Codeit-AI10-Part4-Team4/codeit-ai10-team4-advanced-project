#!/usr/bin/env python3
"""템플릿 초기화 스크립트 — 새 프로젝트 이름으로 일괄 치환 후 스스로를 삭제한다.

Usage:
    python scripts/init_template.py --name my-service --owner Yopkigom
    python scripts/init_template.py --name my-service --package my_core \\
        --owner Yopkigom --repo my-service-repo

치환 내용:
    my-ai-project      -> --name  (배포판 이름: pyproject, FastAPI title, 문서)
    app_core           -> --package (파이썬 패키지: 디렉토리명 + import 경로, 기본값은 name의 스네이크)
    {{GITHUB_OWNER}}   -> --owner (이슈 config, README 배지 URL)
    {{GITHUB_REPO}}    -> --repo  (기본값은 --name)
그 외:
    README.md          <- README.project.md 로 교체 (템플릿 소개 -> 프로젝트 README 스켈레톤)
    scripts/init_template.py 자신을 삭제
"""

import argparse
import re
import sys
from pathlib import Path

DIST_TOKEN = "my-ai-project"
PACKAGE_TOKEN = "app_core"
OWNER_TOKEN = "{{GITHUB_OWNER}}"
REPO_TOKEN = "{{GITHUB_REPO}}"

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".ipynb_checkpoints"}
# README.md(템플릿 소개)는 README.project.md 로 대체되므로 치환 대상에서 제외
SKIP_FILES = {SELF, ROOT / "README.md"}


def iter_text_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def replace_in_file(path: Path, table: dict[str, str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False  # binary file
    new_text = text
    for old, new in table.items():
        new_text = new_text.replace(old, new)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="배포판 이름 (예: my-service)")
    parser.add_argument("--package", help="파이썬 패키지명 (기본: --name의 스네이크케이스)")
    parser.add_argument("--owner", required=True, help="GitHub owner (계정/조직)")
    parser.add_argument("--repo", help="GitHub 리포 이름 (기본: --name)")
    args = parser.parse_args()

    name = args.name
    package = args.package or name.replace("-", "_").replace(".", "_")
    repo = args.repo or name

    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        parser.error(f"--name '{name}' 은 소문자/숫자/._- 만 허용합니다.")
    if not package.isidentifier():
        parser.error(f"--package '{package}' 는 유효한 파이썬 식별자가 아닙니다.")

    table = {
        DIST_TOKEN: name,
        PACKAGE_TOKEN: package,
        OWNER_TOKEN: args.owner,
        REPO_TOKEN: repo,
    }

    changed = [p for p in iter_text_files(ROOT) if replace_in_file(p, table)]
    for p in changed:
        print(f"치환: {p.relative_to(ROOT)}")

    old_pkg_dir = ROOT / "src" / PACKAGE_TOKEN
    if old_pkg_dir.is_dir() and package != PACKAGE_TOKEN:
        old_pkg_dir.rename(ROOT / "src" / package)
        print(f"이름 변경: src/{PACKAGE_TOKEN} -> src/{package}")

    project_readme = ROOT / "README.project.md"
    if project_readme.exists():
        project_readme.replace(ROOT / "README.md")
        print("교체: README.md <- README.project.md")

    SELF.unlink()
    print("삭제: scripts/init_template.py")

    print(
        "\n초기화 완료. 다음 단계:\n"
        "  1) python3 -m venv .venv && source .venv/bin/activate\n"
        '  2) pip install -e ".[dev]"\n'
        "  3) pip install pre-commit && pre-commit install && "
        "pre-commit install --hook-type pre-push\n"
        f"  4) bash scripts/setup-github.sh {args.owner}/{repo} [--solo]  (gh 인증 필요)\n"
        "  5) 남은 수동 설정은 docs/TEMPLATE_GUIDE.md 참고 (Discussions 카테고리 등)\n"
        "  6) git add -A && git commit  (치환 결과 커밋)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
