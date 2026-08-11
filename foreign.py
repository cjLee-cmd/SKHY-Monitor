"""외국인 성분 분해 — 실측 기반.

■ 검증된 분해 (387일)
  외국인 ↔ 공매도 상관 -0.491 (t=-10.93) → 회귀로 숏 연동분 분리, R² 24.1%
  숏 연동분  : +5일 예측 상관 +0.129 (t=+2.50) ★유의
  잔차(방향성): +5일 예측 상관 +0.096 (t=+1.84) 유의 미달

■ 외국계 창구 (KIS inquire-member)
  매도·매수 상위 5개 회원사 중 외국계 비중을 집계.
  상위 5개만 제공되므로 하한 추정치다.

■ 폐기한 것
  F-PASSIVE — MSCI EM AUM 이론 계산값만 있고 관측 불가.
  static 고정 문구 + 고정 입장(+0.3)으로 협의체를 왜곡했다.
  패시브 분리에는 MSCI 리밸런싱 일정·편입비중 변화가 필요하나 미확보.
"""
import json, math, os, statistics, time, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "docs", "data")
OUT  = os.path.join(DATA, "foreign_decomp.json")
TOK  = os.path.join(BASE, ".kistoken")
KIS  = "https://openapi.koreainvestment.com:9443"
KST  = timezone(timedelta(hours=9))

STOCKS = {"samsung": ("005930", "삼성전자"), "hynix": ("000660", "SK하이닉스")}
# 외국계 회원사 (KIS 표기 기준)
FOREIGN_HOUSES = ["모간", "메릴", "골드만", "씨티", "제이피", "노무라", "다이와",
                  "UBS", "CS", "맥쿼리", "홍콩", "비엔피", "도이치", "바클레이",
                  "미즈호", "SG", "CLSA", "JP", "HSBC"]


def _env():
    p = os.path.join(BASE, ".env")
    if not os.path.exists(p): return
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError: pass


def token():
    _env()
    try:
        with open(TOK, encoding="utf-8") as f: t = json.load(f)
        if time.time() - t["at"] < 70000: return t["tok"]
    except (OSError, ValueError, KeyError): pass
    ak, sk = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not (ak and sk): return None
    req = urllib.request.Request(KIS + "/oauth2/tokenP",
        data=json.dumps({"grant_type": "client_credentials",
                         "appkey": ak, "appsecret": sk}).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        tk = json.load(r)["access_token"]
    try:
        with open(TOK, "w", encoding="utf-8") as f:
            json.dump({"tok": tk, "at": time.time()}, f)
    except OSError: pass
    return tk


def num(x):
    try: return float(str(x).replace(",", ""))
    except (TypeError, ValueError): return 0.0


def members(tk, code):
    """회원사별 매매 — 외국계 창구 비중 산출."""
    h = {"content-type": "application/json", "authorization": "Bearer " + tk,
         "appkey": os.environ.get("KIS_APP_KEY", ""),
         "appsecret": os.environ.get("KIS_APP_SECRET", ""), "tr_id": "FHKST01010600"}
    q = "FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=" + code
    try:
        req = urllib.request.Request(
            KIS + "/uapi/domestic-stock/v1/quotations/inquire-member?" + q, headers=h)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except Exception:
        return None
    o = d.get("output")
    if isinstance(o, list): o = o[0] if o else {}
    if not o: return None
    def side(pfx):
        tot = fr = 0.0; hit = []
        for i in range(1, 6):
            nm = str(o.get("{}_mbcr_name{}".format(pfx, i), "")).strip()
            qt = num(o.get("total_{}_qty{}".format(pfx, i)))
            if not nm: continue
            tot += qt
            if any(h2 in nm for h2 in FOREIGN_HOUSES):
                fr += qt; hit.append({"name": nm, "qty": qt})
        return {"total": tot, "foreign": fr,
                "foreign_pct": round(fr / tot * 100, 1) if tot else 0, "houses": hit}
    s, b = side("seln"), side("shnu")
    return {"sell": s, "buy": b,
            "net_foreign_qty": b["foreign"] - s["foreign"],
            "foreign_share_pct": round((b["foreign"] + s["foreign"]) /
                                       (b["total"] + s["total"]) * 100, 1)
                                 if (b["total"] + s["total"]) else 0}


def decompose(stock):
    """공매도 회귀로 외국인을 숏연동분 / 잔차로 분해."""
    try:
        with open(os.path.join(DATA, "krx_investors.json"), encoding="utf-8") as f:
            inv = json.load(f)
        with open(os.path.join(DATA, "krx_extra.json"), encoding="utf-8") as f:
            ext = json.load(f)
    except (OSError, ValueError):
        return None
    SR = {r["date"]: r for r in ext.get("shortsale", {}).get(stock, [])}
    rows = [r for r in inv.get(stock, []) if r["date"] in SR]
    if len(rows) < 60: return None
    F = [r["외국인"] / 1e11 for r in rows]
    S = [SR[r["date"]]["공매도거래대금"] / 1e11 for r in rows]
    ms, mf = statistics.mean(S), statistics.mean(F)
    vs = statistics.pvariance(S)
    if not vs: return None
    beta = sum((S[i] - ms) * (F[i] - mf) for i in range(len(S))) / len(S) / vs
    alpha = mf - beta * ms
    link = [alpha + beta * s for s in S]
    resid = [F[i] - link[i] for i in range(len(F))]
    c = sum((S[i]-ms)*(F[i]-mf) for i in range(len(S)))/len(S) / (
        statistics.pstdev(S)*statistics.pstdev(F) or 1)
    return {"n": len(rows), "beta": round(beta, 3), "alpha": round(alpha, 3),
            "r2_pct": round(c*c*100, 1),
            "recent5": {"total": round(sum(F[-5:]), 2),
                        "short_linked": round(sum(link[-5:]), 2),
                        "residual": round(sum(resid[-5:]), 2)},
            "last_date": rows[-1]["date"]}


def main():
    tk = token()
    now = datetime.now(KST)
    snap = {"ts_kst": now.strftime("%m-%d %H:%M"), "stocks": {},
            "note": "공매도 회귀 분해 + 외국계 창구 비중. 패시브/액티브 분리는 데이터 부재로 미제공."}
    for key, (code, name) in STOCKS.items():
        e = {"name": name, "decomp": decompose(key)}
        if tk:
            m = members(tk, code)
            if m: e["brokers"] = m
        snap["stocks"][key] = e
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("foreign: {}".format(snap["ts_kst"]))
    for k, v in snap["stocks"].items():
        print("\n  [{}]".format(v["name"]))
        d = v.get("decomp")
        if d:
            r = d["recent5"]
            print("    분해: 외국인 = {:+.2f} + {:.3f}×공매도 (R² {:.1f}%, n={})".format(
                d["alpha"], d["beta"], d["r2_pct"], d["n"]))
            print("    최근5일 총 {:+.2f} = 숏연동 {:+.2f} + 잔차(방향성) {:+.2f}  [~{}]".format(
                r["total"], r["short_linked"], r["residual"], d["last_date"]))
        b = v.get("brokers")
        if b:
            print("    외국계 창구: 매수 {:.1f}% / 매도 {:.1f}% · 순 {:+,.0f}주".format(
                b["buy"]["foreign_pct"], b["sell"]["foreign_pct"], b["net_foreign_qty"]))
            for h in b["buy"]["houses"]: print("      매수 {} {:,.0f}주".format(h["name"], h["qty"]))
            for h in b["sell"]["houses"]: print("      매도 {} {:,.0f}주".format(h["name"], h["qty"]))


if __name__ == "__main__":
    main()
