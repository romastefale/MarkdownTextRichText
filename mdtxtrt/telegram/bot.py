from __future__ import annotations

import asyncio
import io
from urllib.parse import urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from html import escape as html_escape

from mdtxtrt.conversion.markdown import import_markdown
from mdtxtrt.services.imports import EncodingChoiceRequired, import_file, import_key_for_bytes
from mdtxtrt.telegram.message import build_input_rich_message


class TelegramRuntime:
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
        url = self.web_app_url(**params)
        if not url:
            return None
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]]
        )

    def _remember_destination(self, message: Message) -> dict | None:
        if message.from_user is None:
            return None
        chat = message.chat
        title = getattr(chat, "title", None) or ("Conversa privada" if str(getattr(chat, "type", "")) == "private" else None)
        username = getattr(chat, "username", None)
        chat_type = getattr(getattr(chat, "type", None), "value", None) or str(getattr(chat, "type", "unknown"))
        return self.store.remember_telegram_destination(
            int(message.from_user.id), chat.id, chat_type=chat_type, title=title, username=username, source="bot_update"
        )

    async def _rich(self, chat_id: int | str, markdown: str, *, reply_markup=None):
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
        document = message.document
        buffer = io.BytesIO()
        await self.bot.download(document, destination=buffer, timeout=60)
        raw = buffer.getvalue()
        if not raw:
            raise ValueError("Arquivo vazio.")
        name = document.file_name or "import.txt"
        mime = document.mime_type or "application/octet-stream"
        unique = document.file_unique_id or document.file_id
        return raw, name, mime, unique

    async def _finish_import(self, message: Message, *, owner_id: int, reply_chat_id: int | str | None = None, mode: str | None = None, encoding: str | None = None):
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
            note = "Importação pronta com trechos que exigem revisão antes de converter/publicar."
        await self._rich(
            reply_chat_id if reply_chat_id is not None else message.chat.id,
            note,
            reply_markup=self.web_app_markup("Abrir importação", draft=draft["id"], source="telegram_import"),
        )

    async def start_command(self, message: Message):
        self._remember_destination(message)
        await self._rich(
            message.chat.id,
            "**MDTXTRT**\n\nEditor e conversor Rich para `.md` e `.txt`. Você pode converter diretamente pelo bot ou abrir o editor visual.",
            reply_markup=self.web_app_markup(),
        )

    async def help_command(self, message: Message):
        self._remember_destination(message)
        await self._rich(
            message.chat.id,
            "**Comandos MDTXTRT**\n\n`/start` — apresentação\n`/help` — ajuda\n`/importar` — importar `.md`/`.txt`\n`/converter` — converter sem abrir o aplicativo\n`/editor` — abrir o editor\n`/formatos` — formatos implementados\n`/cancelar` — cancelar operação pendente",
            reply_markup=self.web_app_markup(),
        )

    async def importar_command(self, message: Message):
        self._remember_destination(message)
        if message.from_user is None:
            return
        if message.reply_to_message and message.reply_to_message.document:
            try:
                await self._finish_import(message.reply_to_message, owner_id=int(message.from_user.id), reply_chat_id=message.chat.id)
            except EncodingChoiceRequired as exc:
                self.store.set_pending_action(int(message.from_user.id), "import", {"import_key": exc.import_key, "encoding_choices": exc.choices})
                await self._rich(message.chat.id, "O arquivo não é UTF-8. Abra o editor para escolher explicitamente o encoding.", reply_markup=self.web_app_markup())
            return
        if message.document:
            await self.document_message(message)
            return
        self.store.set_pending_action(int(message.from_user.id), "import", {})
        await self._rich(message.chat.id, "Envie ou encaminhe agora um arquivo `.md` ou `.txt`.", reply_markup=self.web_app_markup())

    async def _convert_document_message(self, source_message: Message, *, reply_chat_id: int | str, owner_id: int):
        raw, name, _, _ = await self._read_document(source_message)
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix not in {"md", "txt"}:
            raise ValueError("Conversão direta aceita somente arquivos .md e .txt.")
        try:
            source = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("O arquivo não é UTF-8; use `/importar` para escolher explicitamente o encoding.") from exc
        if suffix == "txt":
            await self.bot.send_rich_message(chat_id=reply_chat_id, rich_message=InputRichMessage(html=html_escape(source, quote=False)), request_timeout=60)
        else:
            document, _ = import_markdown(source)
            rich = build_input_rich_message(document, self.store, owner_id)
            await self.bot.send_rich_message(chat_id=reply_chat_id, rich_message=rich, request_timeout=60)

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
                target = message.reply_to_message
                source = (target.rich_message.markdown if target.rich_message and target.rich_message.markdown else (target.text or target.caption or ""))
            else:
                parts = (message.text or "").split(maxsplit=1)
                source = parts[1] if len(parts) > 1 else ""
            if not source:
                self.store.set_pending_action(owner_id, "converter", {})
                await self._rich(message.chat.id, "Envie um arquivo `.md`/`.txt` ou responda a uma mensagem com `/converter`.", reply_markup=self.web_app_markup())
                return
            document, _ = import_markdown(source)
            rich = build_input_rich_message(document, self.store, owner_id)
            await self.bot.send_rich_message(chat_id=message.chat.id, rich_message=rich, request_timeout=60)
        except ValueError as exc:
            await self._rich(message.chat.id, str(exc), reply_markup=self.web_app_markup())

    async def editor_command(self, message: Message):
        self._remember_destination(message)
        await self._rich(message.chat.id, "Abra o editor visual do MDTXTRT.", reply_markup=self.web_app_markup())

    async def formatos_command(self, message: Message):
        self._remember_destination(message)
        await self._rich(message.chat.id, "**Formatos implementados**\n\nEntrada: `.md` e `.txt`.\nSaídas no editor: Telegram Rich, Markdown, TXT e Telegraph.\nTelegram Rich oferece Markdown Rich, HTML Rich e Blocks quando a estrutura permitir.", reply_markup=self.web_app_markup())

    async def cancelar_command(self, message: Message):
        if message.from_user is None:
            return
        owner_id = int(message.from_user.id)
        had_pending = bool(self.store.pending_action(owner_id, "import") or self.store.pending_action(owner_id, "converter"))
        self.store.clear_pending_action(owner_id, "import")
        self.store.clear_pending_action(owner_id, "converter")
        await self._rich(message.chat.id, "Operação pendente cancelada." if had_pending else "Não havia operação pendente para cancelar.")

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
                await self._rich(message.chat.id, str(exc), reply_markup=self.web_app_markup())
            return
        if caption == "/importar" or pending_import:
            try:
                await self._finish_import(message, owner_id=owner_id, reply_chat_id=message.chat.id)
            except EncodingChoiceRequired as exc:
                self.store.set_pending_action(owner_id, "import", {"encoding_choices": exc.choices, "import_key": exc.import_key})
                await self._rich(message.chat.id, "O arquivo não é UTF-8. Abra o editor para escolher explicitamente o encoding.", reply_markup=self.web_app_markup())
            except ValueError as exc:
                await self._rich(message.chat.id, str(exc), reply_markup=self.web_app_markup())

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
            details = name or "Localização"
            await self._rich(
                message.chat.id,
                f"**{details} recebida.**\n\n{location.latitude}, {location.longitude}\n\nVolte ao editor para confirmar a inserção.",
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
        return dispatcher

    async def start(self):
        if not self.settings.telegram_token:
            return
        self.bot = Bot(self.settings.telegram_token)
        self.dispatcher = self.build_dispatcher()
        me = await self.bot.get_me(request_timeout=60)
        self.username = me.username or ""
        await self.bot.set_my_commands(
            [
                BotCommand(command="start", description="Apresentar o MDTXTRT"),
                BotCommand(command="help", description="Ajuda e exemplos"),
                BotCommand(command="importar", description="Importar .md ou .txt"),
                BotCommand(command="converter", description="Converter sem abrir o editor"),
                BotCommand(command="editor", description="Abrir o editor visual"),
                BotCommand(command="formatos", description="Ver formatos implementados"),
                BotCommand(command="cancelar", description="Cancelar operação pendente"),
            ]
        )
        url = self.web_app_url()
        if url:
            await self.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Editor", web_app=WebAppInfo(url=url)))
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
        await self._rich(
            user_id,
            "**Selecionar localização**\n\nEnvie uma Location ou Venue pela interface nativa de anexos do Telegram. Não é necessário compartilhar sua localização atual; escolha a localização que deseja inserir no documento.",
            reply_markup=self.web_app_markup("Voltar ao editor", draft=draft_id),
        )

    async def send_document_to_chat(self, user_id: int, chat_id: int | str, document: dict, *, format_mode: str = "rich_markdown"):
        if self.bot is None:
            raise RuntimeError("Bot não iniciado.")
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
