#!/usr/bin/env python3
"""
카드 PNG -> MP4. 두 가지 출력을 만든다.

1) build_card_clips()  카드 한 장 = MP4 한 개 (1080x1350). 캐러셀에 영상 슬라이드로 올린다.
2) build_reel()        카드 전체를 이어붙인 한 개의 릴스 MP4 (1080x1920).

둘 다 정지 화면이고 무음 오디오 트랙을 넣는다.

카드는 그대로 두고 파일 형식만 영상으로 바꾼다.
1080x1350 카드를 1080x1920 캔버스 위에 얹되, 배경은 카드와 같은 그라데이션으로 채워
검은 레터박스가 생기지 않게 한다. 카드를 살짝 위로 올려 하단에 릴스 UI(캡션·버튼)가
가릴 공간을 남긴다.
"""
import subprocess
import shutil
from pathlib import Path
from PIL import Image

W, H = 1080, 1920
CARD_W, CARD_H = 1080, 1350
CARD_TOP = 215          # 아래쪽에 355px 확보 — 릴스 캡션/버튼이 덮는 영역
FPS = 30

THEME_BG = {
    "dark":  ("#0e1420", "#121a28"),
    "light": ("#f7f4ea", "#efe9d8"),
}

# 카드 종류별 화면 유지 시간(초). 8장 기준 총 22.5초.
DEFAULT_DURATIONS = {
    "cover": 2.5,
    "hook":  2.5,
    "item":  3.0,
    "outro": 2.5,
}


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _canvas(theme: str) -> Image.Image:
    """카드와 같은 세로 그라데이션으로 1080x1920 배경을 만든다."""
    top, bot = (_hex(x) for x in THEME_BG.get(theme, THEME_BG["dark"]))
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        row = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = row
    return img


def _kind(path: Path) -> str:
    """01_cover.png -> 'cover'"""
    stem = path.stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def build_reel(paths: list[Path], out_path: Path, theme: str = "dark",
               durations: dict | None = None) -> Path:
    """PNG 목록을 순서대로 이어붙인 릴스 MP4를 만들고 경로를 반환한다."""
    if not paths:
        raise ValueError("카드가 없습니다.")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg가 없습니다. 러너에 ffmpeg를 설치하세요.")

    dur = {**DEFAULT_DURATIONS, **(durations or {})}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent / "_reel_frames"
    work.mkdir(exist_ok=True)

    base = _canvas(theme)
    frames: list[tuple[Path, float]] = []
    for p in paths:
        card = Image.open(p).convert("RGB")
        if card.size != (CARD_W, CARD_H):
            card = card.resize((CARD_W, CARD_H), Image.LANCZOS)
        frame = base.copy()
        frame.paste(card, (0, CARD_TOP))
        fp = work / f"{p.stem}.png"
        frame.save(fp)
        frames.append((fp, float(dur.get(_kind(p), dur["item"]))))

    # concat demuxer용 목록. 마지막 파일은 한 번 더 적어야 마지막 duration이 반영된다.
    listing = "".join(
        f"file '{fp.resolve()}'\nduration {d}\n" for fp, d in frames
    ) + f"file '{frames[-1][0].resolve()}'\n"
    list_file = work / "list.txt"
    list_file.write_text(listing, encoding="utf-8")

    total = sum(d for _, d in frames)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        # 무음 오디오 트랙 — 없으면 일부 플레이어/업로드 경로에서 문제가 생긴다
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-vsync", "cfr",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{total:.2f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패:\n{proc.stderr[-2000:]}")

    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    return out_path


if __name__ == "__main__":
    import sys
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out"
    theme = sys.argv[2] if len(sys.argv) > 2 else "dark"
    pngs = sorted(out_dir.glob("[0-9][0-9]_*.png"))
    print(build_reel(pngs, out_dir / "reel.mp4", theme))


# ── 카드별 개별 클립 ──────────────────────────────────────────────
# 캐러셀 슬라이드용. 카드 크기(1080x1350) 그대로, 패딩 없음.
# 인스타 영상 슬라이드는 최소 3초여야 해서 기본 5초로 잡는다.
CLIP_SECONDS = 5.0


def build_card_clips(paths: list[Path], out_dir: Path,
                     seconds: float = CLIP_SECONDS) -> list[Path]:
    """카드 PNG 한 장당 MP4 한 개를 만들어 경로 목록(순서 유지)을 반환한다."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg가 없습니다. 러너에 ffmpeg를 설치하세요.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    seconds = max(3.0, float(seconds))   # 인스타 최소 3초
    clips = []
    for p in paths:
        out = out_dir / f"{p.stem}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(p),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v", "-map", "1:a",
            "-t", f"{seconds:.2f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 실패({p.name}):\n{proc.stderr[-1500:]}")
        clips.append(out)
    return clips
