"""에이전트 협의체 v2 — agents/ 컨텍스트를 읽어 실행한다.

컨텍스트만 수정하면 발언이 바뀐다 (알고리즘 수정 불필요).
"""
import json, os, statistics
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
AG   = os.path.join(BASE, "agents")
DATA = os.path.join(BASE, "docs", "data")
KST  = timezone(timedelta(hours=9))
OUT  = os.path.join(DATA, "council.json")


def load(p, d=None):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return d


def load_agents():
    out = {}
    for sub in ('market', 'meta'):
        d = os.path.join(AG, sub)
        if not os.path.isdir(d): continue
        for f in sorted(os.listdir(d)):
            if f.endswith('.json'):
                a = load(os.path.join(d, f))
                if a: out[a['id']] = a
    return out


def recent(inv, stock, key, n=5):
    rows = inv.get(stock, [])[-n:]
    return sum(r.get(key, 0) for r in rows) / 1e12 if rows else 0.0


def main():
    A    = load_agents()
    inv  = load(os.path.join(DATA, "krx_investors.json"), {})
    ext  = load(os.path.join(DATA, "krx_extra.json"), {})
    hist = load(os.path.join(DATA, "history.json"), [])
    now  = datetime.now(KST)

    bas   = ext.get('basis_kospi200', [])
    mb    = bas[-1].get('시장베이시스') if bas else None
    tb    = bas[-1].get('이론베이시스') if bas else None
    prem  = [r['premium_pct'] for r in hist if r.get('trusted') is not False]
    cur_p = prem[-1] if prem else None
    stale = inv.get('samsung', [{}])[-1].get('date', '?')

    log = {"at": now.strftime('%Y-%m-%d %H:%M'), "rounds": [], "data_asof": stale}

    # ── R1: 자기 진술 (컨텍스트의 confidence로 가중) ──
    r1 = []
    def add(aid, text, ev):
        a = A.get(aid, {})
        r1.append({"id": aid, "icon": a.get('icon', '•'), "name": a.get('name', aid),
                   "conf": a.get('confidence'), "text": text, "evidence": ev,
                   "falsify": a.get('falsification', '')})

    f5 = recent(inv, 'samsung', '외국인') + recent(inv, 'hynix', '외국인')
    add("F-ACTIVE", "최근 5일 합산 {:+.2f}조. {}".format(
        f5, "매도 지속" if f5 < 0 else "순매수 전환"),
        "전일반응 {} / 베이시스상관 {}".format(
            A.get('F-ACTIVE',{}).get('parameters',{}).get('전일반응',{}).get('v'),
            A.get('F-ACTIVE',{}).get('parameters',{}).get('베이시스상관',{}).get('v')))

    r5 = recent(inv, 'samsung', '개인') + recent(inv, 'hynix', '개인')
    add("R-RETAIL", "저는 {:+.2f}조 흡수.".format(r5),
        "당일동행 {}".format(A.get('R-RETAIL',{}).get('parameters',{}).get('당일동행',{}).get('v')))

    d5 = recent(inv, 'samsung', '금융투자') + recent(inv, 'hynix', '금융투자')
    add("I-DEALER", "저는 {:+.2f}조. 베이시스 {}".format(
        d5, "{:+.2f}".format(mb) if mb is not None else "미확인"),
        "베이시스상관 {}".format(A.get('I-DEALER',{}).get('parameters',{}).get('베이시스상관_전체',{}).get('v')))

    c5 = recent(inv, 'samsung', '기타법인')
    add("C-BUYBACK", "삼성 {:+.2f}조. {}".format(c5, "집행 중" if c5 > 0.3 else "정지"),
        A.get('C-BUYBACK',{}).get('parameters',{}).get('26년5~7월',{}).get('v', ''))

    log["rounds"].append({"n": 1, "title": "자기 진술", "items": r1})

    # ── R2: 교차 반박 ──
    r2 = []
    def rb(a, b, t):
        r2.append({"from": a, "to": b, "text": t})
    if f5 < 0 and r5 > 0:
        rb("V-VERIFY", "R-RETAIL",
           "외국인 {:+.2f}조 매도를 당신이 {:+.2f}조로 흡수. 수급상 유일 흡수처입니다.".format(f5, r5))
    if c5 < 0.3:
        rb("V-VERIFY", "C-BUYBACK", "완충재 정지. 개인 단독 흡수 구조입니다.")
    if mb is not None and tb and mb > tb * 1.5:
        rb("P-ARB", "I-DEALER", "베이시스 이론치 {:.1f}배. 현물 매도 미소진.".format(mb/tb))
    # 저신뢰 에이전트 자동 경고
    for aid, a in A.items():
        c = a.get('confidence')
        if c is not None and c < 0.4:
            rb("M-CHAIR", aid, "신뢰도 {:.2f} — 발언 가중치 하향, 재검증 필요.".format(c))
    log["rounds"].append({"n": 2, "title": "교차 반박", "items": r2})

    # ── R3: 검증 ──
    N = ['금융투자','보험','투신','사모','은행','기타금융','연기금',
         '기타법인','개인','외국인','기타외국인']
    bad = 0
    for s in ('samsung', 'hynix'):
        for r in inv.get(s, [])[-20:]:
            if r.get('_src') == 'KIS-3분류': continue
            if abs(sum(r.get(k, 0) for k in N)) > 1e6: bad += 1
    v = [{"check": "수급 항등식(Σ=0)", "result": "위반 {}건".format(bad),
          "pass": bad == 0},
         {"check": "프리미엄", "result": "{:.2f}%".format(cur_p) if cur_p else "없음",
          "pass": cur_p is not None},
         {"check": "수급 데이터 기준일", "result": stale, "pass": True}]
    log["rounds"].append({"n": 3, "title": "검증", "items": v})

    # ── R4: 종합 ──
    risk = sum([f5 < 0, r5 > 0, c5 < 0.3,
                bool(mb is not None and tb and mb > tb * 1.5)])
    verdict = ["안정", "주의", "경계", "위험"][min(risk, 3)]
    log["verdict"] = {"risk": risk, "max": 4, "label": verdict,
                      "detail": "외국인 {} · 개인 {} · 자사주 {} · 베이시스 {}".format(
                          "매도" if f5 < 0 else "매수",
                          "흡수" if r5 > 0 else "이탈",
                          "정지" if c5 < 0.3 else "가동",
                          "이상" if (mb is not None and tb and mb > tb*1.5) else "정상")}
    log["rounds"].append({"n": 4, "title": "의장 종합",
                          "items": [{"text": "위험신호 {}/4 → 「{}」".format(risk, verdict)}]})

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)

    print("council: {} | 위험 {}/4 「{}」 | 에이전트 {}개 | 데이터 {}".format(
        log["at"], risk, verdict, len(A), stale))
    for it in r1:
        c = it.get('conf')
        print("  {} {:<12} conf={} \"{}\"".format(
            it['icon'], it['id'], "{:.2f}".format(c) if c else " — ", it['text']))
    for it in r2:
        print("  ⚔️ {} → {}: {}".format(it['from'], it['to'], it['text'][:60]))


if __name__ == "__main__":
    main()
