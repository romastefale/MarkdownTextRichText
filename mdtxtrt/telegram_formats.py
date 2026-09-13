"""Compilador Rich explícito adaptado da fonte física monolítica para o rebuild modular."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re

from pydantic import TypeAdapter

from aiogram.types import (
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaVoiceNote,
    InputRichBlockUnion,
)


_VOID = {"br", "hr", "img", "input", "tg-map"}
_SEMANTIC = re.compile(r"<tg-entity\b", re.I)
_MEDIA_URI = re.compile(r"^tg://(photo|video|document|audio)\?id=([A-Za-z0-9_-]{1,64})$", re.I)


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | bool] = field(default_factory=dict)
    children: list["_Node | str"] = field(default_factory=list)


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        node = _Node(tag.lower(), {name.lower(): (value if value is not None else True) for name, value in attrs})
        self.stack[-1].children.append(node)
        if node.tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        node = _Node(tag.lower(), {name.lower(): (value if value is not None else True) for name, value in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def contains_semantic_entities(source: str) -> bool:
    return bool(_SEMANTIC.search(source or ""))


def _items(value):
    if isinstance(value, list):
        return value
    return [value]


def _inline_children(node: _Node):
    result = []
    for child in node.children:
        value = _inline(child)
        result.extend(_items(value))
    result = [item for item in result if item != ""]
    if not result:
        return ""
    if len(result) == 1:
        return result[0]
    return result


def _inline(value: _Node | str):
    if isinstance(value, str):
        return value
    tag = value.tag
    inner = _inline_children(value)
    wrappers = {
        "b": "bold", "strong": "bold", "i": "italic", "em": "italic",
        "u": "underline", "ins": "underline", "s": "strikethrough",
        "strike": "strikethrough", "del": "strikethrough", "code": "code",
        "mark": "marked", "sub": "subscript", "sup": "superscript",
        "tg-spoiler": "spoiler",
    }
    if tag in wrappers:
        return {"type": wrappers[tag], "text": inner}
    if tag == "br":
        return "\n"
    if tag == "tg-emoji":
        return {"type": "custom_emoji", "custom_emoji_id": str(value.attrs.get("emoji-id") or ""), "alternative_text": _plain(inner)}
    if tag == "tg-time":
        return {"type": "date_time", "text": inner, "unix_time": int(value.attrs.get("unix") or 0), "date_time_format": str(value.attrs.get("format") or "")}
    if tag == "tg-math":
        return {"type": "mathematical_expression", "expression": _plain(inner)}
    if tag == "tg-reference":
        return {"type": "reference", "text": inner, "name": str(value.attrs.get("name") or "")}
    if tag == "tg-entity":
        typ = str(value.attrs.get("type") or "")
        fields = {
            "mention": "username", "hashtag": "hashtag", "cashtag": "cashtag",
            "bot_command": "bot_command", "bank_card_number": "bank_card_number",
        }
        field_name = fields.get(typ)
        if not field_name:
            raise ValueError(f"Tipo semântico Rich explícito desconhecido: {typ or '(vazio)' }.")
        parameter = value.attrs.get(field_name, value.attrs.get("value"))
        if parameter in (None, False, ""):
            raise ValueError(f"Entidade Rich {typ} sem o parâmetro {field_name}.")
        return {"type": typ, "text": inner, field_name: str(parameter)}
    if tag == "a":
        if value.attrs.get("name") not in (None, False, ""):
            return {"type": "anchor", "name": str(value.attrs["name"])}
        href = str(value.attrs.get("href") or "")
        if href.startswith("tg://user?id="):
            user_id = int(href.split("=", 1)[1])
            return {"type": "text_mention", "text": inner, "user": {"id": user_id, "is_bot": False, "first_name": _plain(inner) or "Telegram user"}}
        if href.startswith("mailto:"):
            return {"type": "email_address", "text": inner, "email_address": href[7:]}
        if href.startswith("tel:"):
            return {"type": "phone_number", "text": inner, "phone_number": href[4:]}
        if href.startswith("#"):
            return {"type": "anchor_link", "text": inner, "anchor_name": href[1:]}
        return {"type": "url", "text": inner, "url": href}
    if tag in {"cite", "span"}:
        return inner
    raise ValueError(f"Tag <{tag}> não pode ocupar uma posição RichText inline.")


def _plain(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain(item) for item in value)
    if isinstance(value, dict):
        return _plain(value.get("text") or value.get("alternative_text") or value.get("expression") or "")
    return str(value or "")


def _caption(node: _Node | None):
    if node is None:
        return None
    text_items = []
    credit_items = []
    for child in node.children:
        if isinstance(child, _Node) and child.tag == "cite":
            credit_items.extend(_items(_inline_children(child)))
        else:
            text_items.extend(_items(_inline(child)))
    text = [item for item in text_items if item != ""]
    credit = [item for item in credit_items if item != ""]
    if not text and not credit:
        return None
    return {"text": text[0] if len(text) == 1 else text, "credit": (credit[0] if len(credit) == 1 else credit) or None}


def _media_block(node: _Node, media_by_id: dict[str, object]) -> dict:
    src = str(node.attrs.get("src") or "")
    match = _MEDIA_URI.match(src)
    if not match:
        raise ValueError("Entidade Rich explícita exige que a mídia use referência tg:// associada.")
    scheme, media_id = match.groups()
    media = media_by_id.get(media_id)
    if media is None:
        raise ValueError(f"Referência de mídia Rich sem arquivo associado: {media_id}.")
    if isinstance(media, InputMediaPhoto): typ, field_name = "photo", "photo"
    elif isinstance(media, InputMediaAnimation): typ, field_name = "animation", "animation"
    elif isinstance(media, InputMediaVideo): typ, field_name = "video", "video"
    elif isinstance(media, InputMediaVoiceNote): typ, field_name = "voice_note", "voice_note"
    elif isinstance(media, InputMediaAudio): typ, field_name = "audio", "audio"
    elif isinstance(media, InputMediaDocument): typ, field_name = "document", "document"
    else:
        typ, field_name = scheme.lower(), scheme.lower()
    return {"type": typ, field_name: media}


def _child_blocks(node: _Node, media_by_id: dict[str, object]) -> list[dict]:
    blocks: list[dict] = []
    loose: list[_Node | str] = []
    def flush() -> None:
        if not loose:
            return
        holder = _Node("span", children=list(loose))
        text = _inline_children(holder)
        loose.clear()
        if _plain(text).strip():
            blocks.append({"type": "paragraph", "text": text})
    for child in node.children:
        if isinstance(child, str):
            if child.strip(): loose.append(child)
            continue
        if child.tag in {"cite", "figcaption", "caption", "summary"}:
            continue
        if child.tag == "input" and child.attrs.get("type") == "checkbox":
            continue
        if child.tag in {"b","strong","i","em","u","ins","s","strike","del","code","mark","sub","sup","a","tg-spoiler","tg-emoji","tg-time","tg-reference","tg-entity","span"}:
            loose.append(child)
            continue
        flush()
        blocks.extend(_block(child, media_by_id))
    flush()
    return blocks


def _block(node: _Node, media_by_id: dict[str, object]) -> list[dict]:
    tag = node.tag
    if tag == "p": return [{"type": "paragraph", "text": _inline_children(node)}]
    if re.fullmatch(r"h[1-6]", tag): return [{"type": "heading", "text": _inline_children(node), "size": int(tag[1])}]
    if tag == "footer": return [{"type": "footer", "text": _inline_children(node)}]
    if tag == "hr": return [{"type": "divider"}]
    if tag == "pre":
        code = next((x for x in node.children if isinstance(x, _Node) and x.tag == "code"), None)
        target = code or node
        language = ""
        if code:
            language = str(code.attrs.get("class") or "").removeprefix("language-")
        return [{"type": "pre", "text": _plain(_inline_children(target)), "language": language or None}]
    if tag == "a" and node.attrs.get("name") not in (None, False, ""):
        return [{"type": "anchor", "name": str(node.attrs["name"])}]
    if tag in {"img", "video", "audio", "tg-document"}:
        return [_media_block(node, media_by_id)]
    if tag == "tg-map":
        lat = node.attrs.get("lat", node.attrs.get("latitude")); lon = node.attrs.get("long", node.attrs.get("longitude"))
        if lat in (None, False, "") or lon in (None, False, ""):
            raise ValueError("Mapa Rich sem latitude/longitude.")
        block = {"type": "map", "location": {"latitude": float(lat), "longitude": float(lon)}}
        for name in ("zoom", "width", "height"):
            if node.attrs.get(name) not in (None, False, ""): block[name] = int(node.attrs[name])
        return [block]
    if tag == "tg-math-block":
        return [{"type": "mathematical_expression", "expression": _plain(_inline_children(node))}]
    if tag == "tg-button-row":
        buttons = []
        for button in (x for x in node.children if isinstance(x, _Node) and x.tag == "tg-button"):
            attrs = button.attrs
            item = {"text": _inline_children(button)}
            if attrs.get("style") not in (None, False, ""): item["style"] = str(attrs["style"])
            typ = str(attrs.get("type") or "")
            if typ == "url": item["url"] = str(attrs.get("url") or "")
            elif typ == "callback_data": item["callback_data"] = str(attrs.get("data") or "")
            elif typ == "web_app": item["web_app"] = {"url": str(attrs.get("url") or "")}
            elif typ == "login_url":
                item["login_url"] = {"url": str(attrs.get("url") or ""), "forward_text": attrs.get("forward-text") if attrs.get("forward-text") not in (None, False) else None, "request_write_access": True if "request-write-access" in attrs else None}
            elif typ == "switch_inline_query": item["switch_inline_query"] = str(attrs.get("query") or "")
            elif typ == "switch_inline_query_current_chat": item["switch_inline_query_current_chat"] = str(attrs.get("query") or "")
            elif typ == "switch_inline_query_chosen_chat":
                item["switch_inline_query_chosen_chat"] = {"query": str(attrs.get("query") or ""), "allow_user_chats": True if "allow-user-chats" in attrs else None, "allow_bot_chats": True if "allow-bot-chats" in attrs else None, "allow_group_chats": True if "allow-group-chats" in attrs else None, "allow_channel_chats": True if "allow-channel-chats" in attrs else None}
            elif typ == "copy_text": item["copy_text"] = {"text": str(attrs.get("text") or "")}
            elif typ == "disabled": item["disabled"] = {}
            else: raise ValueError(f"Tipo de botão Rich explícito desconhecido: {typ or '(vazio)'}.")
            buttons.append(item)
        return [{"type": "buttons", "buttons": buttons, "align": str(node.attrs.get("align")) if node.attrs.get("align") not in (None, False, "") else None}]
    if tag == "figure":
        media = next((x for x in node.children if isinstance(x, _Node) and x.tag in {"img","video","audio","tg-document","tg-map"}), None)
        if media is None: raise ValueError("<figure> Rich sem bloco de mídia ou mapa.")
        block = _block(media, media_by_id)[0]
        caption_node = next((x for x in node.children if isinstance(x, _Node) and x.tag == "figcaption"), None)
        caption = _caption(caption_node)
        if caption: block["caption"] = caption
        return [block]
    if tag in {"blockquote", "aside"}:
        cite = next((x for x in node.children if isinstance(x, _Node) and x.tag == "cite"), None)
        credit = _inline_children(cite) if cite else None
        if tag == "aside" or "expandable" in node.attrs:
            body_holder = _Node("span", children=[x for x in node.children if x is not cite and not (isinstance(x, str) and not x.strip())])
            typ = "pullquote" if tag == "aside" else "expandable_blockquote"
            return [{"type": typ, "text": _inline_children(body_holder), "credit": credit}]
        return [{"type": "blockquote", "blocks": _child_blocks(node, media_by_id), "credit": credit}]
    if tag == "details":
        summary = next((x for x in node.children if isinstance(x, _Node) and x.tag == "summary"), None)
        return [{"type": "details", "summary": _inline_children(summary) if summary else "", "blocks": _child_blocks(node, media_by_id), "is_open": True if "open" in node.attrs else None}]
    if tag in {"ul", "ol"}:
        items = []
        for li in (x for x in node.children if isinstance(x, _Node) and x.tag == "li"):
            checkbox = next((x for x in li.children if isinstance(x, _Node) and x.tag == "input" and x.attrs.get("type") == "checkbox"), None)
            item = {"blocks": _child_blocks(li, media_by_id)}
            if checkbox: item.update({"has_checkbox": True, "is_checked": True if "checked" in checkbox.attrs else None})
            if tag == "ol":
                if li.attrs.get("value") not in (None, False, ""): item["value"] = int(li.attrs["value"])
                if li.attrs.get("type") not in (None, False, ""): item["type"] = str(li.attrs["type"])
            items.append(item)
        return [{"type": "list", "items": items}]
    if tag == "table":
        caption_node = next((x for x in node.children if isinstance(x, _Node) and x.tag == "caption"), None)
        rows = []
        for tr in (x for x in node.children if isinstance(x, _Node) and x.tag == "tr"):
            row = []
            for cell in (x for x in tr.children if isinstance(x, _Node) and x.tag in {"td", "th"}):
                value = {"text": _inline_children(cell), "align": str(cell.attrs.get("align") or "left"), "valign": str(cell.attrs.get("valign") or "top")}
                if cell.tag == "th": value["is_header"] = True
                for name in ("colspan", "rowspan"):
                    if cell.attrs.get(name) not in (None, False, ""): value[name] = int(cell.attrs[name])
                row.append(value)
            rows.append(row)
        return [{"type": "table", "cells": rows, "caption": _inline_children(caption_node) if caption_node else None, "is_bordered": True if "bordered" in node.attrs else None, "is_striped": True if "striped" in node.attrs else None, "is_compact": True if "compact" in node.attrs else None}]
    if tag in {"tg-collage", "tg-slideshow"}:
        caption_node = next((x for x in node.children if isinstance(x, _Node) and x.tag == "figcaption"), None)
        return [{"type": "collage" if tag == "tg-collage" else "slideshow", "blocks": _child_blocks(node, media_by_id), "caption": _caption(caption_node)}]
    raise ValueError(f"Bloco canônico <{tag}> não possui projeção Rich explícita sem perda.")


def compile_semantic_blocks(source: str, media_by_id: dict[str, object]) -> list[InputRichBlockUnion]:
    parser = _TreeParser(); parser.feed(source); parser.close()
    blocks = _child_blocks(parser.root, media_by_id)
    if not blocks:
        raise ValueError("Documento Rich sem blocos após a projeção explícita.")
    adapter = TypeAdapter(InputRichBlockUnion)
    return [adapter.validate_python(block) for block in blocks]



def explicit_blocks_from_markdown(source: str, media_by_id: dict[str, object]) -> list[InputRichBlockUnion]:
    return compile_semantic_blocks(source, media_by_id)
