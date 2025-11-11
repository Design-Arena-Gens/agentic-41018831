from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
from typing import Any, Dict

from ._youtube import (
    extract_video_id_from_url,
    fetch_comment_threads,
    get_env_api_key,
    normalize_params,
)


def _parse_query(path: str) -> Dict[str, Any]:
    parsed = urllib.parse.urlparse(path)
    qs = urllib.parse.parse_qs(parsed.query)
    def get_one(name: str) -> str:
        v = qs.get(name)
        return v[0] if v else ""
    return {
        "url": get_one("url").strip(),
        "videoId": get_one("videoId").strip(),
        "pageToken": get_one("pageToken").strip() or None,
        "order": get_one("order").strip() or None,
        "includeReplies": (get_one("includeReplies").lower() in {"1","true","yes","on"}),
        "maxResults": int(get_one("maxResults")) if get_one("maxResults") else None,
        "maxRepliesPerThread": int(get_one("maxRepliesPerThread")) if get_one("maxRepliesPerThread") else 20,
    }


class handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: Dict[str, Any]):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            q = _parse_query(self.path)

            video_id = q["videoId"]
            if not video_id and q["url"]:
                video_id = extract_video_id_from_url(q["url"]) or ""

            if not video_id:
                self._send(400, {"error": "Missing 'videoId' or parsable 'url' query param."})
                return

            try:
                api_key = get_env_api_key()
            except RuntimeError as e:
                self._send(500, {"error": str(e)})
                return

            max_results, order = normalize_params(q["maxResults"], q["order"])

            data = fetch_comment_threads(
                video_id=video_id,
                api_key=api_key,
                max_results=max_results,
                page_token=q["pageToken"],
                order=order,
                include_replies=q["includeReplies"],
                max_replies_per_thread=q["maxRepliesPerThread"],
            )

            self._send(200, data)
        except Exception as ex:
            self._send(500, {"error": "Internal server error", "details": str(ex)})
