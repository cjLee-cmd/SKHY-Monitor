"""괴리율 밴드 매매 신호 엔진 v2 + ntfy/카카오 알림.

규칙 v2 (2026-07-16 재설계, 검증 전까지 가설):
  - 밴드: bands.py의 당일 시가 앵커 방식 (P0 ± delta)
  - 매수 신호: 플랫 상태에서 프리미엄 >= 매수선
  - 청산 신호: 보유 중 (프리미엄 <= 청산선) 또는 (고점 대비 -3% 트레일링 스탑)
  - 한국 정규장 + 신뢰 데이터(trusted)에서만 발동
  - 포지션-신호이력 불일치 시 이력 기준 자동 보정 (7/15 중복매수 버그 재발 방지)

상태는 docs/data/signal_state.json 에 저장 (entry_price/peak_price 포함).
알림: NTFY_TOPIC(ntfy.sh) 및 KAKAO_* 환경변수가 있을 때만 시도.
실패해도 수집 파이프라인은 절대 중단하지 않는다.
"""
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "docs", "data", "history.json")
STATE = os.path.join(BASE, "docs", "data", "signal_state.json")
KST = timezone(timedelta(hours=9))
DASH_URL = "https://cjlee-cmd.github.io/SKHY-Monitor/"

from bands import current_bands
_B = current_bands()
BUY_AT = _B["buy_at"]
SELL_AT = _B["sell_at"]
BAND_REASON = _B["reason"]
STOP_PCT = 3.0
MAX_LOG = 200


def in_kr_session(t):
    return t.weekday() < 5 and (9 * 60) <= (t.hour * 60 + t.minute) <= (15 * 60 + 30)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"position": "flat", "signals": []}


def reconcile(st):
    """신호 이력과 포지션이 어긋나면 이력을 기준으로 보정한다."""
    sigs = [s for s in st.get("signals", []) if s.get("actionable", True)]
    if sigs:
        expect = "holding" if sigs[-1]["type"] == "BUY" else "flat"
        if st.get("position") != expect:
            print("경고: 포지션({}) != 신호이력({}) — 이력 기준으로 보정".format(
                st.get("position"), expect))
            st["position"] = expect
            if expect == "flat":
                st.pop("entry_price", None)
                st.pop("peak_price", None)
    return st


