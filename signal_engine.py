"""괴리율 밴드 매매 신호 엔진 + 카카오톡 알림.

규칙 v1 (2026-07-14 도출, 10일 검증 전까지 가설):
  - 매수 신호: 프리미엄 >= BUY_AT (30%)
  - 청산 신호: 보유 중 프리미엄 <= SELL_AT (24%)
  - 한국 정규장 + 신뢰 데이터(trusted)에서만 발동

상태는 docs/data/signal_state.json 에 저장되어 Actions 재실행 간 유지된다.
카카오 발송은 KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 환경변수가 있을 때만 시도.
없으면 신호만 기록하고 넘어간다(수집 파이프라인은 절대 중단하지 않음).
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

BUY_AT = 30.0    # 매수 밴드(프리미엄 상단 돌파)
SELL_AT = 24.0   # 청산 밴드(하단 복귀)
MAX_LOG = 200


def in_kr_session(t):
    return t.weekday() < 5 and (9 * 60) <= (t.hour * 60 + t.minute) <= (15 * 60 + 30)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"position": "flat", "bands": {"buy_at": BUY_AT, "sell_at": SELL_AT},
                "signals": []}


def save_state(st):
    st["bands"] = {"buy_at": BUY_AT, "sell_at": SELL_AT}
    st["signals"] = st.get("signals", [])[-MAX_LOG:]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def ntfy_send(title, text, is_buy):
    """macOS/iOS 네이티브 푸시 (ntfy.sh). 토픽명은 비밀이므로 환경변수로만 읽는다.

    실패해도 예외를 전파하지 않는다(수집 파이프라인 중단 방지).
    """
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("ntfy: NTFY_TOPIC 없음, 발송 생략")
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        req = urllib.request.Request(
            "{}/{}".format(server, topic),
            data=text.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",          # iOS 잠금화면 돌파
                "Tags": "chart_with_upwards_trend" if is_buy else "chart_with_downwards_trend",
                "Click": "https://cjlee-cmd.github.io/SKHY-Monitor/",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.load(r)
        print("ntfy 발송: 성공 (id={})".format(res.get("id")))
        return True
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
            "link": {"web_url": "https://cjlee-cmd.github.io/SKHY-Monitor/",
                      "mobile_web_url": "https://cjlee-cmd.github.io/SKHY-Monitor/"},
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


def main():
    hist = json.load(open(HIST, encoding="utf-8"))
    if not hist:
        return
    last = hist[-1]
    t = datetime.fromisoformat(last["ts"]).astimezone(KST)
    prem = last["premium_pct"]

    st = load_state()
    pos = st.get("position", "flat")

    if last.get("trusted") is False:
        print("signal: 불신뢰 데이터, 스킵")
        return

    # 직전 프리미엄로 밴드 교차 감지 (밖 -> 안으로 진입한 순간만)
    prev = None
    for r in reversed(hist[:-1]):
        if r.get("trusted") is not False:
            prev = r["premium_pct"]
            break

    crossed = None
    if prev is not None:
        if prev < BUY_AT and prem >= BUY_AT:
            crossed = "BUY"
        elif prev > SELL_AT and prem <= SELL_AT:
            crossed = "SELL"

    if not crossed:
        save_state(st)
        print("signal: 교차 없음 (프리미엄 {:.2f}% / 포지션 {})".format(prem, pos))
        return

    kr_open = in_kr_session(t)
    fired = None
    if kr_open:
        if crossed == "BUY" and pos == "flat":
            fired = "BUY"
            st["position"] = "holding"
        elif crossed == "SELL" and pos == "holding":
            fired = "SELL"
            st["position"] = "flat"

    # 교차는 언제나 기록(차트 표시용). 카카오 알림은 실제 매매신호일 때만.
    reason = "" if fired else (
        "장외" if not kr_open else
        ("보유중" if crossed == "BUY" else "미보유"))
    sig = {
        "type": crossed,
        "time_kst": last["ts_kst"],
        "premium_pct": prem,
        "kr_price": last["kr_price"],
        "adr_price": last["adr_price"],
        "actionable": bool(fired),
        "reason": reason,
    }
    st.setdefault("signals", []).append(sig)
    save_state(st)

    if not fired:
        print("signal: 교차 기록만 ({} {:.2f}% / {})".format(crossed, prem, reason))
        return

    if True:
        emoji = "\U0001F4C8" if fired == "BUY" else "\U0001F4C9"
        label = "매수 신호" if fired == "BUY" else "청산 신호"
        msg = ("{} [SKHY 괴리율] {}\n"
               "프리미엄 {:.2f}% ({})\n"
               "한국 {:,.0f}원 / ADR ${:.2f}\n"
               "규칙 v1: 매수>={:.0f}% 청산<={:.0f}%\n"
               "* 검증 중인 가설입니다. 투자 판단은 본인 책임.").format(
            emoji, label, prem, last["ts_kst"],
            last["kr_price"], last["adr_price"], BUY_AT, SELL_AT)
        kakao_send(msg)

        # macOS/iOS 네이티브 푸시
        is_buy = fired == "BUY"
        ntfy_title = "SKHY 매수 신호" if is_buy else "SKHY 청산 신호"
        ntfy_body = (
            "프리미엄 {:.2f}%  (밴드 {:.0f}% {})
"
            "한국 {:,.0f}원  /  ADR ${:.2f}
"
            "{} KST
"
            "※ 검증 중인 가설입니다. 투자 판단은 본인 책임."
        ).format(
            prem,
            BUY_AT if is_buy else SELL_AT,
            "돌파" if is_buy else "복귀",
            last["kr_price"], last["adr_price"], last["ts_kst"],
        )
        ntfy_send(ntfy_title, ntfy_body, is_buy)

        print("SIGNAL {}: 프리미엄 {:.2f}% @ {}".format(fired, prem, last["ts_kst"]))



if __name__ == "__main__":
    main()
