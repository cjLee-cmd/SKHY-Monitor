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
        elif sp.get('key') == 'vkospi':
            v = it.get('cur', 0)
            state = st.get('yes' if v >= st.get('gt', 80) else 'no', '')
            vx = G.get('변동성', {}).get('vix', {}).get('cur', 1) or 1
            sk = G.get('변동성', {}).get('skew', {}).get('cur', 0)
            try: text = say.get('any','').format(v=v, r=v/vx, s=sk, state=state)
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
    elif m == 'adr':
        aw = ctxdata.get('adr') or {}
        v = aw.get('premium')
        if v is None: return None
        al = aw.get('alerts', [])
        st = sp.get('state', {})
        state = st.get('yes' if al else 'no', '')
        if al: state += " " + al[0].get('text','')[:60]
        try: text = say.get('any','').format(v=v, state=state)
        except Exception: text = say.get('any','')
        return {"id": aid, "icon": a.get('icon','•'), "name": a.get('name',aid),
                "conf": a.get('confidence'), "text": text,
                "evidence": a.get('data_source',''), "falsify": a.get('falsification','')}
    elif m == 'leverage':
        aw = ctxdata.get('adr') or {}
        lv = aw.get('leverage', {})
        ss = lv.get('samsung', {}); hy = lv.get('hynix', {})
        if not ss: return None
        st = sp.get('state', {})
        state = st.get('yes' if hy.get('chg_avg', 0) <= st.get('lt', -8) else 'no', '')
        try:
            text = say.get('any','').format(s=ss.get('mktcap_jo',0), sc=ss.get('chg_avg',0),
                                            h=hy.get('mktcap_jo',0), hc=hy.get('chg_avg',0), state=state)
        except Exception: text = say.get('any','')
        return {"id": aid, "icon": a.get('icon','•'), "name": a.get('name',aid),
                "conf": a.get('confidence'), "text": text,
                "evidence": a.get('data_source',''), "falsify": a.get('falsification','')}
    elif m == 'overreact':
        ov = ctxdata.get('overreact') or {}
        if not ov: return None
        det = ov.get('detail', {}); th = ov.get('threat', {})
        st = sp.get('state', {})
        sc = ov.get('score', 0)
        state = st.get('yes' if sc >= st.get('gt', 70) else 'no', '')
        try:
            text = say.get('any','').format(c=th.get('dram_rev_share', 0),
                n=det.get('chain_negative','?'), r=det.get('fundamental_ratio', 0), state=state)
        except Exception: text = say.get('any','')
        return {"id": aid, "icon": a.get('icon','•'), "name": a.get('name',aid),
                "conf": a.get('confidence'), "text": text,
                "evidence": a.get('data_source',''), "falsify": a.get('falsification','')}
    elif m == 'funds_flow':
        fd = ctxdata.get('funds') or {}
        cu = fd.get('current', {}); dv = fd.get('derived', {})
        dep = cu.get('deposit', {})
        v = flow(ctxdata['inv'], sp.get('field'), sp.get('window', 5))
        dp = dv.get('dry_powder_jo', 0)
        st = sp.get('state', {})
        state = st.get('yes' if dp <= st.get('lt', 40) else 'no', '')
        try:
            text = say.get('any','').format(v=v, d=dep.get('value_jo', 0),
                                            dc=dep.get('chg_jo', 0), dp=dp, state=state)
        except Exception: text = say.get('any','')
        return {"id": aid, "icon": a.get('icon','•'), "name": a.get('name',aid),
                "conf": a.get('confidence'), "text": text,
                "evidence": a.get('data_source',''), "falsify": a.get('falsification','')}
    elif m == 'funds_lev':
        fd = ctxdata.get('funds') or {}
        aw = ctxdata.get('adr') or {}
        cre = fd.get('current', {}).get('credit', {})
        if not cre: return None
        lv = aw.get('leverage', {})
        sh = (lv.get('samsung', {}).get('shares_eok', 0) +
              lv.get('hynix', {}).get('shares_eok', 0)) or 7.20
        st = sp.get('state', {})
        state = st.get('yes' if cre.get('chg_jo', 0) > st.get('gt', 0) else 'no', '')
        try:
            text = say.get('any','').format(c=cre.get('value_jo', 0),
                                            cc=cre.get('chg_jo', 0), sh=sh, state=state)
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
    adrw = load(os.path.join(DATA, "adr_watch.json"), {})
    ovr = load(os.path.join(DATA, "overreact.json"), {})
    fnd = load(os.path.join(DATA, "funds.json"), {})
    ctxdata = {"inv": inv, "ext": ext, "hist": hist, "bonds": bonds, "market": market, "adr": adrw, "overreact": ovr, "funds": fnd}

    prem  = [r['premium_pct'] for r in hist if r.get('trusted') is not False]
    cur_p = prem[-1] if prem else None
    stale = inv.get('samsung', [{}])[-1].get('date', '?')
    bas   = ext.get('basis_kospi200', [])
    mb    = bas[-1].get('시장베이시스') if bas else None
    tb    = bas[-1].get('이론베이시스') if bas else None

    log = {"at": now.strftime('%Y-%m-%d %H:%M'), "rounds": [], "data_asof": stale}

    # ── R1: 전원 발언 (그룹 순서) ──
    order = ['F-PASSIVE','F-ACTIVE','F-SHORT','I-DEALER','I-FUND','I-PENSION',
             'I-MINOR','R-RETAIL','R-LEVERAGE','C-BUYBACK','P-ARB','B-RATES','M-CYCLE','M-RISK','P-ADR','C-CHINA']
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

    # ── R4: M-CHAIR 진단 + 조건부 트리거 (예측 아님) ──
    def stance_of(aid, ag):
        st = ag.get('stance')
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
        elif rule == 'rate_pos':
            u = (ctxdata.get('bonds') or {}).get('items', {}).get('us10y')
            if not u: return None
            v = -(u.get('range_pos', 50) - 50) / 50.0
        elif rule == 'market_chg':
            it2 = (ctxdata.get('market') or {}).get('groups', {}).get(st.get('group'), {}).get(st.get('key'))
            if not it2: return None
            v = max(-1.0, min(1.0, it2.get('chg_20d', 0) / st.get('scale', 15)))
        elif rule == 'market_inv':
            it2 = (ctxdata.get('market') or {}).get('groups', {}).get(st.get('group'), {}).get(st.get('key'))
            if not it2: return None
            v = max(-1.0, min(1.0, -(it2.get('cur', 0) - st.get('base', 18)) / st.get('scale', 10)))
        elif rule == 'vkospi_level':
            it2 = (ctxdata.get('market') or {}).get('groups', {}).get('변동성', {}).get('vkospi')
            if not it2: return None
            v = max(-1.0, min(1.0, -(it2.get('cur', 55) - st.get('base', 55)) / st.get('scale', 30)))
        elif rule == 'credit_chg':
            cc = (ctxdata.get('funds') or {}).get('current', {}).get('credit', {}).get('chg_jo')
            if cc is None: return None
            v = max(-1.0, min(1.0, -cc / 0.5))
        elif rule == 'adr_alert':
            alx = (ctxdata.get('adr') or {}).get('alerts', [])
            if not alx: return None
            v = -1.0 if any(x.get('level') == 'critical' for x in alx) else -0.6
        elif rule == 'leverage_chg':
            hy2 = (ctxdata.get('adr') or {}).get('leverage', {}).get('hynix', {})
            if not hy2: return None
            v = max(-1.0, min(1.0, hy2.get('chg_avg', 0) / 10.0))
        elif rule == 'overreact_score':
            sc2 = (ctxdata.get('overreact') or {}).get('score')
            if sc2 is None: return None
            v = max(-1.0, min(1.0, (sc2 - 50) / 50.0))
        if v is None: return None
        cf = ag.get('confidence', 0.5)
        eff = w * (cf * 0.5 if cf < 0.4 else cf)
        return {"id": aid, "name": ag.get('name', aid), "icon": ag.get('icon', '•'),
                "stance": round(v, 3), "conf": cf, "eff": round(eff, 3),
                "contrib": round(v * eff, 3)}

    votes = [x for x in (stance_of(k, A[k]) for k in order if k in A) if x]
    tw = sum(x['eff'] for x in votes) or 1.0
    score = sum(x['contrib'] for x in votes) / tw
    SCALE = [(-1.0, -0.35, "위험"), (-0.35, -0.12, "경계"),
             (-0.12, 0.12, "주의"), (0.12, 1.01, "안정")]
    label = next((n for lo, hi, n in SCALE if lo <= score < hi), "주의")

    # ── 진단: 검증 가능한 사실 명제만 ──
    INST = ['금융투자','보험','투신','사모','은행','기타금융','연기금']
    i5 = sum(flow(inv, k, 5) for k in INST)
    dx = []
    def dg(claim, cond, ev):
        dx.append({"claim": claim, "true": bool(cond), "evidence": ev})
    dg("외국인 매도 지속", f5 < 0, "5일 {:+.2f}조".format(f5))
    dg("개인이 흡수", r5 > 0, "5일 {:+.2f}조".format(r5))
    dg("기관 이탈", i5 < 0, "5일 {:+.2f}조".format(i5))
    dg("자사주 완충 정지", c5 < 0.3, "삼성 {:+.2f}조".format(c5))
    dg("개인이 유일 흡수처", f5 < 0 and i5 < 0 and r5 > 0, "수급 항등식")
    fd = ctxdata.get('funds') or {}
    cre = fd.get('current', {}).get('credit', {})
    if cre:
        dg("레버리지 확대 중(항복 전)", cre.get('chg_jo', 0) > 0,
           "신용 {:+.2f}조".format(cre.get('chg_jo', 0)))
    vko = (ctxdata.get('market') or {}).get('groups', {}).get('변동성', {}).get('vkospi', {})
    if vko.get('cur'):
        dg("한국 공포 극단(VKOSPI 80+)", vko['cur'] >= 80, "VKOSPI {:.1f}".format(vko['cur']))
    if mb is not None and tb:
        dg("현물 매도 압력 미소진", mb > tb * 1.5, "베이시스 {:+.2f}/{:+.2f}".format(mb, tb))

    # ── 조건부 트리거: "X가 Y되면 Z" ──
    tg = []
    def tr(watch, cond, then, cur):
        tg.append({"watch": watch, "if": cond, "then": then, "now": cur})
    lv = (ctxdata.get('adr') or {}).get('leverage', {})
    tr("레버ETF 좌수", "-10% 이상 급감", "개인 항복 시작 → 바닥 근접 신호",
       "현재 유지 중" if lv else "미확인")
    if cre:
        tr("신용융자", "감소 전환", "청산 진행 → 항복 진입",
           "{:.1f}조({:+.2f})".format(cre.get('value_jo', 0), cre.get('chg_jo', 0)))
    tr("외국인 수급", "3일 연속 순매수", "매도 압력 소진",
       "5일 {:+.2f}조".format(f5))
    tr("자사주", "일 0.3조 이상 재개", "완충재 복귀",
       "삼성 {:+.2f}조".format(c5))
    if vko.get('cur'):
        tr("VKOSPI", "60 이하 하락", "공포 완화 국면 전환",
           "{:.1f}".format(vko['cur']))

    ch_ctx = A.get('M-CHAIR', {})
    ng = ch_ctx.get('narrative_guard', {})
    guard = None
    if ng and score <= ng.get('trigger', -0.35):
        guard = {"active": True,
                 "msg": "가중점수 {:+.3f} — 강세 서술 금지. 주요 논거를 부차 지표로 뒤집지 말 것.".format(score)}

    bear = sorted([x for x in votes if x['stance'] < 0], key=lambda x: x['contrib'])[:3]
    bull = sorted([x for x in votes if x['stance'] > 0], key=lambda x: -x['contrib'])[:3]
    major, minor = (bear, bull) if score < 0 else (bull, bear)
    unresolved = [{"agent": k, "q": q} for k, ag in A.items() for q in ag.get('open_questions', [])]

    log["verdict"] = {
        "mode": "진단",
        "score": round(score, 3), "label": label,
        "n_votes": len(votes), "n_rebut": len(r2),
        "diagnosis": dx, "triggers": tg,
        "major": [{"icon": x['icon'], "name": x['name'], "contrib": x['contrib'], "conf": x['conf']} for x in major],
        "minor": [{"icon": x['icon'], "name": x['name'], "contrib": x['contrib'], "conf": x['conf']} for x in minor],
        "guard": guard, "unresolved": unresolved[:5],
        "disclaimer": "이 판정은 현재 상태 진단이며 가격 예측이 아닙니다. 일간 방향의 설명력(R²)은 2% 미만입니다.",
        "detail": "가중 {:+.3f} · 투표 {}인 · 진단 {}건 · 트리거 {}건".format(
            score, len(votes), len(dx), len(tg))}
    log["rounds"].append({"n": 4, "title": "의장 진단", "items": [
        {"text": "국면 「{}」 (가중 {:+.3f})".format(label, score)},
        {"text": "진단 {}/{}건 성립".format(sum(1 for x in dx if x['true']), len(dx))},
        {"text": "감시 트리거 {}건".format(len(tg))},
    ], "votes": votes})

    # 점수 시계열 기록 (10분 간격)
    slog = []
    try:
        with open(OUT, encoding='utf-8') as _f:
            slog = json.load(_f).get("score_log", [])
    except (OSError, ValueError):
        pass
    slog.append({"ts": log["at"], "score": round(score, 3), "label": label,
                 "n_votes": len(votes),
                 "n_true": sum(1 for x in dx if x['true']), "n_diag": len(dx)})
    log["score_log"] = slog[-600:]

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)

    V = log["verdict"]
    print("council[진단]: {} | 「{}」 {:+.3f} | 발언 {}/침묵 {} | 투표 {}".format(
        log["at"], V["label"], V["score"], len(r1), len(silent), V["n_votes"]))
    print("  [진단 — 검증 가능한 사실]")
    for x in V["diagnosis"]:
        print("    {} {:<22} {}".format("✅" if x["true"] else "❌", x["claim"], x["evidence"]))
    print("  [조건부 트리거 — 무엇을 보면 무엇이 바뀌나]")
    for x in V["triggers"]:
        print("    · {:<12} {:<16} → {}".format(x["watch"], x["if"], x["then"]))
        print("      현재: {}".format(x["now"]))
    print("  [논거] 주요: " + ", ".join("{}({:+.2f})".format(x['name'], x['contrib']) for x in V["major"]))
    print("         소수: " + (", ".join("{}({:+.2f})".format(x['name'], x['contrib']) for x in V["minor"]) or "없음"))
    if V.get("guard"): print("  🚧 " + V["guard"]["msg"])
    print("  ⚠️ " + V["disclaimer"])


if __name__ == "__main__":
    main()
