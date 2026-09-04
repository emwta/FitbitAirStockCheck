#!/usr/bin/env python3
"""
Google Store multi-variant stock checker -> Telegram notifier (fast/async).

Watches several color variants of a product (each its own store.google.com
config URL). All variants are checked CONCURRENTLY using one shared browser
instance (one tab per variant) instead of sequentially, and each page only
waits for its buy/notify button to actually appear instead of waiting for
"networkidle" (which Google's analytics traffic can delay) or a fixed sleep.

Sends ONE formatted Telegram message showing the status of ALL variants
whenever ANY variant's status changes (in-stock <-> out-of-stock). No
message is sent if nothing changed since the last run.

State (last known status per variant) is persisted to state.json so re-runs
on GitHub Actions know whether anything actually changed.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ---- Config -----------------------------------------------------------

TITLE = "Fitbit Air Stock Monitor"

VARIANTS: dict[str, str] = {
    "Obsidian": (
        "https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections="
        "eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEE9Il0sWyIyIiwiTVE9PSJdXSwicHJlZmVycmVkQ2FyZSI6IlRIZDBkVUZqIiwic3Vic2NyaXB0aW9ucyI6W1siWDJkdmIyZHNaVjlvWldGc2RHaGZjSEpsYldsMWJWOHpiVjkwY21saGJGOW1ZVzA9IiwiVEhkMGRVRmoiXV0sInRyYWRlSW4iOnsic2VsZWN0aW9uIjozfX0%3D"
    ),
    "Lavender": (
        "https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections="
        "eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEE9Il0sWyIyIiwiTWc9PSJdXSwicHJlZmVycmVkQ2FyZSI6IlRIZDBkVUZqIiwic3Vic2NyaXB0aW9ucyI6W1siWDJkdmIyZHNaVjlvWldGc2RHaGZjSEpsYldsMWJWOHpiVjkwY21saGJGOW1ZVzA9IiwiVEhkMGRVRmoiXV0sInRyYWRlSW4iOnsic2VsZWN0aW9uIjozfX0%3D"
    ),
    "Berry": (
        "https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections="
        "eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEE9Il0sWyIyIiwiTkE9PSJdXSwicHJlZmVycmVkQ2FyZSI6IlRIZDBkVUZqIiwic3Vic2NyaXB0aW9ucyI6W1siWDJkdmIyZHNaVjlvWldGc2RHaGZjSEpsYldsMWJWOHpiVjkwY21saGJGOW1ZVzA9IiwiVEhkMGRVRmoiXV0sInRyYWRlSW4iOnsic2VsZWN0aW9uIjozfX0%3D"
    ),
    "Fog": (
        "https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections="
        "eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEE9Il0sWyIyIiwiTXc9PSJdXSwicHJlZmVycmVkQ2FyZSI6IlRIZDBkVUZqIiwic3Vic2NyaXB0aW9ucyI6W1siWDJkdmIyZHNaVjlvWldGc2RHaGZjSEpsYldsMWJWOHpiVjkwY21saGJGOW1ZVzA9IiwiVEhkMGRVRmoiXV0sInRyYWRlSW4iOnsic2VsZWN0aW9uIjozfX0%3D"
    ),
    "Pokemon": (
        "https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections="
        "eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEk9Il0sWyIyIiwiT0E9PSJdXSwicHJlZmVycmVkQ2FyZSI6IlRIZDBkVUZqIiwic3Vic2NyaXB0aW9ucyI6W1siWDJkdmIyZHNaVjlvWldGc2RHaGZjSEpsYldsMWJWOHpiVjkwY21saGJGOW1ZVzA9IiwiVEhkMGRVRmoiXV0sInRyYWRlSW4iOnsic2VsZWN0aW9uIjozfX0%3D"
    ),
}

STATE_FILE = Path(__file__).parent / "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TZ = ZoneInfo("Asia/Bangkok")  # ICT

# How long to wait for a buy/notify button to show up before giving up on a
# variant and falling back to whatever buttons happen to be on the page.
BUTTON_WAIT_MS = 12000

# Extra settle time after the button appears, to let the real stock-status
# API response (which can arrive after the initial skeleton render) update
# the DOM before we read the label. This runs concurrently across all
# variant tabs, so it doesn't multiply by the number of variants.
SETTLE_MS = 2500

# Phrases that indicate the item CANNOT be purchased right now.
OUT_OF_STOCK_PHRASES = [
    "sold out",
    "notify me",
    "out of stock",
    "temporarily out of stock",
    "coming soon",
    "unavailable",
    "在庫切れ",       # out of stock
    "入荷通知",       # restock notification
    "品切れ",         # out of stock
    "販売終了",       # sales ended
]

# Phrases that indicate it CAN be purchased.
IN_STOCK_PHRASES = [
    "buy",
    "add to cart",
    "check out",
    "カートに追加",   # add to cart
    "購入",           # purchase
    "レジに進む",     # proceed to checkout
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BUTTON_SELECTOR = (
    "button[aria-label*='Buy' i], button[aria-label*='Notify' i], "
    "[data-test-id*='buy' i] button, main button"
)


async def fetch_status(browser, name: str, url: str) -> tuple[str, dict]:
    """Render one variant's page (its own tab) and classify in/out of stock."""
    page = await browser.new_page(user_agent=USER_AGENT)
    try:
        # domcontentloaded is enough - we don't need every background
        # analytics/tracking request to finish (that's what made
        # "networkidle" slow and sometimes time out).
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        try:
            await page.wait_for_selector(BUTTON_SELECTOR, timeout=BUTTON_WAIT_MS)
        except PlaywrightTimeoutError:
            pass  # fall through and just grab whatever buttons exist

        # The button shown right after page load is often a default/skeleton
        # state (e.g. "Buy") - the REAL stock status arrives a bit later via
        # a background API call that updates the DOM. Give that a bounded
        # moment to land before reading the label. Since all variants run
        # concurrently, this delay overlaps across tabs instead of stacking.
        await page.wait_for_timeout(SETTLE_MS)

        async def read_label() -> str:
            for selector in [
                "button[aria-label*='Buy' i]",
                "button[aria-label*='Notify' i]",
                "[data-test-id*='buy' i] button",
                "main button",
            ]:
                els = await page.query_selector_all(selector)
                if els:
                    texts = [t.strip() for t in await asyncio.gather(*(e.inner_text() for e in els))]
                    joined = " | ".join(t for t in texts if t)
                    if joined:
                        return joined

            buttons = await page.query_selector_all("button")
            texts = [t.strip() for t in await asyncio.gather(*(b.inner_text() for b in buttons))]
            return " | ".join(t for t in texts if t)

        label = await read_label()
        # Stabilization check: if the label is still changing (stock status
        # API response still landing), wait a bit more and re-read. Prefer
        # the later, more-settled reading.
        await page.wait_for_timeout(1000)
        label_recheck = await read_label()
        if label_recheck and label_recheck != label:
            label = label_recheck
    finally:
        await page.close()

    # The collected label often concatenates buttons from unrelated cards on
    # the page (e.g. an "Original" family card AND a "Special Edition" family
    # card, plus Pixel Care+/trade-in buttons). The actual CTA for the
    # variant selected via the URL is reliably the LAST segment(s), e.g.
    # "...ログインして入荷通知を登録する" (out of stock) or
    # "...カートに追加する | こちら" (in stock). Only inspect the tail.
    segments = [s.strip() for s in label.split("|") if s.strip()]
    tail = " ".join(segments[-2:]) if len(segments) >= 2 else (segments[-1] if segments else "")
    tail_lower = tail.lower()

    is_out = any(p in tail_lower for p in OUT_OF_STOCK_PHRASES)
    is_in = any(p in tail_lower for p in IN_STOCK_PHRASES)
    in_stock = is_in and not is_out

    return name, {"in_stock": in_stock, "raw_label": label, "tail_checked": tail}


