#!/usr/bin/env python3
"""
GitHub Actions 진입점.

설정을 config.json이 아니라 **환경변수(레포 시크릿)**에서 읽는다.
로컬 실행용 run_daily.py와 역할은 같고 입력 방식만 다르다.

동작:
  1) 오늘 날짜(KST)와 슬롯(am/pm)에 해당하는 content/news_YYYYMMDD_{slot}.json 을 찾는다
  2) 없으면 조용히 종료 (콘텐츠를 아직 안 만든 날 워크플로가 실패로 뜨지 않게)
  3) 검증 -> 카드 생성 (여기까지는 시크릿 없이도 동작)
  4) 시크릿이 모두 있으면 Cloudinary 업로드 -> 인스타 캐러셀 게시
     없으면 생성만 하고 종료 (PNG는 Actions 아티팩트로 남는다)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from generate_cards import generate
from build_reel import build_reel, build_card_clips
from upload_cloudinary import upload_all, upload_video, upload_videos
from publish_instagram import (publish_carousel, publish_reel,
                               publish_video_carousel, refresh_long_lived_token)
from validate_news import validate

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


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

    handle = os.environ.get("ACCOUNT_HANDLE", "itsue_issue")

    # 2) 카드 생성 — 게시 자격증명이 없어도 여기까지는 항상 수행한다.
    #    (Actions 아티팩트로 PNG가 남으므로 수동 업로드가 가능하다)
    out_dir = ROOT / "out"
    paths = generate(news, out_dir, handle)
    print(f"[info] 카드 {len(paths)}장 생성 -> out/")

    # format
    #   "carousel_video"(기본) 카드 한 장 = MP4 한 개 -> 영상 캐러셀로 피드 게시
    #   "reel"                 카드 전체를 이어붙인 MP4 한 개 -> 릴스 게시
    #   "carousel"             기존 PNG 이미지 캐러셀
    fmt = news.get("format", "carousel_video").lower()
    reel_path = None
    clips = []

    # 배경음악(선택): assets/bgm/ 안의 음원. news.json의 "bgm"으로 파일명을 지정하거나
    # 비워두면 폴더의 첫 번째 파일을 쓴다. 없으면 무음.
    # ⚠️ Meta 사운드 컬렉션(facebook.com/sound)에서 받은 음원만 쓸 것.
    #    그 라이선스만 인스타·페북 게시에서 상업적 사용까지 커버한다.
    bgm = None
    bgm_dir = ROOT / "assets" / "bgm"
    named = (news.get("bgm") or "").strip()
    if named:
        cand = bgm_dir / named
        bgm = cand if cand.exists() else None
        if bgm is None:
            print(f"[warn] bgm 파일을 찾지 못했습니다: assets/bgm/{named} — 무음으로 진행합니다.")
    elif bgm_dir.is_dir():
        found = sorted(f for f in bgm_dir.iterdir()
                       if f.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac"))
        bgm = found[0] if found else None
    if bgm:
        print(f"[info] 배경음악: assets/bgm/{bgm.name}")
    if fmt == "carousel_video":
        clips = build_card_clips(
            paths, out_dir,
            seconds=(news.get("clip") or {}).get("seconds", 5.0),
            bgm=bgm,
        )
        print(f"[info] 카드별 영상 {len(clips)}개 생성 -> out/*.mp4")
    elif fmt == "reel":
        reel_path = build_reel(
            paths, out_dir / "reel.mp4",
            theme=news.get("theme", "dark"),
            durations=(news.get("reel") or {}).get("durations"),
            bgm=bgm,
        )
        print(f"[info] 릴스 영상 생성 -> out/{reel_path.name}")

    # 3) 게시 자격증명 확인. 하나라도 없으면 생성만 하고 정상 종료.
    creds = {k: os.environ.get(k, "").strip()
             for k in ("IG_USER_ID", "IG_LONG_LIVED_TOKEN",
                       "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET")}
    missing = [k for k, v in creds.items() if not v]
    dry = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

    if dry or missing:
        why = "DRY_RUN 지정" if dry else f"시크릿 미등록: {', '.join(missing)}"
        print(f"[skip] 자동 게시를 건너뜁니다 ({why}).")
        made = {"carousel_video": "카드별 MP4와 PNG",
                "reel": "릴스 MP4와 카드 PNG"}.get(fmt, "카드 PNG")
        print(f"[info] {made}는 이 실행의 Artifacts에서 내려받아 수동 게시할 수 있습니다.")
        print("--- 캡션 ---")
        print(news.get("caption", ""))
        print("--- 캡션 끝 ---")
        return

    ig_user, token = creds["IG_USER_ID"], creds["IG_LONG_LIVED_TOKEN"]
    cloud, preset = creds["CLOUDINARY_CLOUD_NAME"], creds["CLOUDINARY_UPLOAD_PRESET"]

    # 4) 토큰 갱신 시도 (실패해도 기존 토큰으로 진행)
    try:
        refreshed = refresh_long_lived_token(token)
        token = refreshed["access_token"]
        exp = refreshed.get("expires_in")
        print(f"[info] 토큰 갱신됨. 만료까지 {int(exp)//86400}일" if exp else "[info] 토큰 갱신됨")
        print("[note] 갱신된 토큰은 저장되지 않습니다. 60일 안에 시크릿을 수동 갱신하세요.")
    except Exception as e:
        print(f"[warn] 토큰 갱신 실패(무시하고 진행): {e}")

    # 5) 호스팅 업로드 + 6) 인스타 게시
    if fmt == "carousel_video":
        video_urls = upload_videos(clips, cloud, preset)
        print(f"[info] 영상 {len(video_urls)}개 업로드 완료")
        res = publish_video_carousel(
            user_id=ig_user, video_urls=video_urls,
            caption=news.get("caption", ""), access_token=token,
        )
    elif fmt == "reel":
        video_url = upload_video(reel_path, cloud, preset)
        # 표지 PNG를 커버로 지정 — 영상 첫 프레임을 쓰면 그리드에서 상단이 잘린다
        cover_url = upload_all([paths[0]], cloud, preset)[0]
        print("[info] 영상·커버 업로드 완료")
        res = publish_reel(
            user_id=ig_user, video_url=video_url, cover_url=cover_url,
            caption=news.get("caption", ""), access_token=token,
        )
    else:
        urls = upload_all(paths, cloud, preset)
        print(f"[info] {len(urls)}장 업로드 완료")
        res = publish_carousel(
            user_id=ig_user, image_urls=urls,
            caption=news.get("caption", ""), access_token=token,
        )
    print(json.dumps({"ok": True, "media_id": res.get("id"),
                      "permalink": res.get("permalink")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
