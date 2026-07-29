#!/usr/bin/env bash
# .github/labels.yml 의 라벨을 레포에 생성/갱신한다.
# 사전조건: gh auth login (repo 권한), python3 + pyyaml (pre-commit 설치 시 함께 깔림)
set -euo pipefail

REPO="${1:?사용법: bash scripts/apply-labels.sh <owner>/<repo>}"
LABELS_FILE="$(dirname "$0")/../.github/labels.yml"

emit_labels() {
  python3 - "$LABELS_FILE" <<'PY'
import sys

try:
    import yaml
except ImportError:
    sys.exit("pyyaml 이 필요합니다: pip install pyyaml")

with open(sys.argv[1], encoding="utf-8") as f:
    for label in yaml.safe_load(f):
        print(f"{label['name']}\t{label['color']}\t{label.get('description', '')}")
PY
}

emit_labels | while IFS=$'\t' read -r name color desc; do
  # 이미 있으면 갱신(--force), 없으면 생성
  gh label create "$name" --color "$color" --description "$desc" --repo "$REPO" --force
done

echo "라벨 적용 완료: $REPO"
