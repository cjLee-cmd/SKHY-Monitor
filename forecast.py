"""내일(다음 거래일) 개장 예측 + 자동 채점 (설계서 P0/P1, M0 단계).

원리 (실측 2026-07-14~16):
  - 미국장이 밤새 만든 괴리(x1 = 미마감 프리미엄 - 당일 P0)는 한국 개장 갭이 흡수
  - 내일 P0(개장 프리미엄)는 오늘 P0 레벨을 대체로 이월 (33.51 -> 32.73 실측)

정직성 규칙:
  - 표본 게이트: T1 표본 n<10 이면 status=learning, UI는 '학습 중' 표시
  - 예측은 신호 엔진에 입력되지 않는다 (정보 전용)
  - REGIME_BREAKS(bands.py 공유) 이후 옛 표본 자동 폐기
10분 루프마다 실행: 예측은 계속 갱신(잠정A -> 미마감 반영B), 채점은 개장 후 1회.
"""
import json
import os
from datetime import datetime, timezone, timedelta, date

from bands import REGIME_BREAKS

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
BANDS = os.path.join(BASE, "docs", "data", "bands.json")
FC = os.path.join(BASE, "docs", "data", "forecast.json")
FCLOG = os.path.join(BASE, "docs", "data", "forecast_log.json")
KST = timezone(timedelta(hours=9))
GATE_N = 10          # T1 표본 게이트
ALPHA = 0.5          # M0: 갭 = x1의 50% 흡수 가정 (표본 부족으로 보수적)
GAP_BAND = 4.0       # 갭 80% 구간 반폭 (%p) — 실측 개장갭 |9.57|,|8.74| 감안
P0_BAND = 3.0        # P0 구간 반폭 (%p)
MAX_LOG = 240


def kst(r):
    return datetime.fromisoformat(r["ts"]).astimezone(KST)


def in_kr(t):
    return t.weekday() < 5 and 9 * 60 <= t.hour * 60 + t.minute <= 15 * 60 + 30


def next_trading_day(d):
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def regime_cut(as_of):
    cut = None
    for br in REGIME_BREAKS:
        b = date.fromisoformat(br)
        if as_of >= b:
            cut = b
    return cut


def day_rows(hist):
    days = {}
    for r in hist:
        t = kst(r)
        if in_kr(t):
            days.setdefault(t.date(), []).append(r)
    return days


def train_samples(days, today):
    """과거 (전일 P0, 당일 P0, 개장갭) 표본 수 — 게이트 판정용."""
    cut = regime_cut(today)
    ds = sorted(d for d in days if d < today and (cut is None or d >= cut))
    return max(0, len(ds) - 1)


def score_prev(log, days, hist):
    """미채점 예측 중 실현값이 도착한 것을 채점."""
    changed = False
    for e in log:
        if e.get("realized_p0") is not None:
            continue
        d = date.fromisoformat(e["date"])
        rows = days.get(d)
        if not rows:
            continue
        p0 = rows[0]["premium_pct"]
        open_kr = rows[0]["kr_price"]
        prev = [r for r in hist if kst(r).date() < d and in_kr(kst(r))]
        gap = None
        if prev:
            gap = round((open_kr / prev[-1]["kr_price"] - 1) * 100, 2)
        e["realized_p0"] = p0
        e["realized_gap"] = gap
        if e.get("p0_p50") is not None:
            e["p0_abs_err"] = round(abs(p0 - e["p0_p50"]), 2)
        if gap is not None and e.get("gap_p50") is not None:
            e["gap_abs_err"] = round(abs(gap - e["gap_p50"]), 2)
            e["gap_abs_err_rw"] = round(abs(gap), 2)  # 기준선(갭=0) 오차
        changed = True
        print("FORECAST 채점 {}: P0 실현 {:.2f} (오차 {}) / 갭 실현 {} (오차 {})".format(
            e["date"], p0, e.get("p0_abs_err"), gap, e.get("gap_abs_err")))
    return changed


def main():
    hist = load(HIST, [])
    if not hist:
        return
    days = day_rows(hist)
    last = hist[-1]
    now = kst(last)
    today = now.date()

    # 오늘 P0 (한국장 관측이 있으면 그 첫 값, 없으면 밴드 로그의 p0)
    p0_today = None
    if today in days:
        p0_today = days[today][0]["premium_pct"]
    else:
        blog = load(BANDS, [])
        if blog and blog[-1].get("p0") is not None:
            p0_today = blog[-1]["p0"]
    if p0_today is None:
        print("forecast: 앵커 없음, 생략")
        return

    target = next_trading_day(today)
    prem = last["premium_pct"]
    x1 = round(prem - p0_today, 2)          # 지금까지 벌어진 당일 잔차 (미마감 전 잠정)
    us_done = now.hour >= 5 and now.hour < 9  # 미국 정규장 마감 직후 구간(05~09시)이면 확정 단계
    stage = "B-미마감반영" if us_done else "A-잠정"

    n = train_samples(days, target)
    p0_p50 = round(p0_today + 0.3 * x1, 2)   # 레벨 이월 + 당일 잔차 30% 반영
    gap_p50 = round(ALPHA * x1, 2)

    fc = {
        "date": target.isoformat(),
        "made_at": last["ts_kst"],
        "model": "M0-baseline",
        "stage": stage,
        "n_train": n,
        "gate_n": GATE_N,
        "status": "learning" if n < GATE_N else "active",
        "inputs": {"p0_today": p0_today, "premium_now": prem, "x1": x1},
        "p0_fc": {"p10": round(p0_p50 - P0_BAND, 2), "p50": p0_p50, "p90": round(p0_p50 + P0_BAND, 2)},
        "gap_fc": {"p10": round(gap_p50 - GAP_BAND, 2), "p50": gap_p50, "p90": round(gap_p50 + GAP_BAND, 2)},
        "note": "표본 {}/{} — 기준선(M0) 참고용. 신호와 무관.".format(n, GATE_N),
    }
    with open(FC, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=1)

    # 로그: 날짜당 1건 유지(마지막 갱신본), 채점은 실현 후 고정
    log = load(FCLOG, [])
    entry = {"date": fc["date"], "made_at": fc["made_at"], "model": fc["model"],
             "stage": stage, "n_train": n,
             "p0_p50": p0_p50, "gap_p50": gap_p50,
             "realized_p0": None, "realized_gap": None}
    if log and log[-1]["date"] == entry["date"] and log[-1].get("realized_p0") is None:
        log[-1] = entry
    elif not log or log[-1]["date"] != entry["date"]:
        log.append(entry)

    score_prev(log, days, hist)
    with open(FCLOG, "w", encoding="utf-8") as f:
        json.dump(log[-MAX_LOG:], f, ensure_ascii=False, indent=1)

    print("FORECAST {} [{}] P0 {:.2f} ({:.2f}~{:.2f}) / 갭 {:+.2f}%p ({:+.2f}~{:+.2f}) n={}".format(
        fc["date"], stage, p0_p50, fc["p0_fc"]["p10"], fc["p0_fc"]["p90"],
        gap_p50, fc["gap_fc"]["p10"], fc["gap_fc"]["p90"], n))


if __name__ == "__main__":
    main()
