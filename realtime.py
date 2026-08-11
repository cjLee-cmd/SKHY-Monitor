"""실시간 투자자 수급 — KIS investor-trend-estimate.

■ 핵심 발견 (2026-08-11)
  HTS의 별표(*) 수치 = 외국인/기관 '추정' 순매수량. 장중 실시간 제공.
  마감 후에야 집계되는 inquire-investor / foreign-institution-total 과 다르다.

■ 정확한 호출법 — 이 조합만 작동한다
  path   /uapi/domestic-stock/v1/quotations/investor-trend-estimate
  tr_id  HHPTJ04160200          ← FHPTJ04160200(X), FHKST644400C0(X)
  param  MKSC_SHRN_ISCD=005930  ← FID_INPUT_ISCD(X), FID_COND_MRKT_DIV_CODE 단독(X)

■ 응답 필드
  bsop_hour_gb        시간대 구분 (1, 2 …)
  frgn_fake_ntby_qty  외국인 추정 순매수 수량
  orgn_fake_ntby_qty  기관 추정 순매수 수량
  sum_fake_ntby_qty   합계 → 개인 = -합계 (역산)

■ 주의
  · 토큰 발급은 1분 1회 제한 → .kistoken 캐시 필수 (403 방지)
  · '추정치'라 마감 확정치와 오차가 있다
  · 개인은 직접 제공 안 됨. 수급 항등식으로 역산

■ 실패했던 다른 경로 (재시도 금지)
  · inquire-investor         → 장중 전부 0
  · foreign-institution-total → 상위 30 랭킹, 종목 누락 발생
  · 네이버/KRX 웹            → CORS·로그인 차단
"""
import json, os, time, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "docs", "data", "realtime_flow.json")
TOK  = os.path.join(BASE, ".kistoken")
KIS  = "https://openapi.koreainvestment.com:9443"
KST  = timezone(timedelta(hours=9))
STOCKS = {"samsung": ("005930", "삼성전자"), "hynix": ("000660", "SK하이닉스")}
MAXLOG = 600


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
    except OSError:
        pass


def token():
    """토큰 캐시 — 1분 1회 제한 때문에 반드시 재사용."""
    _env()
    try:
        with open(TOK, encoding="utf-8") as f:
            t = json.load(f)
        if time.time() - t["at"] < 70000:
            return t["tok"]
    except (OSError, ValueError, KeyError):
        pass
    ak, sk = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not (ak and sk): return None
    req = urllib.request.Request(
        KIS + "/oauth2/tokenP",
        data=json.dumps({"grant_type": "client_credentials",
                         "appkey": ak, "appsecret": sk}).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        tk = json.load(r)["access_token"]
    try:
        with open(TOK, "w", encoding="utf-8") as f:
            json.dump({"tok": tk, "at": time.time()}, f)
    except OSError:
        pass
    return tk


def call(tk, path, tr, params):
    q = "&".join("{}={}".format(k, v) for k, v in params.items())
    h = {"content-type": "application/json", "authorization": "Bearer " + tk,
         "appkey": os.environ.get("KIS_APP_KEY", ""),
         "appsecret": os.environ.get("KIS_APP_SECRET", ""), "tr_id": tr}
    try:
        req = urllib.request.Request(KIS + path + "?" + q, headers=h)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception:
        return {}


def num(x):
    try: return float(str(x).replace(",", ""))
    except (TypeError, ValueError): return 0.0


def main():
    tk = token()
    if not tk:
        print("realtime: 토큰 실패"); return
    now = datetime.now(KST)
    snap = {"ts_kst": now.strftime("%m-%d %H:%M"), "stocks": {},
            "method": "KIS investor-trend-estimate / HHPTJ04160200 / MKSC_SHRN_ISCD"}

    for key, (code, name) in STOCKS.items():
        p = call(tk, "/uapi/domestic-stock/v1/quotations/inquire-price",
                 "FHKST01010100",
                 {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}).get("output", {})
        px = num(p.get("stck_prpr"))
        d = call(tk, "/uapi/domestic-stock/v1/quotations/investor-trend-estimate",
                 "HHPTJ04160200", {"MKSC_SHRN_ISCD": code})
        rows = d.get("output2") or d.get("output") or d.get("output1") or []
        if isinstance(rows, dict): rows = [rows]
        if not rows: continue
        r = rows[0]
        f = num(r.get("frgn_fake_ntby_qty")); o = num(r.get("orgn_fake_ntby_qty"))
        s = num(r.get("sum_fake_ntby_qty"))
        snap["stocks"][key] = {
            "name": name, "price": px, "chg_pct": num(p.get("prdy_ctrt")),
            "slot": r.get("bsop_hour_gb"),
            "foreign_qty": f, "foreign_eok": round(f * px / 1e8, 1),
            "inst_qty": o, "inst_eok": round(o * px / 1e8, 1),
            "retail_qty": -s, "retail_eok": round(-s * px / 1e8, 1),
            "slots": [{"slot": x.get("bsop_hour_gb"),
                       "frgn": num(x.get("frgn_fake_ntby_qty")),
                       "orgn": num(x.get("orgn_fake_ntby_qty"))} for x in rows]}

    # 트리거 판정 — 379일 구조가 뒤집혔는가
    tg = []
    for k, v in snap["stocks"].items():
        if v["foreign_qty"] > 0 and v["retail_qty"] < 0:
            tg.append({"stock": v["name"], "level": "high",
                       "text": "역할 전환 — 외국인 매수 {:+,.0f}억 / 개인 매도 {:+,.0f}억".format(
                           v["foreign_eok"], v["retail_eok"])})
    snap["triggers"] = tg

    log = []
    try:
        with open(OUT, encoding="utf-8") as f:
            log = json.load(f).get("log", [])
    except (OSError, ValueError):
        pass
    log.append({"ts": snap["ts_kst"],
                **{k: v["foreign_eok"] for k, v in snap["stocks"].items()}})
    snap["log"] = log[-MAXLOG:]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("realtime: {} | {}종목".format(snap["ts_kst"], len(snap["stocks"])))
    for k, v in snap["stocks"].items():
        print("  [{}] {:,.0f} ({:+.2f}%)".format(v["name"], v["price"], v["chg_pct"]))
        print("     외국인 {:>+10,.0f}주 {:>+8,.0f}억 | 기관 {:>+9,.0f}주 | 개인 {:>+10,.0f}주 {:>+8,.0f}억".format(
            v["foreign_qty"], v["foreign_eok"], v["inst_qty"], v["retail_qty"], v["retail_eok"]))
    for t in tg:
        print("  🚨 [{}] {}".format(t["stock"], t["text"]))


if __name__ == "__main__":
    main()
