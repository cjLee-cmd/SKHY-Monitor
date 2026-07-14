"""데이터 정리: 오염 구간에 신뢰 플래그(trusted)를 부여한다.

오염 정의: 미국 주간거래 시간대(09:00~16:30 KST)인데 ADR을 야후에서 받은 레코드.
야후는 주간거래 체결을 제공하지 않아 ADR이 멈춰 있고, 그 결과 프리미엄이
최대 8%p 과소평가되었다. 복원되지 않은 구간은 분석에서 제외한다.

사용: python3 clean_data.py --apply
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE, "docs", "data", "history.json")
KST = timezone(timedelta(hours=9))


def is_us_daytime(ts):
    t = datetime.fromisoformat(ts).astimezone(KST)
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return 9 * 60 <= hm <= 16 * 60 + 30


def main():
    apply = "--apply" in sys.argv
    hist = json.load(open(HISTORY_PATH, encoding="utf-8"))

    n_trust = n_bad = 0
    for r in hist:
        src = str(r.get("adr_source", ""))
        # KIS에서 받았으면 무조건 신뢰. 아니면 주간거래 구간일 때만 불신뢰.
        trusted = src.startswith("KIS") or not is_us_daytime(r["ts"])
        r["trusted"] = trusted
        if trusted:
            n_trust += 1
        else:
            r["untrusted_reason"] = "yahoo_no_daytime_session"
            n_bad += 1

    print("신뢰 {}건 / 불신뢰 {}건".format(n_trust, n_bad))
    if apply:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
        print("✅ 플래그 적용 완료")
    else:
        print("(미리보기. --apply 로 적용)")


if __name__ == "__main__":
    main()
