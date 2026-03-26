import requests
import time
import logging
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────
RAPIDAPI_KEY = "785e7ea308mshc88fb29d2de2ac7p12a681jsn71d79500bcd9"
RAPIDAPI_HOST = "pinnacle-football-odds.p.rapidapi.com"
API_URL = "https://pinnacle-football-odds.p.rapidapi.com/dropping_odds"

TELEGRAM_TOKEN = "7912248885:AAFwOdg0rX3weVr6NXzW1adcUorvlRY8LyI"
CHAT_ID = "-1003588715273"

POLL_INTERVAL = 300     # 5 minuti

# ── FILTRI ───────────────────────────────────────────────────────────────
QUOTA_MIN = 1.20
QUOTA_MAX = 2.50
MIN_MOVE_PCT = 5.0      # % minima rispetto all'ULTIMA quota notificata
# ────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# Dizionario: "eventId|selection" → ultima quota notificata
# Es: "1626545858|AWAY" → 2.10
last_notified_price: dict = {}


def make_track_key(row: dict) -> str:
    return f"{row['eventId']}|{row['selection']}"


def fetch_movements() -> list:
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    }
    params = {
        "limit": 200,
        "historyDays": 1,
        "minDropPct": 1,
        "dropMode": "total",
        "time": "today",
        "period": 0,
        "sort": "dropPct",
        "order": "desc",
    }
    try:
        r = requests.get(API_URL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("rows", [])
    except Exception as e:
        log.error(f"Errore fetch API: {e}")
        return []


def should_notify(row: dict) -> tuple:
    """
    Logica di notifica basata sull'ultima quota notificata.

    PRIMA VOLTA (partita mai vista):
      → notifica se old→new >= 5%

    GIA' NOTIFICATA:
      → confronta last_price → new
      → notifica solo se si è mossa ancora di >=5% rispetto all'ultima notifica
      → ignora se ferma o si è mossa meno del 5%

    Restituisce (True, direction, pct) oppure (False, "", 0)
    """
    if row.get("marketType") != "1X2":
        return False, "", 0
    if "prematch" not in row.get("source", ""):
        return False, "", 0

    old = row.get("oldPrice", 0)
    new = row.get("newPrice", 0)
    if old <= 0 or new <= 0:
        return False, "", 0

    if not (QUOTA_MIN <= old <= QUOTA_MAX):
        return False, "", 0
    if not (QUOTA_MIN <= new <= QUOTA_MAX):
        return False, "", 0

    track_key = make_track_key(row)
    last_price = last_notified_price.get(track_key)

    if last_price is None:
        # Prima volta: confronta old → new
        pct = abs((new - old) / old) * 100
        if pct < MIN_MOVE_PCT:
            return False, "", 0
        direction = "CALO" if new < old else "RIALZO"
        return True, direction, pct
    else:
        # Già notificata: confronta last_price → new
        if last_price == new:
            return False, "", 0

        pct = abs((new - last_price) / last_price) * 100
        if pct < MIN_MOVE_PCT:
            return False, "", 0

        direction = "CALO" if new < last_price else "RIALZO"
        return True, direction, pct


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Errore Telegram: {e}")
        return False


def intensity_label(pct: float) -> str:
    if pct >= 20:
        return "🔥 FORTE"
    elif pct >= 10:
        return "⚡ MEDIO"
    return "📌 LIEVE"


def build_message(row: dict, direction: str, pct: float, is_continuation: bool) -> str:
    old = row["oldPrice"]
    new = row["newPrice"]
    ts = row.get("time", "")[:16]
    label = intensity_label(pct)
    track_key = make_track_key(row)
    last_price = last_notified_price.get(track_key)

    dir_emoji = "📉" if direction == "CALO" else "📈"
    dir_text = "⬇️ CALO QUOTA" if direction == "CALO" else "⬆️ RIALZO QUOTA"
    hint = "💡 <i>Selezione sta diventando favorita</i>" if direction == "CALO" else "💡 <i>Selezione sta diventando outsider</i>"
    sel_emoji = {"HOME": "🏠", "AWAY": "✈️", "DRAW": "🤝"}.get(row["selection"], "🎯")

    continuation_line = ""
    if is_continuation and last_price:
        continuation_line = f"🔁 <i>Continua: ultima notifica a {last_price:.2f}</i>\n"

    msg = (
        f"{dir_emoji} <b>PINNACLE 1X2</b> — {dir_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>{row['league']}</b>\n"
        f"⚽ <b>{row['home']} vs {row['away']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{sel_emoji} Selezione: <b>{row['selection']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>{old:.2f} → {new:.2f}</b>  ({pct:.1f}%)  {label}\n"
        f"{continuation_line}"
        f"🕐 Rilevato: {ts}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{hint}"
    )
    return msg


def run():
    log.info("🤖 Pinnacle 1X2 Bot avviato")
    send_telegram(
        "🤖 <b>Pinnacle 1X2 Bot avviato!</b>\n\n"
        f"📊 Mercato: <b>Solo 1X2 pre-partita</b>\n"
        f"📏 Range quote: <b>{QUOTA_MIN} → {QUOTA_MAX}</b>\n"
        f"⚡ Soglia: <b>{MIN_MOVE_PCT}%</b> rispetto all'ultima quota notificata\n"
        f"🔁 Movimenti continui tracciati\n"
        f"⏱ Controllo ogni 5 minuti"
    )

    while True:
        log.info("Controllo movimenti...")
        rows = fetch_movements()
        new_alerts = 0

        for row in rows:
            valid, direction, pct = should_notify(row)
            if not valid:
                continue

            track_key = make_track_key(row)
            is_continuation = track_key in last_notified_price

            msg = build_message(row, direction, pct, is_continuation)
            if send_telegram(msg):
                last_notified_price[track_key] = row["newPrice"]
                new_alerts += 1
                log.info(
                    f"{'CONTINUA' if is_continuation else 'NUOVO'} | "
                    f"{direction} {pct:.1f}% | "
                    f"{row['home']} vs {row['away']} | "
                    f"{row['oldPrice']:.2f}→{row['newPrice']:.2f} | "
                    f"{row['selection']}"
                )
                time.sleep(0.5)

        log.info(f"Ciclo: {new_alerts} alert | {len(last_notified_price)} partite tracciate")

        if len(last_notified_price) > 500:
            last_notified_price.clear()
            log.info("Cache prezzi resettata")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
