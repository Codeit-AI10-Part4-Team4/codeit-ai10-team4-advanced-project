"""광고 문구 생성 — 현재는 템플릿 스텁.

━━ 실제 모델로 교체할 지점 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) VLM: 업로드된 사진 → caption ("갈색 크로플, 시럽, 디저트")
   현재는 사용자가 '상품명'을 직접 입력한다. VLM 이 붙으면 자동으로 채워진다.

2) LLM: build_prompt() 가 만든 프롬프트를 그대로 넣으면 된다.
   이 프롬프트에는 compliance.prompt_constraints() 로 만든 금지 규칙이
   이미 포함돼 있다 (Stage A). 그래서 애초에 위반 문구가 생성되지 않는다.
   → docs/02_광고규제_준수기능_설계.md 2장
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import compliance


@dataclass
class Candidate:
    headline: str
    sub: str
    hashtags: list[str]


# 스타일 어조별 문구 템플릿. {p} = 상품명
_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "warm": [
        ("오늘도 {p}, 준비했어요", "정성껏 만들어 두고 기다립니다"),
        ("따뜻한 {p} 나왔습니다", "천천히 즐기다 가세요"),
        ("{p} 좋아하시죠", "오늘 특히 잘 나왔어요"),
        ("한 템포 쉬어가는 {p}", "동네에서 편하게 들르세요"),
    ],
    "modern": [
        ("{p}", "새로 준비했습니다"),
        ("{p}, 새롭게", "담백하게 즐기는 한 접시"),
        ("오늘의 {p}", "매일 아침 준비합니다"),
        ("{p} 시작합니다", "간결하게, 제대로"),
    ],
    "bold": [
        ("{p} 특가", "오늘 하루만"),
        ("지금 {p}", "놓치면 아쉬운 가격"),
        ("{p} 들어왔습니다", "수량 한정"),
        ("이번 주 {p}", "서두르세요"),
    ],
    "natural": [
        ("신선한 {p}", "매일 아침 들여옵니다"),
        ("오늘 들어온 {p}", "제철 그대로"),
        ("{p}, 그대로", "좋은 재료만 씁니다"),
        ("바로 준비한 {p}", "신선할 때 만나보세요"),
    ],
}


def build_prompt(
    product: str,
    industry: dict,
    style: dict,
    fmt: dict,
    tags: set[str],
    caption: str = "",
) -> str:
    """실제 LLM 에 보낼 프롬프트 (금지 규칙 주입 포함)."""
    return "\n".join(
        [
            "당신은 동네 소상공인의 광고 문구를 쓰는 카피라이터입니다.",
            "",
            f"[상품] {product or caption}",
            f"[업종] {industry['label']} — {industry['copy_persona']}",
            f"[톤] {style['label']} — {style['copy_tone']}",
            f"[규격] {fmt['label']} · 헤드라인 {fmt['max_headline_chars']}자 이내,"
            f" 서브카피 {fmt['max_sub_chars']}자 이내",
            "",
            "[반드시 지킬 것]",
            compliance.prompt_constraints(tags),
            "",
            "위 조건으로 헤드라인·서브카피·해시태그를 3안 제안하세요.",
            "가격은 지어내지 마세요. 사장님이 직접 입력한 값만 사용합니다.",
        ]
    )


def generate(
    product: str,
    industry: dict,
    style: dict,
    fmt: dict,
    tags: set[str],
    n: int = 3,
    seed: int = 0,
) -> list[Candidate]:
    """문구 후보 n개 생성.

    한 장만 주면 마음에 안 들 때 방법이 없다. 3안을 주고 고르게 하는 것이
    '제어 가능성'의 가장 싼 구현이다. — docs/01 5장 P1-6
    """
    p = (product or industry["label"]).strip()
    pool = _TEMPLATES.get(style["id"], _TEMPLATES["modern"])
    rnd = random.Random(f"{p}|{industry['id']}|{style['id']}|{seed}")
    picked = rnd.sample(pool, k=min(n, len(pool)))

    tags_base = [t for t in industry.get("keywords", [])][:2]
    results: list[Candidate] = []
    for head_t, sub_t in picked:
        head = head_t.format(p=p)[: fmt["max_headline_chars"]]
        sub = sub_t.format(p=p)[: fmt["max_sub_chars"]]
        results.append(
            Candidate(
                headline=head,
                sub=sub,
                hashtags=[f"#{p.replace(' ', '')}", f"#{industry['label'].split('·')[0]}"]
                + [f"#{t}" for t in tags_base],
            )
        )
    return results
