# filename: z_score_alert_telegram_mexc.py
import requests
import numpy as np
import time
import itertools
from datetime import datetime

# =========================
# 🔧 설정
# =========================
TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"  # 채널/그룹이면 -100... 형식

# MEXC 선물 심볼 표기
SYMBOLS = [
    "BTC_USDT","ETH_USDT","ETC_USDT","SOL_USDT","ADA_USDT",
    "DOT_USDT","XRP_USDT","XLM_USDT","DOGE_USDT","1000SHIB_USDT",
    "AVAX_USDT","LTC_USDT","LINK_USDT","TRX_USDT"
]

INTERVAL = "Min5"   # 5분봉
Z_PERIOD = 300      # Z-score 계산 구간(캔들 수)
Z_THRESHOLD = 3.0   # 알림 임계값
RENOTIFY_COOLDOWN = 300  # 초(=5분). 같은 페어 재알림 쿨다운

# 요청 공통
BASE = "https://contract.mexc.com/api/v1/contract/kline"
HEADERS = {"User-Agent": "Mozilla/5.0 (z-score-bot/1.0)"}

# 캐시/상태
price_cache = {}      # {symbol: [(ts_ms, close), ...]}
last_alert_time = {}  # {"BTC_USDT/ETH_USDT": epoch_seconds}
session = requests.Session()


# =========================
# 📤 텔레그램
# =========================
def send_telegram_bundled(messages):
    if not messages:
        return
    full_msg = "<b>📊 Z-score 감지 알림</b>\n\n" + "\n\n".join(messages)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": full_msg, "parse_mode": "HTML"}
    try:
        r = session.get(url, params=params, timeout=10)
        r.raise_for_status()
        print("📤 묶음 알림 전송됨", flush=True)
    except Exception as e:
        # 텔레그램 오류는 실행엔 지장 없도록 로깅만
        print(f"[전송 오류] {e}", flush=True)


# =========================
# 🔎 MEXC Kline 가져오기/파싱
# =========================
def _parse_item(it):
    """
    MEXC kline item 포맷은 환경에 따라 dict 또는 list로 제공될 수 있음.
    - dict 예: {"t": 1717228800000, "o":"...", "h":"...", "l":"...", "c":"...", "v":"..."}
    - list 예: [time, open, high, low, close, volume, ...]
    두 경우 모두 (ts_ms:int, close:float)로 변환.
    """
    if isinstance(it, dict):
        t = it.get("t") or it.get("time")
        c = it.get("c") or it.get("close")
        if t is None or c is None:
            return None
        return int(t), float(c)
    elif isinstance(it, (list, tuple)) and len(it) >= 5:
        # [time, open, high, low, close, volume, ...]
        return int(it[0]), float(it[4])
    return None


def mexc_klines(symbol: str, limit: int = 500):
    """
    K라인 요청. 성공 시 [(ts_ms, close), ...] 반환, 실패 시 None.
    429/네트워크 오류에 대해 짧은 백오프 포함.
    """
    params = {"symbol": symbol, "interval": INTERVAL, "limit": limit}
    try:
        r = session.get(BASE, params=params, headers=HEADERS, timeout=10)
        if r.status_code == 429:
            print(f"[레이트리밋] {symbol}: 429 → 0.5s 대기", flush=True)
            time.sleep(0.5)
            r = session.get(BASE, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        body = r.json()
        data = body["data"] if isinstance(body, dict) and "data" in body else body
        if not data:
            return []
        parsed = [_parse_item(x) for x in data]
        parsed = [p for p in parsed if p]
        return parsed
    except requests.HTTPError as e:
        txt = ""
        try:
            txt = r.text[:200]
        except Exception:
            pass
        print(f"[HTTP 오류] {symbol}: {r.status_code} {txt}", flush=True)
        return None
    except Exception as e:
        print(f"[요청 오류] {symbol}: {e}", flush=True)
        return None


# =========================
# 📥 초기 로딩 & 최신 봉 갱신
# =========================
def init_fetch_all_prices():
    for symbol in SYMBOLS:
        data = mexc_klines(symbol, limit=500)
        if data is None:
            print(f"[❌ 초기 오류] {symbol}: 요청 실패", flush=True)
            continue
        if not data:
            print(f"[❌ 초기 오류] {symbol}: 데이터 없음", flush=True)
            continue
        price_cache[symbol] = data[-(Z_PERIOD + 10):]
        print(f"✅ {symbol}: {len(data)}개 수집", flush=True)


def fetch_latest_price(symbol):
    data = mexc_klines(symbol, limit=1)
    if data is None:
        print(f"[✖ 최신 봉 오류] {symbol}: 요청 실패", flush=True)
        return
    if not data:
        print(f"[✖ 최신 봉 오류] {symbol}: 빈 응답", flush=True)
        return
    ts, close = data[-1]
    buf = price_cache.get(symbol, [])
    if not buf or ts > buf[-1][0]:
        buf.append((ts, close))
        price_cache[symbol] = buf[-(Z_PERIOD + 10):]


# =========================
# 🧮 Z-score
# =========================
def compute_z(s1, s2):
    d1 = price_cache.get(s1)
    d2 = price_cache.get(s2)
    if not d1 or not d2:
        return None
    n = min(len(d1), len(d2))
    if n < Z_PERIOD + 1:
        return None
    p1 = np.array([x[1] for x in d1[-n:]], dtype=float)
    p2 = np.array([x[1] for x in d2[-n:]], dtype=float)
    r1 = np.log(p1 / p1[0])
    r2 = np.log(p2 / p2[0])
    spread = r1 - r2
    s_hist = spread[-Z_PERIOD:]
    s_now = spread[-1]
    std = np.std(s_hist, ddof=1)
    if std < 1e-8:
        return None
    return (s_now - np.mean(s_hist)) / std


# =========================
# 🔁 모니터링 루프
# =========================
def monitor_once():
    alert_sent = False
    now = time.time()
    messages = []

    # 최신 봉 갱신
    for sym in SYMBOLS:
        fetch_latest_price(sym)
        time.sleep(0.1)  # 레이트리밋 여유

    # 페어별 Z-score 계산 & 알림 수집
    for s1, s2 in itertools.combinations(SYMBOLS, 2):
        key = f"{s1}/{s2}"
        if now - last_alert_time.get(key, 0) < RENOTIFY_COOLDOWN:
            continue
        z = compute_z(s1, s2)
        if z is None:
            # 디버그 원하면 아래 주석 해제
            # print(f"[SKIP] {key} 계산불가", flush=True)
            continue
        if abs(z) >= Z_THRESHOLD:
            direction = "▲ 상승" if z > 0 else "▼ 하락"
            icon = "🔴" if abs(z) >= 3.0 else "📊"
            z_value = f"<b>{z:.3f}</b>" if abs(z) >= 3.0 else f"{z:.3f}"
            msg = f"{icon} <code>{s1} / {s2}</code>\nZ-score: {z_value} {direction}"
            messages.append(msg)
            last_alert_time[key] = now
            alert_sent = True

    if messages:
        send_telegram_bundled(messages)

    return alert_sent


def monitor_loop():
    print("📌 초기 데이터 수집 중...", flush=True)
    init_fetch_all_prices()
    print("✅ 감시 시작\n", flush=True)

    loop = 0
    while True:
        print(f"🔄 Loop {loop} 시작", flush=True)
        sent = monitor_once()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "🔔 알림 전송됨" if sent else "📭 알림 없음"
        print(f"🕵️ [{now_str}] 감시 중... - {status}", flush=True)
        loop += 1
        time.sleep(10)


if __name__ == "__main__":
    monitor_loop()
