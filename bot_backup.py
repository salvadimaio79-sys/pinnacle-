import os
import time
import csv
import re
import unicodedata
from io import StringIO
from difflib import SequenceMatcher

import logging
import requests

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("footystats-bot")

# =========================
# Environment
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN", "7912248885:AAFwOdg0rX3weVr6NXzW1adcUorvlRY8LyI")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID", "6146221712")

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "785e7ea308mshc88fb29d2de2ac7p12a681jsn71d79500bcd9")
RAPIDAPI_HOST = "soccer-football-info.p.rapidapi.com"

GITHUB_CSV_URL = "https://raw.githubusercontent.com/salvadimaio79-sys/footystats-bot/main/matches_today.csv"
AVG_GOALS_THRESHOLD = float(os.getenv("AVG_GOALS_THRESHOLD", "2.70"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "180"))

LEAGUE_EXCLUDE_KEYWORDS = [
    "esoccer", "volta", "8 mins", "h2h", "e-football", "fifa", "pes", 
    "battle", "virtual", "cyber", "efootball"
]

# Cache notifiche
notified_matches: set[str] = set()

# =========================
# Telegram
# =========================
def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_TOKEN/CHAT_ID mancanti")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
        if r.ok:
            logger.info("Telegram: messaggio inviato")
            return True
        logger.error("Telegram %s: %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("Telegram exception: %s", e)
    return False

# =========================
# CSV
# =========================
def load_csv_from_github():
    try:
        logger.info("Scarico CSV: %s", GITHUB_CSV_URL)
        r = requests.get(GITHUB_CSV_URL, timeout=30)
        r.raise_for_status()
        rows = list(csv.DictReader(StringIO(r.text)))
        logger.info("CSV caricato (%d righe)", len(rows))
        return rows
    except Exception as e:
        logger.exception("Errore caricamento CSV: %s", e)
        return []

def get_avg_goals(row) -> float:
    keys = [
        "Average Goals", "AVG Goals", "AvgGoals", "Avg Goals",
        "Avg Total Goals", "Average Total Goals"
    ]
    for k in keys:
        v = row.get(k)
        if v is None or str(v).strip() == "":
            continue
        try:
            return float(str(v).replace(",", "."))
        except:
            continue
    return 0.0

def filter_matches_by_avg(matches):
    """Filtra match con AVG >= soglia ED esclude esports ED filtra per oggi"""
    out = []
    excluded = 0
    wrong_date = 0
    
    # Data di oggi
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")  # es. "2024-12-16"
    
    for m in matches:
        try:
            # Controlla data match
            date_gmt = m.get("date_GMT", "")
            
            # Estrai data (formato: "Dec 16 2024" o "2024-12-16" o simili)
            if date_gmt:
                # Prova parsing diversi formati
                match_date = None
                
                # Formato 1: "Dec 16 2024 - 3:00pm"
                if "202" in date_gmt:  # Contiene anno
                    import re
                    # Estrai "Dec 16 2024"
                    date_part = re.search(r'([A-Za-z]+ \d+ 202\d)', date_gmt)
                    if date_part:
                        try:
                            dt = datetime.strptime(date_part.group(1), "%b %d %Y")
                            match_date = dt.strftime("%Y-%m-%d")
                        except:
                            pass
                
                # Se non è oggi, salta
                if match_date and match_date != today:
                    wrong_date += 1
                    continue
            
            # Escludi esports
            league = m.get("League", "").lower()
            country = m.get("Country", "").lower()
            
            if any(kw in league or kw in country for kw in LEAGUE_EXCLUDE_KEYWORDS):
                excluded += 1
                continue
            
            # Controlla AVG
            if get_avg_goals(m) >= AVG_GOALS_THRESHOLD:
                out.append(m)
        except:
            pass
    
    logger.info("Filtrati per AVG >= %.2f: %d", AVG_GOALS_THRESHOLD, len(out))
    if excluded > 0:
        logger.info("Esclusi %d match esports/virtuali", excluded)
    if wrong_date > 0:
        logger.info("Esclusi %d match di altri giorni", wrong_date)
    
    return out

# =========================
# Live events
# =========================
def get_live_matches():
    try:
        url = f"https://{RAPIDAPI_HOST}/live/full/"
        headers = {'x-rapidapi-key': RAPIDAPI_KEY, 'x-rapidapi-host': RAPIDAPI_HOST}
        params = {'i': 'en_US', 'f': 'json', 'e': 'no'}
        
        r = requests.get(url, headers=headers, params=params, timeout=25)
        if not r.ok:
            logger.error("HTTP %s", r.status_code)
            return []
        
        data = r.json()
        events = []
        
        for event in data.get("result", []):
            team_a = event.get("teamA", {})
            team_b = event.get("teamB", {})
            
            home = team_a.get("name", "").strip()
            away = team_b.get("name", "").strip()
            
            if not home or not away:
                continue
            
            # Escludi esports
            league = event.get("league", {})
            
            # Prova diversi formati per la lega
            if isinstance(league, dict):
                league_name = league.get("name") or league.get("cc") or "Unknown"
            elif isinstance(league, str):
                league_name = league
            else:
                league_name = "Unknown"
            
            # Fallback: prova anche "leagueName" o "competition"
            if league_name == "Unknown":
                league_name = event.get("leagueName") or event.get("competition") or event.get("tournament", {}).get("name", "Unknown")
            
            if any(kw in league_name.lower() for kw in LEAGUE_EXCLUDE_KEYWORDS):
                continue
            
            # Estrai minuto
            timer = event.get("timer", "")
            minute = 0
            if timer and ':' in timer:
                try:
                    minute = int(timer.split(':')[0])
                except:
                    pass
            
            # Estrai score (gestisci stringhe vuote!)
            score_a = team_a.get("score", {})
            score_b = team_b.get("score", {})
            
            # Safe conversion - handle empty strings
            try:
                home_score = int(score_a.get("f", 0) or 0) if isinstance(score_a, dict) else 0
            except (ValueError, TypeError):
                home_score = 0
            
            try:
                away_score = int(score_b.get("f", 0) or 0) if isinstance(score_b, dict) else 0
            except (ValueError, TypeError):
                away_score = 0
            
            events.append({
                "home": home,
                "away": away,
                "league": league_name,
                "minute": minute,
                "home_score": home_score,
                "away_score": away_score,
                "SS": f"{home_score}-{away_score}"
            })
        
        logger.info("API live-events: %d match live", len(events))
        return events
        
    except Exception as e:
        logger.exception("Errore get_live_matches: %s", e)
        return []

# =========================
# Matching nomi squadre
# =========================
STOPWORDS = {
    "fc","cf","sc","ac","club","cd","de","del","da","do","d","u19","u20","u21","u23",
    "b","ii","iii","women","w","reserves","team","sv","afc","youth","if","fk"
}

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))

