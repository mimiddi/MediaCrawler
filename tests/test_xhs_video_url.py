# -*- coding: utf-8 -*-
"""Tests for Xiaohongshu video URL extraction."""

from store.xhs import get_video_url_arr


def test_origin_video_key_has_priority():
    note_item = {
        "type": "video",
        "video": {
            "consumer": {"originVideoKey": "spectrum/abc"},
            "media": {"stream": {"h264": [{"masterUrl": "http://cdn/fallback.mp4"}]}},
        },
    }
    assert get_video_url_arr(note_item) == [
        "http://sns-video-bd.xhscdn.com/spectrum/abc"
    ]


def test_picks_highest_resolution_across_codecs_camel_case():
    note_item = {
        "type": "video",
        "video": {
            "consumer": {},
            "media": {
                "stream": {
                    "h265": [
                        {"masterUrl": "http://cdn/720.mp4", "backupUrls": ["http://cdn/720b.mp4"], "height": 720}
                    ],
                    "h264": [
                        {"masterUrl": "http://cdn/1080.mp4", "backupUrls": ["http://cdn/1080b.mp4"], "height": 1080}
                    ],
                }
            },
        },
    }
    assert get_video_url_arr(note_item) == ["http://cdn/1080.mp4"]


def test_supports_snake_case_html_fallback():
    note_item = {
        "type": "video",
        "video": {
            "consumer": {},
            "media": {
                "stream": {
                    "h264": [
                        {"master_url": "http://cdn/720.mp4", "backup_urls": ["http://cdn/720b.mp4"], "height": 720}
                    ],
                    "av1": [
                        {"master_url": "http://cdn/1440.mp4", "backup_urls": ["http://cdn/1440b.mp4"], "height": 1440}
                    ],
                }
            },
        },
    }
    assert get_video_url_arr(note_item) == ["http://cdn/1440.mp4"]


def test_falls_back_to_backup_url():
    note_item = {
        "type": "video",
        "video": {
            "consumer": {},
            "media": {
                "stream": {
                    "h264": [
                        {"master_url": "", "backup_urls": ["http://cdn/backup.mp4"], "height": 720}
                    ]
                }
            },
        },
    }
    assert get_video_url_arr(note_item) == ["http://cdn/backup.mp4"]


def test_returns_empty_for_missing_video_info():
    assert get_video_url_arr({"type": "video"}) == []
    assert get_video_url_arr({"type": "normal"}) == []
