#!/usr/bin/env python3
"""PNG 파일들을 Cloudinary(unsigned upload)에 올리고 공개 URL 목록을 반환한다."""
from pathlib import Path
import requests


def upload_all(paths: list[Path], cloud_name: str, upload_preset: str) -> list[str]:
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    urls = []
    for p in paths:
        with open(p, "rb") as f:
            resp = requests.post(
                url,
                data={"upload_preset": upload_preset},
                files={"file": (p.name, f, "image/png")},
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        urls.append(data["secure_url"])
    return urls


if __name__ == "__main__":
    import sys, json
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "out"
    pngs = sorted(out_dir.glob("*.png"))
    urls = upload_all(pngs, cfg["cloudinary"]["cloud_name"], cfg["cloudinary"]["upload_preset"])
    print("\n".join(urls))


def upload_video(path, cloud_name: str, upload_preset: str) -> str:
    """MP4 한 개를 Cloudinary에 올리고 공개 URL을 반환한다."""
    from pathlib import Path as _P
    p = _P(path)
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"
    with open(p, "rb") as f:
        resp = requests.post(
            url,
            data={"upload_preset": upload_preset},
            files={"file": (p.name, f, "video/mp4")},
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()["secure_url"]


def upload_videos(paths, cloud_name: str, upload_preset: str) -> list[str]:
    """MP4 여러 개를 순서대로 올리고 공개 URL 목록을 반환한다."""
    return [upload_video(p, cloud_name, upload_preset) for p in paths]
