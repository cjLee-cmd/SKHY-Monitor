"""SK하이닉스 본주(000660.KS) · ADR(SKHY) · 환율(KRW=X) 수집 스크립트.

GitHub Actions가 주기적으로 실행해 docs/data/history.json 에 기록을 누적한다.
프리미엄 = ADR 가격 / (본주 × 0.1 / 환율) - 1
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


def yahoo_quote(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1d&range=1d".format(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["chart"]["result"][0]["meta"].get("regularMarketPrice")


def main():
    kr_price = yahoo_quote("000660.KS")
    adr_price = yahoo_quote("SKHY")
    usdkrw = yahoo_quote("KRW=X")

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

    print("OK {} KST | 본주 {:,.0f}원 | ADR ${:.2f} | 환율 {:.1f} | 패리티 ${:.2f} | 프리미엄 {:+.2f}%".format(
        row["ts_kst"], kr_price, adr_price, usdkrw, parity, premium_pct))


if __name__ == "__main__":
    main()
