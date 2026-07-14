"""오염된 주간거래 구간을 KIS 분봉으로 복원하는 일회성 스크립트.

야후는 주간거래(09:00~16:30 KST) 체결을 제공하지 않아, 그 구간 데이터의 ADR이
멈춰 있다. KIS 해외주식 분봉 API(EXCD=BAQ)로 실제 체결가를 받아 덮어쓴다.

사용: python3 backfill.py          (미리보기만)
      python3 backfill.py --apply  (실제 적용)
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_prices import (load_dotenv, kis_token, http_json, KIS_BASE,
                          HISTORY_PATH, RATIO, KST)


def kis_minute_chart(token, app_key, app_secret, symbol, excd, nmin="5"):
    """해외주식 분봉 조회. 최근 체결부터 역순으로 반환된다."""
    url = (KIS_BASE + "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
           "?AUTH=&EXCD={}&SYMB={}&NMIN={}&PINC=1&NEXT=&NREC=120&FILL=&KEYB="
           .format(excd, symbol, nmin))
    res = http_json(url, headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "HHDFS76950200",
    })
    return res


def main():
    apply = "--apply" in sys.argv
    load_dotenv()
    app_key = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    if not (app_key and app_secret):
        print("KIS 키 없음(.env 필요). 중단.")
        return

    token = kis_token(app_key, app_secret)
    res = kis_minute_chart(token, app_key, app_secret, "SKHY", "BAQ", nmin="5")

    print("rt_cd:", res.get("rt_cd"), "|", res.get("msg1"))
    rows = res.get("output2") or []
    print("분봉 건수:", len(rows))
    if not rows:
        print("응답 샘플:", json.dumps(res, ensure_ascii=False)[:400])
        return

    print("샘플 레코드:", json.dumps(rows[0], ensure_ascii=False))

    # 분봉 → {UTC epoch: 종가}
    chart = {}
    for r in rows:
        d = r.get("xymd") or r.get("kymd")
        t = r.get("xhms") or r.get("khms")
        last = r.get("last") or r.get("clos")
        if not (d and t and last):
            continue
        try:
            # 현지(미국 ET) 시각으로 옴. UTC-4(EDT) 가정
            dt = datetime.strptime(d + t.zfill(6), "%Y%m%d%H%M%S")
            dt = dt.replace(tzinfo=timezone(timedelta(hours=-4)))
            chart[int(dt.timestamp())] = float(last)
        except (ValueError, TypeError):
            continue

    if not chart:
        print("분봉 파싱 실패")
        return

    ks = sorted(chart)
    print("분봉 범위(KST): {} ~ {}".format(
        datetime.fromtimestamp(ks[0], KST).strftime("%m-%d %H:%M"),
        datetime.fromtimestamp(ks[-1], KST).strftime("%m-%d %H:%M")))
    print("가격 범위: ${:.2f} ~ ${:.2f}".format(min(chart.values()), max(chart.values())))

    # history 보정
    hist = json.load(open(HISTORY_PATH, encoding="utf-8"))

    def us_daytime(t):
        if t.weekday() >= 5:
            return False
        hm = t.hour * 60 + t.minute
        return 9 * 60 <= hm <= 16 * 60 + 30

    fixed = 0
    for r in hist:
        if str(r.get("adr_source", "")).startswith("KIS"):
            continue
        ts = datetime.fromisoformat(r["ts"])
        t_kst = ts.astimezone(KST)
        if not us_daytime(t_kst):
            continue
        target = int(ts.timestamp())
        near = min(chart, key=lambda k: abs(k - target))
        if abs(near - target) > 400:   # 5분봉 기준, 오차 400초 초과면 포기
            continue
        new_adr = chart[near]
        old_adr = r["adr_price"]
        parity = r["kr_price"] * RATIO / r["usdkrw"]
        new_prem = (new_adr / parity - 1) * 100
        if fixed < 6:
            print("  {} | ADR ${:.2f} -> ${:.2f} | 프리미엄 {:+.2f}% -> {:+.2f}%".format(
                r["ts_kst"], old_adr, new_adr, r["premium_pct"], new_prem))
        r["adr_price"] = round(new_adr, 4)
        r["premium_pct"] = round(new_prem, 2)
        r["adr_session"] = "daytime"
        r["adr_source"] = "KIS/BAQ(backfill)"
        fixed += 1

    print("\n복원 대상: {}건".format(fixed))
    if apply and fixed:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
        print("✅ 적용 완료")
    elif fixed:
        print("(미리보기 모드. 적용하려면 --apply)")


if __name__ == "__main__":
    main()
