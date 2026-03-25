import requests
import time
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

API_URL = "https://pinnacle-football-odds.p.rapidapi.com/dropping_odds?limit=100&minDropPct=5&dropMode=total&time=today&period=0&sort=dropPct&order=desc"

HEADERS = {
    "x-rapidapi-host": "pinnacle-football-odds.p.rapidapi.com",
    "x-rapidapi-key": os.getenv("RAPIDAPI_KEY")
}

seen = set()

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg
    })

while True:
    try:
        response = requests.get(API_URL, headers=HEADERS, timeout=10)
        data = response.json()

        for row in data["rows"]:
            key = row["oddsKey"]

            if key in seen:
                continue

            seen.add(key)

            # FILTRO (modifica qui)
            if row["dropPct"] < 10:
                continue

            msg = f"""🔥 QUOTA IN CALO

🏆 {row['league']}
⚽ {row['home']} vs {row['away']}

📊 {row['market']} | {row['selection']}
💰 {row['oldPrice']} → {row['newPrice']}
📉 Drop: {row['dropPct']}%
"""

            send(msg)

        time.sleep(60)

    except Exception as e:
        print("Errore:", e)
        time.sleep(30)
