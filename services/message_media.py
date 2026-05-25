"""Normalize image and attachment payloads for chat messages."""
from __future__ import annotations

from typing import Any


MAX_MEDIA_ITEMS = 32
MAX_MEDIA_FIELD_LENGTH = 2048


def clean_text(value: Any, max_length: int = MAX_MEDIA_FIELD_LENGTH) -> str:
    return str(value or "").strip()[:max_length]


def normalize_images(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("images 必须是数组")

    images: list[dict[str, Any]] = []
    for item in value[:MAX_MEDIA_ITEMS]:
        if isinstance(item, str):
            source = clean_text(item)
            image = {"url": source}
        elif isinstance(item, dict):
            source = clean_text(
                item.get("url") or item.get("src") or item.get("path")
            )
            image = {
                "url": source,
                "alt": clean_text(item.get("alt") or item.get("name"), 200),
                "title": clean_text(item.get("title"), 200),
            }
            image = {key: val for key, val in image.items() if val}
        else:
            raise ValueError("images 只支持字符串或对象")

        if not image.get("url"):
            raise ValueError("images 中存在空图片地址")
        images.append(image)
    return images


def normalize_attachments(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("attachments 必须是数组")

    allowed_keys = {
        "name",
        "url",
        "src",
        "path",
        "type",
        "mime_type",
        "mimeType",
        "alt",
        "title",
        "size",
    }
    attachments: list[dict[str, Any]] = []
    for item in value[:MAX_MEDIA_ITEMS]:
        if isinstance(item, str):
            attachment = {"url": clean_text(item)}
        elif isinstance(item, dict):
            attachment = {}
            for key in allowed_keys:
                if key not in item:
                    continue
                raw_value = item[key]
                if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                    attachment[key] = (
                        raw_value
                        if isinstance(raw_value, (int, float, bool))
                        else clean_text(raw_value)
                    )
            if "url" not in attachment and attachment.get("src"):
                attachment["url"] = attachment["src"]
            if "url" not in attachment and attachment.get("path"):
                attachment["url"] = attachment["path"]
            attachment = {
                key: val for key, val in attachment.items() if val not in ("", None)
            }
        else:
            raise ValueError("attachments 只支持字符串或对象")

        if not attachment:
            raise ValueError("attachments 中存在空附件")
        attachments.append(attachment)
    return attachments
