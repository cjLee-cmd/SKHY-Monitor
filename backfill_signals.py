"""과거 데이터에 규칙 v1을 소급 적용해 신호를 생성한다.

signal_engine.py와 동일한 판정 로직을 쓴다:
  - 한국 정규장(09:00~15:30, 평일) + 신뢰 데이터에서만 판정
  - flat 상태에서 프리미엄 >= BUY_AT  -> BUY (진입)
  - holding 상태에서 프리미엄 <= SELL_AT -> SELL (청산)

사용: python3 backfill_signals.py          (미리보기)
      python3 backfill_signals.py --apply  (적용)
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
STATE = os.path.join(BASE, "docs", "data", "signal_state.json")
KST = timezone(timedelta(hours=9))

BUY_AT = 30.0
SELL_AT = 24.0


def in_kr_session(t):
    return t.weekday() < 5 and (9 * 60) <= (t.hour * 60 + t.minute) <= (15 * 60 + 30)


def main():
    apply = "--apply" in sys.argv
    hist = json.load(open(HIST, encoding="utf-8"))

    pos = "flat"
    signals = []
    considered = 0
    prev = None

    for r in hist:
        if r.get("trusted") is False:
            continue
        t = datetime.fromisoformat(r["ts"]).astimezone(KST)
        p = r["premium_pct"]

        # 밴드 교차 감지 (밖 -> 안으로 진입한 순간). 세션 무관하게 전부 기록.
        crossed = None
        if prev is not None:
            if prev < BUY_AT and p >= BUY_AT:
                crossed = "BUY"
            elif prev > SELL_AT and p <= SELL_AT:
                crossed = "SELL"
        prev = p

        if not crossed:
            continue

        kr_open = in_kr_session(t)
        if kr_open:
            considered += 1

        # 실제 매매신호 조건: 한국 정규장 + 상태기계 통과
        actionable = False
        if kr_open:
            if crossed == "BUY" and pos == "flat":
                pos, actionable = "holding", True
            elif crossed == "SELL" and pos == "holding":
                pos, actionable = "flat", True

        signals.append({
            "type": crossed,
            "time_kst": r["ts_kst"],
            "premium_pct": p,
            "kr_price": r["kr_price"],
            "adr_price": r["adr_price"],
            "actionable": actionable,
            "reason": ("" if actionable else
                       ("장외" if not kr_open else
                        ("보유중" if crossed == "BUY" else "미보유"))),
            "backfilled": True,
        })

    print("밴드 교차 {}회 (● 실제매매 {}건 / ○ 미체결 {}건)".format(len(signals), sum(1 for x in signals if x["actionable"]), sum(1 for x in signals if not x["actionable"])))
    print("밴드: 매수 >= {:.0f}% / 청산 <= {:.0f}%\n".format(BUY_AT, SELL_AT))

    entry = None
    total = 0.0
    for s in signals:
        mark = "●" if s["actionable"] else "○"
        line = "  {} {:4s} {} | {:5.2f}% | {:>10,.0f}원".format(
            mark, s["type"], s["time_kst"], s["premium_pct"], s["kr_price"])
        if not s["actionable"]:
            line += "  ({})".format(s["reason"])
        elif s["type"] == "BUY":
            entry = s
        elif entry:
            pnl = (s["kr_price"] / entry["kr_price"] - 1) * 100
            total += pnl
            line += "  → 손익 {:+.2f}%".format(pnl)
            entry = None
        print(line)

    if entry:
        print("  (미청산 포지션: {} 진입가 {:,.0f}원)".format(entry["time_kst"], entry["kr_price"]))
    print("\n완결된 매매 합산: {:+.2f}% (비용 미반영)".format(total))
    print("최종 포지션: {}".format(pos))

    if apply:
        state = {
            "position": pos,
            "bands": {"buy_at": BUY_AT, "sell_at": SELL_AT},
            "signals": signals,
        }
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        print("\n✅ signal_state.json 적용 완료")
    else:
        print("\n(미리보기. --apply 로 적용)")


if __name__ == "__main__":
    main()
