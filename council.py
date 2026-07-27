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
    elif m == 'bonds':
        b = ctxdata.get('bonds') or {}
        it = b.get('items', {}); dv = b.get('derived', {})
        u = it.get('us10y', {}); j = it.get('usdjpy', {})
        if not u: return None
        v = u.get('cur', 0)
        st = sp.get('state', {})
        state = st.get('yes' if u.get('range_pos', 0) >= 80 else 'no', '')
        try:
            text = say.get('any', '').format(v=v, p=u.get('range_pos', 0),
                c=dv.get('curve_30_10', 0), j=j.get('cur', 0),
                jp=j.get('range_pos', 0), state=state)
        except (KeyError, ValueError):
            text = say.get('any', '')
        return {"id": aid, "icon": a.get('icon','•'), "name": a.get('name',aid),
                "conf": a.get('confidence'), "text": text,
                "evidence": a.get('data_source',''), "falsify": a.get('falsification','')}
    elif m == 'market':
        mk = ctxdata.get('market') or {}
        G = mk.get('groups', {}); dv = mk.get('derived', {})
        it = G.get(sp.get('group'), {}).get(sp.get('key'))
        if not it: return None
        st = sp.get('state', {})
        if sp.get('key') == 'mu':
            v = it.get('chg_20d', 0)
            state = st.get('yes' if v <= st.get('lt', -10) else 'no', '')
            sx = G.get('해외지수', {}).get('sox', {}).get('chg_20d', 0)
            ts = G.get('반도체Peer', {}).get('tsm', {}).get('chg_20d', 0)
            try: text = say.get('any','').format(v=v, s=sx, t=ts, state=state)
            except Exception: text = say.get('any','')
        else:
            v = it.get('cur', 0)
            state = st.get('yes' if v >= st.get('gt', 99) else 'no', '')
            oil = G.get('원자재', {}).get('oil', {}).get('chg_20d', 0)
            kv = dv.get('kospi_vs_spx_20d', 0)
            try: text = say.get('any','').format(v=v, p=it.get('range_pos',0), o=oil, k=kv, state=state)
            except Exception: text = say.get('any','')
        return {"id": aid, "icon": a.get('icon','•'), "name": a.get('name',aid),
                "conf": a.get('confidence'), "text": text,
                "evidence": a.get('data_source',''), "falsify": a.get('falsification','')}
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
    bonds = load(os.path.join(DATA, "bonds.json"), {})
    market = load(os.path.join(DATA, "market.json"), {})
    ctxdata = {"inv": inv, "ext": ext, "hist": hist, "bonds": bonds, "market": market}

    prem  = [r['premium_pct'] for r in hist if r.get('trusted') is not False]
    cur_p = prem[-1] if prem else None
    stale = inv.get('samsung', [{}])[-1].get('date', '?')
    bas   = ext.get('basis_kospi200', [])
    mb    = bas[-1].get('시장베이시스') if bas else None
    tb    = bas[-1].get('이론베이시스') if bas else None

    log = {"at": now.strftime('%Y-%m-%d %H:%M'), "rounds": [], "data_asof": stale}

    # ── R1: 전원 발언 (그룹 순서) ──
    order = ['F-PASSIVE','F-ACTIVE','F-SHORT','I-DEALER','I-FUND','I-PENSION',
             'I-MINOR','R-RETAIL','R-LEVERAGE','C-BUYBACK','P-ARB','B-RATES','M-CYCLE','M-RISK']
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

    # ── R4: M-CHAIR 신뢰도 가중 종합 ──
    def stance_of(aid, a):
        """컨텍스트의 stance 규칙으로 -1(약세)~+1(강세) 산출."""
        st = a.get('stance')
        if not st: return None
        rule = st.get('rule'); w = st.get('w', 0.5)
        v = None
        if rule == 'flow_sign':
            x = flow(inv, st.get('field'), 5, st.get('stock'))
            v = max(-1.0, min(1.0, x / 2.0))
            if st.get('invert'): v = -v
        elif rule == 'threshold':
            x = flow(inv, st.get('field'), 5, st.get('stock'))
            v = 0.6 if x > st.get('gt', 0) else -0.6
        elif rule == 'static':
            v = st.get('value', 0)
        elif rule == 'basis_gap':
            if mb is None or not tb: return None
            v = -0.7 if mb > tb * 1.5 else 0.2
        elif rule == 'market_chg':
            mk = ctxdata.get('market') or {}
            it = mk.get('groups', {}).get(st.get('group'), {}).get(st.get('key'))
            if not it: return None
            v = max(-1.0, min(1.0, it.get('chg_20d', 0) / st.get('scale', 15)))
        elif rule == 'market_inv':
            mk = ctxdata.get('market') or {}
            it = mk.get('groups', {}).get(st.get('group'), {}).get(st.get('key'))
            if not it: return None
            v = max(-1.0, min(1.0, -(it.get('cur', 0) - st.get('base', 18)) / st.get('scale', 10)))
        elif rule == 'rate_pos':
            b = ctxdata.get('bonds') or {}
            u = b.get('items', {}).get('us10y')
            if not u: return None
            p = u.get('range_pos', 50)
            v = -(p - 50) / 50.0
        if v is None: return None
        c = a.get('confidence', 0.5)
        eff = w * (c * 0.5 if c < 0.4 else c)   # 저신뢰 감산
        return {"id": aid, "name": a.get('name', aid), "icon": a.get('icon','•'),
                "stance": round(v, 3), "weight": round(w, 2),
                "conf": c, "eff": round(eff, 3), "contrib": round(v * eff, 3)}

    votes = [x for x in (stance_of(aid, A[aid]) for aid in order if aid in A) if x]
    tw = sum(x['eff'] for x in votes) or 1.0
    score = sum(x['contrib'] for x in votes) / tw

    SCALE = [(-1.0,-0.35,"위험"),(-0.35,-0.12,"경계"),(-0.12,0.12,"주의"),(0.12,1.01,"안정")]
    label = next((n for lo,hi,n in SCALE if lo <= score < hi), "주의")

    bear = sorted([x for x in votes if x['stance'] < 0], key=lambda x: x['contrib'])[:3]
    bull = sorted([x for x in votes if x['stance'] > 0], key=lambda x: -x['contrib'])[:3]
    major, minor = (bear, bull) if score < 0 else (bull, bear)

    unresolved = []
    for aid, a in A.items():
        for q in a.get('open_questions', []):
            unresolved.append({"agent": aid, "q": q})

    log["verdict"] = {
      "score": round(score, 3), "label": label,
      "n_votes": len(votes), "n_rebut": len(r2),
      "major": [{"icon":x['icon'],"name":x['name'],"contrib":x['contrib'],"conf":x['conf']} for x in major],
      "minor": [{"icon":x['icon'],"name":x['name'],"contrib":x['contrib'],"conf":x['conf']} for x in minor],
      "unresolved": unresolved[:5],
      "detail": "가중점수 {:+.3f} · 투표 {}인 · 반박 {}건".format(score, len(votes), len(r2))}

    ch = A.get('M-CHAIR', {})
    log["rounds"].append({"n": 4, "title": "의장 종합",
      "items": [
        {"text": "가중 점수 {:+.3f} → 「{}」".format(score, label)},
        {"text": "주요 논거: " + ", ".join("{} {}({:+.2f})".format(x['icon'],x['name'],x['contrib']) for x in major)},
        {"text": "소수 의견: " + (", ".join("{} {}({:+.2f})".format(x['icon'],x['name'],x['contrib']) for x in minor) or "없음")},
        {"text": "미해결 {}건 → S-SEARCH 이관".format(len(unresolved))},
      ],
      "votes": votes})

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)

    print("council: {} | 「{}」 점수 {:+.3f} | 발언 {}/침묵 {} | 투표 {}인".format(
        log["at"], log["verdict"]["label"], log["verdict"]["score"],
        len(r1), len(silent), len(votes)))
    for it in r1:
        c = it.get('conf')
        print("  {} {:<12} {} {}".format(it['icon'], it['id'],
              "conf={:.2f}".format(c) if c else "       ", it['text'][:52]))
    for it in silent:
        print("  🔇 {:<12} 침묵".format(it['id']))
    for it in r2:
        print("  ⚔️ {} → {}: {}".format(it['from'], it['to'], it['text'][:48]))
    print("  ⚖️ M-CHAIR 종합")
    print("     주요: " + ", ".join("{}({:+.2f})".format(x['name'], x['contrib']) for x in major))
    print("     소수: " + (", ".join("{}({:+.2f})".format(x['name'], x['contrib']) for x in minor) or "없음"))
    print("     미해결 {}건".format(len(unresolved)))


if __name__ == "__main__":
    main()
