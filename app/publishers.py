from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, BinaryIO

import requests


class PublishError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _json_or_error(response: requests.Response, action: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise PublishError(f"{action} tra ve du lieu khong hop le (HTTP {response.status_code}).") from exc
    if not response.ok:
        detail = payload.get("error") or payload
        raise PublishError(f"{action} that bai (HTTP {response.status_code}): {detail}", response.status_code)
    return payload


class TikTokPublisher:
    api_base = "https://open.tiktokapis.com"

    def __init__(self, access_token: str, session: requests.Session | None = None):
        if not access_token:
            raise PublishError("Chua cau hinh TIKTOK_ACCESS_TOKEN trong .env.")
        self.access_token = access_token
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def creator_info(self) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base}/v2/post/publish/creator_info/query/",
            headers=self.headers,
            timeout=30,
        )
        payload = _json_or_error(response, "TikTok creator info")
        if payload.get("error", {}).get("code") not in {None, "ok"}:
            error_code = payload["error"].get("code")
            raise PublishError(
                f"TikTok creator info loi: {payload['error']}",
                401 if error_code == "access_token_invalid" else None,
            )
        return payload.get("data") or {}

    def publish_video(
        self,
        video_path: Path,
        title: str,
        privacy_level: str = "SELF_ONLY",
        is_aigc: bool = True,
    ) -> dict[str, Any]:
        creator = self.creator_info()
        allowed_privacy = creator.get("privacy_level_options") or []
        if allowed_privacy and privacy_level not in allowed_privacy:
            raise PublishError(
                f"Quyen rieng tu '{privacy_level}' khong duoc tai khoan TikTok cho phep. "
                f"Lua chon hop le: {', '.join(allowed_privacy)}"
            )

        file_size = video_path.stat().st_size
        if file_size <= 64 * 1024 * 1024:
            chunk_size = file_size
        else:
            chunk_size = 10 * 1024 * 1024
        total_chunks = max(1, math.ceil(file_size / chunk_size))
        init_payload = {
            "post_info": {
                "title": title[:2200],
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
                "brand_content_toggle": False,
                "brand_organic_toggle": True,
                "is_aigc": is_aigc,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        }
        response = self.session.post(
            f"{self.api_base}/v2/post/publish/video/init/",
            headers=self.headers,
            json=init_payload,
            timeout=45,
        )
        payload = _json_or_error(response, "Khoi tao TikTok Direct Post")
        if payload.get("error", {}).get("code") not in {None, "ok"}:
            error_code = payload["error"].get("code")
            raise PublishError(
                f"TikTok init loi: {payload['error']}",
                401 if error_code == "access_token_invalid" else None,
            )
        data = payload.get("data") or {}
        upload_url = data.get("upload_url")
        publish_id = data.get("publish_id")
        if not upload_url or not publish_id:
            raise PublishError("TikTok khong tra ve upload_url/publish_id.")

        with video_path.open("rb") as video_file:
            self._upload_chunks(upload_url, video_file, file_size, chunk_size)

        return {
            "platform": "tiktok",
            "publishId": publish_id,
            "privacyLevel": privacy_level,
            "status": "processing",
        }

    def _upload_chunks(self, upload_url: str, video_file: BinaryIO, file_size: int, chunk_size: int) -> None:
        start = 0
        while start < file_size:
            chunk = video_file.read(chunk_size)
            if not chunk:
                break
            end = start + len(chunk) - 1
            response = self.session.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                },
                data=chunk,
                timeout=180,
            )
            if response.status_code not in {200, 201, 206}:
                raise PublishError(f"Upload chunk TikTok that bai (HTTP {response.status_code}): {response.text[:300]}")
            start = end + 1

    def fetch_status(self, publish_id: str) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base}/v2/post/publish/status/fetch/",
            headers=self.headers,
            json={"publish_id": publish_id},
            timeout=30,
        )
        payload = _json_or_error(response, "Kiem tra trang thai TikTok")
        if payload.get("error", {}).get("code") not in {None, "ok"}:
            raise PublishError(f"TikTok status loi: {payload['error']}")
        return payload.get("data") or {}


class FacebookReelsPublisher:
    def __init__(
        self,
        page_id: str,
        page_access_token: str,
        graph_version: str = "v26.0",
        session: requests.Session | None = None,
    ):
        if not page_id or not page_access_token:
            raise PublishError("Chua cau hinh FACEBOOK_PAGE_ID/FACEBOOK_PAGE_ACCESS_TOKEN trong .env.")
        self.page_id = page_id
        self.page_access_token = page_access_token
        self.graph_version = graph_version.strip("/") or "v26.0"
        self.session = session or requests.Session()

    @property
    def endpoint(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/video_reels"

    def publish_video(self, video_path: Path, description: str, title: str = "") -> dict[str, Any]:
        start_response = self.session.post(
            self.endpoint,
            params={"access_token": self.page_access_token, "upload_phase": "start"},
            timeout=45,
        )
        start_payload = _json_or_error(start_response, "Khoi tao Facebook Reel")
        video_id = start_payload.get("video_id")
        upload_url = start_payload.get("upload_url")
        if not video_id or not upload_url:
            raise PublishError("Facebook khong tra ve video_id/upload_url.")

        file_size = video_path.stat().st_size
        with video_path.open("rb") as video_file:
            upload_response = self.session.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {self.page_access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                },
                data=video_file,
                timeout=300,
            )
        _json_or_error(upload_response, "Upload Facebook Reel")

        finish_response = self.session.post(
            self.endpoint,
            params={
                "access_token": self.page_access_token,
                "video_id": video_id,
                "upload_phase": "finish",
                "video_state": "PUBLISHED",
                "description": description,
                "title": title or description[:80],
            },
            timeout=60,
        )
        finish_payload = _json_or_error(finish_response, "Publish Facebook Reel")
        if not finish_payload.get("success"):
            raise PublishError(f"Facebook khong xac nhan publish: {finish_payload}")
        return {
            "platform": "facebook",
            "videoId": video_id,
            "status": "processing",
        }


def publishing_config() -> dict[str, Any]:
    return {
        "tiktokConfigured": bool(os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()),
        "facebookConfigured": bool(
            os.getenv("FACEBOOK_PAGE_ID", "").strip()
            and os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
        ),
        "facebookPageId": os.getenv("FACEBOOK_PAGE_ID", "").strip(),
        "metaGraphVersion": os.getenv("META_GRAPH_VERSION", "v26.0").strip() or "v26.0",
    }


def refresh_tiktok_access_token(
    client_key: str,
    client_secret: str,
    refresh_token: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if not client_key or not client_secret or not refresh_token:
        raise PublishError("Thieu TikTok Client Key, Client Secret hoac Refresh Token de lam moi token.")
    http = session or requests.Session()
    response = http.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    payload = _json_or_error(response, "Lam moi TikTok access token")
    if payload.get("error"):
        raise PublishError(f"TikTok token refresh loi: {payload.get('error_description') or payload['error']}")
    if not payload.get("access_token") or not payload.get("refresh_token"):
        raise PublishError("TikTok token refresh khong tra ve du access_token/refresh_token.")
    return payload
