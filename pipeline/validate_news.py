#!/usr/bin/env python3
"""
news.json 게시 전 검증.

2026-08-27 성장 분석에서 나온 규칙을 코드로 강제한다.
체크리스트는 잊어버리지만 이건 안 잊어버린다.

사용법:
  python validate_news.py news_0827_pm.json
  -> 위반 사항을 출력하고, ERROR가 있으면 exit code 1
"""
import json
import re
import sys
from pathlib import Path

MAX_HASHTAGS = 5          # 2025-12-18 인스타 공식 제한
MIN_CARDS, MAX_CARDS = 7, 10   # 조사상 7~10장이 최적 (플랫폼 상한은 20)
BANNED_CTA = ["좋아요 눌러", "좋아요 부탁", "좋아요 눌러주세요"]  # 참여 -4.9% 역효과


def validate(news: dict) -> tuple[list[str], list[str]]:
    errors, warns = [], []
    items = news.get("items", [])
    caption = news.get("caption", "")

    # ── 카드 수 ────────────────────────────────
    n_cards = len(items) + 2 + (1 if news.get("hook") else 0)
    if not (MIN_CARDS <= n_cards <= MAX_CARDS):
        warns.append(f"카드 {n_cards}장 — 권장 {MIN_CARDS}~{MAX_CARDS}장 범위를 벗어남")

    # ── 훅 카드(2번째 표지) ────────────────────
    if not news.get("hook"):
        errors.append(
            "hook 없음 — 2번 카드는 두 번째 표지여야 한다. "
            "인스타는 캐러셀을 봤지만 안 넘긴 사람에게 2번 미디어부터 재노출한다."
        )
    elif news["hook"].get("line", "") == news.get("headline", ""):
        errors.append("hook.line이 표지 headline과 동일 — 반복이 아니라 다른 각도의 훅이어야 한다")

    # ── 해석 한 줄 (애그리게이터 정책 방어 + 전송 유도) ──
    missing = [i + 1 for i, it in enumerate(items) if not it.get("sowhat")]
    if missing:
        errors.append(
            f"sowhat 누락: {missing}번 아이템 — 사실만 나열하면 "
            "'실질적 편집' 근거가 약해 추천에서 빠질 수 있다"
        )

    # ── 해시태그 ──────────────────────────────
    tags = re.findall(r"#\S+", caption)
    if len(tags) > MAX_HASHTAGS:
        errors.append(f"해시태그 {len(tags)}개 — 2025.12부터 게시물당 {MAX_HASHTAGS}개 제한")

    # ── CTA ───────────────────────────────────
    if not news.get("question"):
        errors.append("question 없음 — 댓글 요청은 댓글 +203%, 마무리 카드의 핵심 장치다")
    for bad in BANNED_CTA:
        if bad in caption:
            errors.append(f"캡션에 '{bad}' — 좋아요 요청은 참여 -4.9%로 역효과")
    if "저장" not in caption:
        warns.append("캡션에 저장 요청 없음 — 저장 요청은 참여 +92%")

    # ── 출처 ──────────────────────────────────
    for i, it in enumerate(items, 1):
        if not it.get("source"):
            errors.append(f"{i}번 아이템 출처 없음")

    return errors, warns


def main():
    path = Path(sys.argv[1])
    news = json.loads(path.read_text(encoding="utf-8"))
    errors, warns = validate(news)

    for w in warns:
        print(f"[WARN]  {w}")
    for e in errors:
        print(f"[ERROR] {e}")

    if not errors and not warns:
        print(f"[OK] {path.name} — 모든 규칙 통과")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
