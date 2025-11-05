# filename: z_score_alert_telegram_mexc.py
import requests, numpy as np, time, itertools
from datetime import datetime

TELEGRAM_TOKEN = "8086474503:AAEgYSqUDtb8GgL4aWkE3_VnFr4m4ea2dgU"
TELEGRAM_CHAT_ID = "-1002618818544"

# ⬇️ SHIB 교정(1000SHIB_USDT → SHIB_USDT)
SYMBOLS = [
    "BTC_USDT","ETH_USDT","ETC_USDT","SOL_USDT","ADA_USDT",
    "DOT_USDT","XRP_USDT","XLM_USDT","DOGE_USDT","SHIB_USDT",
    "AVAX_USDT","LTC_USDT","LINK_USDT","TRX_USDT"
]

Z_PERIOD=300; Z_THRESHOLD=3.0; RENOTIFY_COOLDOWN=300
BASE = "https://contract.mexc.com/api/v1/contract/kline"
HEADERS={"User-Agent":"Mozilla/5.0 (z-score-bot/1.0)"}
price_cache={}; last_alert_time={}; session=requests.Session()

def send_telegram_bundled(messages):
    if not messages: return
    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params={"chat_id":TELEGRAM_CHAT_ID,"text":"<b>📊 Z-score 감지 알림</b>\n\n"+'\n\n'.join(messages),"parse_mode":"HTML"}
    try:
        r=session.get(url,params=params,timeout=10); r.raise_for_status()
        print("📤 묶음 알림 전송됨", flush=True)
    except Exception as e:
        print(f"[전송 오류] {e}", flush=True)

def _parse_item(it):
    if isinstance(it, dict):
        t=it.get("t") or it.get("time"); c=it.get("c") or it.get("close")
        if t is None or c is None: return None
        return int(t), float(c)
    if isinstance(it,(list,tuple)) and len(it)>=5:
        return int(it[0]), float(it[4])
    return None

def mexc_klines(symbol:str, limit:int=500):
    # 1차: type=Min5, 2차: interval=Min5 (일부 배포 호환)
    variants = [
        {"type":"Min5","limit":limit},
        {"interval":"Min5","limit":limit}
    ]
    for params in variants:
        try:
            q={"symbol":symbol, **params}
            r=session.get(BASE, params=q, headers=HEADERS, timeout=10)
            if r.status_code==429:
                print(f"[레이트리밋] {symbol}: 429 → 0.5s 대기", flush=True); time.sleep(0.5)
                r=session.get(BASE, params=q, headers=HEADERS, timeout=10)
            r.raise_for_status()
            body=r.json()
            data = body["data"] if isinstance(body,dict) and "data" in body else body
            if not data: 
                # 빈 배열이면 다음 variant 시도
                continue
            parsed=[_parse_item(x) for x in data]; parsed=[p for p in parsed if p]
            if parsed: return parsed
        except requests.HTTPError:
            # 404/기타면 다음 variant 시도 (마지막 실패는 바깥에서 처리)
            print(f"[HTTP 오류] {symbol}: {r.status_code} {r.text[:120]}", flush=True)
        except Exception as e:
            print(f"[요청 오류] {symbol}: {e}", flush=True)
    return None  # 모든 variant 실패

def init_fetch_all_prices():
    for s in SYMBOLS:
        data=mexc_klines(s, limit=500)
        if data is None: 
            print(f"[❌ 초기 오류] {s}: 요청 실패", flush=True); continue
        if not data:
            print(f"[❌ 초기 오류] {s}: 데이터 없음", flush=True); continue
        price_cache[s]=data[-(Z_PERIOD+10):]
        print(f"✅ {s}: {len(data)}개 수집", flush=True)

def fetch_latest_price(s):
    data=mexc_klines(s, limit=1)
    if not data: 
        print(f"[✖ 최신 봉 오류] {s}: 빈 응답/요청 실패", flush=True); return
    ts, close=data[-1]
    buf=price_cache.get(s,[])
    if not buf or ts>buf[-1][0]:
        buf.append((ts,close)); price_cache[s]=buf[-(Z_PERIOD+10):]

def compute_z(s1,s2):
    d1, d2 = price_cache.get(s1), price_cache.get(s2)
    if not d1 or not d2: return None
    n=min(len(d1),len(d2))
    if n<Z_PERIOD+1: return None
    p1=np.array([x[1] for x in d1[-n:]],float)
    p2=np.array([x[1] for x in d2[-n:]],float)
    spread=np.log(p1/p1[0]) - np.log(p2/p2[0])
    hist=spread[-Z_PERIOD:]; now=spread[-1]
    std=np.std(hist, ddof=1)
    if std<1e-8: return None
    return (now - np.mean(hist)) / std

def monitor_once():
    sent=False; now=time.time(); msgs=[]
    for s in SYMBOLS:
        fetch_latest_price(s); time.sleep(0.1)
    for s1,s2 in itertools.combinations(SYMBOLS,2):
        key=f"{s1}/{s2}"
        if now - last_alert_time.get(key,0) < RENOTIFY_COOLDOWN: continue
        z=compute_z(s1,s2)
        if z is None: continue
        if abs(z)>=Z_THRESHOLD:
            icon="🔴" if abs(z)>=3.0 else "📊"
            direction="▲ 상승" if z>0 else "▼ 하락"
            ztxt=f"<b>{z:.3f}</b>" if abs(z)>=3.0 else f"{z:.3f}"
            msgs.append(f"{icon} <code>{s1} / {s2}</code>\nZ-score: {ztxt} {direction}")
            last_alert_time[key]=now; sent=True
    if msgs: send_telegram_bundled(msgs)
    return sent

def monitor_loop():
    print("📌 초기 데이터 수집 중...", flush=True); init_fetch_all_prices()
    print("✅ 감시 시작\n", flush=True); loop=0
    while True:
        print(f"🔄 Loop {loop} 시작", flush=True)
        sent=monitor_once()
        print(f"🕵️ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 감시 중... - {'🔔 알림 전송됨' if sent else '📭 알림 없음'}", flush=True)
        loop+=1; time.sleep(10)

if __name__ == "__main__": monitor_loop()
