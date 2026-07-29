"""P-ADR 감시 + 레버리지 ETF 실데이터 수집.

P-ADR 트리거 3종:
  T1 급변    프리미엄 일변화 |Δ| >= 8%p
  T2 방향괴리 한국↑ & ADR↓ (또는 반대) — 한쪽만 재평가된 상태
  T3 야간이탈 한국 마감 후 ADR 변화 >= 5% — 익일 갭 예고 (최우선)
"""
import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "docs", "data")
HIST = os.path.join(DATA, "history.json")
OUT  = os.path.join(DATA, "adr_watch.json")
KST  = timezone(timedelta(hours=9))

T1_THR = 8.0    # %p
T2_THR = 1.5    # % (양방향 최소 움직임)
T3_THR = 5.0    # % (야간 ADR 변화)

LEV_KEYS = ('삼성전자', '하이닉스')


def load(p, d=None):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return d


def _load_env():
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


def krx_etf(bas_dd):
    _load_env()
    key = os.environ.get("KRX_AUTH_KEY")
    if not key: return []
    url = "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd?basDd=" + bas_dd
    try:
        req = urllib.request.Request(url, headers={"AUTH_KEY": key})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode('utf-8', 'replace')
        raw = re.sub(r'[\x00-\x1f]', ' ', raw)
        d = json.loads(raw)
    except Exception as e:
        print("adr_watch: KRX ETF 실패", e); return []
    rows = next((d[k] for k in d if isinstance(d[k], list)), [])
    out = []
    for r in rows:
        nm = str(r.get('ISU_NM', ''))
        if '레버리지' not in nm and '인버스' not in nm: continue
        if not any(k in nm for k in LEV_KEYS): continue
        def n(k):
            try: return float(str(r.get(k, 0)).replace(',', ''))
            except: return 0.0
        out.append({"code": r.get('ISU_CD'), "name": nm[:30],
                    "close": n('TDD_CLSPRC'), "nav": n('NAV'),
                    "chg": n('FLUC_RT'), "mktcap": n('MKTCAP'),
                    "shares": n('LIST_SHRS'), "vol": n('ACC_TRDVAL'),
                    "inverse": '인버스' in nm})
    return out


def main():
    now = datetime.now(KST)
    hist = [r for r in (load(HIST, []) or []) if r.get('trusted') is not False]
    if not hist: print("adr_watch: 데이터 없음"); return

    from collections import OrderedDict
    days = OrderedDict()
    for r in hist: days.setdefault(r['ts_kst'][:5], []).append(r)
    ks = list(days.keys())
    cur = days[ks[-1]]
    last = cur[-1]

    alerts = []
    # T1 급변
    if len(ks) >= 2:
        p0 = days[ks[-2]][-1]['premium_pct']
        dp = last['premium_pct'] - p0
        if abs(dp) >= T1_THR:
            alerts.append({"trigger": "T1", "level": "high",
                "text": "프리미엄 {:+.2f}%p 급변 ({:.2f}% → {:.2f}%). 한쪽 시장만 재평가된 상태.".format(
                    dp, p0, last['premium_pct'])})
        # T2 방향 괴리
        k0 = days[ks[-2]][-1]['kr_price']; a0 = days[ks[-2]][-1]['adr_price']
        kr = (last['kr_price']/k0 - 1) * 100
        ar = (last['adr_price']/a0 - 1) * 100
        if abs(kr) >= T2_THR and abs(ar) >= T2_THR and kr * ar < 0:
            alerts.append({"trigger": "T2", "level": "high",
                "text": "방향 괴리: 한국 {:+.2f}% vs ADR {:+.2f}%. 뒤따라갈 쪽은 {}.".format(
                    kr, ar, "한국" if abs(ar) > abs(kr) else "미국")})

    # T3 야간 이탈 (한국 마감 15:30 이후 ADR 변화)
    close_tick = None
    for r in cur:
        hm = r['ts_kst'][6:]
        if hm <= "15:30": close_tick = r
    if close_tick and close_tick is not last:
        an = (last['adr_price']/close_tick['adr_price'] - 1) * 100
        if abs(an) >= T3_THR:
            alerts.append({"trigger": "T3", "level": "critical",
                "text": "한국 마감 후 ADR {:+.2f}% (${:.2f} → ${:.2f}). 익일 개장 갭 예고.".format(
                    an, close_tick['adr_price'], last['adr_price'])})

    # 레버리지 ETF
    etf = []
    for back in range(0, 5):
        d = (now - timedelta(days=back)).strftime("%Y%m%d")
        etf = krx_etf(d)
        if etf: break

    ss = [e for e in etf if '삼성전자' in e['name'] and not e['inverse']]
    hy = [e for e in etf if '하이닉스' in e['name'] and not e['inverse']]
    def agg(lst):
        return {"n": len(lst),
                "mktcap_jo": round(sum(e['mktcap'] for e in lst)/1e12, 2),
                "vol_jo": round(sum(e['vol'] for e in lst)/1e12, 2),
                "chg_avg": round(sum(e['chg'] for e in lst)/len(lst), 2) if lst else 0}
    lev_sum = {"samsung": agg(ss), "hynix": agg(hy),
               "inverse_n": len([e for e in etf if e['inverse']])}

    if lev_sum['hynix']['chg_avg'] <= -8:
        alerts.append({"level": "high", "trigger": "LEV",
            "text": "하이닉스 레버ETF 평균 {:+.1f}%. 반대매매·환매 압력.".format(lev_sum['hynix']['chg_avg'])})

    snap = {"ts_kst": now.strftime('%m-%d %H:%M'),
            "premium": last['premium_pct'], "kr": last['kr_price'], "adr": last['adr_price'],
            "alerts": alerts, "leverage": lev_sum, "etf_detail": etf[:16],
            "thresholds": {"T1": T1_THR, "T2": T2_THR, "T3": T3_THR}}

    log = (load(OUT, {}) or {}).get("log", [])
    if not log or log[-1].get("ts_kst", "")[:5] != snap["ts_kst"][:5]:
        log.append({"ts_kst": snap["ts_kst"], "premium": snap["premium"],
                    "n_alerts": len(alerts)})
    snap["log"] = log[-200:]

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("adr_watch: {} | 프리미엄 {:.2f}% | 경보 {}건 | 레버ETF {}종".format(
        snap['ts_kst'], snap['premium'], len(alerts), len(etf)))
    for a in alerts:
        print("  🚨 [{}] {}".format(a['trigger'], a['text']))
    print("  레버ETF 삼성 {}종 시총 {}조 (평균 {:+.1f}%) / 하이닉스 {}종 {}조 ({:+.1f}%)".format(
        lev_sum['samsung']['n'], lev_sum['samsung']['mktcap_jo'], lev_sum['samsung']['chg_avg'],
        lev_sum['hynix']['n'], lev_sum['hynix']['mktcap_jo'], lev_sum['hynix']['chg_avg']))


if __name__ == "__main__":
    main()
