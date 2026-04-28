#!/usr/bin/env python3
"""
Telegram-агент керування сайтом "Річка Життя".
"""

import os
import re
import subprocess
import functools
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

load_dotenv()

TOKEN        = os.getenv("TELEGRAM_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ALLOWED_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "gaffoss/church-website")

SITE_DIR  = os.path.dirname(os.path.abspath(__file__))
INDEX     = os.path.join(SITE_DIR, "index.html")
NEWS_HTML = os.path.join(SITE_DIR, "news.html")

MONTHS_UK = ["січ","лют","бер","квіт","трав","черв",
             "лип","серп","вер","жовт","лист","груд"]

# Очікує введення: {chat_id: 'news' | 'announce' | 'schedule'}
pending: dict[int, str] = {}


# ── Клавіатура ─────────────────────────────────────────────────

MAIN_MENU = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📰 Додати новину",      callback_data="btn_news"),
        InlineKeyboardButton("📢 Оголошення",          callback_data="btn_announce"),
        InlineKeyboardButton("🗑 Видалити оголошення", callback_data="btn_clear_announce"),
    ],
    [
        InlineKeyboardButton("📅 Розклад",             callback_data="btn_schedule"),
        InlineKeyboardButton("🖼 Галерея",              callback_data="btn_gallery"),
    ],
    [
        InlineKeyboardButton("🚀 Опублікувати сайт",   callback_data="btn_deploy"),
        InlineKeyboardButton("📊 Статус",              callback_data="btn_status"),
    ],
    [
        InlineKeyboardButton("❓ Допомога",             callback_data="btn_help"),
    ],
])


# ── Utilities ──────────────────────────────────────────────────

def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()

def write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def date_uk() -> str:
    n = datetime.now()
    return f"{n.day} {MONTHS_UK[n.month - 1]}. {n.year}"

def date_en() -> str:
    return datetime.now().strftime("%b %-d, %Y")


# ── Git ────────────────────────────────────────────────────────

def _git(*args) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", *args], cwd=SITE_DIR,
        capture_output=True, text=True
    )
    return r.returncode == 0, (r.stdout + r.stderr).strip()

def git_push(message: str) -> tuple[bool, str]:
    remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
    _git("remote", "set-url", "origin", remote_url)
    _git("add", "-A")
    ok, out = _git("commit", "-m", message)
    if not ok:
        if "nothing to commit" in out:
            return True, "Немає нових змін."
        return False, f"Помилка commit:\n{out}"
    ok, out = _git("push")
    if ok:
        return True, f"✅ Задеплоєно: {message}"
    return False, f"❌ Push помилка:\n{out}"


# ── Auth ───────────────────────────────────────────────────────

def owner_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        cid = str(update.effective_chat.id)
        if ALLOWED_ID and cid != ALLOWED_ID:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text("⛔ Доступ заборонено.")
            return
        return await func(update, ctx)
    return wrapper


# ── Логіка новини (спільна для команди і кнопки) ───────────────

async def _do_news(text: str, reply) -> None:
    if "|" not in text:
        await reply("❗ Формат: *Заголовок | Текст новини*", parse_mode="Markdown")
        return

    title, body = [p.strip() for p in text.split("|", 1)]
    duk, den = date_uk(), date_en()
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    card = f"""
      <article class="news-card" data-cat="community">
        <div class="news-card-top">
          <div class="news-meta">
            <span class="news-date" data-uk="{duk}" data-en="{den}">{duk}</span>
            <span class="news-cat" data-uk="Громада" data-en="Community">Громада</span>
          </div>
          <div class="news-title"
            data-uk="{title}"
            data-en="{title}">
            {title}
          </div>
          <p class="news-text"
            data-uk="{body}"
            data-en="{body}">
            {body}
          </p>
        </div>
        <div class="news-card-bottom">
          <a href="#" class="news-read-btn">
            <span data-uk="Читати далі" data-en="Read more">Читати далі</span> →
          </a>
        </div>
      </article>"""

    marker = '<div class="news-grid" id="newsGrid">'
    html = read(NEWS_HTML)
    if marker not in html:
        await reply("❌ Не знайдено #newsGrid у news.html")
        return
    write(NEWS_HTML, html.replace(marker, marker + card, 1))

    preview = body[:130] + ("…" if len(body) > 130 else "")
    idx = read(INDEX)
    idx = re.sub(
        r'(class="np-title"\s*\n?\s*data-uk=")[^"]*("\s*data-en=")[^"]*(">[^<]*</div>)',
        rf'\1{title}\2{title}\3', idx, count=1
    )
    idx = re.sub(
        r'(class="np-text"\s*\n?\s*data-uk=")[^"]*("\s*data-en=")[^"]*(">[^<]*</p>)',
        rf'\1{preview}\2{preview}\3', idx, count=1
    )
    write(INDEX, idx)

    ok, out = git_push(f"news: {title[:70]}")
    await reply(f"📰 *Новину додано!*\n_{title}_\n\n{out}", parse_mode="Markdown")


