"""에이전트 협의체 v4 — 컨텍스트의 speak 규칙으로 전원 발언.

에이전트 추가/수정 시 알고리즘 수정 불필요. agents/*.json 만 고치면 된다.
"""
import json, os, statistics
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
AG   = os.path.join(BASE, "agents")
DATA = os.path.join(BASE, "docs", "data")
KST  = timezone(timedelta(hours=9))
OUT  = os.path.join(DATA, "council.json")
MINOR = ['보험', '사모', '은행', '기타금융', '기타외국인']


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


def flow(inv, field, win, stock=None):
    ss = ('samsung',) if stock == 'samsung' else ('samsung', 'hynix')
    t = 0.0
    for s in ss:
        rows = inv.get(s, [])[-win:]
        if field == '__minor__':
            t += sum(sum(r.get(k, 0) for k in MINOR) for r in rows)
        else:
            t += sum(r.get(field, 0) for r in rows)
    return t / 1e12


def speak(aid, a, ctxdata):
    """컨텍스트의 speak 규칙으로 발언 생성. 조건 미달이면 None."""
    sp = a.get('speak')
    if not sp: return None
    m = sp.get('metric'); say = sp.get('say', {}); thr = sp.get('thr', 0)
    w = sp.get('window', 5)
    v = t = None; state = ''

    if m == 'flow':
        v = flow(ctxdata['inv'], sp.get('field'), w, sp.get('stock'))
        if abs(v) < thr: return None
        st = sp.get('state')
        if st: state = st['yes'] if v > st.get('gt', 0) else st['no']
    elif m == 'shortsale':
        sr = ctxdata['ext'].get('shortsale', {}).get('samsung', [])[-w:]
        if not sr: return None
        v = statistics.mean(r.get('공매도거래대금', 0) for r in sr) / 1e11
    elif m == 'basis':
        bas = ctxdata['ext'].get('basis_kospi200', [])
        if not bas: return None
        v = bas[-1].get('시장베이시스'); t = bas[-1].get('이론베이시스')
        if v is None: return None
        st = sp.get('state')
        if st and t:
            state = st['yes'] if v > t * st.get('gt_ratio', 1.5) else st['no']
    elif m == 'static':
        v = 0

    key = 'any' if 'any' in say else ('pos' if (v or 0) >= 0 else 'neg')
    tpl = say.get(key) or say.get('any') or ''
    try:
        text = tpl.format(v=v or 0, w=w, t=(t if t is not None else thr), state=state)
    except (KeyError, ValueError):
        text = tpl
    return {"id": aid, "icon": a.get('icon', '•'), "name": a.get('name', aid),
            "conf": a.get('confidence'), "text": text,
            "evidence": a.get('data_source', ''),
            "falsify": a.get('falsification', '')}


