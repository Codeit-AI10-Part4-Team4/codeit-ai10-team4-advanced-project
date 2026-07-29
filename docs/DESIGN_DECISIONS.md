# 설계 결정 기록 (DESIGN_DECISIONS)

이 템플릿은 실전 5인 팀 프로젝트
([Codeit-AI10-Part3-4Team/intermediate-project](https://github.com/Codeit-AI10-Part3-4Team/intermediate-project),
정부 RFP 분석 RAG 서비스)의 GitHub 구성을 추출·일반화한 것입니다.
원본에서 무엇을 가져오고, 무엇을 고치고, 무엇을 버렸는지 기록합니다.

## 1. 분류: 범용 / 범용화 / 특화 제외

### 그대로 채택 (범용)

| 자산 | 이유 |
|---|---|
| pre-commit 구성 (nbstripout·위생·ruff·pre-push pytest) | 언어/도메인 무관, CI와 동일 기준이라는 설계가 핵심 가치 |
| `.gitattributes` nbstripout filter | 노트북 협업의 필수 방어선 |
| PR 템플릿, 라벨 체계, 이슈 config(blank 금지) | 팀 규모·도메인 무관 |
| Discussion 협업 일지 템플릿 | 일일 스탠드업 대체 자산으로 검증됨 |
| `.gitignore` (Jupyter·secrets·데이터·모델 아티팩트) | AI 프로젝트 공통 |
| src 레이아웃 + editable install + 무거운 extra 분리 | CI 경량화·의존성 위생의 핵심 패턴 |
| ruff/mypy/pytest 설정 (`pyproject.toml`) | 점진 도입 주석 포함 그대로 유효 |

### 수정 후 채택 (범용화 + 결함 보완)

| 항목 | 원본의 문제 | 템플릿의 처리 |
|---|---|---|
| CI `paths:` 필터 | required check와 조합 시 해당 경로 무변경 PR이 영원히 블록되는 함정 | ci.yml에서 paths 제거(모든 PR에서 실행), 주석으로 근거 명시 |
| required check context | `"check"`(notebook-check)만 지정 — path 필터형이라 위 함정에 해당하고, 정작 CI(lint/test)는 미지정 | contexts를 CI 잡 이름(`Lint & Type Check`, `Unit tests (pytest)`)으로 교체, notebook-check는 advisory로 |
| `require_code_owner_reviews: true` | CODEOWNERS 파일이 없어 no-op | CODEOWNERS 스켈레톤 동봉 + 기본 false, 작성 후 켜도록 안내 |
| `setup-github.sh` REPO 기본값 | 원본 리포 하드코딩 | 필수 인자로 변경 + `--solo` 모드 추가(1인 프로젝트에서 승인 1 요구는 자기 머지 불가) |
| `apply-labels.sh`의 yq 의존 | yq는 기본 미설치 환경이 많음 | python3+pyyaml로 교체(pre-commit 설치 시 함께 깔림) |
| 이슈 config의 Discussions URL | org/리포 URL 하드코딩 | `{{GITHUB_OWNER}}/{{GITHUB_REPO}}` 플레이스홀더 + init 스크립트 치환 |
| 파이썬 버전 불일치 | ci.yml 3.12 / notebook-check.yml 3.11 | 3.12로 통일 |
| CLAUDE.md gitignore | 원본은 개인별 설정으로 간주해 미공유 | 에이전트 가이드를 팀 공유 자산으로 전환: `AGENTS.md`(표준, 원본) + `CLAUDE.md`(import 포인터) 커밋 |
| 이슈 템플릿 dropdown | RAG 6단계(parsing~llm) 하드코딩 | 일반 모듈명(api/core/eval)으로 교체 + TODO 주석 |

### 제외 (프로젝트 특화)

- `rag_core` 6단계 파이프라인 코드·계약(schemas/interfaces), `frontend/`(Streamlit),
  `deploy/`(GCP VM·systemd·JupyterHub), 도메인 extras(retrieval/parsing 등),
  프롬프트 템플릿, 골든 데이터셋, 진행 산출물(notebooks 내용물, output 등)
- 단, 이들이 남긴 **패턴**(단방향 의존, thin 라우터, extra 분리, eval 분리,
  notebooks→src 라이프사이클)은 AGENTS.md와 디렉토리 골격으로 계승했습니다.

## 2. 신규 추가

- `scripts/init_template.py` — GitHub 템플릿의 고질적 약점(변수 치환 부재,
  cookiecutter와의 차이)을 보완하는 일괄 rename 스크립트. 실행 후 자기 삭제.
- `README.project.md` — 템플릿 소개용 README와 파생 프로젝트용 README의 분리
  (init 시 교체). 두 문서의 독자가 다르기 때문.
- `docs/TEMPLATE_GUIDE.md` — "파일은 복사되지만 설정은 복사되지 않는다"는 대원칙과
  재적용 절차·함정 모음.
- 스모크 테스트(`tests/api/test_main.py`) — 파생 리포가 생성 직후부터 CI green인지
  즉시 확인 가능하게.

## 3. 장단점 평가 (트레이드오프)

- **모든 PR에서 CI 실행** (paths 필터 제거): 문서 전용 PR에도 1~2분의 CI 비용이
  들지만, required check의 신뢰성이 우선. 비용이 커지면 잡 내부 필터로 전환.
- **squash 전용 머지**: 노트북 실험 커밋이 main을 오염시키지 않는 대신 feature
  브랜치의 세부 이력은 PR에만 남음. 팀 프로젝트에서 유효성 검증된 선택.
- **한국어 문서·템플릿**: 사용 주체(한국어 팀)에 맞춘 선택. 국제 공개 OSS로
  전환하려면 번역 필요.
- **GitHub 템플릿 방식** (vs cookiecutter/copier): 웹 UI 원클릭 생성과 낮은 진입
  장벽을 얻는 대신 변수 치환·업데이트 전파를 포기 — 치환은 init 스크립트로,
  전파는 수동 역반영(TEMPLATE_GUIDE §7)으로 보완.

## 4. 개정 이력

- **2026-07-13 — 무료 플랜 private 리포 대응**: 무료 private에서 브랜치 보호 API가
  403을 반환하는데, `setup-github.sh`가 `set -e`로 전체 중단되어 정작 지원되는
  설정(머지 전략·라벨)까지 미적용되던 문제를 "경고 후 계속"으로 완화.
  ci.yml에 `concurrency`(중복 실행 취소) 추가 — private 무료 Actions 분한도
  (월 2,000분) 절약. CODEOWNERS·CI 배지·Secret scanning의 플랜 제약을 문서화
  (TEMPLATE_GUIDE §6, GitHub Docs 플랜 기능표 기준).
