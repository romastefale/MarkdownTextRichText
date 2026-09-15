from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import patch

from aiogram.types import (
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockExpandableBlockQuotation,
    InputRichBlockList,
    InputRichBlockListItem,
    InputRichBlockMathematicalExpression,
    InputRichBlockParagraph,
    InputRichBlockPreformatted,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
    RichMessageButton,
    WebAppInfo,
)

from mdtxtrt.conversion.traditional import traditional_compatibility
from mdtxtrt.config import load_settings
from mdtxtrt.services.conversion import review, select_telegram_mode
from mdtxtrt.telegram.bot import TelegramRuntime
from mdtxtrt.telegram.message import build_input_rich_message


class DummyStore:
    def get_blob(self, user_id, media_id):  # pragma: no cover - media not used in this gate
        raise AssertionError("release gate sample must not request media")


class DummySettings:
    telegram_token = ""
    web_app_url = "https://example.invalid/app"


def basic_document():
    return {
        "schema": "mdtxtrt.document/v1",
        "nodes": [
            {"id": "p1", "type": "paragraph", "html": "Texto <strong>simples</strong>."},
            {"id": "c1", "type": "code", "language": "python", "text": "print('ok')"},
        ],
    }


def advanced_document():
    return {
        "schema": "mdtxtrt.document/v1",
        "nodes": [
            {"id": "h1", "type": "heading", "level": 1, "html": "Título"},
            {"id": "t1", "type": "table", "rows": [[{"text": "A", "header": True}, {"text": "B", "header": True}], [{"text": "1"}, {"text": "2"}]]},
            {"id": "m1", "type": "math", "expression": "E = mc^2", "display": True},
        ],
    }


def validate_aiogram_models():
    blocks = [
        InputRichBlockSectionHeading(text="MDTXTRT", size=1),
        InputRichBlockParagraph(text="Parágrafo"),
        InputRichBlockList(items=[InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Item")])]),
        InputRichBlockPreformatted(text="print('ok')", language="python"),
        InputRichBlockExpandableBlockQuotation(text="Expansível"),
        InputRichBlockTable(
            cells=[
                [RichBlockTableCell(align="left", valign="middle", text="Recurso", is_header=True), RichBlockTableCell(align="center", valign="middle", text="Disponível", is_header=True)],
                [RichBlockTableCell(align="left", valign="middle", text="Tabela"), RichBlockTableCell(align="center", valign="middle", text="Sim")],
            ],
            is_bordered=True,
            is_compact=True,
        ),
        InputRichBlockMathematicalExpression(expression="E = mc^2"),
        InputRichBlockDetails(summary="Mais", blocks=[InputRichBlockParagraph(text="Detalhes")], is_open=False),
        InputRichBlockButtons(
            buttons=[RichMessageButton(text="Entrar no MDTXTRT", style="success", web_app=WebAppInfo(url="https://example.invalid/app"))],
            align="center",
        ),
    ]
    rich = InputRichMessage(blocks=blocks, skip_entity_detection=True)
    dumped = rich.model_dump(exclude_none=True)
    assert dumped.get("blocks"), "InputRichMessage.blocks não foi serializado"


def validate_render_selection():
    basic = basic_document()
    advanced = advanced_document()
    assert select_telegram_mode(basic) == "rich_markdown"
    assert select_telegram_mode(advanced) == "blocks"

    basic_review = review(basic, "telegram")
    advanced_review = review(advanced, "telegram")
    assert basic_review["recommended"] == "rich_markdown"
    assert advanced_review["recommended"] == "blocks"
    assert advanced_review["mechanism"] == "Rich Message · Blocks"

    traditional_ok, traditional_warnings = traditional_compatibility(basic)
    assert traditional_ok and not traditional_warnings
    advanced_ok, advanced_warnings = traditional_compatibility(advanced)
    assert not advanced_ok and advanced_warnings

    built_basic = build_input_rich_message(basic, DummyStore(), 1, format_mode="rich_markdown")
    assert built_basic.markdown is not None and built_basic.html is None and built_basic.blocks is None
    built_blocks = build_input_rich_message(advanced, DummyStore(), 1, format_mode="blocks")
    assert built_blocks.blocks is not None and built_blocks.markdown is None and built_blocks.html is None
    built_html = build_input_rich_message(basic, DummyStore(), 1, format_mode="html")
    assert built_html.html is not None and built_html.markdown is None and built_html.blocks is None


def validate_dispatcher():
    runtime = TelegramRuntime(DummySettings(), DummyStore())
    dispatcher = runtime.build_dispatcher()
    handlers = getattr(dispatcher.message, "handlers", [])
    assert len(handlers) >= 10, f"dispatcher possui apenas {len(handlers)} handlers"
    callbacks = {getattr(item.callback, "__name__", "") for item in handlers}
    expected = {
        "start_command", "help_command", "importar_command", "converter_command", "editor_command",
        "formatos_command", "cancelar_command", "document_message", "location_message", "pending_text_message",
    }
    missing = expected - callbacks
    assert not missing, f"handlers ausentes: {sorted(missing)}"


def validate_static_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "mdtxtrt/static/index.html").read_text(encoding="utf-8")
    js = (root / "mdtxtrt/static/release.js").read_text(encoding="utf-8")
    css = (root / "mdtxtrt/static/release.css").read_text(encoding="utf-8")

    for token in ('data-heading="1"', 'data-heading="2"', 'data-heading="3"', 'Prévia'):
        assert token in html, f"interface sem requisito: {token}"
    for token in ("BackButton", "SettingsButton", "viewportStableHeight", "destination_id", "/api/conversion/review", "/api/telegram/send"):
        assert token in js, f"Mini App sem integração: {token}"
    assert "#ff7a00" in css.lower(), "accent laranja ausente"
    assert "--tg-safe-area-inset-top" in css and "--tg-content-safe-area-inset-top" in css
    assert "font-size:16px" in css.replace(" ", "")


def validate_simple_environment_names():
    encoded_key = base64.b64encode(b"k" * 32).decode("ascii")
    with patch.dict(os.environ, {"TOKEN": "bot123:test", "KEY": encoded_key}, clear=True):
        settings = load_settings()
    assert settings.telegram_token == "123:test"
    assert settings.telegraph_aes_key == b"k" * 32


if __name__ == "__main__":
    validate_aiogram_models()
    validate_render_selection()
    validate_dispatcher()
    validate_static_contract()
    validate_simple_environment_names()
    print("release gate: OK")
