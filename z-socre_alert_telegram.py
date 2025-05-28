import requests
import numpy as np
import time
import itertools
from datetime import datetime, timedelta

# ✅ 텔레그램 설정
TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"

# ✅ 감시할 종목 목록
symbols = [
    "BTCUSDT", "ETHUSDT", "ETCUSDT", "SOLUSDT", "ADAUSDT",
    "DOTUSDT", "XRPUSDT", "XLMUSDT", "DOGEUSDT", "1000SHIBUSDT",
    "AVAXUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"
]

Z_PERIOD = 300
Z_THRESHOLD = 2.9
RENOTIFY_COOLDOWN = 300  # 동일 쌍 알림 쿨다운 (초)

# 기준 시각 (과거 데이터 필터 기준)
start_time = datetime(2025, 4, 1, 0, 0)
start_ts_ms = int(start_time.timestamp() * 1000)

# 전역 상태 저장
price_cache = {}
last_alert_time = {}

# ✅ 텔레그램 전송 함수
def send_telegram(text, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    if parse_mode:
        params["parse_mode"] = parse_mode

    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        print(f"📤 전송됨:\n{text}", flush=True)
    except Exception as e:
        print(f"[전송 오류] {e}", flush=True)

# ✅ 바이낸스 캔들 데이터 요청 함수 (캐싱 포함)
def fetch_klines(symbol, limit=1000):
    if symbol in price_cache:
        return price_cache[symbol]

    print(f"⏳ [요청] {symbol} 가격 데이터 요청 중...", flush=True)

    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "5m",
        "startTime": int((datetime.utcnow() - timedelta(days=3)).timestamp() * 1000),
        "limit": limit
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ZScoreBot/1.0; +https://yourdomain.com)"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        result = [(int(d[0]), float(d[4])) for d in data]
        price_cache[symbol] = result
        print(f"✅ [성공] {symbol} 수신 완료 ({len(result)}개)", flush=True)
        return result

    except requests.exceptions.HTTPError as e:
        print(f"[❌ 오류] {symbol} 데이터 수신 실패: {e} ({response.status_code})", flush=True)
    except requests.exceptions.RequestException as e:
        print(f"[❌ 오류] {symbol} 네트워크 문제: {e}", flush=True)
    
    return []

# ✅ Z-score 계산 함수
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

    z = (s_now - mean) / std
    return z

# ✅ 한 주기 감시 함수
def monitor_once():
    alert = False
    now = time.time()

    for s1, s2 in itertools.combinations(symbols, 2):
        key = f"{s1}/{s2}"
        last_time = last_alert_time.get(key, 0)

        if now - last_time < RENOTIFY_COOLDOWN:
            continue

        raw1 = fetch_klines(s1)
        time.sleep(0.75)
        raw2 = fetch_klines(s2)
        time.sleep(0.75)

        filtered1 = [(ts, price) for ts, price in raw1 if ts >= start_ts_ms]
        filtered2 = [(ts, price) for ts, price in raw2 if ts >= start_ts_ms]

        if len(filtered1) < Z_PERIOD + 1 or len(filtered2) < Z_PERIOD + 1:
            print(f"[SKIP] {key} → 데이터 부족 ({len(filtered1)} / {len(filtered2)})", flush=True)
            continue

        price_cache[s1] = filtered1
        price_cache[s2] = filtered2

        z = compute_z(s1, s2)
        if z is None:
            print(f"[SKIP] {key} → Z-score 계산 실패", flush=True)
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

# ✅ 루프 감시 시작 함수
def monitor_loop():
    print("📌 기준시각:", datetime.fromtimestamp(start_ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S"), flush=True)
    print("✅ 감시 시작\n", flush=True)

    loop_count = 0

    while True:
        print(f"🔄 Loop {loop_count} 시작", flush=True)
        sent = monitor_once()
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "🔔 알림 전송됨" if sent else "📭 알림 없음"
        print(f"🕵️ [{t}] 감시 중... - {status}", flush=True)
        time.sleep(10)
        loop_count += 1

# ✅ 실행 시작
if __name__ == "__main__":
    monitor_loop()
