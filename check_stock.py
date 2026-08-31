#!/usr/bin/env python3
"""
Google Store stock checker -> Telegram notifier.

Loads the (JS-rendered) product config URL with Playwright, inspects the
buy/notify button, and sends a Telegram message when the item goes from
"out of stock" to "in stock" (so you don't get spammed every run).

State (last known status) is persisted to state.json so re-runs on GitHub
Actions know whether the status just changed.
"""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---- Config -----------------------------------------------------------

# The product URL to watch. You can point this at any store.google.com
# product/config URL - just paste the full link (including query string).
PRODUCT_URL = os.environ.get(
    "PRODUCT_URL",
    "https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections="
    "eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEE9Il1dLCJwcmVmZXJyZWRDYXJlIjoiVEhkMGRVRmoiLCJzdWJzY3JpcHRpb25zIjpbWyJYMmR2YjJkc1pWOW9aV0ZzZEdoZmNISmxiV2wxYlY4emJWOTBjbWxoYkY5bVlXMD0iLCJUSGQwZFVGaiJdXSwidHJhZGVJbiI6eyJzZWxlY3Rpb24iOjN9fQ%3D%3D",
)

STATE_FILE = Path(__file__).parent / "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Phrases that indicate the item CANNOT be purchased right now.
OUT_OF_STOCK_PHRASES = [
    "sold out",
    "notify me",
    "out of stock",
    "temporarily out of stock",
    "coming soon",
    "unavailable",
]

# Phrases that indicate it CAN be purchased.
IN_STOCK_PHRASES = [
    "buy",
    "add to cart",
    "check out",
]


def fetch_status() -> dict:
    """Render the page and return {'in_stock': bool, 'raw_label': str}."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))
        page.goto(PRODUCT_URL, wait_until="networkidle", timeout=60000)

        # Give the SPA a moment to finish hydrating price/buy button state.
        page.wait_for_timeout(3000)

        # Try common selectors for the primary purchase button first.
        label = ""
        for selector in [
            "button[aria-label*='Buy' i]",
            "button[aria-label*='Notify' i]",
            "[data-test-id*='buy' i] button",
            "main button",
        ]:
            els = page.query_selector_all(selector)
            if els:
                label = " | ".join(e.inner_text().strip() for e in els if e.inner_text().strip())
                if label:
                    break

        if not label:
            # Fallback: just grab all button text on the page.
            buttons = page.query_selector_all("button")
            label = " | ".join(b.inner_text().strip() for b in buttons if b.inner_text().strip())

        browser.close()

    label_lower = label.lower()
    is_out = any(p in label_lower for p in OUT_OF_STOCK_PHRASES)
    is_in = any(p in label_lower for p in IN_STOCK_PHRASES)

    # If both/neither matched, default to "unknown" -> treated as out-of-stock
    # so we never silently miss a restock, but we also don't false-positive.
    in_stock = is_in and not is_out

    return {"in_stock": in_stock, "raw_label": label}


def load_last_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"in_stock": False, "raw_label": ""}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured (missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); skipping send.")
        print("Message would have been:", message)
        return

    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "false",
    }).encode()

    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def main() -> int:
    current = fetch_status()
    previous = load_last_state()

    print(f"Previous: {previous}")
    print(f"Current:  {current}")

    if current["in_stock"] and not previous.get("in_stock"):
        send_telegram(
            "🟢 มีของแล้ว! Google Fitbit Air กลับมามีสถานะซื้อได้\n"
            f"ปุ่มที่เจอ: {current['raw_label']}\n"
            f"{PRODUCT_URL}"
        )
    elif not current["in_stock"] and previous.get("in_stock"):
        # Optional: notify when it goes OUT of stock too. Comment out if unwanted.
        send_telegram(
            "🔴 หมดสต๊อกแล้ว (สถานะเปลี่ยนจากมีของ -> หมด)\n"
            f"{PRODUCT_URL}"
        )
    else:
        print("No status change - no notification sent.")

    save_state(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
