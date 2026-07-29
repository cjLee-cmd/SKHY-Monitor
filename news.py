"""뉴스·공시 감시 v2 — 3소스 통합 + 오분류 방지.

소스
  A 국내뉴스  구글 뉴스 RSS (ko)   — 시장 전반
  B 영문뉴스  Yahoo Finance RSS    — 해외 Peer 선행
  C 공시      DART 최근공시 RSS     — 사실 확정

혼선 방지 4장치
  1) 소스 화이트리스트  에이전트마다 받을 소스를 제한
  2) 배타적 라우팅      기사당 최대 2개 에이전트 (점수 상위)
  3) 키워드 특이도      흔한 단어는 낮은 점수, 고유명사는 높은 점수
  4) 최소 점수 문턱     문턱 미달이면 미배정 (억지 배정 금지)
"""
import json, os, re, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "docs", "data", "news.json")
KST  = timezone(timedelta(hours=9))
UA   = {"User-Agent": "Mozilla/5.0"}

KR_QUERIES  = ["SK하이닉스", "삼성전자 반도체", "메모리 반도체 중국",
               "외국인 순매도 코스피", "반대매매 신용잔고"]
EN_TICKERS  = ["MU", "ASML", "TSM"]
DART_KEYS   = ["삼성전자", "SK하이닉스"]

# (키워드, 특이도) — 특이도 3=고유명사, 2=업계용어, 1=흔한말
ROUTE = {
 "C-CHINA":   [("CXMT",3),("창신",3),("YMTC",3),("DUV",3),("노광",3),
               ("중국",1),("국산화",2),("자립",2)],
 "M-CYCLE":   [("마이크론",3),("Micron",3),("HBM",3),("D램",2),("DRAM",2),
               ("낸드",2),("감산",2),("증산",2),("사이클",1)],
 "F-ACTIVE":  [("외국인",2),("순매도",2),("순매수",2),("MSCI",3),("패시브",2)],
 "R-LEVERAGE":[("반대매매",3),("신용잔고",3),("신용융자",3),("레버리지",2),("미수",2)],
 "B-RATES":   [("연준",3),("FOMC",3),("국채",2),("금리",1),("환율",1)],
 "P-ADR":     [("ADR",3),("예탁증서",3),("상호전환",3),("괴리율",2)],
 "C-BUYBACK": [("자사주",3),("소각",3),("배당",2)],
 "M-RISK":    [("서킷브레이커",3),("사이드카",3),("패닉",2),("폭락",1),("급락",1)],
}
SRC_ALLOW = {  # 에이전트별 허용 소스
 "C-CHINA":["kr","en"], "M-CYCLE":["kr","en"], "F-ACTIVE":["kr"],
 "R-LEVERAGE":["kr"], "B-RATES":["kr","en"], "P-ADR":["kr"],
 "C-BUYBACK":["kr","dart"], "M-RISK":["kr"],
}
MIN_SCORE = 3      # 문턱: 고유명사 1개 또는 업계용어 2개
MAX_AGENTS = 2     # 기사당 최대 배정

EVENTS = {
 "critical": [("서킷브레이커",),("사이드카",),("거래정지",),("반대매매",)],
 "high":     [("목표가","하향"),("목표주가","하향"),("투자의견","하향"),("감산",),("적자",)],
 "info":     [("목표가","상향"),("수주",),("공급계약",),("증설",),("자사주","매입")],
}


def rss(url, limit=20):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8', 'replace')
    except Exception:
        return []
    out = []
    for it in re.findall(r'<item>(.*?)</item>', raw, re.S)[:limit]:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S)
        if not t: continue
        title = re.sub(r'<[^>]+>', '', t.group(1)).strip()
        for a, b in (('&quot;','"'),('&amp;','&'),('&#39;',"'"),('&lt;','<'),('&gt;','>')):
            title = title.replace(a, b)
        out.append({"title": title, "pub": (d.group(1)[:16] if d else "")})
    return out


def collect():
    items = []
    for q in KR_QUERIES:
        for a in rss("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
                     + "&hl=ko&gl=KR&ceid=KR:ko", 15):
            a.update({"src": "kr", "q": q}); items.append(a)
    for t in EN_TICKERS:
        for a in rss("https://feeds.finance.yahoo.com/rss/2.0/headline?s="
                     + t + "&region=US&lang=en-US", 10):
            a.update({"src": "en", "q": t}); items.append(a)
    for a in rss("https://dart.fss.or.kr/api/todayRSS.xml", 60):
        if any(k in a['title'] for k in DART_KEYS):
            a.update({"src": "dart", "q": "DART"}); items.append(a)
    # 중복 제거
    seen, out = set(), []
    for a in items:
        k = a['title'][:45]
        if k in seen: continue
        seen.add(k); out.append(a)
    return out


def route(title, src):
    """특이도 가중 점수 → 상위 2개만, 문턱 미달은 미배정."""
    sc = {}
    for ag, kws in ROUTE.items():
        if src not in SRC_ALLOW.get(ag, []): continue
        s = sum(w for k, w in kws if k in title)
        if s >= MIN_SCORE: sc[ag] = s
    return [a for a, _ in sorted(sc.items(), key=lambda x: -x[1])[:MAX_AGENTS]]


def main():
    now = datetime.now(KST)
    items = collect()
    prev = {}
    try:
        with open(OUT, encoding='utf-8') as f: prev = json.load(f)
    except (OSError, ValueError): pass
    old = {x['title'][:45] for x in prev.get('items', [])}

    routed, alerts, unassigned = {}, [], 0
    for a in items:
        a['agents'] = route(a['title'], a['src'])
        if not a['agents']: unassigned += 1
        for ag in a['agents']:
            routed[ag] = routed.get(ag, 0) + 1
        if a['title'][:45] in old: continue
        for lvl, pats in EVENTS.items():
            for p in pats:
                if all(k in a['title'] for k in p):
                    alerts.append({"level": lvl, "kw": "+".join(p), "src": a['src'],
                                   "title": a['title'][:76], "agents": a['agents']})
                    break
            else: continue
            break

    order = {"critical":0, "high":1, "info":2}
    alerts.sort(key=lambda x: order.get(x['level'], 9))
    bysrc = {}
    for a in items: bysrc[a['src']] = bysrc.get(a['src'], 0) + 1

    snap = {"ts_kst": now.strftime('%m-%d %H:%M'), "n_items": len(items),
            "by_source": bysrc, "routed": routed, "unassigned": unassigned,
            "alerts": alerts[:12], "items": items[:80],
            "guards": {"min_score": MIN_SCORE, "max_agents": MAX_AGENTS,
                       "src_whitelist": True, "specificity_weighted": True}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("news2: {} | {}건 (국내 {} / 영문 {} / 공시 {}) | 미배정 {}건".format(
        snap['ts_kst'], len(items), bysrc.get('kr',0), bysrc.get('en',0),
        bysrc.get('dart',0), unassigned))
    print("  [배정]")
    for ag, n in sorted(routed.items(), key=lambda x: -x[1]):
        print("    {:<12}{:>3}건  (소스 {})".format(ag, n, "/".join(SRC_ALLOW[ag])))
    if alerts:
        print("  [경보]")
        for a in alerts[:7]:
            print("    [{}] {} <{}> {}".format(a['level'], a['kw'], a['src'], a['title'][:48]))


if __name__ == "__main__":
    main()
