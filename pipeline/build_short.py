#!/usr/bin/env python3
"""
유튜브 쇼츠(세로 30초) 제작.

카드뉴스와 다른 별도 템플릿을 쓴다. 쇼츠는 손에 들고 스쳐 보는 화면이라
한 장에 한 문장, 글자를 크게 — 카드 8장을 그대로 옮기면 하나도 안 읽힌다.

나레이션 mp3를 주면 그 길이에 맞춰 씬 시간을 비율대로 늘리고 줄인다.
없으면 씬에 적힌 seconds 그대로, 무음으로 만든다.
"""
import base64
import mimetypes
import re
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

from generate_cards import esc, rich, _inline_css, _fit_block
from build_chart import render_chart

HERE = Path(__file__).parent
CARDS = HERE / "cards"

W, H = 1080, 1920
FPS = 30
# 사진이 있는 씬은 글 영역이 줄어드니 글자도 작게 잡는다
MAX_FONT_PHOTO, MAX_FONT_TEXT = 76, 112
# 쇼츠는 상단에 제목, 하단에 설명·버튼이 겹친다. 안전하게 쓸 수 있는 세로 구간.
SAFE_TOP, SAFE_BOTTOM = 150, 1600
DEFAULT_SECONDS = 5.0


def _resolve_photo(src: str, out_dir: Path, idx: int, base_dir: Path | None):
    """로컬 경로 또는 URL을 받아 로컬 파일 경로로 돌려준다.

    URL은 빌드 시점에 내려받는다 (GitHub Actions 러너는 외부망이 열려 있다).
    ⚠️ 공공누리 제1유형·CC 라이선스 등 상업적 이용이 허용된 출처만 쓸 것.
       언론사 보도사진(나무위키 등에 올라온 것 포함)은 저작권 침해다.
    """
    if str(src).startswith(("http://", "https://")):
        import urllib.request
        ext = Path(str(src).split("?")[0]).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        dst = out_dir / f"photo{idx:02d}{ext}"
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
                f.write(r.read())
            return dst
        except Exception as e:
            print(f"[warn] 사진을 받지 못했습니다({src}): {e} — 글자만으로 만듭니다.")
            return None
    p = (base_dir / src) if base_dir else Path(src)
    if not p.exists():
        print(f"[warn] 사진을 찾지 못했습니다: {p} — 글자만으로 만듭니다.")
        return None
    return p


def _data_uri(path: Path) -> str:
    """사진을 파일 경로가 아니라 data URI로 심는다.
    렌더링 시점에 외부 파일 로딩을 기다릴 필요가 없어 누락이 안 생긴다."""
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def build_scene(kicker, text, note, handle, step, accent="economy", theme="dark",
                photo=None, credit=None):
    tpl = (CARDS / "template_short.html").read_text(encoding="utf-8")
    tpl = _inline_css(tpl, theme)

    if photo:
        tpl = tpl.replace("__PHOTO__", _data_uri(Path(photo)))
        tpl = tpl.replace("__PHOTOCLS__", "credited" if credit else "")
        if credit:
            tpl = tpl.replace("__CREDIT__", esc(credit))
        else:
            tpl = re.sub(r"<!--CREDIT_START-->.*?<!--CREDIT_END-->", "", tpl, flags=re.S)
    else:
        tpl = re.sub(r"<!--PHOTO_START-->.*?<!--PHOTO_END-->", "", tpl, flags=re.S)

    tpl = tpl.replace("__BODYCLS__", "has-photo" if photo else "")
    tpl = tpl.replace("__ACCENT__", accent)
    tpl = tpl.replace("__KICKER__", esc(kicker))
    tpl = tpl.replace("__TEXT__", rich(text, accent).replace("\n", "<br>"))
    tpl = tpl.replace("__HANDLE__", esc(handle))
    tpl = tpl.replace("__STEP__", esc(step))
    if note:
        tpl = tpl.replace("__NOTE__", rich(note, accent).replace("\n", "<br>"))
    else:
        tpl = re.sub(r"<!--NOTE_START-->.*?<!--NOTE_END-->", "", tpl, flags=re.S)
    return tpl


