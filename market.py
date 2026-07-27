"""시장 환경 모니터 — 해외지수·변동성·원자재·반도체 Peer.

bonds.py(채권·환율)와 짝을 이뤄 주가 주변 환경을 완성한다.
"""
import json, os, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "docs", "data", "market.json")
KST  = timezone(timedelta(hours=9))
MAX  = 400
UA   = {"User-Agent": "Mozilla/5.0"}

GROUPS = {
 "해외지수": {
   "spx":  ("%5EGSPC", "S&P 500"),
   "ndx":  ("%5EIXIC", "나스닥"),
   "sox":  ("%5ESOX",  "필라델피아반도체"),
 },
 "국내지수": {
   "kospi":  ("%5EKS11", "코스피"),
   "kosdaq": ("%5EKQ11", "코스닥"),
 },
 "변동성": {
   "vix": ("%5EVIX", "VIX"),
 },
 "원자재": {
   "oil":    ("CL=F", "WTI 유가"),
   "gold":   ("GC=F", "금"),
   "copper": ("HG=F", "구리"),
 },
 "반도체Peer": {
   "mu":   ("MU",   "마이크론"),
   "tsm":  ("TSM",  "TSMC"),
   "nvda": ("NVDA", "엔비디아"),
 },
}


def fetch(sym, rng="3mo"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + sym + "?interval=1d&range=" + rng)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)['chart']['result'][0]
    except Exception:
        return None
    q = d['indicators']['quote'][0]
    h = [c for c in q['close'] if c]
    if len(h) < 5: return None
    cur = d.get('meta', {}).get('regularMarketPrice') or h[-1]
    return {"cur": cur, "d1": h[-2], "d5": h[-6] if len(h) > 5 else h[0],
            "d20": h[-21] if len(h) > 21 else h[0], "d60": h[0],
            "lo": min(h), "hi": max(h)}


def main():
    now = datetime.now(KST)
    snap = {"ts": now.isoformat(), "ts_kst": now.strftime('%m-%d %H:%M'), "groups": {}}

    for g, syms in GROUPS.items():
        snap["groups"][g] = {}
        for key, (sym, name) in syms.items():
            r = fetch(sym)
            if not r: continue
            pos = ((r['cur']-r['lo'])/(r['hi']-r['lo'])*100) if r['hi'] > r['lo'] else 50
            snap["groups"][g][key] = {
                "name": name, "cur": round(r['cur'], 2),
                "chg_1d": round((r['cur']/r['d1']-1)*100, 2),
                "chg_5d": round((r['cur']/r['d5']-1)*100, 2),
                "chg_20d": round((r['cur']/r['d20']-1)*100, 2),
                "chg_60d": round((r['cur']/r['d60']-1)*100, 2),
                "range_pos": round(pos, 0),
            }

    G = snap["groups"]
    def g(grp, k, f='cur'):
        return G.get(grp, {}).get(k, {}).get(f)

    # 파생 지표
    d = {}
    if g('반도체Peer','mu','chg_20d') is not None and g('해외지수','sox','chg_20d') is not None:
        d['mu_vs_sox_20d'] = round(g('반도체Peer','mu','chg_20d') - g('해외지수','sox','chg_20d'), 2)
    if g('국내지수','kospi','chg_20d') is not None and g('해외지수','spx','chg_20d') is not None:
        d['kospi_vs_spx_20d'] = round(g('국내지수','kospi','chg_20d') - g('해외지수','spx','chg_20d'), 2)
    if g('해외지수','sox','chg_20d') is not None and g('해외지수','ndx','chg_20d') is not None:
        d['sox_vs_ndx_20d'] = round(g('해외지수','sox','chg_20d') - g('해외지수','ndx','chg_20d'), 2)
    snap["derived"] = d

    # 경보
    al = []
    vix = G.get('변동성', {}).get('vix', {})
    if vix.get('cur', 0) >= 25:
        al.append({"level":"high","text":"VIX {} — 공포 구간. 위험자산 회피.".format(vix['cur'])})
    elif vix.get('cur', 99) <= 14:
        al.append({"level":"low","text":"VIX {} — 안심 구간. 낙관 과열 주의.".format(vix['cur'])})
    sox = G.get('해외지수', {}).get('sox', {})
    if sox.get('chg_20d', 0) <= -8:
        al.append({"level":"high","text":"필라델피아반도체 20일 {:+.1f}% — 섹터 조정.".format(sox['chg_20d'])})
    mu = G.get('반도체Peer', {}).get('mu', {})
    if mu.get('chg_20d', 0) <= -10:
        al.append({"level":"high","text":"마이크론 20일 {:+.1f}% — 메모리 사이클 경고.".format(mu['chg_20d'])})
    oil = G.get('원자재', {}).get('oil', {})
    if oil.get('chg_20d', 0) >= 15:
        al.append({"level":"mid","text":"유가 20일 {:+.1f}% — 인플레·비용 압박.".format(oil['chg_20d'])})
    if d.get('kospi_vs_spx_20d', 0) <= -5:
        al.append({"level":"mid","text":"코스피가 S&P 대비 {:+.1f}%p 열위 — 한국 디스카운트 확대.".format(d['kospi_vs_spx_20d'])})
    snap["alerts"] = al

    log = []
    try:
        with open(OUT, encoding='utf-8') as f: log = json.load(f).get("log", [])
    except (OSError, ValueError): pass
    if not log or log[-1].get("ts_kst","")[:5] != snap["ts_kst"][:5]:
        log.append({"ts_kst": snap["ts_kst"], "spx": g('해외지수','spx'),
                    "sox": g('해외지수','sox'), "vix": g('변동성','vix'),
                    "mu": g('반도체Peer','mu'), "oil": g('원자재','oil')})
    snap["log"] = log[-MAX:]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    n = sum(len(v) for v in G.values())
    print("market: {} | {}개 항목 | 경보 {}건".format(snap['ts_kst'], n, len(al)))
    for grp, items in G.items():
        print("  [{}]".format(grp))
        for k, v in items.items():
            print("    {:<16} {:>10,.2f}  1일 {:+6.2f}%  20일 {:+6.2f}%  범위 {:>3}%".format(
                v['name'], v['cur'], v['chg_1d'], v['chg_20d'], int(v['range_pos'])))
    for k, v in d.items():
        print("  [파생] {:<18} {:+.2f}%p".format(k, v))
    for a in al:
        print("  ⚠️ [{}] {}".format(a['level'], a['text']))


if __name__ == "__main__":
    main()
