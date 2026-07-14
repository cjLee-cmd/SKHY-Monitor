"""매시간 괴리율 자동 분석.

history.json을 읽어 최신 상태·1시간 변화·24시간 범위를 계산하고
규칙 기반 한줄 해석을 붙여 docs/data/analysis_log.json에 시간당 1건 누적한다.
"""
import json
import os
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
LOG = os.path.join(BASE, "docs", "data", "analysis_log.json")
KST = timezone(timedelta(hours=9))
MAX_LOG = 240  # 10일치


def ts(r):
    return datetime.fromisoformat(r["ts"])


def in_kr_session(t_kst):
    return t_kst.weekday() < 5 and (9, 0) <= (t_kst.hour, t_kst.minute) <= (15, 30)


def in_us_session(t_utc):
    # 미국 정규장 13:30~20:00 UTC (서머타임)
    return t_utc.weekday() < 5 and 13 * 60 + 30 <= t_utc.hour * 60 + t_utc.minute <= 20 * 60


def main():
    with open(HIST, encoding="utf-8") as f:
        hist = json.load(f)
    if not hist:
        return

    now = ts(hist[-1])
    last = hist[-1]
    now_kst = now.astimezone(KST)

    def nearest_before(minutes):
        target = now - timedelta(minutes=minutes)
        cands = [r for r in hist if ts(r) <= target]
        return cands[-1] if cands else None

    h1 = nearest_before(60)
    day = [r for r in hist if ts(r) >= now - timedelta(hours=24)]

    prem = last["premium_pct"]
    d1h = round(prem - h1["premium_pct"], 2) if h1 else None
    lo24 = min(r["premium_pct"] for r in day)
    hi24 = max(r["premium_pct"] for r in day)

    kr_chg = round((last["kr_price"] / h1["kr_price"] - 1) * 100, 2) if h1 else None
    adr_chg = round((last["adr_price"] / h1["adr_price"] - 1) * 100, 2) if h1 else None

    # 규칙 기반 해석
    parts = []
    if d1h is None:
        parts.append("비교할 1시간 전 데이터 없음")
    elif abs(d1h) < 0.5:
        parts.append("프리미엄 안정({:+.2f}%p)".format(d1h))
    elif d1h > 0:
        parts.append("프리미엄 확대({:+.2f}%p)".format(d1h))
    else:
        parts.append("프리미엄 축소({:+.2f}%p)".format(d1h))

    if d1h is not None and abs(d1h) >= 0.5 and kr_chg is not None and adr_chg is not None:
        if abs(kr_chg) >= abs(adr_chg) * 1.5:
            parts.append("한국 본주 주도({:+.2f}%)".format(kr_chg))
        elif abs(adr_chg) >= abs(kr_chg) * 1.5:
            parts.append("미국 ADR 주도({:+.2f}%)".format(adr_chg))
        else:
            parts.append("양시장 동반 이동")

    if prem >= 28:
        parts.append("경고: 24시간 밴드 상단권(28%+)")
    elif prem <= 20:
        parts.append("주목: 20% 이하 진입")

    kr_open = in_kr_session(now_kst)
    us_open = in_us_session(now.astimezone(timezone.utc))
    sess = "한국장" if kr_open else ("미국장" if us_open else "양장 마감")
    parts.append(sess + " 시간대")

    entry = {
        "hour_key": now_kst.strftime("%Y-%m-%d %H"),
        "time_kst": now_kst.strftime("%m-%d %H:%M"),
        "kr_price": last["kr_price"],
        "adr_price": last["adr_price"],
        "usdkrw": last["usdkrw"],
        "premium_pct": prem,
        "premium_1h_delta": d1h,
        "premium_24h_range": [lo24, hi24],
        "kr_1h_pct": kr_chg,
        "adr_1h_pct": adr_chg,
        "n_samples_24h": len(day),
        "summary": " · ".join(parts),
    }

    log = []
    if os.path.exists(LOG):
        try:
            with open(LOG, encoding="utf-8") as f:
                log = json.load(f)
        except (ValueError, OSError):
            log = []

    if log and log[-1]["hour_key"] == entry["hour_key"]:
        log[-1] = entry  # 같은 시간대는 갱신
    else:
        log.append(entry)
    log = log[-MAX_LOG:]

    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)

    print("ANALYZE {} | 프리미엄 {:+.2f}% | {}".format(entry["time_kst"], prem, entry["summary"]))


if __name__ == "__main__":
    main()
