# GitHub PR 절차별 체크리스트

작업 브랜치(`feature`)의 변경분을 `main`에 안전하게 합치는 표준 절차입니다.
흐름: **feature 브랜치 생성 → 커밋 → PR 제출 → 리뷰/논의 → main으로 merge**.

> 📖 공식 가이드: [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)

---

## 1단계. 로컬에서 최신화 & 충돌 해결

> 🔧 충돌은 **main을 내 브랜치로 merge하는 순간** 드러납니다. 따라서 "충돌 확인"은 merge 이후 단계입니다.

1. **자신의 작업물을 모두 commit** 합니다.
   - ⚠️ 노트북(`.ipynb`)은 commit 전 **출력 셀이 제거**됐는지 확인하세요(`nbstripout`). 안 하면 CI `Notebook Sanity Check`가 실패합니다.
   ```bash
   git add -A
   git commit -m "작업 내용 요약"
   ```

2. **main 브랜치를 최신 상태로** 갱신합니다.
   ```bash
   git checkout main
   git pull origin main
   git checkout -          # 내 작업 브랜치로 복귀
   ```

3. **main의 최신 내용을 내 브랜치로 merge** 합니다. (PR 없이 로컬에서 가능)
   ```bash
   git merge main
   ```

4. **충돌(conflict)이 있으면 해결**합니다. 없으면 다음 단계로.
   - 📖 [명령줄에서 충돌 해결하기](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/addressing-merge-conflicts/resolving-a-merge-conflict-using-the-command-line)

5. **수정된 내용을 push** 합니다.
   ```bash
   git push origin <내-브랜치명>
   ```

---

## 2단계. PR 생성 (GitHub 웹)

6. 팀의 GitHub 저장소 웹 페이지로 이동합니다.

7. 상단 **Pull requests** → **New pull request** 버튼을 선택합니다.

8. **base = `main`**, **compare = 내 브랜치**로 지정하고 PR 생성 버튼을 누릅니다.

9. PR 서식([템플릿](../.github/pull_request_template.md))에 **무엇을 했는지 / 어떻게 동작을 확인하는지**를 기술하고,
   오른쪽 **Reviewers**에서 **리뷰어를 지정**한 뒤 제출합니다.
   - ℹ️ `.github/CODEOWNERS` 작성 시 리뷰어가 자동 배정됩니다.

10. 제출 후 **팀 메신저로 리뷰어에게 PR 요청**을 알립니다.

---

## 3단계. 리뷰 & 병합

11. 리뷰어가 PR을 확인하고, 수정이 필요한 부분에 **댓글로 피드백**을 남깁니다.

12. 피드백 받은 작업자가 **내(작업) 브랜치에 수정 커밋**을 push 합니다.
    - 같은 브랜치로 push하면 **수정 내용이 PR에 자동 반영**됩니다.

13. 작업자가 수정 사실을 리뷰어에게 알리고, 리뷰어는 확인 후 **Resolve conversation**으로 해결 처리합니다.

14. **승인(Approve) + CI 통과**를 확인한 뒤, 작업자가 **Merge** 합니다.
    - ⚠️ 브랜치 보호 규칙상 *승인 + CI 통과* 전에는 Merge 버튼이 비활성화됩니다 (1인 프로젝트는 `--solo` 설정 시 승인 생략).
    - ✅ 병합 방식은 **Squash and merge** (노트북 실험 커밋이 main 히스토리를 오염시키지 않도록 — 리포 설정상 squash만 허용됩니다).
    - 🧹 병합 후 브랜치는 자동 삭제됩니다 (`delete-branch-on-merge`).

---

### 한눈 요약

| 단계 | 위치 | 핵심 |
|------|------|------|
| 1 | 로컬 | commit → main 최신화 → merge → 충돌 해결 → push |
| 2 | 웹 | New PR → base=main/compare=내 브랜치 → 서식+리뷰어 → 제출 → 메신저 알림 |
| 3 | 웹 | 리뷰 피드백 → 수정 push(자동 반영) → 승인+CI → Squash merge → 브랜치 삭제 |
