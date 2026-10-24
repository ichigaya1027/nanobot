"""Place late-admitted observations before QQ action receipts in model input."""

from __future__ import annotations

from collections import defaultdict
from itertools import groupby
from typing import Any, cast

from nanobot.channels.napcat.group_agent import GroupMessage
from nanobot.channels.napcat.group_rendering import render_group_messages
from nanobot.runtime_context import RUNTIME_CONTEXT_MESSAGE_META
from nanobot.utils.helpers import image_placeholder_text


def _fragment(
    source: dict[str, Any], records: list[dict[str, Any]],
    original_text: str, *, last: bool,
) -> dict[str, Any]:
    text = render_group_messages([GroupMessage.parse(record) for record in records])
    paths = {path for record in records for path in record["media"]}
    all_paths = [
        path for record in source["context_metadata"]["napcat_observation"]
        for path in record["media"]
    ]
    content = source["content"]
    fragment = dict(source)
    fragment["context_metadata"] = {"napcat_observation": records}
    if isinstance(content, str):
        if not content.startswith(original_text):
            raise ValueError("Group observation text does not match its records")
        suffix = content[len(original_text):]
        breadcrumbs = "\n" + "\n".join(image_placeholder_text(path) for path in all_paths)
        media_suffix = ""
        if all_paths and suffix.endswith(breadcrumbs):
            suffix = suffix[:-len(breadcrumbs)]
            media_suffix = "".join(
                "\n" + image_placeholder_text(path) for path in all_paths if path in paths
            )
        fragment["content"] = text + (suffix if last else "") + media_suffix
    else:
        blocks: list[dict[str, Any]] = []
        for block in cast(list[dict[str, Any]], content):
            if block.get("type") == "image_url":
                if block["_meta"]["path"] in paths:
                    blocks.append(block)
            elif block.get("type") == "text" and block["text"].startswith(original_text):
                suffix = block["text"][len(original_text):] if last else ""
                blocks.append({**block, "text": text + suffix})
            elif block.get("text") in {image_placeholder_text(path) for path in all_paths}:
                if block["text"] in {image_placeholder_text(path) for path in paths}:
                    blocks.append(block)
            elif last:
                blocks.append(block)
        fragment["content"] = blocks
    if not last and "_meta" in fragment:
        fragment["_meta"] = {
            key: value for key, value in fragment["_meta"].items()
            if key != RUNTIME_CONTEXT_MESSAGE_META
        }
    return fragment


def prepare_group_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder a copy; admission, wakeups and persisted transcript stay intact.

    Only move observations across receipts already preceding their batch. The
    assistant's tool request therefore stays ahead of the inserted user input.
    A batch spanning a receipt is split and rendered with fresh line prefixes.
    """
    receipts = [
        (index, message["context_metadata"]["napcat_action"])
        for index, message in enumerate(messages)
        if message.get("role") == "tool"
        and "napcat_action" in message.get("context_metadata", {})
    ]
    before: dict[int, list[dict[str, Any]]] = defaultdict(list)
    kept: list[list[dict[str, Any]]] = [[] for _ in messages]
    for index, message in enumerate(messages):
        records = message.get("context_metadata", {}).get("napcat_observation")
        if message.get("role") != "user" or not records:
            kept[index].append(message)
            continue
        destinations = [
            next((
                target for target, receipt in receipts
                if target < index and receipt["group_id"] == record["group_id"]
                and record["received_at_ns"] <= receipt["completed_at_ns"]
            ), index)
            for record in records
        ]
        if all(target == index for target in destinations):
            kept[index].append(message)
            continue
        original_text = render_group_messages([GroupMessage.parse(record) for record in records])
        for target, group in groupby(zip(destinations, records), key=lambda item: item[0]):
            part = [record for _, record in group]
            destination = kept[index] if target == index else before[target]
            destination.append(_fragment(
                message, part, original_text, last=part[-1] is records[-1],
            ))
    return [
        message
        for index in range(len(messages))
        for message in [*before[index], *kept[index]]
    ]