def norm_text(s: str) -> str:
    s = strip_accents(s).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[''`]", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

def team_tokens(name: str) -> set[str]:
    toks = [t for t in norm_text(name).split() if t and t not in STOPWORDS]
    toks = [t for t in toks if len(t) >= 3 or t.isdigit()]
    return set(toks)

def token_match(a: str, b: str) -> bool:
    A, B = team_tokens(a), team_tokens(b)
    if not A or not B:
        return False
    if A == B or A.issubset(B) or B.issubset(A):
        return True
    inter = A & B
    if len(A) == 1 or len(B) == 1:
        return len(inter) >= 1
    return len(inter) >= 2

def fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_text(a), norm_text(b)).ratio()

def is_acronym_match(short: str, long: str) -> bool:
    """Check se short è acronimo di long (es. ABB = Academia Balompie Boliviano)"""
    short_clean = norm_text(short).replace(" ", "")
    long_words = norm_text(long).split()
    
    # Filtra stopwords
    long_words_filtered = [w for w in long_words if w not in STOPWORDS and len(w) >= 3]
    
    if len(short_clean) < 2 or len(short_clean) > 6:
        return token_match(short, long)
    
    # Costruisci acronimo
    if len(long_words_filtered) >= len(short_clean):
        acronym = "".join(w[0] for w in long_words_filtered if w)
        if short_clean == acronym[:len(short_clean)] or short_clean == acronym:
            return True
    
    return token_match(short, long)

def match_teams(csv_match, live_match) -> bool:
    csv_home = csv_match.get("Home Team") or csv_match.get("Home") or ""
    csv_away = csv_match.get("Away Team") or csv_match.get("Away") or ""
    live_home = live_match.get("home", "")
    live_away = live_match.get("away", "")
    
    # 1) Token match
    if token_match(csv_home, live_home) and token_match(csv_away, live_away):
        return True
    
    # 2) Acronym match
    if is_acronym_match(csv_home, live_home) and is_acronym_match(csv_away, live_away):
        return True
    
    # 3) Fuzzy fallback
    rh = fuzzy_ratio(csv_home, live_home)
    ra = fuzzy_ratio(csv_away, live_away)
    if (rh >= 0.72 and ra >= 0.60) or (rh >= 0.60 and ra >= 0.72):
        return True
    
    return False

# =========================
# Business logic
# =========================
def check_matches():
    logger.info("=" * 60)
    logger.info("INIZIO CONTROLLO")
    logger.info("=" * 60)
    
    csv_matches = load_csv_from_github()
    if not csv_matches:
        logger.warning("CSV vuoto")
        return
    
    filtered = filter_matches_by_avg(csv_matches)
    if not filtered:
        logger.info("Nessun match con AVG >= soglia")
        return
    
    live = get_live_matches()
    if not live:
        logger.info("Nessun live attualmente")
        return
    
    matched = 0
    opportunities = 0
    
    for cm in filtered:
        for lm in live:
            if not match_teams(cm, lm):
                continue
            
            matched += 1
            
            # Controlla HT 0-0
            minute = lm.get("minute", 0)
            if not (44 <= minute <= 47):
                continue
            
            if lm.get("home_score", 0) != 0 or lm.get("away_score", 0) != 0:
                continue
            
            # Match a HT 0-0!
            logger.info("Abbinato: %s vs %s | %s | %d' | %s",
                       lm['home'], lm['away'], lm['SS'], minute, lm['league'])
            
            # Controlla se già notificato
            key = f"{lm['home']}|{lm['away']}"
            if key in notified_matches:
                continue
            
            # Invia notifica
            avg = get_avg_goals(cm)
            
            # Estrai paese dal CSV
            country = cm.get("Country", "Unknown")
            
            msg = (
                "🚨 <b>SEGNALE OVER 1.5!</b>\n\n"
                f"⚽ <b>{lm['home']} vs {lm['away']}</b>\n"
                f"🌍 {country}\n"
                f"🏆 {lm['league']}\n"
                f"📊 AVG Goals: <b>{avg:.2f}</b>\n"
                f"⏱️ <b>{minute}'</b> - Risultato: <b>{lm['SS']}</b>\n"
                "✅ Controlla quote live!\n\n"
                "🎯 <b>Punta Over 1.5 FT</b>"
            )
            
            if send_telegram_message(msg):
                notified_matches.add(key)
                opportunities += 1
    
    logger.info("Riepilogo: Abbinati CSV↔Live=%d | Opportunità=%d", matched, opportunities)
    logger.info("=" * 60)

def main():
    logger.info("Bot avviato")
    logger.info("Soglia AVG: %.2f | Check ogni: %d sec", AVG_GOALS_THRESHOLD, CHECK_INTERVAL)
    
    send_telegram_message("🤖 <b>FootyStats Bot avviato</b>\nMonitoraggio partite in corso…")
    
    while True:
        try:
            check_matches()
            logger.info("Sleep %ds…", CHECK_INTERVAL)
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            send_telegram_message("⛔ Bot arrestato")
            break
        except Exception as e:
            logger.exception("Errore loop principale: %s", e)
            time.sleep(60)

if __name__ == "__main__":
    main()
