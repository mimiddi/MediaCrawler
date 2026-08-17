#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill local media for MediaCrawler Xiaohongshu JSON exports.

Reads exported note/comment JSON files, downloads every media URL referenced in
``image_list`` / ``video_url`` (notes) and ``pictures`` (comments) to local disk,
then writes the local relative paths back into new ``local_image_paths`` /
``local_video_paths`` / ``local_pictures`` fields on each record.

The original URL fields are kept unchanged, records are never merged, and
downloads are de-duplicated by URL.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx


BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "xhs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "*/*",
}

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "application/octet-stream": None,
}


def split_urls(value: str) -> List[str]:
    if not value or not str(value).strip():
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def fallback_ext(url: str, kind: str) -> str:
    path = urlsplit(url).path.lower()
    for ext in (".jpeg", ".jpg", ".png", ".webp", ".gif", ".mp4"):
        if ext in path:
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg" if kind in ("img", "comment_img") else ".mp4"


def resolve_ext(content_type: str, fallback: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    return CONTENT_TYPE_EXT.get(ct) or fallback


def download(url: str, kind: str, insecure: bool = False) -> Tuple[bytes, str, str]:
    """Download bytes and return (content, extension, content_type)."""
    last_error: Optional[Exception] = None
    for verify in (not insecure, False):
        try:
            with httpx.Client(
                headers=HEADERS,
                follow_redirects=True,
                timeout=30.0,
                verify=verify,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                ext = resolve_ext(content_type, fallback_ext(url, kind))
                return response.content, ext, content_type
        except httpx.HTTPError as exc:
            last_error = exc
            if verify is False:
                break
    raise RuntimeError(f"{type(last_error).__name__}: {last_error}")


def media_kind_dir(note_id: str, kind: str) -> pathlib.Path:
    if kind == "video":
        return DATA_DIR / "videos" / note_id
    if kind == "comment_img":
        return DATA_DIR / "comment_images" / note_id
    return DATA_DIR / "images" / note_id


def make_filename(
    note_id: str,
    kind: str,
    comment_id: Optional[str],
    ext: str,
    counters: Dict[Tuple[str, str, Optional[str]], int],
) -> str:
    key = (note_id, kind, comment_id)
    index = counters.get(key, 0)
    counters[key] = index + 1
    if kind == "video":
        return f"{note_id}_video_{index}{ext}"
    if kind == "comment_img":
        return f"{note_id}_{comment_id}_img_{index}{ext}"
    return f"{note_id}_img_{index}{ext}"


def to_relative(path: pathlib.Path) -> str:
    return os.path.relpath(path, BASE_DIR).replace("\\", "/")


def ensure_downloaded(
    url: str,
    note_id: str,
    kind: str,
    comment_id: Optional[str],
    cache: Dict[str, Optional[str]],
    counters: Dict[Tuple[str, str, Optional[str]], int],
    downloaded: List[Dict],
    failed: List[Dict],
    insecure: bool,
) -> Optional[str]:
    if url in cache:
        return cache[url]

    try:
        content, ext, content_type = download(url, kind, insecure=insecure)
    except Exception as exc:  # noqa: BLE001 - report every failure individually
        failed.append(
            {
                "url": url,
                "note_id": note_id,
                "comment_id": comment_id,
                "kind": kind,
                "reason": str(exc),
            }
        )
        cache[url] = None
        return None

    filename = make_filename(note_id, kind, comment_id, ext, counters)
    target_dir = media_kind_dir(note_id, kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_bytes(content)
    rel_path = to_relative(target_path)
    cache[url] = rel_path
    downloaded.append(
        {
            "url": url,
            "local_path": rel_path,
            "note_id": note_id,
            "comment_id": comment_id,
            "kind": kind,
            "content_type": content_type,
            "size_bytes": len(content),
        }
    )
    print(f"[ok] {url} -> {rel_path}", flush=True)
    return rel_path


def process_contents(
    records: List[Dict],
    insecure: bool,
    cache: Dict[str, Optional[str]],
    counters: Dict[Tuple[str, str, Optional[str]], int],
    downloaded: List[Dict],
    failed: List[Dict],
) -> None:
    for record in records:
        note_id = record.get("note_id")
        image_urls = split_urls(record.get("image_list"))
        video_urls = split_urls(record.get("video_url"))

        record["local_image_paths"] = [
            path
            for url in image_urls
            if (path := ensure_downloaded(url, note_id, "img", None, cache, counters, downloaded, failed, insecure))
        ]
        record["local_video_paths"] = [
            path
            for url in video_urls
            if (path := ensure_downloaded(url, note_id, "video", None, cache, counters, downloaded, failed, insecure))
        ]


def process_comments(
    records: List[Dict],
    insecure: bool,
    cache: Dict[str, Optional[str]],
    counters: Dict[Tuple[str, str, Optional[str]], int],
    downloaded: List[Dict],
    failed: List[Dict],
) -> None:
    for record in records:
        note_id = record.get("note_id")
        comment_id = record.get("comment_id")
        picture_urls = split_urls(record.get("pictures"))
        record["local_pictures"] = [
            path
            for url in picture_urls
            if (path := ensure_downloaded(url, note_id, "comment_img", comment_id, cache, counters, downloaded, failed, insecure))
        ]


def write_json(path: pathlib.Path, data: List[Dict]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def derive_date(content_path: pathlib.Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", content_path.stem)
    return match.group(1) if match else "unknown"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--content-json",
        type=pathlib.Path,
        default=DATA_DIR / "json" / "detail_contents_2026-08-17.json",
    )
    parser.add_argument(
        "--comment-json",
        type=pathlib.Path,
        default=DATA_DIR / "json" / "detail_comments_2026-08-17.json",
    )
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification")
    args = parser.parse_args(argv)

    content_path = args.content_json
    comment_path = args.comment_json
    date = derive_date(content_path)

    content_records = json.loads(content_path.read_text(encoding="utf-8"))
    comment_records = json.loads(comment_path.read_text(encoding="utf-8"))

    cache: Dict[str, Optional[str]] = {}
    counters: Dict[Tuple[str, str, Optional[str]], int] = {}
    downloaded: List[Dict] = []
    failed: List[Dict] = []

    process_contents(content_records, args.insecure, cache, counters, downloaded, failed)
    process_comments(comment_records, args.insecure, cache, counters, downloaded, failed)

    content_out = content_path.with_name(f"{content_path.stem}_with_media.json")
    comment_out = comment_path.with_name(f"{comment_path.stem}_with_media.json")
    write_json(content_out, content_records)
    write_json(comment_out, comment_records)

    report = {
        "summary": {
            "total_unique_urls": len(cache),
            "downloaded": len(downloaded),
            "failed": len(failed),
        },
        "downloaded": downloaded,
        "failed": failed,
    }
    report_path = content_path.with_name(f"media_download_report_{date}.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )

    print(f"[done] content -> {content_out}", flush=True)
    print(f"[done] comments -> {comment_out}", flush=True)
    print(f"[done] report -> {report_path}", flush=True)
    print(
        f"[summary] downloaded={len(downloaded)} failed={len(failed)}",
        flush=True,
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
