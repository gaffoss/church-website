#!/usr/bin/env python3
"""
Telegram-агент керування сайтом "Річка Життя".

Команди:
  /news Заголовок | Текст    — додає новину в news.html і прев'ю в index.html
  /schedule Нд 12:00 | Ср 19:00 | Пт 14:00  — оновлює розклад
  /announce Текст            — банер-оголошення на головній
  /status                    — статус репозиторію
  /deploy                    — git push без змін (ручний деплой)
"""

import os
import re
import subprocess
import functools
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TOKEN       = os.getenv("TELEGRAM_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ALLOWED_ID  = os.getenv("TELEGRAM_CHAT_ID", "")

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX    = os.path.join(SITE_DIR, "index.html")
NEWS_HTML = os.path.join(SITE_DIR, "news.html")

GITHUB_REPO = "gaffoss/church-website"

MONTHS_UK = ["січ","лют","бер","квіт","трав","черв",
             "лип","серп","вер","жовт","лист","груд"]


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
    # Встановити remote з токеном із .env
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
            await update.message.reply_text("⛔ Доступ заборонено.")
            return
        return await func(update, ctx)
    return wrapper


# ── /news ──────────────────────────────────────────────────────

@owner_only
async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    if "|" not in text:
        await update.message.reply_text(
            "❗ Формат:\n/news Заголовок | Текст новини"
        )
        return

    title, body = [p.strip() for p in text.split("|", 1)]
    duk, den = date_uk(), date_en()
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    # ── Картка для news.html ──────────────────────────────
    card = f"""
      <!-- AGENT:{ts} -->
      <article class="news-card" data-cat="community">
        <div class="news-card-top">
          <div class="news-meta">
            <span class="news-date" data-uk="{duk}" data-en="{den}">{duk}</span>
            <span class="news-cat" data-uk="Громада" data-en="Community">Громада</span>
          </div>
          <div class="news-title" data-uk="{title}" data-en="{title}">{title}</div>
          <p class="news-text" data-uk="{body}" data-en="{body}">{body}</p>
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
        await update.message.reply_text("❌ Не знайдено #newsGrid у news.html")
        return
    write(NEWS_HTML, html.replace(marker, marker + card, 1))

    # ── Прев'ю у index.html (перша np-картка) ────────────
    preview_body = body[:130] + ("…" if len(body) > 130 else "")
    idx = read(INDEX)

    idx = re.sub(
        r'(class="np-title"\s*\n?\s*data-uk=")[^"]*("\s*data-en=")[^"]*(">[^<]*</div>)',
        rf'\1{title}\2{title}\3',
        idx, count=1
    )
    idx = re.sub(
        r'(class="np-text"\s*\n?\s*data-uk=")[^"]*("\s*data-en=")[^"]*(">[^<]*</p>)',
        rf'\1{preview_body}\2{preview_body}\3',
        idx, count=1
    )
    write(INDEX, idx)

    ok, out = git_push(f"news: {title[:70]}")
    await update.message.reply_text(
        f"📰 *Новину додано!*\n_{title}_\n\n{out}",
        parse_mode="Markdown"
    )


# ── /schedule ──────────────────────────────────────────────────

@owner_only
async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Формат: /schedule Нд 12:00-14:00 | Ср 19:00 | Пт 14:00
    Або:    /schedule Нд 12:00 | Ср 00:00 | Пт 14:00
    """
    text = " ".join(ctx.args).strip()
    if not text or "|" not in text:
        await update.message.reply_text(
            "❗ Формат:\n/schedule Нд 12:00-14:00 | Ср 19:00 | Пт 14:00"
        )
        return

    parts = [p.strip() for p in text.split("|")]

    def extract_time(s: str) -> str:
        # "Нд 12:00-14:00"  →  "12:00-14:00"
        tokens = s.split()
        return tokens[-1] if len(tokens) >= 2 else s

    times = [extract_time(p) for p in parts]
    nd = times[0] if len(times) > 0 else ""
    sr = times[1] if len(times) > 1 else ""
    pt = times[2] if len(times) > 2 else ""

    html = read(INDEX)

    # Оновити footer мітки розкладу
    if nd:
        html = re.sub(r'(data-uk="☀️ Нд — )[^"]*(")', rf'\g<1>{nd}\2', html)
        html = re.sub(r'(data-en="☀️ Sun — )[^"]*(")', rf'\g<1>{nd}\2', html)
    if sr:
        html = re.sub(r'(data-uk="📖 Ср — )[^"]*(")', rf'\g<1>{sr}\2', html)
        html = re.sub(r'(data-en="📖 Wed — )[^"]*(")', rf'\g<1>{sr}\2', html)
    if pt:
        html = re.sub(r'(data-uk="🙏 Пт — )[^"]*(")', rf'\g<1>{pt}\2', html)
        html = re.sub(r'(data-en="🙏 Fri — )[^"]*(")', rf'\g<1>{pt}\2', html)

    # Оновити рядок розкладу "Нд 12:00 · Ср 00:00 · Пт 14:00"
    new_line = " · ".join(filter(None, [
        f"Нд {nd}" if nd else "",
        f"Ср {sr}" if sr else "",
        f"Пт {pt}" if pt else ""
    ]))
    html = re.sub(
        r'(data-uk="Sun [^"]*" data-en=")[^"]*(")',
        rf'\1{new_line}\2',
        html
    )

    write(INDEX, html)
    ok, out = git_push(f"schedule: {text[:70]}")
    await update.message.reply_text(
        f"📅 *Розклад оновлено!*\n{text}\n\n{out}",
        parse_mode="Markdown"
    )


# ── /announce ──────────────────────────────────────────────────

@owner_only
async def cmd_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    if not text:
        await update.message.reply_text("❗ Формат: /announce Текст оголошення")
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
        "</div>\n"
        "<!-- ANNOUNCE END -->"
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
    await update.message.reply_text(
        f"📢 *Оголошення опубліковано!*\n_{text}_\n\n{out}",
        parse_mode="Markdown"
    )


# ── /status ────────────────────────────────────────────────────

@owner_only
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, log    = _git("log", "--oneline", "-5")
    _, dirty  = _git("status", "--short")

    pages_url = f"https://gaffoss.github.io/church-website/"
    repo_url  = f"https://github.com/{GITHUB_REPO}"

    await update.message.reply_text(
        f"🌐 *Статус сайту*\n\n"
        f"📁 Репо: {repo_url}\n"
        f"🔗 Сайт: {pages_url}\n\n"
        f"📝 *Останні коміти:*\n```\n{log or '—'}\n```\n\n"
        f"📋 *Незбережені зміни:*\n```\n{dirty or 'немає'}\n```",
        parse_mode="Markdown"
    )


# ── /deploy ────────────────────────────────────────────────────

@owner_only
async def cmd_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Деплой на GitHub Pages...")
    ok, out = git_push("deploy: manual trigger via Telegram")
    icon = "✅" if ok else "❌"
    await update.message.reply_text(f"{icon} {out}")


# ── Main ───────────────────────────────────────────────────────

def main():
    if not TOKEN:
        raise SystemExit("❌ TELEGRAM_TOKEN не знайдено в .env")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("news",     cmd_news))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("announce", cmd_announce))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("deploy",   cmd_deploy))

    print("🤖 Агент запущено. Очікуємо команди...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
