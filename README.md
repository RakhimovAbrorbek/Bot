# PDF Thumbnail Bot

A Telegram bot that posts a PDF to a channel with a custom cover thumbnail —
the same way Telegram on iOS/macOS attaches PDF previews — so the cover renders
on Android, Windows, web, and desktop too.

## How it works

The bot uses Telegram's Bot API method `sendDocument` with the `thumbnail`
parameter ([docs](https://core.telegram.org/bots/api#senddocument)). Telegram
ignores the thumbnail unless it is **JPEG, ≤320×320 pixels, and <200 KB**, so
the bot resizes/recompresses any image you give it with Pillow before sending.

### Flow

1. `/start` — bot greets and asks for a thumbnail image.
2. You send a JPEG or PNG → it's normalized to a Telegram-compliant JPEG.
3. You send a PDF → bot uploads the PDF + thumbnail to the channel and replies
   "✅ Successfully sent to channel!"

Temp files live in the OS temp dir under `tg_pdf_bot/` and are deleted right
after sending.

## Setup

### 1. Create the bot and channel

- Talk to [@BotFather](https://t.me/BotFather), `/newbot`, save the token.
- Create your channel, add the bot as an **administrator** with **Post Messages**
  permission.
- Get the channel id: either use `@username` for public channels, or forward a
  message from the channel to [@userinfobot](https://t.me/userinfobot) to read a
  numeric `-100…` id (required for private channels).

### 2. Install

```bash
git clone <this-repo> && cd bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# edit .env and fill in BOT_TOKEN and CHANNEL_ID
```

### 4. Run

```bash
python bot.py
```

You'll see logs like:

```
2026-05-14 ... | INFO  | pdf-thumb-bot | Bot starting. Channel: -1001234567890
```

Open the bot in Telegram, `/start`, send an image, then send a PDF.

## Notes

- Bot API limits document uploads to **50 MB**. For larger files you'd need a
  local Bot API server.
- The thumbnail is rendered server-side by Telegram, so once the message is
  posted, every Telegram client (iOS, macOS, Android, Windows, web, Linux) will
  show the same preview.
- Each user has their own temp file names keyed by `user_id`, so multiple users
  can use the bot concurrently without colliding.
- Logging is at INFO; bump to DEBUG by editing `logging.basicConfig` in
  `bot.py` if you need network-level traces.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Chat not found` | Bot isn't a member/admin of the channel, or `CHANNEL_ID` is wrong. |
| `Not enough rights` | Bot needs **Post Messages** admin permission. |
| Thumbnail missing on Android | Make sure your image isn't a PDF/HEIC etc. Only JPEG/PNG are accepted; the bot rejects others. |
| `File is too big` | Bot API caps at 50 MB. |
