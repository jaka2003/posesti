"""
Nepremicnine.net monitor za Gorenjsko — zemljisca do 300.000 EUR.
Preveri stran, primerja z seen.json in poslje email za nove oglase.
Zazene se enkratno; ponovitev na 20 min ureja Windows Task Scheduler.
"""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"
LOG_FILE = BASE_DIR / "monitor.log"
ENV_FILE = BASE_DIR / ".env"

BASE_URL = "https://www.nepremicnine.net/oglasi-prodaja/gorenjska/posest/cena-do-300000eur/"
SORT_QUERY = "?s=16"  # s=16 = "Razvrsti po datumu" (najnovejsi prvi)
PAGES_TO_FETCH = 2    # pri datumskem sortu vsi novi padejo na stran 1; 2 je safety net

# ---------- config / env ----------

def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


# ---------- logging ----------

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("posesti")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ---------- scrape ----------

ID_RX = re.compile(r"_(\d+)/?$")


def fetch_page(url: str, retries: int = 3) -> str:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, impersonate="chrome120", timeout=30)
            if r.status_code == 200:
                return r.text
            last_err = f"HTTP {r.status_code}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(3 * attempt)
    raise RuntimeError(f"Fetch failed after {retries} attempts: {last_err}")


def parse_listings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for box in soup.select("div.property-box"):
        url_meta = box.find("meta", attrs={"itemprop": "mainEntityOfPage"})
        if not url_meta:
            continue
        ad_url = url_meta.get("content", "").strip()
        if not ad_url:
            continue
        m = ID_RX.search(ad_url)
        if not m:
            continue
        ad_id = m.group(1)

        h2 = box.find("h2")
        title = h2.get_text(strip=True) if h2 else "(brez naslova)"

        # Price: first text containing €
        price = ""
        price_el = box.find(string=re.compile(r"€"))
        if price_el:
            price = price_el.strip()

        # Type/category from itemprop=category meta or first label
        category = ""
        cat_meta = box.find("meta", attrs={"itemprop": "category"})
        if cat_meta:
            category = cat_meta.get("content", "")

        # Short description — try .property-details paragraph
        desc = ""
        details = box.select_one(".property-details")
        if details:
            # Find the longest text node (usually the description)
            for p in details.find_all(["p", "span", "div"]):
                txt = p.get_text(" ", strip=True)
                if len(txt) > len(desc) and len(txt) < 400:
                    desc = txt

        out.append(
            {
                "id": ad_id,
                "url": ad_url,
                "title": title,
                "price": price,
                "category": category,
                "desc": desc,
            }
        )
    return out


# ---------- state ----------

def load_seen() -> dict:
    if not SEEN_FILE.exists():
        return {"ids": []}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"ids": []}


def save_seen(state: dict) -> None:
    SEEN_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- email ----------

def build_email_body(listings: list[dict]) -> tuple[str, str]:
    plain_lines = [f"Najdenih {len(listings)} novih oglasov:\n"]
    html_parts = [
        "<html><body style='font-family:Arial,sans-serif'>",
        f"<h2>Najdenih {len(listings)} novih oglasov</h2>",
    ]
    for ad in listings:
        plain_lines.append(f"- {ad['title']} | {ad['price']}")
        plain_lines.append(f"  {ad['url']}")
        if ad["desc"]:
            plain_lines.append(f"  {ad['desc']}")
        plain_lines.append("")

        html_parts.append(
            "<div style='margin-bottom:18px;padding:12px;border:1px solid #ddd;border-radius:6px'>"
            f"<a href='{ad['url']}' style='font-size:16px;font-weight:bold;color:#1a73e8;text-decoration:none'>{ad['title']}</a>"
            f"<div style='color:#0a8a3a;font-weight:bold;margin:4px 0'>{ad['price']}</div>"
            f"<div style='color:#555;font-size:13px'>{ad['desc']}</div>"
            "</div>"
        )
    html_parts.append("</body></html>")
    return "\n".join(plain_lines), "\n".join(html_parts)


def send_ntfy(listings: list[dict], logger: logging.Logger) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    server = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").strip().rstrip("/") or "https://ntfy.sh"
    # JSON publish endpoint: post na root, topic v body. Tako se izognemo
    # latin-1 omejitvi HTTP headerjev (slovenski znaki Ž, Č, Š).

    sent_any = False
    for ad in listings:
        message = ad["title"]
        if ad["price"]:
            message = f"{ad['title']} — {ad['price']}"
        if ad["desc"]:
            desc = ad["desc"]
            if len(desc) > 300:
                desc = desc[:297] + "..."
            message = f"{message}\n\n{desc}"

        payload = {
            "topic": topic,
            "title": f"Nov oglas: {ad['title']}",
            "message": message,
            "click": ad["url"],
            "tags": ["house_with_garden"],
        }
        try:
            r = requests.post(
                server,
                json=payload,
                impersonate="chrome120",
                timeout=20,
            )
            if 200 <= r.status_code < 300:
                sent_any = True
                logger.info("ntfy poslano: %s (%s)", ad["title"], ad["id"])
            else:
                logger.error("ntfy napaka za %s: HTTP %s %s", ad["id"], r.status_code, r.text[:200])
        except Exception as exc:
            logger.error("ntfy exception za %s: %s", ad["id"], exc)
    return sent_any