def render_scenes(short: dict, out_dir: Path, handle: str, theme: str = "dark",
                  base_dir: Path | None = None) -> list[Path]:
    """씬 목록을 1080x1920 PNG로 렌더링한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = short["scenes"]
    kicker = short.get("kicker", "오늘의 경제")
    paths = []

    # 1) 사진·차트를 먼저 만들어 둔다. render_chart가 playwright를 따로 열기 때문에
    #    아래 브라우저 세션 안에서 호출하면 중첩 에러가 난다.
    photos: dict[int, Path | None] = {}
    for i, sc in enumerate(scenes, 1):
        if sc.get("chart"):
            # 지표는 남의 차트를 캡처하지 않고 우리가 직접 그린다
            photos[i] = render_chart(sc["chart"], out_dir / f"chart{i:02d}.png", theme)
        elif sc.get("photo"):
            photos[i] = _resolve_photo(sc["photo"], out_dir, i, base_dir)
        else:
            photos[i] = None

    # 2) 씬 렌더링
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        for i, sc in enumerate(scenes, 1):
            photo = photos[i]
            html = build_scene(
                sc.get("kicker", kicker), sc["text"], sc.get("note"), handle,
                f"{i}/{len(scenes)}", accent=sc.get("accent", "economy"), theme=theme,
                photo=photo, credit=sc.get("credit"),
            )
            tmp = out_dir / f"_tmp_short_{i}.html"
            tmp.write_text(html, encoding="utf-8")
            page.goto(f"file://{tmp.resolve()}")
            page.evaluate("() => document.fonts.ready")
            # 글자가 많은 씬은 자동으로 줄여 안전 구간 안에 넣는다
            # 글이 위, 사진이 아래다. 사진이 있으면 글은 상단 구간만 쓴다.
            top = SAFE_TOP
            bottom = SAFE_BOTTOM if not photo else 780
            max_font = MAX_FONT_PHOTO if photo else MAX_FONT_TEXT
            _fit_block(page, ".stage", "h1", top, bottom, 44, max_font)
            out = out_dir / f"s{i:02d}.png"
            page.screenshot(path=str(out))
            tmp.unlink()
            paths.append(out)
        browser.close()
    return paths


def _audio_seconds(path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def build_short_video(paths: list[Path], out_path: Path, seconds: list[float],
                      narration=None, tail: float = 0.6) -> Path:
    """씬 PNG를 이어붙여 쇼츠 MP4를 만든다.

    narration을 주면 그 길이(+tail)에 맞춰 씬 시간을 비율대로 다시 배분한다.
    대본을 고쳐 쓰면 영상 길이도 알아서 따라간다.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg가 없습니다.")
    if len(paths) != len(seconds):
        raise ValueError("씬 수와 시간 수가 다릅니다.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if narration:
        target = _audio_seconds(narration) + tail
        ratio = target / sum(seconds)
        seconds = [s * ratio for s in seconds]
    total = sum(seconds)

    listing = "".join(
        f"file '{p.resolve()}'\nduration {d:.3f}\n" for p, d in zip(paths, seconds)
    ) + f"file '{paths[-1].resolve()}'\n"
    list_file = out_path.parent / "_short_list.txt"
    list_file.write_text(listing, encoding="utf-8")

    if narration:
        audio_in = ["-i", str(narration)]
        audio_filter = []
    else:
        audio_in = ["-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100"]
        audio_filter = []

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        *audio_in,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-vsync", "cfr",
        "-c:a", "aac", "-b:a", "160k",
        *audio_filter,
        "-t", f"{total:.2f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패:\n{proc.stderr[-2000:]}")
    return out_path


def build_short(news: dict, out_dir: Path, handle: str, narration=None,
                base_dir: Path | None = None) -> Path:
    short = news.get("short")
    if not short:
        raise ValueError("news.json에 short 블록이 없습니다.")
    paths = render_scenes(short, out_dir, handle, theme=news.get("theme", "dark"),
                          base_dir=base_dir)
    seconds = [float(sc.get("seconds", DEFAULT_SECONDS)) for sc in short["scenes"]]
    return build_short_video(paths, out_dir / "short.mp4", seconds, narration=narration)


if __name__ == "__main__":
    import json, sys
    news = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "out_short"
    narr = sys.argv[3] if len(sys.argv) > 3 else None
    print(build_short(news, out, "econtech.kr", narration=narr))
