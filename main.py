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

# ── FILTRI QUOTE ─────────────────────────────────────────────────────────
QUOTA_MIN = 1.20        # soglia bassa del range
QUOTA_MAX = 2.50        # soglia alta del range

# CALO:   oldPrice <= QUOTA_MAX  AND  newPrice >= QUOTA_MIN  (scende dentro il range)
# RIALZO: oldPrice >= QUOTA_MIN  AND  newPrice <= QUOTA_MAX  (sale dentro il range)
# In entrambi i casi sia old che new devono stare nel range 1.20 - 2.50
# ────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

notified_keys: set = set()


def fetch_movements() -> list:
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    }
    params = {
        "limit": 200,
        "historyDays": 1,
        "minDropPct": 1,          # soglia bassa, filtriamo noi per quote
        "dropMode": "total",
        "time": "today",
        "period": 0,              # full match
        "sort": "dropPct",
        "order": "desc",
    }
    try:
        r = requests.get(API_URL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("rows", [])
    except Exception as e:
        log.error(f"Errore fetch API: {e}")
        return []


def is_valid_movement(row: dict) -> tuple[bool, str]:
    """
    Controlla se il movimento rispetta i criteri:
    - Solo mercato 1X2
    - Solo pre-partita (source prematch)
    - oldPrice e newPrice entrambi nel range 1.20 - 2.50
    - Direzione coerente (calo o rialzo reale)

    Restituisce (True, "CALO"/"RIALZO") oppure (False, "")
    """
    # Solo 1X2
    if row.get("marketType") != "1X2":
        return False, ""

    # Solo pre-partita
    source = row.get("source", "")
    if "prematch" not in source:
        return False, ""

    old = row.get("oldPrice", 0)
    new = row.get("newPrice", 0)

    if old <= 0 or new <= 0:
        return False, ""

    # Entrambe le quote devono stare nel range 1.20 - 2.50
    if not (QUOTA_MIN <= old <= QUOTA_MAX):
        return False, ""
    if not (QUOTA_MIN <= new <= QUOTA_MAX):
        return False, ""

    # Deve esserci un movimento reale
    if old == new:
        return False, ""

    direction = "CALO" if new < old else "RIALZO"
    return True, direction


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


def movimento_label(old: float, new: float) -> str:
    """Indica quanto è significativo il movimento in termini assoluti."""
    diff = abs(new - old)
    pct = abs((new - old) / old) * 100
    if pct >= 20:
        return "🔥 FORTE"
    elif pct >= 10:
        return "⚡ MEDIO"
    else:
        return "📌 LIEVE"


def build_message(row: dict, direction: str) -> str:
    old = row["oldPrice"]
    new = row["newPrice"]
    pct = abs((new - old) / old) * 100
    ts = row.get("time", "")[:16]
    label = movimento_label(old, new)

    if direction == "CALO":
        dir_emoji = "📉"
        dir_text = "⬇️ CALO QUOTA"
        hint = "💡 <i>La selezione sta diventando favorita</i>"
    else:
        dir_emoji = "📈"
        dir_text = "⬆️ RIALZO QUOTA"
        hint = "💡 <i>La selezione sta diventando outsider</i>"

    sel_emoji = {"HOME": "🏠", "AWAY": "✈️", "DRAW": "🤝"}.get(row["selection"], "🎯")

    msg = (
        f"{dir_emoji} <b>PINNACLE 1X2</b> — {dir_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>{row['league']}</b>\n"
        f"⚽ <b>{row['home']} vs {row['away']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{sel_emoji} Selezione: <b>{row['selection']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>{old:.2f} → {new:.2f}</b>  ({pct:.1f}%)  {label}\n"
        f"🕐 Rilevato: {ts}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{hint}"
    )
    return msg


def run():
    log.info("🤖 Pinnacle 1X2 Range Bot avviato")
    send_telegram(
        "🤖 <b>Pinnacle 1X2 Range Bot avviato!</b>\n\n"
        f"📊 Mercato: <b>Solo 1X2 pre-partita</b>\n"
        f"📏 Range quote monitorato: <b>{QUOTA_MIN} → {QUOTA_MAX}</b>\n"
        f"📉 Cali e 📈 rialzi nel range\n"
        f"⏱ Controllo ogni 5 minuti"
    )

    while True:
        log.info("Controllo movimenti...")
        rows = fetch_movements()
        new_alerts = 0
        filtered = 0

        for row in rows:
            key = row.get("oddsKey", "")
            if not key or key in notified_keys:
                continue

            valid, direction = is_valid_movement(row)
            if not valid:
                filtered += 1
                continue

            msg = build_message(row, direction)
            if send_telegram(msg):
                notified_keys.add(key)
                new_alerts += 1
                log.info(
                    f"{direction} | {row['home']} vs {row['away']} | "
                    f"{row['oldPrice']:.2f}→{row['newPrice']:.2f} | "
                    f"{row['selection']}"
                )
                time.sleep(0.5)

        log.info(
            f"Ciclo: {new_alerts} alert inviati | "
            f"{filtered} movimenti fuori range | "
            f"{len(rows)} totali ricevuti"
        )

        # Pulizia cache ogni 2000 chiavi
        if len(notified_keys) > 2000:
            notified_keys.clear()
            log.info("Cache notifiche resettata")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
