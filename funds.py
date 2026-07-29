"""대기자금 수집 — 금융투자협회 FreeSIS.

투자자예탁금·신용융자·CMA·주식형펀드를 매일 기록하고,
R-RETAIL / R-LEVERAGE 에이전트가 실데이터로 발언하게 한다.
"""
import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "docs", "data", "funds.json")
KST  = timezone(timedelta(hours=9))
UA   = {"User-Agent": "Mozilla/5.0"}
MAX  = 400

FIELDS = [("투자자예탁금", "deposit"), ("신용융자", "credit"),
          ("CMA잔고", "cma"), ("주식형펀드 순자산", "equity_fund")]
# 역사적 하한 (동원 여력 계산용)
FLOOR = {"deposit": 58.0}


def main():
    now = datetime.now(KST)
    try:
        req = urllib.request.Request("https://freesis.kofia.or.kr/stat/main.do", headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read().decode('utf-8', 'replace')
    except Exception as e:
        print("funds: 수집 실패", e); return

    txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))
    cur = {}
    for label, key in FIELDS:
        i = txt.find(label)
        if i < 0: continue
        seg = txt[i:i + 160]
        # 형식: 라벨 단위 | MM/DD 값 증감 증감률
        m = re.search(r'(\d{2}/\d{2})\s+([\d,]+)\s+(-?[\d,]+)\s+(-?[\d.]+)%', seg)
        if not m: continue
        unit = 1e8 if '억원' in seg[:30] else 1e6   # 백만원 or 억원
        cur[key] = {"label": label, "date": m.group(1),
                    "value_jo": round(float(m.group(2).replace(',', '')) * unit / 1e12, 2),
                    "chg_jo": round(float(m.group(3).replace(',', '')) * unit / 1e12, 3),
                    "chg_pct": float(m.group(4))}
    if not cur:
        print("funds: 파싱 실패"); return

    # 파생
    d = {}
    dep = cur.get('deposit', {}).get('value_jo')
    cre = cur.get('credit', {}).get('value_jo')
    if dep: d['dry_powder_jo'] = round(dep - FLOOR['deposit'], 1)
    if dep and cre: d['credit_ratio'] = round(cre / dep * 100, 1)

    # 경보
    al = []
    c = cur.get('credit', {})
    if c.get('chg_jo', 0) > 0.2:
        al.append({"level": "high", "text":
            "신용융자 {:+.2f}조 증가 — 하락장에 레버리지 확대. 반대매매 위험 축적.".format(c['chg_jo'])})
    elif c.get('chg_jo', 0) < -0.5:
        al.append({"level": "info", "text":
            "신용융자 {:+.2f}조 감소 — 반대매매·청산 진행 중. 항복 신호 후보.".format(c['chg_jo'])})
    dp = cur.get('deposit', {})
    if dp.get('chg_pct', 0) <= -2.0:
        al.append({"level": "mid", "text":
            "예탁금 {:+.1f}% — 자금 이탈 가속.".format(dp['chg_pct'])})
    ef = cur.get('equity_fund', {})
    if ef.get('chg_pct', 0) <= -5.0:
        al.append({"level": "mid", "text":
            "주식형펀드 {:+.1f}% — 평가손+환매. 투신 매도 압력.".format(ef['chg_pct'])})

    log = []
    try:
        with open(OUT, encoding='utf-8') as f: log = json.load(f).get("log", [])
    except (OSError, ValueError): pass
    stamp = cur.get('deposit', {}).get('date', now.strftime('%m/%d'))
    if not log or log[-1].get('date') != stamp:
        log.append({"date": stamp, "deposit": dep, "credit": cre,
                    "cma": cur.get('cma', {}).get('value_jo')})

    snap = {"ts_kst": now.strftime('%m-%d %H:%M'), "current": cur,
            "derived": d, "alerts": al, "log": log[-MAX:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print("funds: {} | 경보 {}건".format(snap['ts_kst'], len(al)))
    for k, v in cur.items():
        print("  {:<18} {:>8.1f}조  {:+.2f}조 ({:+.2f}%)  [{}]".format(
            v['label'], v['value_jo'], v['chg_jo'], v['chg_pct'], v['date']))
    for k, v in d.items():
        print("  [파생] {:<16} {}".format(k, v))
    for a in al:
        print("  ⚠️ [{}] {}".format(a['level'], a['text']))


if __name__ == "__main__":
    main()
