# AGENTS.md

이 문서는 코드 에이전트(Claude Code, Codex, Cursor 등)가 이 저장소를 파악하는 **단일 진입점**입니다.
Claude Code용 `CLAUDE.md`는 이 파일을 import하는 포인터이므로, 내용 수정은 여기서만 하세요.

> **작성 요령** (채운 뒤 이 블록은 삭제):
> - 명령은 복사-실행 가능한 형태로. "대충 이런 식" 서술 금지.
> - 함정(gotcha)은 반드시 **왜**와 함께 기록 — 이유 없는 금지는 에이전트가 무시하기 쉽습니다.
> - 코드에서 유추 가능한 것(파일 목록, 함수 시그니처)은 적지 말고, **유추 불가능한 것**
>   (의도, 제약, 사고 이력, 배포 환경)을 적으세요.
> - 프로젝트가 성장하면 즉시 갱신 — 낡은 가이드는 없느니만 못합니다.

## 프로젝트 개요

<!-- TODO: 무엇을 만드는 프로젝트인지 2~3문장. 현재 구현 단계(스캐폴딩/구현/운영)와
     "동작하는 것 / 예정인 것"의 경계를 명시하면 에이전트의 착각이 크게 줄어듭니다. -->

언어/스타일: Python 3.12+, PEP8 + 실무 관행. 포맷/린트 기준은 `pyproject.toml`의 `[tool.ruff]`.

## 빌드 / 실행 / 테스트

- **설치 (editable, src 레이아웃)**: `pip install -e ".[dev]"`
  - import는 **`import app_core` / `from api import ...`** (⚠️ `src.` 접두어 없음).
  - 무거운 의존성(torch 계열 등)은 core가 아닌 **별도 extra**에 둘 것 — CI/기본 설치를
    가볍게 유지하는 장치이므로 core로 되돌리지 말 것.
- **API 서버 실행**: `uvicorn api.main:app --reload` → http://127.0.0.1:8000/docs
- **품질 게이트 (커밋/PR 전 반드시 통과)** — CI와 동일:
  - `ruff check src tests` / `ruff format src tests` / `mypy` / `pytest`
- **pre-commit**: `pre-commit install && pre-commit install --hook-type pre-push`
  (commit 훅: ruff+nbstripout+위생 / push 훅: pytest)
- **노트북 규칙**: nbstripout이 출력 셀을 자동 제거(`.gitattributes` filter + pre-commit).
  ⚠️ 출력 포함 채로 커밋된 노트북은 filter와 어긋나 영원히 `modified`로 뜨므로,
  한 번 stripped 상태로 재커밋해 정합성을 맞출 것.

## 아키텍처 규칙 (위반 시 설계 결함)

```
src/api  ──depends on──>  src/app_core
```

- **`app_core`는 `api`를 절대 import하지 않습니다.** `app_core`는 FastAPI 없이 단독
  실행·테스트 가능해야 합니다.
- 내부 import는 `from app_core...` / `from api...`로 통일. 폴더가 `src/`라
  `from src.app_core...`로 쓰기 쉬운데 **런타임에서 깨집니다** — lint가 못 잡는 사각지대.
- `api/` 라우터는 thin하게: 요청 검증 → `app_core` 호출 → 응답 변환만.
  비즈니스 로직을 라우터에 직접 작성하지 마세요.

<!-- TODO: 도메인 파이프라인이 생기면 단계와 의존 방향을 여기 기록.
     예: parsing → chunking → embedding → retrieval (역방향 의존 금지) -->

## 코드 작성 위치 판단

- HTTP/라우팅/인증 등 웹 서버 관심사 → `src/api/`
- 도메인 로직 → `src/app_core/`
- 실험·조사 → `notebooks/` (검증되면 반드시 src/로 함수화 이전 — 노트북 import 금지)
- 평가 자산(골든셋·지표) → `eval/` (지표 함수는 순수 함수로: (예측, 정답) → 점수)
- 테스트 → `tests/`는 `test_<module>.py`로 `src/` 구조 미러링

## 프로젝트 고유 관례

- **데이터/모델 파일 커밋 금지**: 원본 데이터는 `data/`에 두고 `.gitignore` 처리.
- **외부 키·엔드포인트는 환경 변수로**. 노트북·코드에 평문 금지.
- **외부 API 호출 테스트는 mock 사용**: 실 호출은 비용·비결정성으로 금지.
<!-- TODO: 프로젝트를 진행하며 확립된 관례를 계속 추가 -->

## 협업 / Git

- main은 **PR 필수** 보호 규칙 + required check(CI lint/test). 일반 작업은
  feature 브랜치 → PR → Squash merge (절차: `docs/pr-checklist.md`).
- `git pull` 시 staged 변경이 있으면 autostash 복원 실패로 작업이 dangling stash로
  빠질 수 있으니, 작업트리를 clean히 한 뒤 통합할 것. 분실 변경은
  `git fsck --lost-found`로 복구 가능.

<!-- TODO: 배포 환경이 생기면 "인프라 / 배포" 섹션 추가 — 포트, 서비스 구성,
     "하지 말 것"(사고 이력 포함)을 기록. 예: venv에 타 환경 PYTHONPATH 주입 금지(SEGV 사고) -->
