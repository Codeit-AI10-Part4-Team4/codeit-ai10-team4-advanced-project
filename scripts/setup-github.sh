#!/usr/bin/env bash
# GitHub 레포 하드닝: 브랜치 보호 + Merge 전략 + 라벨.
# ── 템플릿으로 리포를 생성해도 이 설정들은 복사되지 않으므로, 리포마다 1회 실행해야 합니다.
#
# 사전조건: gh auth login (해당 레포 admin 권한)
# 사용법:   bash scripts/setup-github.sh <owner>/<repo> [--solo]
#           --solo : 1인 프로젝트용 — PR 승인 요구를 끕니다 (승인자 없이는 머지 불가 방지)
# 주의:     무료 플랜의 private 리포는 브랜치 보호를 지원하지 않습니다(403).
#           이 경우 보호 단계만 건너뛰고 머지 전략·라벨은 계속 적용합니다.
#           GitHub Pro(개인)/Team(조직) 또는 public 전환 시 전부 사용 가능 —
#           docs/TEMPLATE_GUIDE.md §6 참고.
set -euo pipefail

REPO="${1:?사용법: bash scripts/setup-github.sh <owner>/<repo> [--solo]}"
MODE="${2:-}"
SCRIPT_DIR="$(dirname "$0")"

# required_status_checks.contexts 는 ci.yml의 "잡 이름(name:)"과 정확히 일치해야 한다.
# ⚠️ paths 필터가 걸린 워크플로(notebook-check 등)는 required로 지정하지 말 것 —
#    해당 경로 변경이 없는 PR에서는 체크가 생성되지 않아 머지가 영원히 블록된다.
if [[ "$MODE" == "--solo" ]]; then
  REVIEWS='null'
  echo "==> --solo: PR 승인 요구 없음 (보호 규칙의 나머지는 동일)"
else
  # require_code_owner_reviews 는 .github/CODEOWNERS 작성 후 true로 바꿀 것 (파일 없으면 no-op).
  REVIEWS='{ "required_approving_review_count": 1, "require_code_owner_reviews": false }'
fi

echo "==> main 브랜치 보호 규칙 적용"
PROTECTION_OK=true
if ! gh api -X PUT "repos/$REPO/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - > /dev/null <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Lint & Type Check", "Unit tests (pytest)"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": $REVIEWS,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
JSON
then
  PROTECTION_OK=false
  echo "⚠️  브랜치 보호 적용 실패 — 위 오류가 HTTP 403이면 무료 플랜 private 리포 제약입니다."
  echo "    그동안은 로컬 방어선(pre-commit + pre-push pytest)이 품질 게이트를 대신합니다."
  echo "    나머지 설정(머지 전략·라벨)은 계속 적용합니다."
fi

echo "==> Merge 전략: Squash 전용 + 머지 후 브랜치 자동 삭제"
gh repo edit "$REPO" \
  --enable-squash-merge=true \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge=true

echo "==> 라벨 적용"
bash "$SCRIPT_DIR/apply-labels.sh" "$REPO"

if [[ "$PROTECTION_OK" == true ]]; then
  echo "완료: 브랜치 보호 + 머지 전략 + 라벨 적용됨."
else
  echo "완료(부분): 머지 전략 + 라벨만 적용됨 — 브랜치 보호는 미적용."
  echo "  (GitHub Pro 전환 또는 public 전환 후 이 스크립트를 다시 실행하면 적용됩니다.)"
fi
echo "남은 수동 설정(자세한 내용은 docs/TEMPLATE_GUIDE.md):"
echo "  1) Settings > Code security: Secret scanning / Push protection 활성화 (⚠️ public 전용)"
echo "  2) Settings > General > Features: Discussions 활성화"
echo "  3) Discussions > 카테고리 'CollaborationLog' 생성 (API 미지원, 수동 필수)"