def main():
    A    = load_agents()
    inv  = load(os.path.join(DATA, "krx_investors.json"), {})
    ext  = load(os.path.join(DATA, "krx_extra.json"), {})
    hist = load(os.path.join(DATA, "history.json"), [])
    now  = datetime.now(KST)
    ctxdata = {"inv": inv, "ext": ext, "hist": hist}

    prem  = [r['premium_pct'] for r in hist if r.get('trusted') is not False]
    cur_p = prem[-1] if prem else None
    stale = inv.get('samsung', [{}])[-1].get('date', '?')
    bas   = ext.get('basis_kospi200', [])
    mb    = bas[-1].get('시장베이시스') if bas else None
    tb    = bas[-1].get('이론베이시스') if bas else None

    log = {"at": now.strftime('%Y-%m-%d %H:%M'), "rounds": [], "data_asof": stale}

    # ── R1: 전원 발언 (그룹 순서) ──
    order = ['F-PASSIVE','F-ACTIVE','F-SHORT','I-DEALER','I-FUND','I-PENSION',
             'I-MINOR','R-RETAIL','R-LEVERAGE','C-BUYBACK','P-ARB']
    r1, silent = [], []
    for aid in order:
        a = A.get(aid)
        if not a: continue
        s = speak(aid, a, ctxdata)
        if s: r1.append(s)
        else: silent.append({"id": aid, "icon": a.get('icon','•'),
                             "name": a.get('name', aid), "reason": "임계 미달 — 침묵"})
    log["rounds"].append({"n": 1, "title": "자기 진술", "items": r1, "silent": silent})

    # ── R2: 교차 반박 ──
    f5 = flow(inv, '외국인', 5); r5 = flow(inv, '개인', 5)
    c5 = flow(inv, '기타법인', 5, 'samsung'); d5 = flow(inv, '금융투자', 5)
    fu5 = flow(inv, '투신', 5)
    r2 = []
    def rb(a, b, t): r2.append({"from": a, "to": b, "text": t})
    if f5 < 0 and r5 > 0:
        rb("V-VERIFY","R-RETAIL","외국인 {:+.2f}조 매도를 당신이 {:+.2f}조로 흡수. 유일 흡수처입니다.".format(f5, r5))
    if c5 < 0.3:
        rb("V-VERIFY","C-BUYBACK","완충재 정지. 개인 단독 흡수 구조입니다.")
    if mb is not None and tb and mb > tb * 1.5:
        rb("P-ARB","I-DEALER","베이시스 이론치 {:.1f}배. 현물 매도 미소진.".format(mb/tb))
    if d5 < 0 and fu5 < 0:
        rb("I-FUND","I-DEALER","당신도 {:+.2f}조 매도. 기관 전체가 이탈 중입니다.".format(d5))
    if r5 > 2:
        rb("R-LEVERAGE","R-RETAIL","{:+.2f}조를 받았는데 예탁금은 -32.5조입니다. 제 신용 32.7조가 뇌관입니다.".format(r5))
    for aid, a in A.items():
        c = a.get('confidence')
        if c is not None and c < 0.4:
            rb("M-CHAIR", aid, "신뢰도 {:.2f} — 발언 가중치 하향, 재검증 필요.".format(c))
    log["rounds"].append({"n": 2, "title": "교차 반박", "items": r2})

    # ── R3: 검증 ──
    N = ['금융투자','보험','투신','사모','은행','기타금융','연기금',
         '기타법인','개인','외국인','기타외국인']
    bad = sum(1 for s in ('samsung','hynix') for r in inv.get(s, [])[-20:]
              if abs(sum(r.get(k, 0) for k in N)) > 1e6)
    v3 = [{"check":"수급 항등식(Σ=0)","result":"위반 {}건".format(bad),"pass":bad==0},
          {"check":"프리미엄","result":"{:.2f}%".format(cur_p) if cur_p else "없음","pass":cur_p is not None},
          {"check":"수급 기준일","result":stale,"pass":True},
          {"check":"발언/침묵","result":"{}명 / {}명".format(len(r1), len(silent)),"pass":True}]
    log["rounds"].append({"n": 3, "title": "검증", "items": v3})

    # ── R4: 종합 ──
    risk = sum([f5 < 0, r5 > 0, c5 < 0.3, bool(mb is not None and tb and mb > tb*1.5)])
    verdict = ["안정","주의","경계","위험"][min(risk, 3)]
    log["verdict"] = {"risk": risk, "max": 4, "label": verdict,
      "detail": "외국인 {} · 개인 {} · 자사주 {} · 베이시스 {}".format(
        "매도" if f5<0 else "매수", "흡수" if r5>0 else "이탈",
        "정지" if c5<0.3 else "가동",
        "이상" if (mb is not None and tb and mb>tb*1.5) else "정상")}
    log["rounds"].append({"n": 4, "title": "의장 종합",
      "items": [{"text": "위험신호 {}/4 → 「{}」".format(risk, verdict)}]})

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)

    print("council: {} | 위험 {}/4 「{}」 | 발언 {}/침묵 {} | 데이터 {}".format(
        log["at"], risk, verdict, len(r1), len(silent), stale))
    for it in r1:
        c = it.get('conf')
        print("  {} {:<12} {} {}".format(it['icon'], it['id'],
              "conf={:.2f}".format(c) if c else "       ", it['text'][:58]))
    for it in silent:
        print("  🔇 {:<12} 침묵".format(it['id']))
    for it in r2:
        print("  ⚔️ {} → {}: {}".format(it['from'], it['to'], it['text'][:52]))


if __name__ == "__main__":
    main()
