import requests
import numpy as np
import time
import itertools
from datetime import datetime, timedelta

# ✅ 텔레그램 설정
TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"

# ✅ 감시 종목 목록
symbols = [
    "BTCUSDT", "ETHUSDT", "ETCUSDT", "SOLUSDT", "ADAUSDT",
    "DOTUSDT", "XRPUSDT", "XLMUSDT", "DOGEUSDT", "1000SHIBUSDT",
    "AVAXUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"
]

Z_PERIOD = 300
Z_THRESHOLD = 2.8
RENOTIFY_COOLDOWN = 300  # 5분 쿨다운
start_ts_ms = int(datetime(2025, 4, 1, 0, 0).timestamp() * 1000)

price_cache = {}
last_alert_time = {}

# ✅ 텔레그램 메시지 전송 (묶음)
def send_telegram_bundled(messages):
    if not messages:
        return
    full_msg = "<b>📊 Z-score 감지 알림</b>\n\n" + "\n\n".join(messages)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": full_msg,
        "parse_mode": "HTML"
    }
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        print("📤 묶음 알림 전송됨", flush=True)
    except Exception as e:
        print(f"[전송 오류] {e}", flush=True)

# ✅ 최초 전체 수집
def init_fetch_all_prices():
    for symbol in symbols:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": "5m",
            "startTime": int((datetime.utcnow() - timedelta(days=3)).timestamp() * 1000),
            "limit": 1000
        }
        try:
            r = requests.get(url, params=params, timeout=5)
            r.raise_for_status()
            data = r.json()
            filtered = [(int(d[0]), float(d[4])) for d in data if int(d[0]) >= start_ts_ms]
            price_cache[symbol] = filtered[-(Z_PERIOD + 10):]
            print(f"✅ {symbol}: {len(filtered)}개 수집", flush=True)
        except Exception as e:
            print(f"[❌ 초기 오류] {symbol}: {e}", flush=True)

# ✅ 최신 봉만 추가
def fetch_latest_price(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "5m", "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=3)
        r.raise_for_status()
        data = r.json()
        ts, price = int(data[-1][0]), float(data[-1][4])
        if symbol in price_cache and (len(price_cache[symbol]) == 0 or ts > price_cache[symbol][-1][0]):
            price_cache[symbol].append((ts, price))
            price_cache[symbol] = price_cache[symbol][-Z_PERIOD - 10:]
    except Exception as e:
        print(f"[❌ 최신 봉 오류] {symbol}: {e}", flush=True)

# ✅ Z-score 계산
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

# ✅ 감시 1회 루프
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
            print(f"[SKIP] {key} → 계산 실패", flush=True)
            continue
        if abs(z) >= Z_THRESHOLD:
            direction = "▲ 상승" if z > 0 else "▼ 하락"
            icon = "🔴" if abs(z) >= 3.0 else "📊"
            z_value = f"<b>{z:.3f}</b>" if abs(z) >= 3.0 else f"{z:.3f}"
            msg = (
                f"{icon} <code>{s1} / {s2}</code>\n"
                f"Z-score: {z_value} {direction}"
            )
            messages.append(msg)
            last_alert_time[key] = now
            alert = True

    if messages:
        send_telegram_bundled(messages)

    return alert

# ✅ 루프 시작
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

# ✅ 실행
if __name__ == "__main__":
    monitor_loop()