async def fetch_all() -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            results = await asyncio.gather(
                *(fetch_status(browser, name, url) for name, url in VARIANTS.items())
            )
        finally:
            await browser.close()
    return dict(results)


def load_last_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {name: {"in_stock": False, "raw_label": ""} for name in VARIANTS}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def build_message(current: dict) -> str:
    """Build the monospace status table, HTML-escaped and wrapped in <pre>."""
    name_width = max(len(n) for n in VARIANTS) + 4
    lines = []
    for name in VARIANTS:
        status = "🟢 IN" if current[name]["in_stock"] else "🔴 OUT"
        lines.append(f" {name:<{name_width}}{status}")

    now_str = datetime.now(TZ).strftime("%d %b %Y %H:%M ICT")
    separator = "─" * 20

    body = "\n".join([
        separator,
        f" {TITLE}",
        separator,
        "",
        *lines,
        "",
        " Last Check",
        f" {now_str}",
        separator,
    ])

    escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<pre>{escaped}</pre>"


def send_telegram(message_html: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured (missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); skipping send.")
        print("Message would have been:\n", message_html)
        return

    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_html,
        "parse_mode": "HTML",
    }).encode()

    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


async def main_async() -> int:
    previous = load_last_state()
    current = await fetch_all()

    for name, result in current.items():
        print(f"{name}: {result}")

    changed = any(
        current[name]["in_stock"] != previous.get(name, {}).get("in_stock", False)
        for name in VARIANTS
    )

    if changed:
        print("Status changed for at least one variant - sending Telegram notification.")
        send_telegram(build_message(current))
    else:
        print("No status change for any variant - no notification sent.")

    save_state(current)
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