def save_state(st):
    st["bands"] = {"buy_at": BUY_AT, "sell_at": SELL_AT,
                   "p0": _B.get("p0"), "delta": _B.get("delta"),
                   "mode": _B.get("mode"), "reason": BAND_REASON}
    st["signals"] = st.get("signals", [])[-MAX_LOG:]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def ntfy_send(title, body, high=False):
    """ntfy.sh 푸시. 실패해도 예외를 전파하지 않는다."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("ntfy: 토픽 없음, 발송 생략")
        return False
    try:
        payload = json.dumps({
            "topic": topic,
            "title": title,
            "message": body,
            "priority": 5 if high else 3,
            "tags": ["chart_with_upwards_trend"],
            "click": DASH_URL,
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://ntfy.sh/", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = 200 <= r.status < 300
        print("ntfy 발송:", "성공" if ok else r.status)
        return ok
    except Exception as e:
        print("ntfy 발송 실패(무시하고 계속):", e)
        return False


def kakao_send(text):
    """카카오 '나에게 보내기'. 실패해도 예외를 전파하지 않는다."""
    rest_key = os.environ.get("KAKAO_REST_KEY")
    refresh = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not (rest_key and refresh):
        print("kakao: 토큰 없음, 발송 생략")
        return False
    try:
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": rest_key,
            "refresh_token": refresh,
        }).encode()
        req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            access = json.load(r)["access_token"]

        template = json.dumps({
            "object_type": "text",
            "text": text[:190],
            "link": {"web_url": DASH_URL, "mobile_web_url": DASH_URL},
            "button_title": "대시보드",
        }, ensure_ascii=False)
        body2 = urllib.parse.urlencode({"template_object": template}).encode()
        req2 = urllib.request.Request(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data=body2,
            headers={"Authorization": "Bearer " + access},
        )
        with urllib.request.urlopen(req2, timeout=15) as r:
            res = json.load(r)
        ok = res.get("result_code") == 0
        print("kakao 발송:", "성공" if ok else res)
        return ok
    except Exception as e:
        print("kakao 발송 실패(무시하고 계속):", e)
        return False


def notify(title, body, high=False):
    ntfy_send(title, body, high)
    kakao_send(title + "\n" + body)


def main():
    hist = json.load(open(HIST, encoding="utf-8"))
    if not hist:
        return
    last = hist[-1]
    t = datetime.fromisoformat(last["ts"]).astimezone(KST)
    prem = last["premium_pct"]
    kr = last["kr_price"]

    st = reconcile(load_state())
    pos = st.get("position", "flat")

    if not in_kr_session(t) or last.get("trusted") is False:
        save_state(st)
        print("signal: 장외/불신뢰 구간, 판정 스킵 (현재 {:.2f}% / 포지션 {})".format(prem, pos))
        return

    fired = None
    why = ""
    pnl = None

    if pos == "flat":
        if prem >= BUY_AT:
            fired = "BUY"
            why = "매수선 돌파 ({})".format(BAND_REASON)
            st["position"] = "holding"
            st["entry_price"] = kr
            st["peak_price"] = kr
    else:
        if not st.get("entry_price"):
            buys = [s for s in st.get("signals", [])
                    if s.get("actionable", True) and s["type"] == "BUY"]
            st["entry_price"] = buys[-1]["kr_price"] if buys else kr
            st["peak_price"] = kr
            print("보정: entry_price {:,.0f} / peak_price 현재가부터".format(st["entry_price"]))
        peak = max(st.get("peak_price") or kr, kr)
        st["peak_price"] = peak
        stop_line = peak * (1 - STOP_PCT / 100.0)
        if prem <= SELL_AT:
            fired = "SELL"
            why = "청산선 복귀 ({})".format(BAND_REASON)
        elif kr <= stop_line:
            fired = "SELL"
            why = "트레일링 스탑: 고점 {:,.0f} 대비 -{:.0f}%".format(peak, STOP_PCT)
        if fired:
            pnl = (kr / st["entry_price"] - 1) * 100 if st.get("entry_price") else None
            st["position"] = "flat"
            st.pop("entry_price", None)
            st.pop("peak_price", None)

    if fired:
        sig = {"type": fired, "time_kst": last["ts_kst"], "premium_pct": prem,
               "kr_price": kr, "adr_price": last["adr_price"], "why": why}
        if pnl is not None:
            sig["pnl_pct"] = round(pnl, 2)
        st.setdefault("signals", []).append(sig)
        save_state(st)
        label = "매수 신호" if fired == "BUY" else "청산 신호"
        pnl_line = "손익 {:+.2f}% (수수료 미반영)\n".format(pnl) if pnl is not None else ""
        body = ("{}\n프리미엄 {:.2f}% ({})\n한국 {:,.0f}원 / ADR ${:.2f}\n{}"
                "규칙 v2: 매수>={:.2f}% 청산<={:.2f}% 스탑 -{:.0f}%\n"
                "* 검증 중인 가설입니다. 투자 판단은 본인 책임.").format(
            why, prem, last["ts_kst"], kr, last["adr_price"], pnl_line,
            BUY_AT, SELL_AT, STOP_PCT)
        notify("[SKHY] " + label, body, high=True)
        print("SIGNAL {}: {} / 프리미엄 {:.2f}% @ {}".format(fired, why, prem, last["ts_kst"]))
    else:
        save_state(st)
        extra = ""
        if st.get("position") == "holding" and st.get("peak_price"):
            extra = " / 스탑 {:,.0f}".format(st["peak_price"] * (1 - STOP_PCT / 100.0))
        print("signal: 유지 (프리미엄 {:.2f}% / 포지션 {} / 밴드 {:.2f}~{:.2f}{})".format(
            prem, st["position"], SELL_AT, BUY_AT, extra))


if __name__ == "__main__":
    main()
