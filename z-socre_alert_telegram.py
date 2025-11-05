import requests
import numpy as np
import time
import itertools
from datetime import datetime, timedelta

TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"

symbols = [
    "BTC_USDT", "ETH_USDT", "ETC_USDT", "SOL_USDT", "ADA_USDT",
    "DOT_USDT", "XRP_USDT", "XLM_USDT", "DOGE_USDT", "SHIB_USDT",
    "AVAX_USDT", "LTC_USDT", "LINK_USDT", "TRX_USDT"
]

Z_PERIOD = 300
Z_THRESHOLD = 3.0
RENOTIFY_COOLDOWN = 300  # 5분 쿨다운
price_cache = {}
last_alert_time = {}

def send_telegram_bundled(messages):
    if not messages:
        return
    full_msg = "<b>📊 Z-score 감지 알림</b>\n\n" + "\n\n".join(messages)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": full_msg, "parse_mode": "HTML"}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        print("📤 묶음 알림 전송됨", flush=True)
    except Exception as e:
        print(f"[전송 오류] {e}", flush=True)

def init_fetch_all_prices():
    for symbol in symbols:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}"
        params = {"interval": "Min5", "limit": 500}
        try:
            r = requests.get(url, params=params, timeout=5)
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                print(f"[❌ 초기 오류] {symbol}: 데이터 없음", flush=True)
                continue
            filtered = [(int(d["t"]), float(d["c"])) for d in data]
            price_cache[symbol] = filtered[-(Z_PERIOD + 10):]
            print(f"✅ {symbol}: {len(filtered)}개 수집", flush=True)
        except Exception as e:
            print(f"[❌ 초기 오류] {symbol}: {e}", flush=True)

def fetch_latest_price(symbol):
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}"
    params = {"interval": "Min5", "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=3)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            return
        ts, price = int(data[-1]["t"]), float(data[-1]["c"])
        if symbol in price_cache and (len(price_cache[symbol]) == 0 or ts > price_cache[symbol][-1][0]):
            price_cache[symbol].append((ts, price))
            price_cache[symbol] = price_cache[symbol][-Z_PERIOD - 10:]
    except Exception as e:
        print(f"[❌ 최신 봉 오류] {symbol}: {e}", flush=True)

def compute_z(s1, s2):
    d1 = price_cache.get(s1)
    d2 = price_cache.get(s2)
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
    messages = []

    for symbol in symbols:
        fetch_latest_price(symbol)
        time.sleep(0.1)

    for s1, s2 in itertools.combinations(symbols, 2):
        key = f"{s1}/{s2}"
        if now - last_alert_time.get(key, 0) < RENOTIFY_COOLDOWN:
            continue
        z = compute_z(s1, s2)
        if z is None:
            continue
        if abs(z) >= Z_THRESHOLD:
            direction = "▲ 상승" if z > 0 else "▼ 하락"
            icon = "🔴" if abs(z) >= 3.0 else "📊"
            z_value = f"<b>{z:.3f}</b>" if abs(z) >= 3.0 else f"{z:.3f}"
            msg = f"{icon} <code>{s1} / {s2}</code>\nZ-score: {z_value} {direction}"
            messages.append(msg)
            last_alert_time[key] = now
            alert = True

    if messages:
        send_telegram_bundled(messages)

    return alert

def monitor_loop():
    print("📌 초기 데이터 수집 중...", flush=True)
    init_fetch_all_prices()
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
    monitor_loop()
