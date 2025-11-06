import requests
import numpy as np
import time
import itertools
from datetime import datetime, timedelta

# =========================
# ✅ 설정
# =========================
# EXCHANGE: "MEXC_SPOT" 또는 "MEXC_FUTURES"
EXCHANGE = "MEXC_SPOT"  # 선물로 쓰려면 "MEXC_FUTURES"

# 텔레그램 설정
TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"

# 감시 심볼(바이낸스 표기 기반 입력)
symbols = [
    "BTCUSDT", "ETHUSDT", "ETCUSDT", "SOLUSDT", "ADAUSDT",
    "DOTUSDT", "XRPUSDT", "XLMUSDT", "DOGEUSDT", "1000SHIBUSDT",
    "AVAXUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"
]

Z_PERIOD = 300
Z_THRESHOLD = 2.9
RENOTIFY_COOLDOWN = 300  # 5분

# 기준 시점
start_time = datetime(2025, 4, 1, 0, 0)
start_ts_ms = int(start_time.timestamp() * 1000)

price_history = {}
last_alert_time = {}

# =========================
# ✅ 심볼 매핑 (거래소별 표기 차이吸収)
# =========================
def to_mexc_symbol_spot(binance_symbol: str) -> str:
    """
    MEXC 스팟은 바이낸스와 거의 동일 심볼을 사용.
    단, 1000SHIBUSDT 같은 특수 표기는 MEXC에선 SHIBUSDT로 거래됨.
    """
    if binance_symbol == "1000SHIBUSDT":
        return "SHIBUSDT"
    return binance_symbol

def to_mexc_symbol_futures(binance_symbol: str) -> str:
    """
    MEXC USDT-M 선물: 언더바 표기 (예: BTC_USDT)
    또한 1000SHIBUSDT → 1000SHIB_USDT 로 매핑
    """
    if binance_symbol == "1000SHIBUSDT":
        return "1000SHIB_USDT"
    # 기본 변환: XXXUSDT → XXX_USDT
    if binance_symbol.endswith("USDT"):
        return binance_symbol[:-4] + "_USDT"
    return binance_symbol  # 혹시 모를 예외

# =========================
# ✅ 데이터 수집 (MEXC 어댑터)
# =========================
def fetch_klines(symbol, limit=1000):
    """
    거래소별로 캔들을 가져와 [(ts_ms, close_float), ...] 형태로 반환.
    startTime은 일부 엔드포인트에서 필수가 아니라 필터는 로컬에서 적용.
    """
    try:
        if EXCHANGE == "MEXC_SPOT":
            # MEXC Spot (바이낸스 v3와 매우 유사)
            mx_symbol = to_mexc_symbol_spot(symbol)
            url = "https://api.mexc.com/api/v3/klines"
            params = {
                "symbol": mx_symbol,
                "interval": "5m",
                "startTime": int((datetime.utcnow() - timedelta(days=3)).timestamp() * 1000),
                "limit": limit
            }
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            # 응답: [[openTime, open, high, low, close, volume, closeTime, ...], ...]
            klines = [(int(d[0]), float(d[4])) for d in data]

        elif EXCHANGE == "MEXC_FUTURES":
            # MEXC USDT-M Futures
            mx_symbol = to_mexc_symbol_futures(symbol)
            url = "https://contract.mexc.com/api/v1/contract/kline"
            # interval 예: Min1, Min5, Min15, Min60, Day1 ...
            params = {
                "symbol": mx_symbol,
                "interval": "Min5",
                "limit": limit
                # 일부 문서엔 start/end 지원. 여기선 limit로 받고 로컬 필터.
                # "start": int((datetime.utcnow() - timedelta(days=3)).timestamp() * 1000)
            }
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()

            # 응답 형식 방어적 파싱
            rows = data["data"] if isinstance(data, dict) and "data" in data else data
            klines = []
            for row in rows:
                # dict형: {"t": 1712003100000, "o":"", "h":"", "l":"", "c":"", ...}
                if isinstance(row, dict):
                    ts = int(row.get("t"))
                    close = float(row.get("c"))
                else:
                    # 배열형: [t, o, h, l, c, v] 등
                    ts = int(row[0])
                    close = float(row[4])
                klines.append((ts, close))
        else:
            raise ValueError("EXCHANGE 설정이 올바르지 않습니다. 'MEXC_SPOT' 또는 'MEXC_FUTURES'")

        return klines
    except Exception as e:
        print(f"[오류] {EXCHANGE} {symbol} 데이터 수신 실패: {e}")
        return []

# =========================
# ✅ 공통 유틸
# =========================
def send_telegram(text, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        print(f"📤 전송됨: {text[:120]}...")
    except Exception as e:
        print(f"[전송 오류] {e}")

def prepare_price_data():
    for symbol in symbols:
        raw = fetch_klines(symbol, limit=1000)
        filtered = [(ts, price) for ts, price in raw if ts >= start_ts_ms]
        if len(filtered) >= Z_PERIOD + 1:
            price_history[symbol] = filtered
            print(f"{symbol}: {len(filtered)}개 수집 완료 ({EXCHANGE})")
        else:
            print(f"{symbol}: 데이터 부족 ({len(filtered)}개)")

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
        last_time = last_alert_time.get(key, 0)

        if now - last_time >= RENOTIFY_COOLDOWN:
            raw1 = fetch_klines(s1, limit=1000)
            raw2 = fetch_klines(s2, limit=1000)

            filtered1 = [(ts, price) for ts, price in raw1 if ts >= start_ts_ms]
            filtered2 = [(ts, price) for ts, price in raw2 if ts >= start_ts_ms]
            if len(filtered1) < Z_PERIOD + 1 or len(filtered2) < Z_PERIOD + 1:
                print(f"[SKIP] {key} → 데이터 부족")
                continue

            price_history[s1] = filtered1
            price_history[s2] = filtered2

            z = compute_z(s1, s2)
            if z is None:
                print(f"[SKIP] {key} → 계산 실패")
                continue

            if abs(z) >= Z_THRESHOLD:
                direction = "▲ 상승" if z > 0 else "▼ 하락"
                icon = "🔴" if abs(z) >= 3.0 else "📊"
                z_value = f"<b>{z:.3f}</b>" if abs(z) >= 3.0 else f"{z:.3f}"

                msg = (
                    f"{icon} <b>Z-score 감지</b>\n"
                    f"페어: <code>{s1} / {s2}</code>\n"
                    f"Z-score: {z_value} {direction}\n"
                    f"소스: {EXCHANGE}"
                )
                send_telegram(msg, parse_mode="HTML")
                last_alert_time[key] = now
                alert = True
    return alert

def monitor_loop():
    print("📌 기준시각:", datetime.fromtimestamp(start_ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S"))
    print(f"📡 거래소 모드: {EXCHANGE}")
    prepare_price_data()
    print("✅ 감시 시작\n")
    while True:
        sent = monitor_once()
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "🔔 알림 전송됨" if sent else "📭 알림 없음"
        print(f"🕵️ [{t}] 감시 중... - {status}")
        time.sleep(10)

if __name__ == "__main__":
    monitor_loop()
