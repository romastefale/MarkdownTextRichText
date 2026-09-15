from __future__ import annotations

import re
from urllib.parse import quote, unquote

from aiogram.types import (
    BufferedInputFile,
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaVoiceNote,
    InputRichMessage,
    InputRichMessageMedia,
)

from mdtxtrt.conversion.legacy_projection import CanonicalDocument
from mdtxtrt.conversion.markdown import to_markdown
from mdtxtrt.conversion.telegram_html import to_html
from mdtxtrt.telegram_formats import contains_semantic_entities, explicit_blocks_from_markdown

REMOTE_RE = re.compile(
    r"tg://(photo|video|document|audio)\?id=([A-Za-z0-9_-]{1,128})"
    r"(?:&amp;|&)file=([^&\s\"'>)]+)"
    r"(?:(?:&amp;|&)kind=(animation|voice))?",
    re.IGNORECASE,
)
OFFICIAL_RE = re.compile(r"tg://(photo|video|document|audio)\?id=([A-Za-z0-9_-]{1,128})", re.IGNORECASE)


def _input_media(kind: str, media):
    value = (kind or "document").lower()
    if value == "photo":
        return InputMediaPhoto(media=media)
    if value == "video":
        return InputMediaVideo(media=media)
    if value == "animation":
        return InputMediaAnimation(media=media)
    if value == "audio":
        return InputMediaAudio(media=media)
    if value in {"voice", "voice_note"}:
        return InputMediaVoiceNote(media=media)
    return InputMediaDocument(media=media)


def _stored_media(store, user_id: int, media_id: str, kind: str):
    item = store.get_blob(user_id, media_id)
    upload = BufferedInputFile(item["data"], filename=item["name"] or "media.bin")
    return _input_media(kind, upload)


def build_input_rich_message(document: dict, store, user_id: int, *, format_mode: str = "rich_markdown") -> InputRichMessage:
    source = to_markdown(document)
    markdown, refs = CanonicalDocument.from_markdown(source).telegram_markdown()
    media: list[InputRichMessageMedia] = []
    media_ids: set[str] = set()
    for ref in refs:
        media.append(InputRichMessageMedia(id=ref.media_id, media=_stored_media(store, user_id, ref.media_id, ref.kind)))
        media_ids.add(ref.media_id)

    def restore_remote(match: re.Match) -> str:
        scheme, reference_id, encoded_file_id, marker = match.groups()
        file_id = unquote(encoded_file_id)
        kind = marker or scheme.lower()
        if scheme.lower() == "document":
            kind = "document"
        elif scheme.lower() == "photo":
            kind = "photo"
        elif scheme.lower() == "audio" and not marker:
            kind = "audio"
        elif scheme.lower() == "video" and not marker:
            kind = "video"
        if reference_id in media_ids:
            raise ValueError("Identificador de mídia duplicado no documento.")
        media.append(InputRichMessageMedia(id=reference_id, media=_input_media(kind, file_id)))
        media_ids.add(reference_id)
        return f"tg://{scheme.lower()}?id={reference_id}"

    markdown = REMOTE_RE.sub(restore_remote, markdown)
    referenced = {match.group(2) for match in OFFICIAL_RE.finditer(markdown)}
    missing = referenced - media_ids
    if missing:
        raise ValueError("O documento contém referência de mídia sem arquivo associado.")
    media_by_id = {item.id: item.media for item in media}
    if format_mode == "html":
        return InputRichMessage(html=to_html(document), media=media or None)
    if format_mode == "blocks" or contains_semantic_entities(markdown):
        blocks = explicit_blocks_from_markdown(markdown, media_by_id)
        return InputRichMessage(blocks=blocks, skip_entity_detection=True)
    if format_mode != "rich_markdown":
        raise ValueError("Formato Telegram deve ser rich_markdown, html ou blocks.")
    return InputRichMessage(markdown=markdown, media=media or None)


def remote_reference(kind: str, reference_id: str, file_id: str) -> str:
    value = kind.lower()
    if value == "animation":
        scheme, marker = "video", "&kind=animation"
    elif value in {"voice", "voice_note"}:
        scheme, marker = "audio", "&kind=voice"
    elif value in {"photo", "video", "document", "audio"}:
        scheme, marker = value, ""
    else:
        scheme, marker = "document", ""
    return f"tg://{scheme}?id={reference_id}&file={quote(file_id, safe='')}{marker}"
