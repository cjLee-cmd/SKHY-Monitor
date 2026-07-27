"""채권·금리 모니터 — 한국 및 주요국.

수집:
  미국   ^TNX(10Y) ^TYX(30Y) ^FVX(5Y)      → 할인율 채널
  한국   국고채 ETF 2종                      → 국내 금리 방향 프록시
  일본   엔화 + 닛케이                        → 캐리 트레이드
  파생   수익률곡선(30-10, 10-5), 한미 스프레드 프록시
"""
import json, os, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "docs", "data", "bonds.json")
KST  = timezone(timedelta(hours=9))
MAX  = 400

SYMS = {
    "us10y":  ("%5ETNX",     "미 10년물",      "%"),
    "us30y":  ("%5ETYX",     "미 30년물",      "%"),
    "us5y":   ("%5EFVX",     "미 5년물",       "%"),
    "kr10y_etf": ("148070.KS", "KOSEF 국고채10년", "원"),
    "kr3y_etf":  ("114820.KS", "TIGER 국채3년",   "원"),
    "usdjpy": ("JPY=X",      "달러/엔",        "¥"),
    "usdkrw": ("KRW=X",      "달러/원",        "₩"),
}
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(sym, rng="1mo"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + sym + "?interval=1d&range=" + rng)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)['chart']['result'][0]
    except Exception:
        return None
    q = d['indicators']['quote'][0]
    pts = [(t, c) for t, c in zip(d['timestamp'], q['close']) if c]
    if not pts: return None
    m = d.get('meta', {})
    cur = m.get('regularMarketPrice') or pts[-1][1]
    hist = [c for _, c in pts]
    return {"cur": cur, "d1": hist[-2] if len(hist) > 1 else cur,
            "d5": hist[-6] if len(hist) > 5 else hist[0],
            "d20": hist[0],
            "lo": min(hist), "hi": max(hist), "n": len(hist)}


def main():
    now = datetime.now(KST)
    snap = {"ts": now.isoformat(), "ts_kst": now.strftime('%m-%d %H:%M'), "items": {}}

    for key, (sym, name, unit) in SYMS.items():
        r = fetch(sym)
        if not r: continue
        pos = ((r['cur'] - r['lo']) / (r['hi'] - r['lo']) * 100) if r['hi'] > r['lo'] else 50
        snap["items"][key] = {
            "name": name, "unit": unit, "cur": round(r['cur'], 3),
            "chg_1d": round(r['cur'] - r['d1'], 3),
            "chg_5d_pct": round((r['cur']/r['d5'] - 1) * 100, 2),
            "chg_20d_pct": round((r['cur']/r['d20'] - 1) * 100, 2),
            "range_pos": round(pos, 0), "lo": round(r['lo'], 3), "hi": round(r['hi'], 3),
        }

    it = snap["items"]
    def g(k): return it.get(k, {}).get('cur')

    # 파생 지표
    d = {}
    if g('us30y') and g('us10y'): d['curve_30_10'] = round(g('us30y') - g('us10y'), 3)
    if g('us10y') and g('us5y'):  d['curve_10_5']  = round(g('us10y') - g('us5y'), 3)
    if g('usdkrw') and g('usdjpy'):
        d['krw_per_100jpy'] = round(g('usdkrw') / g('usdjpy') * 100, 1)
    snap["derived"] = d

    # 경보 판정
    al = []
    u10 = it.get('us10y', {})
    if u10.get('range_pos', 0) >= 85:
        al.append({"level": "high", "text": "미 10년물 {}% — 1개월 범위 상단 {}%. 할인율 압박.".format(
            u10.get('cur'), u10.get('range_pos'))})
    if d.get('curve_30_10', 0) >= 0.4:
        al.append({"level": "mid", "text": "30-10 스프레드 {:+.2f}%p — 장기 인플레·재정 우려.".format(d['curve_30_10'])})
    jp = it.get('usdjpy', {})
    if jp.get('range_pos', 0) >= 90:
        al.append({"level": "mid", "text": "엔 {} — 범위 상단 {}%. 캐리 청산 위험 축적.".format(
            jp.get('cur'), jp.get('range_pos'))})
    kw = it.get('usdkrw', {})
    if kw.get('range_pos', 100) <= 25:
        al.append({"level": "low", "text": "원화 강세 {} — 외국인 유입 여건 개선.".format(kw.get('cur'))})
    snap["alerts"] = al

    log = []
    try:
        with open(OUT, encoding='utf-8') as f: log = json.load(f).get("log", [])
    except (OSError, ValueError): pass
    if not log or log[-1].get("ts_kst", "")[:5] != snap["ts_kst"][:5]:
        log.append({"ts_kst": snap["ts_kst"], "us10y": g('us10y'),
                    "curve_30_10": d.get('curve_30_10'), "usdjpy": g('usdjpy'),
                    "usdkrw": g('usdkrw')})
    snap["log"] = log[-MAX:]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("bonds: {} | 항목 {}개 | 경보 {}건".format(snap['ts_kst'], len(it), len(al)))
    for k, v in it.items():
        print("  {:<16} {:>10} {}  1일 {:+.3f}  20일 {:+.2f}%  범위 {}%".format(
            v['name'], v['cur'], v['unit'], v['chg_1d'], v['chg_20d_pct'], int(v['range_pos'])))
    for k, v in d.items():
        print("  [파생] {:<14} {}".format(k, v))
    for a in al:
        print("  ⚠️ [{}] {}".format(a['level'], a['text']))


if __name__ == "__main__":
    main()
