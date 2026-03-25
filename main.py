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

POLL_INTERVAL = 300        # 5 minuti
MIN_DROP_PCT = 10.0        # soglia minima movimento %
HISTORY_DAYS = 1           # ultimi N giorni
# ────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# Tiene traccia degli oddsKey già notificati per evitare duplicati
notified_keys: set = set()


def fetch_movements(drop_mode: str = "total") -> list:
    """Chiama l'API e restituisce i movimenti filtrati."""
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    }
    params = {
        "limit": 100,
        "historyDays": HISTORY_DAYS,
        "minDropPct": MIN_DROP_PCT,
        "dropMode": drop_mode,
        "time": "today",
        "period": 0,
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


def send_telegram(text: str) -> bool:
    """Invia un messaggio Telegram."""
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


def direction_emoji(old: float, new: float) -> str:
    if new < old:
        return "📉"   # quota scende → selezione favorita
    elif new > old:
        return "📈"   # quota sale → selezione sfavorita
    return "➡️"


def format_market(market_type: str, market: str, line: str) -> str:
    if market_type == "1X2":
        return "1X2"
    if market_type == "AH":
        return f"Asian Handicap {line}"
    if market_type == "OU":
        return f"Over/Under {line}"
    return market


def build_message(row: dict) -> str:
    old = row["oldPrice"]
    new = row["newPrice"]
    pct = row["dropPct"]
    emoji = direction_emoji(old, new)
    direction = "⬇️ CALO" if new < old else "⬆️ RIALZO"
    market_str = format_market(row["marketType"], row["market"], row["line"])
    ts = row.get("time", "")[:16]

    msg = (
        f"{emoji} <b>MOVIMENTO QUOTA PINNACLE</b> {direction}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>{row['league']}</b>\n"
        f"⚽ {row['home']} vs {row['away']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Mercato: <b>{market_str}</b>\n"
        f"🎯 Selezione: <b>{row['selection']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Quota: <b>{old:.3f}</b> → <b>{new:.3f}</b>\n"
        f"📏 Variazione: <b>{pct:.1f}%</b>\n"
        f"🕐 Rilevato: {ts}"
    )
    return msg


def run():
    log.info("🤖 Pinnacle Odds Bot avviato")
    send_telegram(
        "🤖 <b>Pinnacle Odds Bot avviato!</b>\n"
        f"Monitoraggio ogni 5 minuti\n"
        f"Soglia minima: ±{MIN_DROP_PCT}% | Tutti i mercati"
    )

    while True:
        log.info("Controllo movimenti...")
        rows = fetch_movements()
        new_alerts = 0

        for row in rows:
            key = row.get("oddsKey", "")
            if not key or key in notified_keys:
                continue

            # Filtra per soglia
            if abs(row.get("dropPct", 0)) < MIN_DROP_PCT:
                continue

            msg = build_message(row)
            if send_telegram(msg):
                notified_keys.add(key)
                new_alerts += 1
                log.info(f"Notifica inviata: {row['home']} vs {row['away']} | {row['dropPct']}%")
                time.sleep(0.5)  # evita flood Telegram

        log.info(f"Ciclo completato: {new_alerts} nuovi alert su {len(rows)} movimenti")

        # Pulizia memoria ogni 1000 chiavi
        if len(notified_keys) > 1000:
            notified_keys.clear()
            log.info("Cache notifiche resettata")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
    
