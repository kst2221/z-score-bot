import requests
import numpy as np
import time
import itertools
from datetime import datetime, timedelta
from keep_alive import keep_alive

TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"

symbols = [
    "BTCUSDT", "ETHUSDT", "ETCUSDT", "SOLUSDT", "ADAUSDT",
    "DOTUSDT", "XRPUSDT", "XLMUSDT", "DOGEUSDT", "1000SHIBUSDT",
    "AVAXUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"
]

Z_PERIOD = 300
Z_THRESHOLD = 2.8
RENOTIFY_COOLDOWN = 300  # 5분

price_history = {}
last_alert_time = {}

# ✅ 텔레그램
def send_telegram(text, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        print(f"📤 전송됨:\n{text}", flush=True)
    except Exception as e:
        print(f"[전송 오류] {e}", flush=True)

# ✅ 캔들 요청 (startTime 제거, limit=500)
def fetch_klines(symbol, limit=500):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "5m",
        "limit": limit
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        return [(int(d[0]), float(d[4])) for d in r.json()]
    except Exception as e:
        print(f"[❌ 오류] {symbol}: {e}", flush=True)
        return []

# ✅ Z-score 계산
def compute_z(s1, s2):
    d1 = price_history.get(s1)
    d2 = price_history.get(s2)
    if not d1 or not d2:
        return None
    min_len = min(len(d1), len(d2))
    p1 = np.array([x[1] for x in d1[-min_len:]])
    p2 = np.array([x[1] for x in d2[-min_len:]])
    r1 = np.log(p1 / p1[0])
    r2 = np.log(p2 / p2[0])
    spread = r1 - r2
    s_now = spread[-1]
    s_hist = spread[-Z_PERIOD:]
    mean = np.mean(s_hist)
    std = np.std(s_hist, ddof=1)
    return None if std < 1e-8 else (s_now - mean) / std

# ✅ 감시 1회
def monitor_once():
    alert = False
    now = time.time()
    for s1, s2 in itertools.combinations(symbols, 2):
        key = f"{s1}/{s2}"
        if now - last_alert_time.get(key, 0) < RENOTIFY_COOLDOWN:
            continue

        raw1 = fetch_klines(s1)
        time.sleep(0.3)
        raw2 = fetch_klines(s2)
        time.sleep(0.3)

        if len(raw1) < Z_PERIOD + 1 or len(raw2) < Z_PERIOD + 1:
            print(f"[SKIP] {key} → 데이터 부족", flush=True)
            continue

        price_history[s1] = raw1
        price_history[s2] = raw2
        z = compute_z(s1, s2)

        if z is None:
            print(f"[SKIP] {key} → 계산 실패", flush=True)
            continue

        if abs(z) >= Z_THRESHOLD:
            icon = "🔴" if abs(z) >= 3.0 else "📊"
            direction = "▲ 상승" if z > 0 else "▼ 하락"
            z_txt = f"<b>{z:.3f}</b>" if abs(z) >= 3.0 else f"{z:.3f}"
            msg = (
                f"{icon} <b>Z-score 감지</b>\n"
                f"페어: <code>{s1} / {s2}</code>\n"
                f"Z-score: {z_txt} {direction}"
            )
            send_telegram(msg, parse_mode="HTML")
            last_alert_time[key] = now
            alert = True
    return alert

# ✅ 루프
def monitor_loop():
    print("✅ 감시 시작", flush=True)
    count = 0
    while True:
        print(f"🔄 Loop {count}", flush=True)
        sent = monitor_once()
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"🕵️ [{t}] 상태: {'🔔 알림 전송' if sent else '📭 없음'}", flush=True)
        count += 1
        time.sleep(10)

if __name__ == "__main__":
    keep_alive()
    monitor_loop()