async def _do_announce(text: str, reply) -> None:
    if not text:
        await reply("❗ Введіть текст оголошення")
        return

    banner = (
        "<!-- ANNOUNCE START -->\n"
        '<div id="site-announce" style="position:fixed;bottom:0;left:0;right:0;'
        "z-index:2000;background:rgba(42,157,143,0.95);backdrop-filter:blur(8px);"
        "color:#fff;text-align:center;padding:12px 20px;"
        "font-family:'Nunito',sans-serif;font-weight:700;font-size:.9rem;"
        'display:flex;align-items:center;justify-content:center;gap:16px;">\n'
        f"  <span>📢 {text}</span>\n"
        "  <button onclick=\"this.parentElement.style.display='none'\" "
        "style=\"background:rgba(255,255,255,0.25);border:none;color:#fff;"
        'border-radius:6px;padding:4px 12px;cursor:pointer;font-weight:700;">✕</button>\n'
        "</div>\n<!-- ANNOUNCE END -->"
    )

    html = read(INDEX)
    if "<!-- ANNOUNCE START -->" in html:
        html = re.sub(
            r"<!-- ANNOUNCE START -->.*?<!-- ANNOUNCE END -->",
            banner, html, flags=re.DOTALL
        )
    else:
        html = html.replace("</body>", banner + "\n</body>")
    write(INDEX, html)

    ok, out = git_push(f"announce: {text[:70]}")
    await reply(f"📢 *Оголошення опубліковано!*\n_{text}_\n\n{out}", parse_mode="Markdown")


async def _do_clear_announce(reply) -> None:
    html = read(INDEX)
    if "<!-- ANNOUNCE START -->" not in html:
        await reply("ℹ️ Активного оголошення немає.")
        return
    html = re.sub(
        r"\n?<!-- ANNOUNCE START -->.*?<!-- ANNOUNCE END -->",
        "", html, flags=re.DOTALL
    )
    write(INDEX, html)
    ok, out = git_push("announce: видалено оголошення")
    await reply(f"🗑 *Оголошення видалено!*\n\n{out}", parse_mode="Markdown")


async def _do_schedule(text: str, reply) -> None:
    if "|" not in text:
        await reply(
            "❗ Формат: *Нд 12:00-14:00 | Ср 19:00 | Пт 14:00*",
            parse_mode="Markdown"
        )
        return

    parts = [p.strip() for p in text.split("|")]

    def extract_time(s: str) -> str:
        tokens = s.split()
        return tokens[-1] if len(tokens) >= 2 else s

    times = [extract_time(p) for p in parts]
    nd = times[0] if len(times) > 0 else ""
    sr = times[1] if len(times) > 1 else ""
    pt = times[2] if len(times) > 2 else ""

    html = read(INDEX)
    if nd:
        html = re.sub(r'(data-uk="☀️ Нд — )[^"]*(")', rf'\g<1>{nd}\2', html)
        html = re.sub(r'(data-en="☀️ Sun — )[^"]*(")', rf'\g<1>{nd}\2', html)
    if sr:
        html = re.sub(r'(data-uk="📖 Ср — )[^"]*(")', rf'\g<1>{sr}\2', html)
        html = re.sub(r'(data-en="📖 Wed — )[^"]*(")', rf'\g<1>{sr}\2', html)
    if pt:
        html = re.sub(r'(data-uk="🙏 Пт — )[^"]*(")', rf'\g<1>{pt}\2', html)
        html = re.sub(r'(data-en="🙏 Fri — )[^"]*(")', rf'\g<1>{pt}\2', html)

    write(INDEX, html)
    ok, out = git_push(f"schedule: {text[:70]}")
    await reply(f"📅 *Розклад оновлено!*\n{text}\n\n{out}", parse_mode="Markdown")


# ── Команди ────────────────────────────────────────────────────

@owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Привіт! Я бот керування сайтом церкви.*\n\n"
        "Оберіть дію з меню нижче або введіть команду вручну:",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU,
    )

@owner_only
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Головне меню:*",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU,
    )

@owner_only
async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    await _do_news(text, update.message.reply_text)

@owner_only
async def cmd_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    await _do_announce(text, update.message.reply_text)

@owner_only
async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    await _do_schedule(text, update.message.reply_text)

@owner_only
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, log   = _git("log", "--oneline", "-5")
    _, dirty = _git("status", "--short")
    pages_url = f"https://gaffoss.github.io/church-website/"
    await update.message.reply_text(
        f"🌐 *Статус сайту*\n\n"
        f"📁 Репо: github.com/{GITHUB_REPO}\n"
        f"🔗 Сайт: {pages_url}\n\n"
        f"📝 *Останні коміти:*\n```\n{log or '—'}\n```\n\n"
        f"📋 *Незбережені зміни:*\n```\n{dirty or 'немає'}\n```",
        parse_mode="Markdown",
    )

@owner_only
async def cmd_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Деплой на GitHub Pages...")
    ok, out = git_push("deploy: manual trigger via Telegram")
    await update.message.reply_text(
        f"{'✅' if ok else '❌'} {out}",
        reply_markup=MAIN_MENU,
    )

