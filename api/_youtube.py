import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def get_env_api_key() -> str:
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY environment variable is required to fetch YouTube comments."
        )
    return api_key


def extract_video_id_from_url(url: str) -> Optional[str]:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc in {"youtu.be"}:
            # Short link: https://youtu.be/<id>
            vid = parsed.path.lstrip("/")
            return vid or None
        if parsed.netloc.endswith("youtube.com"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]
            # Embedded or share formats
            match = re.search(r"/embed/([A-Za-z0-9_-]{11})", parsed.path)
            if match:
                return match.group(1)
        # As a fallback, try to match a plausible 11-char id in the URL
        match = re.search(r"([A-Za-z0-9_-]{11})", url)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def normalize_params(max_results: Optional[int], order: Optional[str]) -> Tuple[int, str]:
    mr = 20 if max_results is None else max(1, min(int(max_results), 100))
    od = (order or "relevance").lower()
    if od not in {"relevance", "time"}:
        od = "relevance"
    return mr, od


def _http_get(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.get(endpoint, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_comment_threads(
    video_id: str,
    api_key: str,
    max_results: int = 20,
    page_token: Optional[str] = None,
    order: str = "relevance",
    include_replies: bool = False,
    max_replies_per_thread: int = 20,
) -> Dict[str, Any]:
    # Fetch commentThreads (top-level comments)
    params = {
        "part": "snippet,replies",
        "videoId": video_id,
        "maxResults": max_results,
        "order": order,
        "textFormat": "plainText",
        "key": api_key,
    }
    if page_token:
        params["pageToken"] = page_token

    data = _http_get(f"{YOUTUBE_API_BASE}/commentThreads", params)

    items = data.get("items", [])
    next_page_token = data.get("nextPageToken")

    normalized_threads: List[Dict[str, Any]] = []

    for item in items:
        snippet = item.get("snippet", {})
        top = snippet.get("topLevelComment", {}).get("snippet", {})
        thread_id = item.get("id")
        reply_count = snippet.get("totalReplyCount", 0)

        top_comment = {
            "id": snippet.get("topLevelComment", {}).get("id"),
            "text": top.get("textDisplay"),
            "author": top.get("authorDisplayName"),
            "authorChannelId": (top.get("authorChannelId") or {}).get("value"),
            "publishedAt": top.get("publishedAt"),
            "updatedAt": top.get("updatedAt"),
            "likeCount": top.get("likeCount", 0),
            "isReply": False,
            "parentId": None,
        }

        replies_payload: List[Dict[str, Any]] = []

        # Replies included inline are limited; optionally fetch full replies
        inline_replies = (item.get("replies") or {}).get("comments") or []
        for r in inline_replies:
            rs = r.get("snippet", {})
            replies_payload.append(
                {
                    "id": r.get("id"),
                    "text": rs.get("textDisplay"),
                    "author": rs.get("authorDisplayName"),
                    "authorChannelId": (rs.get("authorChannelId") or {}).get("value"),
                    "publishedAt": rs.get("publishedAt"),
                    "updatedAt": rs.get("updatedAt"),
                    "likeCount": rs.get("likeCount", 0),
                    "isReply": True,
                    "parentId": rs.get("parentId"),
                }
            )

        if include_replies and reply_count and len(replies_payload) < reply_count:
            # Fetch remaining replies via comments.list
            parent_id = top_comment["id"]
            fetched = 0
            next_token = None
            while fetched < max_replies_per_thread:
                limit = min(100, max_replies_per_thread - fetched)
                rp = {
                    "part": "snippet",
                    "parentId": parent_id,
                    "maxResults": limit,
                    "textFormat": "plainText",
                    "key": api_key,
                }
                if next_token:
                    rp["pageToken"] = next_token
                rdata = _http_get(f"{YOUTUBE_API_BASE}/comments", rp)
                ritems = rdata.get("items", [])
                for r in ritems:
                    rs = r.get("snippet", {})
                    replies_payload.append(
                        {
                            "id": r.get("id"),
                            "text": rs.get("textDisplay"),
                            "author": rs.get("authorDisplayName"),
                            "authorChannelId": (rs.get("authorChannelId") or {}).get("value"),
                            "publishedAt": rs.get("publishedAt"),
                            "updatedAt": rs.get("updatedAt"),
                            "likeCount": rs.get("likeCount", 0),
                            "isReply": True,
                            "parentId": rs.get("parentId"),
                        }
                    )
                fetched += len(ritems)
                next_token = rdata.get("nextPageToken")
                if not next_token or not ritems:
                    break

        normalized_threads.append(
            {
                "threadId": thread_id,
                "topLevelComment": top_comment,
                "replyCount": reply_count,
                "replies": replies_payload,
            }
        )

    return {
        "videoId": video_id,
        "nextPageToken": next_page_token,
        "threads": normalized_threads,
    }