def send_telegram(listings: list[dict], logger: logging.Logger) -> bool:
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    sent_any = False
    for ad in listings:
        # Telegram limit je 4096 znakov — vsak oglas posebej.
        lines = [
            f"<b>{ad['title']}</b>",
            f"<b>Cena:</b> {ad['price']}",
        ]
        if ad["desc"]:
            desc = ad["desc"]
            if len(desc) > 500:
                desc = desc[:497] + "..."
            lines.append("")
            lines.append(desc)
        lines.append("")
        lines.append(f'<a href="{ad["url"]}">Odpri oglas</a>')
        text = "\n".join(lines)

        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                impersonate="chrome120",
                timeout=20,
            )
            data = r.json()
            if data.get("ok"):
                sent_any = True
                logger.info("Telegram poslano: %s (%s)", ad["title"], ad["id"])
            else:
                logger.error("Telegram napaka za %s: %s", ad["id"], data)
        except Exception as exc:
            logger.error("Telegram exception za %s: %s", ad["id"], exc)
    return sent_any


def send_email(listings: list[dict], logger: logging.Logger) -> bool:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    to_addr = os.environ.get("MAIL_TO", user)

    if not user or not password:
        logger.warning("SMTP_USER ali SMTP_PASS ni nastavljen — preskakujem email.")
        return False

    plain, html = build_email_body(listings)
    msg = EmailMessage()
    msg["Subject"] = f"[Posesti] {len(listings)} novih oglasov — Gorenjska"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        logger.info("Email poslan na %s", to_addr)
        return True
    except Exception as exc:
        logger.error("Posiljanje emaila spodletelo: %s", exc)
        return False


# ---------- main ----------

def fetch_all_pages(logger: logging.Logger) -> list[dict]:
    listings: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(1, PAGES_TO_FETCH + 1):
        url = f"{BASE_URL}{SORT_QUERY}" if page == 1 else f"{BASE_URL}{page}/{SORT_QUERY}"
        try:
            html = fetch_page(url)
        except Exception as exc:
            logger.error("Fetch napaka (stran %d): %s", page, exc)
            if page == 1:
                raise
            break

        page_listings = parse_listings(html)
        if not page_listings:
            logger.info("Stran %d: prazna — verjetno zadnja stran.", page)
            break

        new_on_page = [ad for ad in page_listings if ad["id"] not in seen_ids]
        for ad in new_on_page:
            seen_ids.add(ad["id"])
        listings.extend(new_on_page)
        logger.info("Stran %d: %d oglasov (%d unikatnih).", page, len(page_listings), len(new_on_page))
        if len(new_on_page) < len(page_listings) * 0.5:
            # Vec kot polovica je ze bila na prejsni strani -> verjetno smo na koncu paginacije
            break
    return listings


def main() -> int:
    load_env()
    logger = setup_logging()
    logger.info("=== Scan zacet ===")
    try:
        listings = fetch_all_pages(logger)
    except Exception as exc:
        logger.error("Fetch napaka: %s", exc)
        return 1

    logger.info("Skupaj %d oglasov.", len(listings))
    if not listings:
        logger.warning("Nic oglasov — verjetno se je HTML spremenil ali blokada.")
        return 2

    state = load_seen()
    seen_ids: set[str] = set(state.get("ids", []))
    first_run = len(seen_ids) == 0

    current_ids = [ad["id"] for ad in listings]
    new_ads = [ad for ad in listings if ad["id"] not in seen_ids]

    if first_run:
        logger.info("Prvi zagon — pomnim %d obstojecih oglasov, brez maila.", len(current_ids))
        state["ids"] = current_ids
        save_seen(state)
        return 0

    if not new_ads:
        logger.info("Ni novih oglasov.")
        return 0

    logger.info("NOVIH oglasov: %d", len(new_ads))
    for ad in new_ads:
        logger.info("  + %s | %s | %s", ad["id"], ad["title"], ad["price"])

    if send_ntfy(new_ads, logger):
        pass
    elif send_telegram(new_ads, logger):
        pass
    else:
        send_email(new_ads, logger)

    # Hrani vse trenutno videne (ne samo nove) — naj raste s straniou.
    state["ids"] = list(seen_ids | set(current_ids))
    save_seen(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
