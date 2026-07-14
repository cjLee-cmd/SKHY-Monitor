"""SK하이닉스 본주(000660) · ADR(SKHY) · 환율 수집 스크립트 v3.

v3 핵심: 미국 ADR의 '주간거래(Overnight / Blue Ocean ATS)' 세션을 반영한다.
  - 야후는 주간거래(한국 09:00~16:30) 체결을 제공하지 않아 그 시간 내내 값이 멈춘다.
  - 한국투자증권(KIS) Open API는 주간거래 거래소(EXCD=BAQ)를 지원한다.

보안:
  - API 키를 코드에 절대 넣지 않는다. 환경변수 KIS_APP_KEY / KIS_APP_SECRET 로만 읽는다.
  - GitHub Actions에서는 repository secret 으로 주입한다.
  - 로컬 테스트는 .env 파일(.gitignore 처리됨)에서 읽는다.
  - KIS 키가 없으면 야후로 자동 폴백한다(주간거래 구간은 stale로 명시).
"""
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

RATIO = 0.1
BASE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE, "docs", "data", "history.json")
MAX_ROWS = 4320
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0"}

KIS_BASE = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE = "/tmp/kis_token.json"


def http_json(url, headers=None, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or UA, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def load_dotenv():
    """로컬 테스트용. .env가 있으면 환경변수로 올린다. 값은 절대 출력하지 않는다."""
    path = os.path.join(BASE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def kis_token(app_key, app_secret):
    """접근토큰. 24시간 유효하므로 /tmp에 캐시해 재발급 제한을 피한다."""
    if os.path.exists(TOKEN_CACHE):
        try:
            with open(TOKEN_CACHE) as f:
                c = json.load(f)
            if c.get("expires_at", 0) > time.time() + 600:
                return c["token"]
        except (ValueError, OSError):
            pass

    res = http_json(
        KIS_BASE + "/oauth2/tokenP",
        headers={"content-type": "application/json"},
        data={"grant_type": "client_credentials",
              "appkey": app_key, "appsecret": app_secret},
        method="POST",
    )
    token = res["access_token"]
    ttl = int(res.get("expires_in", 86400))
    try:
        with open(TOKEN_CACHE, "w") as f:
            json.dump({"token": token, "expires_at": time.time() + ttl}, f)
    except OSError:
        pass
    return token


def kis_overseas_price(token, app_key, app_secret, symbol, excd):
    """해외주식 현재체결가. excd: NAS(나스닥 정규) / BAQ(나스닥 주간거래)."""
    url = (KIS_BASE + "/uapi/overseas-price/v1/quotations/price"
           "?AUTH=&EXCD={}&SYMB={}".format(excd, symbol))
    res = http_json(url, headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "HHDFS00000300",
    })
    out = res.get("output") or {}
    try:
        last = float(out.get("last") or 0)
    except ValueError:
        last = 0.0
    return last if last > 0 else None


def us_session_kst(now):
    """서머타임 기준 미국 세션 (KST)."""
    if now.weekday() >= 5:
        return "closed"
    hm = now.hour * 60 + now.minute
    if 9 * 60 <= hm <= 16 * 60 + 30:
        return "daytime"
    if 17 * 60 <= hm < 22 * 60 + 30:
        return "pre"
    if hm >= 22 * 60 + 30 or hm < 5 * 60:
        return "regular"
    if 5 * 60 <= hm < 9 * 60:
        return "after"
    return "closed"


def get_adr_kis():
    """KIS로 ADR 시세. 실패하면 None을 반환해 야후 폴백을 유도한다."""
    app_key = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    if not (app_key and app_secret):
        return None

    now = datetime.now(KST)
    session = us_session_kst(now)
    order = ["BAQ", "NAS"] if session == "daytime" else ["NAS", "BAQ"]

    token = kis_token(app_key, app_secret)
    for excd in order:
        try:
            price = kis_overseas_price(token, app_key, app_secret, "SKHY", excd)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
            print("KIS {} 실패: {}".format(excd, e))
            continue
        if price:
            label = "daytime" if excd == "BAQ" else session
            return price, label, "KIS/" + excd
    return None


def yahoo_last_trade(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/{}"
           "?interval=1m&range=1d&includePrePost=true".format(symbol))
    res = http_json(url)["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    stamps = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    for t, c in zip(reversed(stamps), reversed(closes)):
        if c is not None:
            price = float(c)
            break
    return price


def naver_kr():
    url = "https://polling.finance.naver.com/api/realtime/domestic/stock/000660"
    j = http_json(url, {"User-Agent": "Mozilla/5.0",
                        "Referer": "https://finance.naver.com"})
    d = j["datas"][0]

    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None

    regular = num(d.get("closePrice"))
    status = (d.get("marketStatus") or "").upper()
    over = d.get("overMarketPriceInfo") or {}
    over_price = num(over.get("overPrice"))
    over_status = (over.get("overMarketStatus") or "").upper()

    now = datetime.now(KST)
    hm = now.hour * 60 + now.minute

    if status == "OPEN":
        return regular, "regular"
    if over_status == "OPEN" and over_price:
        return over_price, ("pre" if hm < 9 * 60 else "after")
    if now.weekday() < 5 and over_price and (hm < 9 * 60 or hm > 15 * 60 + 40):
        return over_price, ("pre" if hm < 9 * 60 else "after")
    return regular, "closed"


def main():
    load_dotenv()

    try:
        kr_price, kr_session = naver_kr()
        if not kr_price:
            raise ValueError("naver empty")
    except Exception as e:
        print("naver 폴백 -> yahoo:", e)
        kr_price, kr_session = yahoo_last_trade("000660.KS"), "unknown"

    adr_src = "Yahoo"
    kis = None
    try:
        kis = get_adr_kis()
    except Exception as e:
        print("KIS 조회 실패:", e)

    if kis:
        adr_price, adr_session, adr_src = kis
    else:
        adr_price = yahoo_last_trade("SKHY")
        s = us_session_kst(datetime.now(KST))
        adr_session = "stale_daytime" if s == "daytime" else s

    usdkrw = yahoo_last_trade("KRW=X")

    if not (kr_price and adr_price and usdkrw):
        raise RuntimeError("invalid quotes: kr={} adr={} fx={}".format(
            kr_price, adr_price, usdkrw))

    parity = kr_price * RATIO / usdkrw
    premium_pct = (adr_price / parity - 1) * 100

    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ts_kst": datetime.now(KST).strftime("%m-%d %H:%M"),
        "kr_price": kr_price,
        "adr_price": round(adr_price, 4),
        "usdkrw": round(usdkrw, 2),
        "parity_usd": round(parity, 2),
        "premium_pct": round(premium_pct, 2),
        "kr_session": kr_session,
        "adr_session": adr_session,
        "adr_source": adr_src,
    }

    history = []
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                history = json.load(f)
        except (ValueError, OSError):
            history = []
    history.append(row)
    history = history[-MAX_ROWS:]

    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print("OK {} | 본주 {:,.0f}[{}] | ADR ${:.2f}[{}] via {} | FX {:.1f} | 프리미엄 {:+.2f}%".format(
        row["ts_kst"], kr_price, kr_session, adr_price, adr_session, adr_src,
        usdkrw, premium_pct))


if __name__ == "__main__":
    main()
