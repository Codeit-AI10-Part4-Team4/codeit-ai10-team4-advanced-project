"""골든셋 15장을 광고로 일괄 생성한다 — 품질 기준선(베이스라인) 잡기.

사진마다 감성 피드형·정보 포스터형을 하나씩 만들어 data/golden_results/ 에
저장하고, 끝나면 형태별로 한 판으로 모은다. 이미 만든 건 건너뛰므로
중간에 끊겨도 다시 실행하면 이어서 돈다.

실행:  python eval/run_golden_images.py          # 전부
       python eval/run_golden_images.py 꽃집     # 한 업종만
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from app_core import config, photo_store
from app_core.fonts import load
from app_core.pipeline import Style, generate_ad
from app_core.schema import AdBrief, CopyCandidate, Store

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "golden_photos" / "선정"
OUT = ROOT / "data" / "golden_results"

#: 업종별 고정 재료 — 조건 통제를 위해 주문·문구를 상수로 고정한다.
#: (업종id, 가게명, 상품, 가격, 톤, 헤드라인, 서브)
RECIPES = {
    "분식한식": ("snack", "든든분식", "떡볶이", 3500, "매콤한", "오늘 뭐 먹지? 고민 끝!", "떡볶이 3,500원"),
    "카페": ("cafe", "모퉁이카페", "아이스라떼", 4500, "차분한", "쉬어가요, 라떼 한 잔", "아이스라떼 4,500원"),
    "베이커리": ("bakery", "아침빵집", "크루아상", 3800, "따뜻한", "갓 구운 냄새를 팝니다", "크루아상 3,800원"),
    "꽃집": ("flower", "연남플라워", "꽃다발", 20000, "화사한", "마음을 전하는 가장 예쁜 방법", "꽃다발 20,000원부터"),
    "소매": ("grocery", "동네마켓", "신상품", 9900, "깔끔한", "오늘 들어온 신상품", "단돈 9,900원"),
}
STYLES: tuple[tuple[Style, str], ...] = (("simple", "감성"), ("poster", "포스터"))
CONDS = ("밝음", "어두움", "복잡")


def main() -> None:
    config.load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None

    for photo in sorted(GOLD.glob("*.jpg")):
        industry_kr, cond = photo.stem.split("_")
        if only and industry_kr != only:
            continue
        industry, shop, product, price, tone, headline, sub = RECIPES[industry_kr]
        brief = AdBrief(
            goal="image",
            product=product,
            price=price,
            tone=tone,
            photo_id=photo_store.save(photo.read_bytes(), photo.name),
        )
        store = Store(
            id=0, user_id=0, industry=industry, name=shop,
            address="서울시 마포구 연남동", phone="02-000-0000",
        )
        copy = CopyCandidate(headline=headline, sub=sub)

        for style, kr in STYLES:
            dst = OUT / f"{photo.stem}_{kr}.png"
            if dst.exists():
                continue
            print(f"{dst.name} 만드는 중...")
            generate_ad(brief, store, copy, style=style).save(dst)

    for _, kr in STYLES:
        _sheet(kr)


def _sheet(kr: str) -> None:
    """형태 하나의 결과 15장을 5업종 × 3조건 한 판으로 모은다."""
    th = 340
    names = list(RECIPES)
    board = Image.new("RGB", (3 * (th + 10) + 150, len(names) * (th + 10) + 60), (24, 26, 30))
    d = ImageDraw.Draw(board)
    for c, cond in enumerate(CONDS):
        d.text((150 + c * (th + 10) + th // 2, 30), cond, font=load("body", 26), fill="white", anchor="mm")
    for r, name in enumerate(names):
        d.text((75, 60 + r * (th + 10) + th // 2), name, font=load("body", 26), fill="white", anchor="mm")
        for c, cond in enumerate(CONDS):
            p = OUT / f"{name}_{cond}_{kr}.png"
            if not p.exists():
                continue
            im = Image.open(p).convert("RGB")
            im.thumbnail((th, th))
            board.paste(im, (150 + c * (th + 10), 60 + r * (th + 10)))
    board.save(OUT / f"한판_{kr}.png")
    print(f"한판_{kr}.png 저장")


if __name__ == "__main__":
    main()
