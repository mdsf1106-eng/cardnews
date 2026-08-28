#!/usr/bin/env python3
"""
GitHub Actions 진입점.

설정을 config.json이 아니라 **환경변수(레포 시크릿)**에서 읽는다.
로컬 실행용 run_daily.py와 역할은 같고 입력 방식만 다르다.

동작:
  1) 오늘 날짜(KST)와 슬롯(am/pm)에 해당하는 content/news_YYYYMMDD_{slot}.json 을 찾는다
  2) 없으면 조용히 종료 (콘텐츠를 아직 안 만든 날 워크플로가 실패로 뜨지 않게)
  3) 검증 -> 카드 생성 -> Cloudinary 업로드 -> 인스타 캐러셀 게시
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from generate_cards import generate
from upload_cloudinary import upload_all
from publish_instagram import publish_carousel, refresh_long_lived_token
from validate_news import validate

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def need(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"[error] 시크릿 {name} 이(가) 비어 있습니다. 레포 Settings > Secrets에서 등록하세요.")
    return v


def pick_news_file() -> Path | None:
    """슬롯 인자(am/pm) + 오늘 KST 날짜로 콘텐츠 파일을 찾는다."""
    slot = (sys.argv[1] if len(sys.argv) > 1 else "pm").lower()
    explicit = os.environ.get("NEWS_FILE", "").strip()
    if explicit:
        p = ROOT / explicit
        return p if p.exists() else None
    today = datetime.now(KST).strftime("%Y%m%d")
    p = ROOT / "content" / f"news_{today}_{slot}.json"
    return p if p.exists() else None


def main():
    news_path = pick_news_file()
    if news_path is None:
        print("[skip] 오늘 슬롯에 해당하는 콘텐츠 파일이 없습니다. 게시하지 않고 종료합니다.")
        return

    print(f"[info] 콘텐츠: {news_path.relative_to(ROOT)}")
    news = json.loads(news_path.read_text(encoding="utf-8"))

    # 1) 규칙 검증 — 위반이면 게시하지 않는다
    errors, warns = validate(news)
    for w in warns:
        print(f"[warn]  {w}")
    if errors:
        for e in errors:
            print(f"[error] {e}")
        sys.exit("[error] 검증 실패로 게시를 중단합니다.")

    ig_user = need("IG_USER_ID")
    token = need("IG_LONG_LIVED_TOKEN")
    cloud = need("CLOUDINARY_CLOUD_NAME")
    preset = need("CLOUDINARY_UPLOAD_PRESET")
    handle = os.environ.get("ACCOUNT_HANDLE", "itsue_issue")

    # 2) 토큰 갱신 시도 (실패해도 기존 토큰으로 진행)
    try:
        refreshed = refresh_long_lived_token(token)
        token = refreshed["access_token"]
        exp = refreshed.get("expires_in")
        print(f"[info] 토큰 갱신됨. 만료까지 {int(exp)//86400}일" if exp else "[info] 토큰 갱신됨")
        print("[note] 갱신된 토큰은 저장되지 않습니다. 60일 안에 시크릿을 수동 갱신하세요.")
    except Exception as e:
        print(f"[warn] 토큰 갱신 실패(무시하고 진행): {e}")

    # 3) 카드 생성
    out_dir = ROOT / "out"
    paths = generate(news, out_dir, handle)
    print(f"[info] 카드 {len(paths)}장 생성")

    # 4) 이미지 호스팅 업로드
    urls = upload_all(paths, cloud, preset)
    print(f"[info] {len(urls)}장 업로드 완료")

    # 5) 인스타 게시
    res = publish_carousel(
        user_id=ig_user, image_urls=urls,
        caption=news.get("caption", ""), access_token=token,
    )
    print(json.dumps({"ok": True, "media_id": res.get("id"),
                      "permalink": res.get("permalink")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
