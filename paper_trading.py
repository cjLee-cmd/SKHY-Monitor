"""Claude 증권 — 가상 페이퍼 트레이딩 엔진.

목적: 수익이 아니라 '가설 검증'. 검증된 엣지가 없는 상태에서 시작하므로
      모든 전략은 벤치마크(단순보유)를 이겨야만 의미가 있다.

계좌 구성 (총 100만원, 2026-07-27 09:00 KST 개시)
  BM  40만원 : 본주 단순보유 (벤치마크)
  S1  20만원 : 프리미엄 밴드 (매수 >= buy_at / 청산 <= sell_at)
  S2  20만원 : 익일 장중 되돌림 (전일 장중 하락 -> 당일 시가매수·종가매도)
  RSV 20만원 : 예비 현금 (미사용)

원칙
  - 매매 1회당 0.15% 비용(수수료+세금+슬리피지) 무조건 차감
  - 재량 개입 금지. 규칙에 정의된 조건만으로 체결
  - 밴드값이 바뀌면 band_changes에 기록 (구간 분리 분석용)
  - 20거래일 전까지 규칙 수정 금지
"""
import json
import os
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
ACCT = os.path.join(BASE, "docs", "data", "accounts.json")
BANDS = os.path.join(BASE, "docs", "data", "bands.json")
KST = timezone(timedelta(hours=9))

START_DATE = "2026-07-27"      # 월요일 개시
COST = 0.0015                  # 왕복이 아닌 1회당 0.15%
INIT = {"BM": 400000, "S1": 200000, "S2": 200000, "RSV": 200000}

STOP_TOTAL = -0.20             # 전체 -20% 시 중단
STOP_STRAT = -0.30             # 개별 전략 -30% 시 중단


def kst_now():
    return datetime.now(KST)


def in_kr_session(t):
    hm = t.hour * 60 + t.minute
    return t.weekday() < 5 and (9 * 60) <= hm <= (15 * 60 + 30)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def new_account():
    return {
        "started": False,
        "start_date": START_DATE,
        "cost_per_trade": COST,
        "accounts": {
            k: {"cash": v, "shares": 0.0, "init": v, "stopped": False}
            for k, v in INIT.items()
        },
        "trades": [],
        "daily": [],
        "band_changes": [],
        "notes": [],
    }


def equity(acc, price):
    return acc["cash"] + acc["shares"] * price


def buy(state, key, price, reason, ts):
    acc = state["accounts"][key]
    if acc["stopped"] or acc["cash"] <= 0:
        return False
    amt = acc["cash"]
    fee = amt * COST
    shares = (amt - fee) / price
    acc["shares"] += shares
    acc["cash"] = 0.0
    state["trades"].append({
        "ts": ts, "acct": key, "side": "BUY", "price": price,
        "shares": round(shares, 6), "fee": round(fee), "reason": reason,
    })
    return True


def sell(state, key, price, reason, ts):
    acc = state["accounts"][key]
    if acc["shares"] <= 0:
        return False
    amt = acc["shares"] * price
    fee = amt * COST
    acc["cash"] += amt - fee
    sold = acc["shares"]
    acc["shares"] = 0.0
    state["trades"].append({
        "ts": ts, "acct": key, "side": "SELL", "price": price,
        "shares": round(sold, 6), "fee": round(fee), "reason": reason,
    })
    return True


def prev_day_direction(hist, today):
    """전 거래일 장중(시가->종가) 방향. S2 신호용."""
    from collections import OrderedDict
    days = OrderedDict()
    for r in hist:
        if r.get("trusted") is False:
            continue
        t = datetime.fromisoformat(r["ts"]).astimezone(KST)
        if not in_kr_session(t):
            continue
        days.setdefault(t.strftime("%Y-%m-%d"), []).append((t, r["kr_price"]))

    keys = [k for k in days if k < today and len(days[k]) >= 4]
    if not keys:
        return None, None
    prev = keys[-1]
    rows = sorted(days[prev])
    o, c = rows[0][1], rows[-1][1]
    return prev, (c / o - 1) * 100


