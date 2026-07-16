"""당일 시가 앵커 기반 매매 밴드 (v2, 2026-07-16 재설계).

v1(10거래일 풀링 분위수)의 실측 문제:
  - 프리미엄 '레벨'이 비정상: 일중앙값이 하루 만에 26.8% -> 32.8% (+6%p) 이동
  - 옛 체제 분위수가 청산선이 되어 청산 불능 (최대 +22.8% 미실현 -> +5.3% 반납)

v2 규칙:
  - 앵커 P0 = 당일 한국 정규장 첫 관측 프리미엄 (개장 갭이 반영된 재설정값)
  - 매수선 = P0 + delta / 청산선 = P0 - delta
  - delta 기본 2.0%p. 과거 5거래일 이상 쌓이면 |당일 잔차|의 80% 분위수로 자동 갱신 (하한 1.5)
  - 개장 전(당일 관측 없음)에는 직전 밴드 이월(carry), 기록조차 없으면 30/24 폴백
밴드 산출·기록만 담당. 신호 판정은 signal_engine.py.
"""
import json
import os
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
BANDS = os.path.join(BASE, "docs", "data", "bands.json")
KST = timezone(timedelta(hours=9))

LOOKBACK_DAYS = 10
DELTA_DEFAULT = 2.0
MIN_DELTA = 2.0     # 실측(7/16): |잔차| 중앙값 2.27 → δ<2는 절반이 밴드 밖(과잉신호)
ADAPT_MIN_DAYS = 2  # 실측 데이터가 δ=2.0 부적합을 보여 조기 적응 (5→2)
ADAPT_MIN_SAMPLES = 30
FALLBACK_BUY = 30.0
FALLBACK_SELL = 24.0
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


def _load_band_log():
    try:
        with open(BANDS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def compute_bands(hist, as_of=None):
    if as_of is None:
        as_of = datetime.now(KST).date()
    days = {}
    for r in hist:
        if r.get("trusted") is False:
            continue
        t = datetime.fromisoformat(r["ts"]).astimezone(KST)
        if not in_kr_session(t):
            continue
        d = t.date()
        if d > as_of or d < as_of - timedelta(days=LOOKBACK_DAYS + 7):
            continue
        days.setdefault(d, []).append((t, r["premium_pct"]))
    for d in days:
        days[d].sort()

    prior = sorted(d for d in days if d < as_of)
    delta = DELTA_DEFAULT
    adaptive = False
    if len(prior) >= ADAPT_MIN_DAYS:
        res = []
        for d in prior:
            p0d = days[d][0][1]
            res.extend(abs(p - p0d) for _, p in days[d])
        if len(res) >= ADAPT_MIN_SAMPLES:
            delta = max(MIN_DELTA, round(quantile(res, 0.80), 2))
            adaptive = True

    today = days.get(as_of)
    n = sum(len(v) for v in days.values())
    if today:
        p0 = today[0][1]
        return {"buy_at": round(p0 + delta, 2), "sell_at": round(p0 - delta, 2),
                "p0": round(p0, 2), "delta": delta, "mode": "anchor",
                "provisional": not adaptive, "n_samples": n,
                "reason": "당일 시가 앵커 {:.2f}% ± {:.2f}%p ({})".format(
                    p0, delta, "잔차 80% 분위수" if adaptive else "기본폭")}

    log = _load_band_log()
    if log:
        prev = log[-1]
        return {"buy_at": prev["buy_at"], "sell_at": prev["sell_at"],
                "p0": prev.get("p0"), "delta": prev.get("delta", delta),
                "mode": "carry", "provisional": True, "n_samples": n,
                "reason": "개장 전 — {} 밴드 이월".format(prev.get("date", "직전"))}

    return {"buy_at": FALLBACK_BUY, "sell_at": FALLBACK_SELL,
            "p0": None, "delta": delta, "mode": "fallback",
            "provisional": True, "n_samples": n,
            "reason": "기록 없음 — 임시 고정값 30/24"}


def current_bands():
    try:
        with open(HIST, encoding="utf-8") as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = []
    return compute_bands(hist)


def main():
    try:
        with open(HIST, encoding="utf-8") as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = []
    today = datetime.now(KST).date()
    b = compute_bands(hist, as_of=today)

    log = _load_band_log()
    entry = {"date": today.isoformat(), "buy_at": b["buy_at"], "sell_at": b["sell_at"],
             "p0": b.get("p0"), "delta": b.get("delta"), "mode": b["mode"],
             "provisional": b["provisional"], "n_samples": b["n_samples"],
             "reason": b["reason"]}

    if b["mode"] == "carry" and log and log[-1].get("mode") == "anchor":
        print("BANDS {} | 개장 전 이월, 기록 갱신 생략 ({})".format(today, b["reason"]))
        return

    if log and log[-1]["date"] == entry["date"]:
        log[-1] = entry
    else:
        log.append(entry)

    with open(BANDS, "w", encoding="utf-8") as f:
        json.dump(log[-MAX_LOG:], f, ensure_ascii=False, indent=1)

    tag = " [잠정]" if b["provisional"] else ""
    print("BANDS {} | 매수 >= {:.2f}% / 청산 <= {:.2f}%{} | {}".format(
        today, b["buy_at"], b["sell_at"], tag, b["reason"]))


if __name__ == "__main__":
    main()
