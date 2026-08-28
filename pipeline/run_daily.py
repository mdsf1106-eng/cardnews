#!/usr/bin/env python3
"""
매일 실행되는 전체 파이프라인:
  news.json (카드뉴스 내용) -> PNG 생성 -> Cloudinary 업로드 -> 토큰 갱신 시도 -> 인스타 캐러셀 게시

사용법:
  python run_daily.py config.json news.json

출력(stdout 마지막 줄, JSON 한 줄):
  {"ok": true, "media_id": "...", "permalink": "...", "new_access_token": "..." (갱신됐다면), "image_urls": [...]}
호출한 Claude 세션은 이 JSON을 읽어 Project 로그와 config를 갱신해야 한다 (토큰이 바뀌었을 수 있으므로).
"""
import json
import sys
from pathlib import Path

from generate_cards import generate
from validate_news import validate
from upload_cloudinary import upload_all
from publish_instagram import refresh_long_lived_token, publish_carousel

HERE = Path(__file__).parent


def main():
    config_path = Path(sys.argv[1])
    news_path = Path(sys.argv[2])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    news = json.loads(news_path.read_text(encoding="utf-8"))

    ig = config["instagram"]
    cl = config["cloudinary"]
    access_token = ig["long_lived_token"]

    result = {"ok": False}

    # 0) 게시 전 검증 — 성장 분석에서 나온 규칙 위반이면 게시하지 않는다
    errors, warns = validate(news)
    for w in warns:
        print(f"[warn] {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"[error] {e}", file=sys.stderr)
        print(json.dumps({"ok": False, "stage": "validate", "errors": errors},
                         ensure_ascii=False))
        sys.exit(1)

    # 1) 토큰 갱신 시도 (24시간 미만이면 실패할 수 있음 -> 무시하고 기존 토큰 사용)
    new_token = None
    try:
        refreshed = refresh_long_lived_token(access_token)
        new_token = refreshed["access_token"]
        access_token = new_token
    except Exception as e:
        print(f"[warn] 토큰 갱신 실패(무시하고 진행): {e}", file=sys.stderr)

    # 2) 카드뉴스 PNG 생성
    out_dir = HERE / "out"
    paths = generate(news, out_dir, config.get("account_handle", ""))
    print(f"[info] {len(paths)}장 생성 완료", file=sys.stderr)

    # 3) Cloudinary 업로드
    image_urls = upload_all(paths, cl["cloud_name"], cl["upload_preset"])
    print(f"[info] {len(image_urls)}장 업로드 완료", file=sys.stderr)

    # 4) 인스타그램 캐러셀 게시
    publish_result = publish_carousel(
        user_id=ig["user_id"],
        image_urls=image_urls,
        caption=news.get("caption", ""),
        access_token=access_token,
    )

    result.update({
        "ok": True,
        "media_id": publish_result["id"],
        "permalink": publish_result.get("permalink"),
        "image_urls": image_urls,
    })
    if new_token:
        result["new_access_token"] = new_token

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
