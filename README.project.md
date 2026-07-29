# my-ai-project

[![src CI (lint + test)](https://github.com/{{GITHUB_OWNER}}/{{GITHUB_REPO}}/actions/workflows/ci.yml/badge.svg)](https://github.com/{{GITHUB_OWNER}}/{{GITHUB_REPO}}/actions/workflows/ci.yml)
<!-- ⚠️ private 리포에서는 워크플로 배지가 외부 임베드 불가라 렌더되지 않습니다 —
     위 배지 줄을 삭제하거나 public 전환 시 사용하세요 (docs/TEMPLATE_GUIDE.md §6). -->


> TODO: 프로젝트 한 줄 소개를 작성하세요.

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push
```

## 실행

```bash
uvicorn api.main:app --reload   # http://127.0.0.1:8000/docs
```

## 품질 게이트 (커밋/PR 전 필수 — CI와 동일)

```bash
ruff check src tests
ruff format src tests
mypy
pytest
```

## 구조

```
├── src/
│   ├── api/         # 웹 서버 관심사 — thin 라우터
│   └── app_core/    # 도메인 로직 — api 미의존
├── tests/           # src/ 구조 미러링
├── notebooks/       # 실험 (검증되면 src/로 이전)
└── eval/            # 평가 자산
```

> TODO: 아키텍처·규칙 상세는 [AGENTS.md](AGENTS.md)에, 협업 절차는
> [docs/pr-checklist.md](docs/pr-checklist.md)에 정리되어 있습니다.
