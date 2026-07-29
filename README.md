# ai-project-template

[![src CI (lint + test)](https://github.com/Yopkigom/ai-project-template/actions/workflows/ci.yml/badge.svg)](https://github.com/Yopkigom/ai-project-template/actions/workflows/ci.yml)

AI 팀 프로젝트용 GitHub 템플릿. **src 레이아웃 파이썬 패키지 + FastAPI 골격 + 노트북 협업
워크플로 + 품질 게이트(CI·pre-commit) + 협업 규약(.github/)** 을 한 번에 제공합니다.

실전 협업 프로젝트([RFP RAG 서비스, 5인 팀](https://github.com/Codeit-AI10-Part3-4Team/intermediate-project))에서
검증된 구성을 일반화한 것입니다. 설계 배경과 원본 대비 변경점은
[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md)에 기록되어 있습니다.

## 빠른 시작

```bash
# 1) GitHub에서 "Use this template" → 새 리포 생성 → clone
git clone https://github.com/<owner>/<repo>.git && cd <repo>

# 2) 프로젝트 이름으로 초기화 (플레이스홀더 일괄 치환 + 스크립트 자신 삭제)
python3 scripts/init_template.py --name my-service --owner <owner>

# 3) 개발 환경
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push

# 4) 리포 설정 재적용 — 템플릿은 "파일"만 복사하고 "설정"은 복사하지 않습니다!
gh auth login
bash scripts/setup-github.sh <owner>/<repo>          # 팀 프로젝트
bash scripts/setup-github.sh <owner>/<repo> --solo   # 1인 프로젝트 (PR 승인 요구 제외)
#   무료 플랜의 private 리포는 브랜치 보호만 건너뜁니다(자동 감지) —
#   전체 제약 매트릭스는 docs/TEMPLATE_GUIDE.md §6 참고
```

전체 절차·주의사항·운용 방법: **[docs/TEMPLATE_GUIDE.md](docs/TEMPLATE_GUIDE.md)**

## 제공하는 것

| 영역 | 내용 |
|---|---|
| 패키징 | src 레이아웃, editable install, 무거운 의존성 extra 분리 패턴 |
| 코드 골격 | `src/api/`(FastAPI, thin 라우터) + `src/app_core/`(도메인, FastAPI 무의존) |
| 품질 게이트 | ruff(lint+format) · mypy · pytest — CI와 pre-commit이 동일 기준 |
| 노트북 협업 | nbstripout 3중 방어(gitattributes·pre-commit·CI), notebooks→src 라이프사이클 |
| 협업 규약 | 이슈/PR/Discussion 템플릿, 라벨, PR 체크리스트, CODEOWNERS 스켈레톤 |
| 리포 설정 | 브랜치 보호·머지 전략·라벨 재적용 스크립트 (`scripts/setup-github.sh`) |
| 에이전트 가이드 | `AGENTS.md` 스켈레톤 (Claude Code · Codex 공용, CLAUDE.md는 포인터) |

## 구조

```
├── .github/            # CI 2종, 이슈/PR/Discussion 템플릿, labels.yml, CODEOWNERS
├── src/
│   ├── api/            # 웹 서버 관심사 (라우팅·검증) — thin하게 유지
│   └── app_core/       # 도메인 로직 — api를 import하지 않음 (단방향 의존)
├── tests/              # src/ 구조 미러링 (test_<module>.py)
├── notebooks/          # 실험·조사 (배포 대상 아님, 검증되면 src/로 함수화 이전)
├── eval/               # 평가 자산 (골든셋·지표) — 코드와 라이프사이클 분리
├── scripts/            # init_template.py, setup-github.sh, apply-labels.sh
└── docs/               # TEMPLATE_GUIDE, DESIGN_DECISIONS, pr-checklist
```

## 라이선스

MIT