@owner_only
async def cmd_clear_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_clear_announce(update.message.reply_text)

@owner_only
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Доступні команди:*\n\n"
        "/news Заголовок \\| Текст — додати новину\n"
        "/announce Текст — банер на головній\n"
        "/clear\\_announce — видалити оголошення\n"
        "/schedule Нд 12:00 \\| Ср 19:00 \\| Пт 14:00\n"
        "/deploy — опублікувати сайт\n"
        "/status — статус репозиторію\n"
        "/menu — показати меню\n\n"
        "💡 Або просто натисніть кнопку в меню!",
        parse_mode="MarkdownV2",
        reply_markup=MAIN_MENU,
    )


# ── Inline кнопки ──────────────────────────────────────────────

PROMPTS = {
    "btn_news":     "✏️ Введи новину у форматі:\n\n*Заголовок | Текст новини*",
    "btn_announce": "✏️ Введи текст оголошення:\n\n_(з'явиться зеленим банером на сайті)_",
    "btn_schedule": "✏️ Введи розклад у форматі:\n\n*Нд 12:00-14:00 | Ср 19:00 | Пт 14:00*",
}

@owner_only
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat_id

    if data in PROMPTS:
        action = data.replace("btn_", "")
        pending[chat_id] = action
        await q.message.reply_text(PROMPTS[data], parse_mode="Markdown")

    elif data == "btn_clear_announce":
        await _do_clear_announce(q.message.reply_text)

    elif data == "btn_deploy":
        await q.message.reply_text("⏳ Деплой на GitHub Pages...")
        ok, out = git_push("deploy: manual trigger via Telegram")
        await q.message.reply_text(
            f"{'✅' if ok else '❌'} {out}",
            reply_markup=MAIN_MENU,
        )

    elif data == "btn_status":
        _, log   = _git("log", "--oneline", "-5")
        _, dirty = _git("status", "--short")
        pages_url = f"https://gaffoss.github.io/church-website/"
        await q.message.reply_text(
            f"🌐 *Статус сайту*\n\n"
            f"📁 Репо: github.com/{GITHUB_REPO}\n"
            f"🔗 Сайт: {pages_url}\n\n"
            f"📝 *Останні коміти:*\n```\n{log or '—'}\n```\n\n"
            f"📋 *Незбережені зміни:*\n```\n{dirty or 'немає'}\n```",
            parse_mode="Markdown",
        )

    elif data == "btn_gallery":
        await q.message.reply_text(
            "🖼 *Галерея*\n\n"
            "Фото галереї знаходяться у папці:\n"
            "`/Users/ludmila/church-website/`\n\n"
            "Файли: `worship1-3.jpg`, `prayer1-6.jpg`,\n"
            "`event1-10.jpg`, `kids1-6.jpg`\n\n"
            "Щоб додати нові фото — скопіюйте їх у папку і надішліть /deploy",
            parse_mode="Markdown",
        )

    elif data == "btn_help":
        await q.message.reply_text(
            "📖 *Доступні команди:*\n\n"
            "/news Заголовок | Текст\n"
            "/announce Текст оголошення\n"
            "/schedule Нд 12:00 | Ср 19:00 | Пт 14:00\n"
            "/deploy — опублікувати\n"
            "/status — статус\n"
            "/menu — головне меню",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU,
        )


# ── Обробник вільного тексту (після кнопки) ────────────────────

@owner_only
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    action = pending.pop(chat_id, None)

    if action is None:
        await update.message.reply_text(
            "Скористайтесь меню або введіть команду.",
            reply_markup=MAIN_MENU,
        )
        return

    text = update.message.text.strip()
    reply = update.message.reply_text

    if action == "news":
        await _do_news(text, reply)
    elif action == "announce":
        await _do_announce(text, reply)
    elif action == "schedule":
        await _do_schedule(text, reply)

    # Показати меню після виконання дії
    await update.message.reply_text("Що далі?", reply_markup=MAIN_MENU)


# ── Main ───────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start",    "Головне меню"),
        BotCommand("menu",     "Головне меню"),
        BotCommand("news",     "Додати новину"),
        BotCommand("announce",       "Оголошення на сайті"),
        BotCommand("clear_announce", "Видалити оголошення"),
        BotCommand("schedule",       "Оновити розклад"),
        BotCommand("deploy",   "Опублікувати сайт"),
        BotCommand("status",   "Статус сайту"),
        BotCommand("help",     "Допомога"),
    ])


def main():
    if not TOKEN:
        raise SystemExit("❌ TELEGRAM_TOKEN не знайдено в .env")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("menu",     cmd_menu))
    app.add_handler(CommandHandler("news",     cmd_news))
    app.add_handler(CommandHandler("announce",       cmd_announce))
    app.add_handler(CommandHandler("clear_announce", cmd_clear_announce))
    app.add_handler(CommandHandler("schedule",       cmd_schedule))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("deploy",   cmd_deploy))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("🤖 Агент запущено. Очікуємо команди...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
