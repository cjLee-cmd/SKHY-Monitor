"""롤링 분위수 기반 매매 밴드 자동 산출."""
import json
import os
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
BANDS = os.path.join(BASE, "docs", "data", "bands.json")
KST = timezone(timedelta(hours=9))

LOOKBACK_DAYS = 10
QUANTILE = 0.20
MIN_SAMPLES = 60
FALLBACK_BUY = 30.0
FALLBACK_SELL = 24.0
MIN_WIDTH = 3.0
MAX_LOG = 120


def in_kr_session(t):
    return t.weekday() < 5 and (9 * 60) <= (t.hour * 60 + t.minute) <= (15 * 60 + 30)


def quantile(vals, q):
    s = sorted(vals)
    if not s:
        return None
    i = q * (len(s) - 1)
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def compute_bands(hist, as_of=None):
    if as_of is None:
        as_of = datetime.now(KST).date()
    cutoff = as_of - timedelta(days=LOOKBACK_DAYS + 5)
    prems = []
    for r in hist:
        if r.get("trusted") is False:
            continue
        t = datetime.fromisoformat(r["ts"]).astimezone(KST)
        if t.date() >= as_of or t.date() < cutoff:
            continue
        if not in_kr_session(t):
            continue
        prems.append(r["premium_pct"])

    if len(prems) < MIN_SAMPLES:
        return {"buy_at": FALLBACK_BUY, "sell_at": FALLBACK_SELL,
                "provisional": True, "n_samples": len(prems),
                "reason": "표본 {}건 < 최소 {}건. 임시 고정값".format(len(prems), MIN_SAMPLES)}

    buy = quantile(prems, 1 - QUANTILE)
    sell = quantile(prems, QUANTILE)
    if buy - sell < MIN_WIDTH:
        mid = (buy + sell) / 2
        buy, sell = mid + MIN_WIDTH / 2, mid - MIN_WIDTH / 2

    return {"buy_at": round(buy, 2), "sell_at": round(sell, 2),
            "provisional": False, "n_samples": len(prems),
            "reason": "최근 {}거래일 한국장 상하위 {:.0f}% 분위수".format(LOOKBACK_DAYS, QUANTILE * 100)}


def current_bands():
    try:
        with open(HIST, encoding="utf-8") as f:
            hist = json.load(f)
    except (OSError, ValueError):
        return {"buy_at": FALLBACK_BUY, "sell_at": FALLBACK_SELL,
                "provisional": True, "n_samples": 0, "reason": "no data"}
    return compute_bands(hist)


def main():
    with open(HIST, encoding="utf-8") as f:
        hist = json.load(f)
    today = datetime.now(KST).date()
    b = compute_bands(hist, as_of=today)

    try:
        with open(BANDS, encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        log = []

    entry = {"date": today.isoformat(), "buy_at": b["buy_at"], "sell_at": b["sell_at"],
             "provisional": b["provisional"], "n_samples": b["n_samples"], "reason": b["reason"]}

    if log and log[-1]["date"] == entry["date"]:
        log[-1] = entry
    else:
        log.append(entry)

    with open(BANDS, "w", encoding="utf-8") as f:
        json.dump(log[-MAX_LOG:], f, ensure_ascii=False, indent=1)

    tag = " [임시]" if b["provisional"] else ""
    print("BANDS {} | 매수 {:.2f}% / 청산 {:.2f}%{} | 표본 {}건".format(
        today, b["buy_at"], b["sell_at"], tag, b["n_samples"]))
    print("  " + b["reason"])


if __name__ == "__main__":
    main()
