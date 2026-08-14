"""갈래 판정 1층(마스크 규칙)을 골든셋 15장으로 채점한다.

정답지는 기준선 실측(2026-08-13, 한판_감성.png)을 보고 사람이 정한 라벨이다.
1층이 말할 수 있는 답은 "generate 확정" 아니면 "모름(None → 2층 몫)"뿐이라,
여기서 보는 건 두 가지다 —
  ① generate 사진을 얼마나 잡아내나
  ② keep/cutout 사진을 generate 로 오판하지 않나 (오판이 제일 치명적이다)
"""

from pathlib import Path

from PIL import Image

from app_core import config
from app_core.background import remove_background
from app_core.photo_router import mask_stats, route_photo

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "golden_photos" / "선정"

#: 정답지 — 기준선 한판을 보고 사람이 정한 갈래
LABELS = {
    "분식한식_밝음": "keep",
    "분식한식_어두움": "cutout",
    "분식한식_복잡": "generate",
    "카페_밝음": "keep",
    "카페_어두움": "keep",
    "카페_복잡": "cutout",
    "베이커리_밝음": "keep",
    "베이커리_어두움": "keep",
    "베이커리_복잡": "generate",
    "꽃집_밝음": "cutout",
    "꽃집_어두움": "keep",
    "꽃집_복잡": "cutout",
    "소매_밝음": "cutout",
    "소매_어두움": "keep",
    "소매_복잡": "generate",
}


def main() -> None:
    config.load_env()
    ok = 0
    print(f"{'사진':<14} {'면적':>5}   판정       정답")
    for name, label in LABELS.items():
        path = GOLD / f"{name}.jpg"
        cut = remove_background(Image.open(path))
        got = route_photo(path.read_bytes(), "image/jpeg", cut)
        mark = "✅" if got == label else "❌"
        ok += got == label
        print(f"{name:<14} {mask_stats(cut).area:>5.2f}   {got:<9} {label:<9} {mark}")

    print(f"\n{ok}/15 맞음")


if __name__ == "__main__":
    main()
