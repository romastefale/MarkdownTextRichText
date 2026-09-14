from __future__ import annotations

import asyncio
import io
from html import escape as html_escape
from urllib.parse import urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    RichBlockTableCell,
    RichMessageButton,
    RichTextBold,
    RichTextItalic,
    RichTextMarked,
    RichTextSpoiler,
    RichTextStrikethrough,
    RichTextUnderline,
    InputRichMessage,
    WebAppInfo,
)

from mdtxtrt.conversion.markdown import import_markdown
from mdtxtrt.conversion.traditional import to_markdown_v2, to_traditional_html
from mdtxtrt.services.imports import EncodingChoiceRequired, import_file, import_key_for_bytes
from mdtxtrt.telegram.message import build_input_rich_message


class TelegramRuntime:
    """Telegram runtime without monkey patches; Bot API 10.3 features are used directly through aiogram 3.31."""

    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self.polling_task: asyncio.Task | None = None
        self.username = ""

    def web_app_url(self, **params) -> str:
        base = self.settings.web_app_url
        if not base:
            return ""
        query = urlencode({key: value for key, value in params.items() if value is not None})
        return base + (("?" + query) if query else "")

    def web_app_markup(self, label: str = "Entrar no MDTXTRT", **params):
        """Traditional inline-keyboard fallback for contexts where a RichMessageButton is unsuitable."""
        url = self.web_app_url(**params)
        if not url:
            return None
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]]
        )

    def _entry_block(self, message: Message | None = None, **params):
        url = self.web_app_url(**params)
        if not url:
            return None
        chat_type = str(getattr(getattr(message, "chat", None), "type", "")) if message is not None else ""
        if chat_type == "private":
            button = RichMessageButton(text="Entrar no MDTXTRT", style="success", web_app=WebAppInfo(url=url))
        else:
            button = RichMessageButton(text="Entrar no MDTXTRT", style="success", url=url)
        return InputRichBlockButtons(buttons=[button], align="center")

    def _remember_destination(self, message: Message) -> dict | None:
        if message.from_user is None:
            return None
        chat = message.chat
        title = getattr(chat, "title", None) or ("Conversa privada" if str(getattr(chat, "type", "")) == "private" else None)
        username = getattr(chat, "username", None)
        chat_type = getattr(getattr(chat, "type", None), "value", None) or str(getattr(chat, "type", "unknown"))
        return self.store.remember_telegram_destination(
            int(message.from_user.id),
            chat.id,
            chat_type=chat_type,
            title=title,
            username=username,
            source="bot_update",
        )

    async def _send_blocks(self, message: Message, blocks: list, *, include_entry: bool = True, **entry_params):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
        outgoing = list(blocks)
        if include_entry:
            entry = self._entry_block(message, **entry_params)
            if entry is not None:
                outgoing.append(entry)
        return await self.bot.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(blocks=outgoing, skip_entity_detection=True),
            request_timeout=60,
        )

    async def _rich_markdown(self, chat_id: int | str, markdown: str, *, reply_markup=None):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
        return await self.bot.send_rich_message(
            chat_id=chat_id,
            rich_message=InputRichMessage(markdown=markdown),
            reply_markup=reply_markup,
            request_timeout=60,
        )

    async def _read_document(self, message: Message) -> tuple[bytes, str, str, str]:
        if self.bot is None or message.document is None:
            raise ValueError("Arquivo ausente.")
        buffer = io.BytesIO()
        await self.bot.download(message.document, destination=buffer, timeout=60)
        raw = buffer.getvalue()
        if not raw:
            raise ValueError("Arquivo vazio.")
        document = message.document
        return (
            raw,
            document.file_name or "import.txt",
            document.mime_type or "application/octet-stream",
            document.file_unique_id or document.file_id,
        )

    async def _finish_import(
        self,
        message: Message,
        *,
        owner_id: int,
        reply_chat_id: int | str | None = None,
        mode: str | None = None,
        encoding: str | None = None,
    ):
        raw, name, mime, unique = await self._read_document(message)
        key = import_key_for_bytes("telegram", raw, unique)
        result = import_file(
            self.store,
            owner_id,
            name=name,
            mime=mime,
            raw=raw,
            import_key=key,
            mode=mode,
            encoding=encoding,
        )
        self.store.clear_pending_action(owner_id, "import")
        draft = result["draft"]
        review = result.get("report") or {}
        note = "Importação pronta."
        if review.get("partial"):
            note = "Importação pronta com trechos que exigem revisão antes de publicar."
        target = reply_chat_id if reply_chat_id is not None else message.chat.id
        await self._rich_markdown(
            target,
            note,
            reply_markup=self.web_app_markup("Abrir importação", draft=draft["id"], source="telegram_import"),
        )

    async def start_command(self, message: Message):
        self._remember_destination(message)
        blocks = [
            InputRichBlockSectionHeading(text="MDTXTRT", size=1),
            InputRichBlockParagraph(text="Crie e converta textos formatados para o Telegram."),
            InputRichBlockList(items=[
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Importe arquivos .md ou .txt")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Converta mensagens diretamente pelo bot")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Use o editor visual")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Confira o resultado antes de enviar")]),
            ]),
            InputRichBlockParagraph(text="O mecanismo adequado é escolhido entre Rich Message e os formatos tradicionais compatíveis."),
        ]
        await self._send_blocks(message, blocks)

    async def help_command(self, message: Message):
        self._remember_destination(message)
        blocks = [
            InputRichBlockSectionHeading(text="Como usar", size=2),
            InputRichBlockParagraph(text=[RichTextBold(text="Importar arquivo"), "\nUse /importar e envie um arquivo .md ou .txt."]),
            InputRichBlockParagraph(text=[RichTextBold(text="Converter texto"), "\nUse /converter com texto, responda a uma mensagem, ou envie o texto depois que o bot entrar em espera."]),
            InputRichBlockParagraph(text=[RichTextBold(text="Editor visual"), "\nUse /editor para escrever, importar, formatar e visualizar o resultado."]),
            InputRichBlockList(items=[
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="/importar — receber arquivo")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="/converter — receber texto")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="/formatos — demonstrar recursos")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="/cancelar — cancelar operação")]),
            ]),
        ]
        await self._send_blocks(message, blocks)

    async def importar_command(self, message: Message):
        self._remember_destination(message)
        if message.from_user is None:
            return
        owner_id = int(message.from_user.id)
        if message.reply_to_message and message.reply_to_message.document:
            try:
                await self._finish_import(message.reply_to_message, owner_id=owner_id, reply_chat_id=message.chat.id)
            except EncodingChoiceRequired as exc:
                self.store.set_pending_action(owner_id, "import", {"import_key": exc.import_key, "encoding_choices": exc.choices})
                await self._rich_markdown(message.chat.id, "O arquivo não é UTF-8. Abra o editor para escolher explicitamente o encoding.", reply_markup=self.web_app_markup())
            return
        if message.document:
            await self.document_message(message)
            return
        self.store.set_pending_action(owner_id, "import", {})
        blocks = [
            InputRichBlockSectionHeading(text="Importar arquivo", size=2),
            InputRichBlockParagraph(text="Envie agora um arquivo .md ou .txt. O conteúdo será analisado antes da conversão e nada será publicado automaticamente."),
        ]
        await self._send_blocks(message, blocks)

    async def _convert_document_message(self, source_message: Message, *, reply_chat_id: int | str, owner_id: int):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
        raw, name, _, _ = await self._read_document(source_message)
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix not in {"md", "txt"}:
            raise ValueError("Conversão direta aceita somente arquivos .md e .txt.")
        try:
            source = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("O arquivo não é UTF-8; use /importar para escolher explicitamente o encoding.") from exc
        if suffix == "txt":
            await self.bot.send_rich_message(
                chat_id=reply_chat_id,
                rich_message=InputRichMessage(html=html_escape(source, quote=False)),
                request_timeout=60,
            )
        else:
            document, _ = import_markdown(source)
            rich = build_input_rich_message(document, self.store, owner_id)
            await self.bot.send_rich_message(chat_id=reply_chat_id, rich_message=rich, request_timeout=60)

    def _message_source(self, message: Message) -> str:
        if message.rich_message is not None:
            if message.rich_message.markdown:
                return message.rich_message.markdown
            if message.rich_message.html:
                return message.rich_message.html
        return message.text or message.caption or ""

    async def _convert_text(self, message: Message, source: str, owner_id: int):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
        document, _ = import_markdown(source)
        rich = build_input_rich_message(document, self.store, owner_id)
        await self.bot.send_rich_message(chat_id=message.chat.id, rich_message=rich, request_timeout=60)

    async def converter_command(self, message: Message):
        self._remember_destination(message)
        if self.bot is None or message.from_user is None:
            return
        owner_id = int(message.from_user.id)
        try:
            if message.reply_to_message and message.reply_to_message.document:
                await self._convert_document_message(message.reply_to_message, reply_chat_id=message.chat.id, owner_id=owner_id)
                return
            if message.reply_to_message:
                source = self._message_source(message.reply_to_message)
            else:
                parts = (message.text or "").split(maxsplit=1)
                source = parts[1] if len(parts) > 1 else ""
            if not source:
                self.store.set_pending_action(owner_id, "converter", {"state": "waiting_text"})
                blocks = [
                    InputRichBlockSectionHeading(text="Converter texto", size=2),
                    InputRichBlockParagraph(text="Envie uma mensagem agora ou responda ao texto que deseja converter."),
                ]
                await self._send_blocks(message, blocks)
                return
            await self._convert_text(message, source, owner_id)
            self.store.clear_pending_action(owner_id, "converter")
        except ValueError as exc:
            await self._rich_markdown(message.chat.id, str(exc), reply_markup=self.web_app_markup())

    async def pending_text_message(self, message: Message):
        """Consume the next normal text message only when /converter created waiting_text."""
        if message.from_user is None or not message.text:
            return
        owner_id = int(message.from_user.id)
        pending = self.store.pending_action(owner_id, "converter")
        if not pending:
            return
        self._remember_destination(message)
        try:
            await self._convert_text(message, message.text, owner_id)
            self.store.clear_pending_action(owner_id, "converter")
        except ValueError as exc:
            await self._rich_markdown(message.chat.id, str(exc), reply_markup=self.web_app_markup())

    async def editor_command(self, message: Message):
        self._remember_destination(message)
        blocks = [
            InputRichBlockSectionHeading(text="Editor MDTXTRT", size=2),
            InputRichBlockParagraph(text="Escreva, importe, formate e visualize sua mensagem em uma interface completa."),
            InputRichBlockParagraph(text="O editor oferece Rich Message, importação .md/.txt, prévia, histórico e destino autorizado."),
        ]
        await self._send_blocks(message, blocks)

    async def formatos_command(self, message: Message):
        self._remember_destination(message)
        table = InputRichBlockTable(
            cells=[
                [
                    RichBlockTableCell(align="left", valign="middle", text="Recurso", is_header=True),
                    RichBlockTableCell(align="center", valign="middle", text="Disponível", is_header=True),
                ],
                [RichBlockTableCell(align="left", valign="middle", text="Títulos"), RichBlockTableCell(align="center", valign="middle", text="Sim")],
                [RichBlockTableCell(align="left", valign="middle", text="Tabelas"), RichBlockTableCell(align="center", valign="middle", text="Sim")],
                [RichBlockTableCell(align="left", valign="middle", text="Fórmulas"), RichBlockTableCell(align="center", valign="middle", text="Sim")],
                [RichBlockTableCell(align="left", valign="middle", text="Botões"), RichBlockTableCell(align="center", valign="middle", text="Sim")],
            ],
            is_bordered=True,
            is_compact=True,
        )
        blocks = [
            InputRichBlockSectionHeading(text="Recursos de formatação", size=2),
            InputRichBlockParagraph(text=[
                RichTextBold(text="negrito"), " · ", RichTextItalic(text="itálico"), " · ",
                RichTextUnderline(text="sublinhado"), " · ", RichTextStrikethrough(text="tachado"), " · ",
                RichTextMarked(text="marcado"), " · ", RichTextSpoiler(text="spoiler"),
            ]),
            InputRichBlockList(items=[
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Lista com marcadores")]),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Lista numerada")], value=2, type="1"),
                InputRichBlockListItem(blocks=[InputRichBlockParagraph(text="Lista de tarefas")], has_checkbox=True, is_checked=True),
            ]),
            InputRichBlockPreformatted(text="print('MDTXTRT')", language="python"),
            InputRichBlockExpandableBlockQuotation(text="Citação expansível Rich real."),
            table,
            InputRichBlockMathematicalExpression(expression="E = mc^2"),
            InputRichBlockDetails(
                summary="Mais possibilidades",
                blocks=[InputRichBlockParagraph(text="Rich Messages permitem referências, documentos, galerias, mapas, botões e blocos recolhíveis.")],
                is_open=False,
            ),
        ]
        await self._send_blocks(message, blocks)

    async def cancelar_command(self, message: Message):
        if message.from_user is None:
            return
        owner_id = int(message.from_user.id)
        had_pending = bool(self.store.pending_action(owner_id, "import") or self.store.pending_action(owner_id, "converter"))
        self.store.clear_pending_action(owner_id, "import")
        self.store.clear_pending_action(owner_id, "converter")
        blocks = [InputRichBlockParagraph(text="Operação cancelada." if had_pending else "Não há nenhuma operação para cancelar.")]
        await self._send_blocks(message, blocks, include_entry=False)

    async def document_message(self, message: Message):
        if message.document is None or message.from_user is None:
            return
        self._remember_destination(message)
        owner_id = int(message.from_user.id)
        caption = (message.caption or "").strip().split(None, 1)[0].split("@", 1)[0].lower()
        pending_import = self.store.pending_action(owner_id, "import")
        pending_converter = self.store.pending_action(owner_id, "converter")
        if caption == "/converter" or pending_converter:
            try:
                await self._convert_document_message(message, reply_chat_id=message.chat.id, owner_id=owner_id)
                self.store.clear_pending_action(owner_id, "converter")
            except ValueError as exc:
                await self._rich_markdown(message.chat.id, str(exc), reply_markup=self.web_app_markup())
            return
        if caption == "/importar" or pending_import:
            try:
                await self._finish_import(message, owner_id=owner_id, reply_chat_id=message.chat.id)
            except EncodingChoiceRequired as exc:
                self.store.set_pending_action(owner_id, "import", {"encoding_choices": exc.choices, "import_key": exc.import_key})
                await self._rich_markdown(message.chat.id, "O arquivo não é UTF-8. Abra o editor para escolher explicitamente o encoding.", reply_markup=self.web_app_markup())
            except ValueError as exc:
                await self._rich_markdown(message.chat.id, str(exc), reply_markup=self.web_app_markup())

    async def location_message(self, message: Message):
        if message.from_user is None:
            return
        self._remember_destination(message)
        location = message.location
        name = None
        address = None
        if message.venue is not None:
            location = message.venue.location
            name = message.venue.title
            address = message.venue.address
        if location is None:
            return
        received = self.store.complete_map_request(
            int(message.from_user.id),
            float(location.latitude),
            float(location.longitude),
            name=name,
            address=address,
        )
        if received:
            await self._rich_markdown(
                message.chat.id,
                f"**{name or 'Localização'} recebida.**\n\n{location.latitude}, {location.longitude}\n\nVolte ao editor para confirmar a inserção.",
                reply_markup=self.web_app_markup("Voltar ao rascunho", draft=received["draft_id"], map_request=received["id"]),
            )

    def build_dispatcher(self) -> Dispatcher:
        dispatcher = Dispatcher()
        dispatcher.message.register(self.start_command, Command("start"))
        dispatcher.message.register(self.help_command, Command("help"))
        dispatcher.message.register(self.importar_command, Command("importar"))
        dispatcher.message.register(self.converter_command, Command("converter"))
        dispatcher.message.register(self.editor_command, Command("editor"))
        dispatcher.message.register(self.formatos_command, Command("formatos"))
        dispatcher.message.register(self.cancelar_command, Command("cancelar"))
        dispatcher.message.register(self.location_message, F.location | F.venue)
        dispatcher.message.register(self.document_message, F.document)
        dispatcher.message.register(self.pending_text_message, F.text)
        return dispatcher

    async def start(self):
        if not self.settings.telegram_token:
            return
        self.bot = Bot(self.settings.telegram_token)
        self.dispatcher = self.build_dispatcher()
        me = await self.bot.get_me(request_timeout=60)
        self.username = me.username or ""
        await self.bot.set_my_commands([
            BotCommand(command="start", description="Conheça o MDTXTRT"),
            BotCommand(command="help", description="Veja como usar o bot"),
            BotCommand(command="importar", description="Converta um arquivo .md ou .txt"),
            BotCommand(command="converter", description="Converta uma mensagem de texto"),
            BotCommand(command="editor", description="Abra o editor completo"),
            BotCommand(command="formatos", description="Veja os formatos disponíveis"),
            BotCommand(command="cancelar", description="Cancele a operação atual"),
        ])
        url = self.web_app_url()
        if url:
            await self.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="MDTXTRT", web_app=WebAppInfo(url=url)))
        await self.bot.delete_webhook(drop_pending_updates=False, request_timeout=60)
        self.polling_task = asyncio.create_task(
            self.dispatcher.start_polling(
                self.bot,
                polling_timeout=10,
                handle_as_tasks=False,
                handle_signals=False,
                close_bot_session=False,
            ),
            name="mdtxtrt-telegram-polling",
        )

    async def stop(self):
        if self.bot is None:
            return
        if self.dispatcher is not None and self.polling_task is not None and not self.polling_task.done():
            await self.dispatcher.stop_polling()
        if self.polling_task is not None:
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
        await self.bot.session.close()

    async def notify_map_request(self, user_id: int, draft_id: str):
        await self._rich_markdown(
            user_id,
            "**Selecionar localização**\n\nEnvie uma Location ou Venue pela interface nativa de anexos do Telegram. Escolha a localização que deseja inserir no documento.",
            reply_markup=self.web_app_markup("Voltar ao editor", draft=draft_id),
        )

    async def send_document_to_chat(self, user_id: int, chat_id: int | str, document: dict, *, format_mode: str = "rich_markdown"):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
        if format_mode == "traditional_html":
            return await self.bot.send_message(chat_id=chat_id, text=to_traditional_html(document), parse_mode="HTML", request_timeout=60)
        if format_mode == "markdown_v2":
            return await self.bot.send_message(chat_id=chat_id, text=to_markdown_v2(document), parse_mode="MarkdownV2", request_timeout=60)
        if format_mode not in {"rich_markdown", "html", "blocks"}:
            raise ValueError("Formato Telegram inválido.")
        rich = build_input_rich_message(document, self.store, user_id, format_mode=format_mode)
        return await self.bot.send_rich_message(chat_id=chat_id, rich_message=rich, request_timeout=60)

    async def send_markdown_to_chat(self, chat_id: int | str, markdown: str):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
        return await self.bot.send_rich_message(
            chat_id=chat_id,
            rich_message=InputRichMessage(markdown=markdown),
            request_timeout=60,
        )
