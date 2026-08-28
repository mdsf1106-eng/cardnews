#!/usr/bin/env python3
"""Instagram Platform API — 캐러셀(2~10장) 생성 및 게시, 장기 토큰 갱신."""
import time
import requests

GRAPH = "https://graph.instagram.com"


def refresh_long_lived_token(access_token: str) -> dict:
    """60일 장기 토큰을 갱신한다 (발급 후 24시간이 지난 토큰만 가능).
    반환: {"access_token": ..., "expires_in": 초단위(대략 60일)}"""
    resp = requests.get(
        f"{GRAPH}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": access_token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _create_child_container(user_id: str, image_url: str, access_token: str) -> str:
    resp = requests.post(
        f"{GRAPH}/{user_id}/media",
        data={"image_url": image_url, "is_carousel_item": "true", "access_token": access_token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _wait_until_finished(container_id: str, access_token: str, timeout_s: int = 120):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"컨테이너 처리 실패: {container_id}")
        time.sleep(3)
    raise TimeoutError(f"컨테이너 처리 시간 초과: {container_id}")


def publish_carousel(user_id: str, image_urls: list[str], caption: str, access_token: str) -> dict:
    """캐러셀(2~10장)을 만들어 게시하고 {"id": media_id, "permalink": url}를 반환한다."""
    if not (2 <= len(image_urls) <= 10):
        raise ValueError("캐러셀은 2~10장이어야 합니다.")

    child_ids = [_create_child_container(user_id, url, access_token) for url in image_urls]
    for cid in child_ids:
        _wait_until_finished(cid, access_token)

    resp = requests.post(
        f"{GRAPH}/{user_id}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    parent_id = resp.json()["id"]
    _wait_until_finished(parent_id, access_token)

    resp = requests.post(
        f"{GRAPH}/{user_id}/media_publish",
        data={"creation_id": parent_id, "access_token": access_token},
        timeout=30,
    )
    resp.raise_for_status()
    media_id = resp.json()["id"]

    resp = requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink", "access_token": access_token},
        timeout=30,
    )
    resp.raise_for_status()
    permalink = resp.json().get("permalink")

    return {"id": media_id, "permalink": permalink}