def main():
    hist = load_json(HIST, [])
    if not hist:
        print("paper: 시세 데이터 없음")
        return
    last = hist[-1]
    price = last["kr_price"]
    prem = last["premium_pct"]
    now = kst_now()
    today = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%d %H:%M")

    state = load_json(ACCT, None) or new_account()

    # 개시 전이면 대기
    if today < START_DATE:
        print("paper: 개시 대기 ({} 시작)".format(START_DATE))
        state["accounts"] = state["accounts"]  # 유지
        save(state)
        return

    # 밴드 로드 + 변경 기록
    blog = load_json(BANDS, [])
    b = blog[-1] if blog else {"buy_at": 30.0, "sell_at": 24.0, "provisional": True}
    prev_band = state.get("current_band")
    cur_band = {"buy_at": b["buy_at"], "sell_at": b["sell_at"],
                "provisional": b.get("provisional", True)}
    if prev_band != cur_band:
        state["band_changes"].append({"ts": ts, **cur_band})
        state["current_band"] = cur_band

    if not state["started"]:
        state["started"] = True
        state["notes"].append({"ts": ts, "msg": "거래 개시. 초기자본 100만원"})

    kr_open = in_kr_session(now)
    hm = now.hour * 60 + now.minute

    # 휴장 감지: 당일 한국장 샘플의 가격이 전혀 안 움직이면 휴장으로 간주.
    # (수집기가 멈춘 가격을 그대로 기록하므로 7/17 제헌절 같은 날 헛매매가 발생)
    if kr_open:
        today_px = [r["kr_price"] for r in hist
                    if datetime.fromisoformat(r["ts"]).astimezone(KST).strftime("%Y-%m-%d") == today
                    and in_kr_session(datetime.fromisoformat(r["ts"]).astimezone(KST))]
        # 당일 가격이 최소 2개 이상 서로 달라야 '실제 거래 중'으로 인정.
        # 휴장일에는 수집기가 멈춘 가격만 기록하므로 값이 1종류뿐이다.
        if len(set(today_px)) < 2:
            kr_open = False
            print("paper: 거래 미확인(가격 무변동), 매매 스킵")

    # ---------- BM: 개시일 첫 틱에 전량 매수 후 보유 ----------
    if kr_open and state["accounts"]["BM"]["shares"] == 0 and state["accounts"]["BM"]["cash"] > 0:
        buy(state, "BM", price, "벤치마크 최초 매수", ts)

    # ---------- S1: 프리미엄 밴드 ----------
    if kr_open:
        s1 = state["accounts"]["S1"]
        if s1["shares"] == 0 and prem >= cur_band["buy_at"]:
            buy(state, "S1", price, "프리미엄 {:.2f}% >= 매수밴드 {:.1f}%".format(
                prem, cur_band["buy_at"]), ts)
        elif s1["shares"] > 0 and prem <= cur_band["sell_at"]:
            sell(state, "S1", price, "프리미엄 {:.2f}% <= 청산밴드 {:.1f}%".format(
                prem, cur_band["sell_at"]), ts)

    # ---------- S2: 익일 장중 되돌림 ----------
    if kr_open:
        s2 = state["accounts"]["S2"]
        pd_key, pd_ret = prev_day_direction(hist, today)
        if s2["shares"] == 0 and hm <= 9 * 60 + 30 and pd_ret is not None and pd_ret < 0:
            if state.get("s2_last_entry") != today:
                if buy(state, "S2", price, "전일({}) 장중 {:.2f}% 하락".format(pd_key, pd_ret), ts):
                    state["s2_last_entry"] = today
        elif s2["shares"] > 0:
            # 원칙: 오버나이트 보유 금지.
            # 마감 직전 샘플이 없어 청산을 놓친 경우 다음 틱에 즉시 청산한다.
            if state.get("s2_last_entry") != today:
                sell(state, "S2", price, "오버나이트 방지 강제청산", ts)
            elif hm >= 15 * 60 + 10:
                sell(state, "S2", price, "당일 종가 청산", ts)

    # ---------- 중단 기준 체크 ----------
    for k, acc in state["accounts"].items():
        if k == "RSV" or acc["stopped"]:
            continue
        ret = equity(acc, price) / acc["init"] - 1
        if ret <= STOP_STRAT:
            acc["stopped"] = True
            if acc["shares"] > 0:
                sell(state, k, price, "손실한도 도달 강제청산", ts)
            state["notes"].append({"ts": ts, "msg": "{} 중단 ({:.1%})".format(k, ret)})

    total = sum(equity(a, price) for a in state["accounts"].values())
    total_init = sum(INIT.values())
    if total / total_init - 1 <= STOP_TOTAL:
        state["notes"].append({"ts": ts, "msg": "전체 손실한도 도달. 전면 재검토 필요"})

    # ---------- 일별 스냅샷 (하루 1건, 갱신) ----------
    snap = {
        "date": today, "ts": ts, "price": price, "premium": prem,
        "total": round(total),
        **{k: round(equity(a, price)) for k, a in state["accounts"].items()},
    }
    if state["daily"] and state["daily"][-1]["date"] == today:
        state["daily"][-1] = snap
    else:
        state["daily"].append(snap)
    state["daily"] = state["daily"][-400:]
    state["trades"] = state["trades"][-500:]

    save(state)

    print("paper {} | 주가 {:,.0f} | 프리미엄 {:.2f}%".format(ts, price, prem))
    print("  총자산 {:,}원 ({:+.2f}%)".format(round(total), (total/total_init-1)*100))
    for k, a in state["accounts"].items():
        e = equity(a, price)
        pos = "보유" if a["shares"] > 0 else "현금"
        print("  {:<4} {:>9,}원 ({:+6.2f}%) {}".format(
            k, round(e), (e/a["init"]-1)*100, pos))


def save(state):
    os.makedirs(os.path.dirname(ACCT), exist_ok=True)
    with open(ACCT, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
