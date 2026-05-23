"""Telegram bot that sends PDFs with a custom thumbnail."""
import logging
import os
import tempfile
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

TMP_DIR = Path(tempfile.gettempdir()) / "tg_pdf_bot"
TMP_DIR.mkdir(parents=True, exist_ok=True)

THUMB_MAX_SIDE = 320
THUMB_MAX_BYTES = 200 * 1024

MAX_PDF_BYTES = 50 * 1024 * 1024

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("pdf-thumb-bot")


def process_thumbnail(src_path: Path, dst_path: Path) -> None:
    """Resize/compress an image to a Telegram-compliant JPEG thumbnail.

    Telegram accepts thumbnails that are JPEG, <= 320x320, and < 200KB.
    """
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)

        quality = 90
        while True:
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=False)
            data = buf.getvalue()
            if len(data) <= THUMB_MAX_BYTES or quality <= 30:
                break
            quality -= 10

        while len(data) > THUMB_MAX_BYTES and min(im.size) > 64:
            new_size = (max(64, im.size[0] - 32), max(64, im.size[1] - 32))
            im = im.resize(new_size, Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()

        dst_path.write_bytes(data)
        logger.info(
            "Thumbnail processed: %dx%d, %d bytes, quality=%d",
            im.size[0], im.size[1], len(data), quality,
        )


def _user_paths(user_id: int) -> tuple[Path, Path, Path]:
    raw = TMP_DIR / f"{user_id}_thumb_raw"
    thumb = TMP_DIR / f"{user_id}_thumb.jpg"
    pdf = TMP_DIR / f"{user_id}_doc.pdf"
    return raw, thumb, pdf


def _cleanup(*paths: Path) -> None:
    for p in paths:
        try:
            if p.exists():
                p.unlink()
                logger.info("Removed temp file: %s", p)
        except OSError as e:
            logger.warning("Failed to remove %s: %s", p, e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("/start from user %s (%s)", user.id, user.username)
    raw, thumb, pdf = _user_paths(user.id)
    _cleanup(raw, thumb, pdf)
    context.user_data.clear()
    await update.message.reply_text(
        f"Hi {user.first_name}! 👋\n\n"
        "Send me an image (JPEG/PNG), then a PDF, and I'll send the PDF back "
        "with that image as its cover thumbnail.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.message
    raw, thumb, _pdf = _user_paths(user.id)

    try:
        if msg.photo:
            tg_file = await msg.photo[-1].get_file()
            logger.info("Received photo from %s, file_id=%s", user.id, tg_file.file_id)
        elif msg.document and msg.document.mime_type in ("image/jpeg", "image/png"):
            tg_file = await msg.document.get_file()
            logger.info(
                "Received image document from %s, mime=%s",
                user.id, msg.document.mime_type,
            )
        else:
            await msg.reply_text("⚠️ Please send a JPEG or PNG image.")
            return

        await tg_file.download_to_drive(custom_path=str(raw))
        process_thumbnail(raw, thumb)
        _cleanup(raw)

        context.user_data["thumb_ready"] = True
        await msg.reply_text("Got it! Now send me your PDF file.")
    except Exception as e:
        logger.exception("Failed to process thumbnail")
        _cleanup(raw, thumb)
        context.user_data.pop("thumb_ready", None)
        await msg.reply_text(f"❌ Failed to process thumbnail: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.message
    doc = msg.document
    raw, thumb, pdf = _user_paths(user.id)

    if doc and doc.mime_type in ("image/jpeg", "image/png"):
        await handle_image(update, context)
        return

    if not doc or doc.mime_type != "application/pdf":
        await msg.reply_text("⚠️ Please send a PDF file (application/pdf).")
        return

    if not context.user_data.get("thumb_ready") or not thumb.exists():
        await msg.reply_text(
            "⚠️ Send a thumbnail image first. Use /start to begin again."
        )
        return

    if doc.file_size and doc.file_size > MAX_PDF_BYTES:
        await msg.reply_text(
            f"❌ PDF is too large ({doc.file_size / 1024 / 1024:.1f} MB). "
            "Bot API limit is 50 MB."
        )
        return

    logger.info(
        "Received PDF from %s: name=%s size=%s",
        user.id, doc.file_name, doc.file_size,
    )

    status = await msg.reply_text("Processing...")

    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(pdf))
        logger.info("PDF downloaded to %s", pdf)

        with open(pdf, "rb") as pdf_f, open(thumb, "rb") as thumb_f:
            sent = await context.bot.send_document(
                chat_id=msg.chat_id,
                document=pdf_f,
                thumbnail=thumb_f,
                filename=doc.file_name or "document.pdf",
                disable_content_type_detection=False,
            )
        logger.info(
            "Sent to user %s, message_id=%s",
            msg.chat_id, sent.message_id,
        )
        await status.edit_text("✅ Done!")
    except TelegramError as e:
        logger.exception("Telegram API error while sending document")
        await status.edit_text(f"❌ Telegram API error: {e.message}")
    except FileNotFoundError as e:
        logger.exception("Missing file during send")
        await status.edit_text(f"❌ Missing file: {e}")
    except Exception as e:
        logger.exception("Unexpected error while sending document")
        await status.edit_text(f"❌ Unexpected error: {e}")
    finally:
        _cleanup(pdf, thumb)
        context.user_data.pop("thumb_ready", None)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"❌ Internal error: {context.error}"
            )
        except TelegramError:
            pass


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_error_handler(error_handler)

    port = os.getenv("PORT")
    webhook_base = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL")

    if port and webhook_base:
        logger.info("Bot starting in webhook mode on port %s", port)
        app.run_webhook(
            listen="0.0.0.0",
            port=int(port),
            url_path=BOT_TOKEN,
            webhook_url=f"{webhook_base.rstrip('/')}/{BOT_TOKEN}",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Bot starting in polling mode.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
