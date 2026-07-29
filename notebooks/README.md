# notebooks/

실험·조사 기록 공간입니다. **배포 대상이 아닙니다.**

## 규칙

- 검증이 끝난 로직은 **반드시 `src/`의 대응 모듈로 함수화해 이전**합니다.
  노트북 자체를 import하지 마세요.
- 담당자별 폴더를 만들고, 파일명에 날짜/버전을 포함하세요.
  예: `notebooks/hj/chunking_experiment_v2.ipynb`
- 출력 셀은 nbstripout이 커밋 시점에 자동 제거합니다 — `pre-commit install`이 안 되어
  있으면 CI(Notebook Sanity Check)에서 걸립니다.
- 실험 등록은 이슈 템플릿 "🔬 실험"으로 — 가설/방법/프로덕션 이전 계획을 남기세요.
