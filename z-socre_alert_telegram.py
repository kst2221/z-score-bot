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
RENOTIFY_COOLDOWN = 300
start_ts_ms = 1743465600000  # 2025-04-01 00:00:00 UTC

price_history = {}
last_alert_time = {}

def send_telegram(text, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        print(f"📤 전송됨:\n{text}", flush=True)
    except Exception as e:
        print(f"[전송 오류] {e}", flush=True)

def fetch_klines(symbol, limit=1000):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "5m",
        "startTime": int((datetime.utcnow() - timedelta(days=3)).timestamp() * 1000),
        "limit": limit
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ZScoreBot/1.0; +https://example.com)"
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        return [(int(d[0]), float(d[4])) for d in data]
    except Exception as e:
        print(f"[❌ 오류] {symbol}: {e}", flush=True)
        return []

def prepare_price_data():
    for symbol in symbols:
        raw = fetch_klines(symbol)
        filtered = [(ts, price) for ts, price in raw if ts >= start_ts_ms]
        if len(filtered) >= Z_PERIOD + 1:
            price_history[symbol] = filtered
            print(f"✅ {symbol}: {len(filtered)}개 수집", flush=True)
        else:
            print(f"[SKIP] {symbol} → 데이터 부족 ({len(filtered)}개)", flush=True)

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
    if std < 1e-8:
        return None
    return (s_now - mean) / std

def monitor_once():
    alert = False
    now = time.time()
    for s1, s2 in itertools.combinations(symbols, 2):
        key = f"{s1}/{s2}"
        if now - last_alert_time.get(key, 0) < RENOTIFY_COOLDOWN:
            continue
        raw1 = fetch_klines(s1)
        raw2 = fetch_klines(s2)
        filtered1 = [(ts, price) for ts, price in raw1 if ts >= start_ts_ms]
        filtered2 = [(ts, price) for ts, price in raw2 if ts >= start_ts_ms]
        if len(filtered1) < Z_PERIOD + 1 or len(filtered2) < Z_PERIOD + 1:
            print(f"[SKIP] {key} → 데이터 부족", flush=True)
            continue
        price_history[s1] = filtered1
        price_history[s2] = filtered2
        z = compute_z(s1, s2)
        if z is None:
            print(f"[SKIP] {key} → 계산 실패", flush=True)
            continue
        if abs(z) >= Z_THRESHOLD:
            direction = "▲ 상승" if z > 0 else "▼ 하락"
            icon = "🔴" if abs(z) >= 3.0 else "📊"
            z_value = f"<b>{z:.3f}</b>" if abs(z) >= 3.0 else f"{z:.3f}"
            msg = (
                f"{icon} <b>Z-score 감지</b>\n"
                f"페어: <code>{s1} / {s2}</code>\n"
                f"Z-score: {z_value} {direction}"
            )
            send_telegram(msg, parse_mode="HTML")
            last_alert_time[key] = now
            alert = True
    return alert

def monitor_loop():
    print("📌 기준시각:", datetime.fromtimestamp(start_ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S"), flush=True)
    prepare_price_data()
    print("✅ 감시 시작\n", flush=True)
    loop_count = 0
    while True:
        print(f"🔄 Loop {loop_count} 시작", flush=True)
        sent = monitor_once()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "🔔 알림 전송됨" if sent else "📭 알림 없음"
        print(f"🕵️ [{now}] 감시 중... - {status}", flush=True)
        loop_count += 1
        time.sleep(10)

if __name__ == "__main__":
    keep_alive()
    monitor_loop()
