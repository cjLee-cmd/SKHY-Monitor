"""과잉반응 판정 알고리즘.

4개 축을 종합해 0~100 점수를 낸다. 높을수록 '과잉반응' 가능성.
  A 통계적 극단성   Z-score (일간 변동성 대비)
  B 밸류체인 동조성  전 밸류체인이 같이 무너졌나 (개별 악재 vs 시스템 충격)
  C 펀더멘털 배율   시총 소멸 / 실제 위협 규모
  D 역사적 되돌림   동급 σ 충격 이후 통계

주의: D의 표본은 매우 작다. 점수는 확률이 아니라 '재검토 필요 신호'다.
"""
import json, math, os, statistics, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "docs", "data", "overreact.json")
KST  = timezone(timedelta(hours=9))
UA   = {"User-Agent": "Mozilla/5.0"}

# 밸류체인 (동조성 판정용)
CHAIN = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
    "MU": "마이크론", "TSM": "TSMC", "ASML": "ASML",
    "%5ESOX": "필라델피아반도체", "NVDA": "엔비디아",
}
TARGETS = ["005930.KS", "000660.KS"]

# 위협 규모 (뉴스 기반, 수동 갱신)
THREAT = {
    "source": "CXMT (중국 창신메모리)",
    "dram_rev_share": 7.7,      # % 글로벌 DRAM 매출 (2026 Q1)
    "shipment_share": 9.0,      # % 출하량
    "capa_share": 11.0,         # % 웨이퍼 생산능력
    "note": "이미 보유한 점유율. 뉴스는 '증가 추세'와 '장비 자립'",
    "updated": "2026-07-28",
}


def fetch(sym, rng="2y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + sym + "?interval=1d&range=" + rng)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)['chart']['result'][0]
    except Exception:
        return None
    q = d['indicators']['quote'][0]
    return [c for c in q['close'] if c]


def analyze(sym, name, days=2):
    h = fetch(sym)
    if not h or len(h) < 300: return None
    R = [(h[i]/h[i-1]-1)*100 for i in range(1, len(h))]
    sd = statistics.pstdev(R[-250:])
    cum = (h[-1]/h[-1-days]-1)*100
    z = cum / (sd * math.sqrt(days)) if sd else 0

    # 동급 충격 이후 되돌림 (에피소드 단위)
    ev = []
    for i in range(days, len(h)-20):
        r = (h[i]/h[i-days]-1)*100
        if sd and r/(sd*math.sqrt(days)) <= z*0.7:
            ev.append(i)
    eps, cur = [], []
    for i in ev:
        if not cur or i-cur[-1] <= 10: cur.append(i)
        else: eps.append(cur); cur = [i]
    if cur: eps.append(cur)
    fwd = {}
    for hz in (5, 20, 60):
        f = [(h[min(e[0]+hz, len(h)-1)]/h[e[0]]-1)*100 for e in eps]
        if f:
            fwd[hz] = {"mean": round(statistics.mean(f), 2),
                       "median": round(statistics.median(f), 2),
                       "up_rate": round(sum(1 for x in f if x > 0)/len(f)*100)}
    return {"name": name, "cum": round(cum, 2), "sd": round(sd, 2),
            "z": round(z, 2), "n_episodes": len(eps), "forward": fwd}


def main():
    now = datetime.now(KST)
    chain = {}
    for sym, nm in CHAIN.items():
        h = fetch(sym, "5d")
        if h and len(h) >= 3:
            chain[nm] = round((h[-1]/h[-3]-1)*100, 2)

    tg = {}
    for sym in TARGETS:
        r = analyze(sym, CHAIN[sym])
        if r: tg[CHAIN[sym]] = r
    if not tg:
        print("overreact: 데이터 부족"); return

    # ── A 통계적 극단성 (0~30) ──
    zmin = min(v['z'] for v in tg.values())
    A = min(30, max(0, (abs(zmin) - 1.5) / 2.0 * 30))

    # ── B 밸류체인 동조성 (0~25) ──
    # 전 체인이 같이 무너지면 '개별 악재'가 아닌 시스템 충격 → 과잉 가능성 ↑
    others = [v for k, v in chain.items() if k not in ('삼성전자', 'SK하이닉스')]
    neg = sum(1 for x in others if x < -2)
    B = min(25, neg / max(len(others), 1) * 25) if others else 0

    # ── C 펀더멘털 배율 (0~25) ──
    # 시총 낙폭 / 위협 점유율. 배율이 클수록 과잉
    drop = abs(statistics.mean(v['cum'] for v in tg.values()))
    ratio = drop / THREAT['dram_rev_share'] if THREAT['dram_rev_share'] else 0
    C = min(25, max(0, (ratio - 1.0) / 2.0 * 25))

    # ── D 역사적 되돌림 (0~20) ──
    ups = []
    for v in tg.values():
        f = v['forward'].get(20)
        if f: ups.append(f['up_rate'])
    D = min(20, (statistics.mean(ups)/100 * 20)) if ups else 0

    score = round(A + B + C + D, 1)
    if score >= 70:   verdict = "과잉 가능성 높음"
    elif score >= 50: verdict = "과잉 가능성 있음"
    elif score >= 30: verdict = "판단 유보"
    else:             verdict = "정당한 재평가"

    snap = {"ts_kst": now.strftime('%m-%d %H:%M'), "score": score, "verdict": verdict,
            "components": {"A_통계극단성": round(A, 1), "B_체인동조성": round(B, 1),
                           "C_펀더멘털배율": round(C, 1), "D_역사되돌림": round(D, 1)},
            "targets": tg, "chain": chain, "threat": THREAT,
            "detail": {"z_min": zmin, "drop_avg": round(drop, 2),
                       "fundamental_ratio": round(ratio, 2),
                       "chain_negative": "{}/{}".format(neg, len(others))},
            "caveat": "역사 표본 {}개로 매우 작음. 확률이 아니라 재검토 신호로 해석할 것.".format(
                max(v['n_episodes'] for v in tg.values()))}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("=" * 68)
    print("overreact: {} | 점수 {}/100 → 「{}」".format(snap['ts_kst'], score, verdict))
    print("=" * 68)
    for k, v in snap['components'].items():
        print("  {:<16} {:>5.1f}".format(k, v))
    print("\n  [대상]")
    for k, v in tg.items():
        print("    {:<10} 2일 {:+6.2f}%  Z {:+.2f}σ  (변동성 {:.2f}%)".format(
            k, v['cum'], v['z'], v['sd']))
        for hz, f in sorted(v['forward'].items()):
            print("      과거 동급 후 +{:<3}일: 평균 {:+6.2f}%  반등확률 {}%".format(
                hz, f['mean'], f['up_rate']))
    print("\n  [밸류체인 2일]")
    for k, v in sorted(chain.items(), key=lambda x: x[1]):
        print("    {:<16} {:+6.2f}%".format(k, v))
    print("\n  [펀더멘털] 낙폭 {:.1f}% / CXMT 점유 {:.1f}% = 배율 {:.2f}x".format(
        drop, THREAT['dram_rev_share'], ratio))
    print("  ⚠️ {}".format(snap['caveat']))


if __name__ == "__main__":
    main()
