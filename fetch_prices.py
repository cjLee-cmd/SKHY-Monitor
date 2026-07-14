"""SK하이닉스 본주(000660) · ADR(SKHY) · 환율(KRW=X) 수집 스크립트 v2.

v2 변경사항:
- 미국 ADR: 프리마켓/애프터마켓 포함 마지막 체결가 사용 (야후 1분봉 includePrePost)
- 한국 본주: 네이버 실시간 API로 정규장 + 시간외(NXT) 가격 반영, 실패 시 야후 폴백
- 세션 라벨(kr_session / adr_session) 기록: regular | pre | after | closed
"""
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

RATIO = 0.1
BASE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE, "docs", "data", "history.json")
MAX_ROWS = 4320
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0"}


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def yahoo_last_trade(symbol):
    """프리/애프터 포함 마지막 체결가와 세션 라벨을 반환."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/{}"
           "?interval=1m&range=1d&includePrePost=true").format(symbol)
    res = http_json(url)["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")

    stamps = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    for t, c in zip(reversed(stamps), reversed(closes)):
        if c is not None:
            price, ts = float(c), int(t)
            break

    session = "closed"
    try:
        reg = meta["currentTradingPeriod"]["regular"]
        if ts is not None:
            if reg["start"] <= ts <= reg["end"]:
                session = "regular"
            elif ts < reg["start"]:
                session = "pre"
            else:
                session = "after"
    except (KeyError, TypeError):
        pass
    return price, session


def naver_kr():
    """네이버 실시간: 정규장 가격 + 시간외(NXT) 가격. (price, session) 반환."""
    url = "https://polling.finance.naver.com/api/realtime/domestic/stock/000660"
    j = http_json(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com"})
    d = j["datas"][0]

    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None

    regular = num(d.get("closePrice"))
    market_status = (d.get("marketStatus") or "").upper()
    over = d.get("overMarketPriceInfo") or {}
    over_price = num(over.get("overPrice"))
    over_status = (over.get("overMarketStatus") or "").upper()

    now_kst = datetime.now(KST)
    hm = now_kst.hour * 60 + now_kst.minute
    is_weekday = now_kst.weekday() < 5

    if market_status == "OPEN":
        return regular, "regular"
    if over_status == "OPEN" and over_price:
        return over_price, ("pre" if hm < 9 * 60 else "after")
    if is_weekday and over_price and (hm < 9 * 60 or hm > 15 * 60 + 40):
        return over_price, ("pre" if hm < 9 * 60 else "after")
    return regular, "closed" if market_status else "regular"


def main():
    # 한국: 네이버 우선, 실패 시 야후 폴백
    try:
        kr_price, kr_session = naver_kr()
        if not kr_price:
            raise ValueError("naver empty")
    except Exception as e:
        print("naver fallback -> yahoo:", e)
        kr_price, kr_session = yahoo_last_trade("000660.KS")

    adr_price, adr_session = yahoo_last_trade("SKHY")
    usdkrw, _ = yahoo_last_trade("KRW=X")

    if not (kr_price and adr_price and usdkrw):
        raise RuntimeError("invalid quotes: kr={} adr={} fx={}".format(kr_price, adr_price, usdkrw))

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

    print("OK {} KST | 본주 {:,.0f}원[{}] | ADR ${:.2f}[{}] | 환율 {:.1f} | 프리미엄 {:+.2f}%".format(
        row["ts_kst"], kr_price, kr_session, adr_price, adr_session, usdkrw, premium_pct))


if __name__ == "__main__":
    main()
