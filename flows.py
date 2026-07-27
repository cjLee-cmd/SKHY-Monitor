"""수급·베이시스 자동 갱신 — 로그인 세션 없이.

경로 2개:
  1) KRX 오픈API   → 선물/현물/미결제 → 베이시스 자동 산출
  2) KIS API(30일) → 투자자별 순매수 → 기존 379일에 신규분만 누적 병합

기존 krx_investors.json(379일, 브라우저 수집분)은 보존하고 뒤에 이어붙인다.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
KST = timezone(timedelta(hours=9))
INV = os.path.join(BASE, "docs", "data", "krx_investors.json")
EXT = os.path.join(BASE, "docs", "data", "krx_extra.json")

FIELDS = ['금융투자','보험','투신','사모','은행','기타금융','연기금',
          '기타법인','개인','외국인','기타외국인']
KIS_MAP = {  # KIS inquire-investor 필드 → 3분류만 제공
    '외국인': 'frgn_ntby_tr_pbmn',
    '기관':   'orgn_ntby_tr_pbmn',
    '개인':   'prsn_ntby_tr_pbmn',
}
STOCKS = {'samsung': '005930', 'hynix': '000660'}


def load(p, d):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return d


def krx_futures(bas_dd):
    """KRX 오픈API — 코스피200 선물 (베이시스 산출용)."""
    key = os.environ.get("KRX_AUTH_KEY")
    if not key:
        print("flows: KRX_AUTH_KEY 없음, 선물 생략"); return None
    url = "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd?basDd=" + bas_dd
    try:
        req = urllib.request.Request(url, headers={"AUTH_KEY": key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except Exception as e:
        print("flows: KRX 선물 실패", e); return None
    rows = next((d[k] for k in d if isinstance(d[k], list)), [])
    # 코스피200 선물 최근월물(야간 제외) 선택
    cand = [r for r in rows
            if r.get('PROD_NM') == '코스피200 선물' and '야간' not in str(r.get('ISU_NM',''))]
    if not cand: return None
    cand.sort(key=lambda r: str(r.get('ISU_NM','')))
    r = cand[0]
    def num(x):
        try: return float(str(x).replace(',', ''))
        except: return None
    fut, spot = num(r.get('TDD_CLSPRC')), num(r.get('SPOT_PRC'))
    if not (fut and spot): return None
    return {"date": bas_dd[:4]+"-"+bas_dd[4:6]+"-"+bas_dd[6:],
            "선물": fut, "현물": spot,
            "시장베이시스": round(fut - spot, 2),
            "미결제약정": num(r.get('ACC_OPNINT_QTY')),
            "종목": r.get('ISU_NM'), "src": "KRX-API"}


def kis_investor(code):
    """KIS — 투자자별 30일 (외국인/기관/개인 3분류)."""
    try:
        from fetch_prices import load_dotenv, kis_token, KIS_BASE
    except ImportError:
        print("flows: fetch_prices 임포트 실패"); return []
    load_dotenv()
    ak, sk = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not (ak and sk): return []
    try:
        tok = kis_token(ak, sk)
        q = "FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=" + code
        req = urllib.request.Request(
            KIS_BASE + "/uapi/domestic-stock/v1/quotations/inquire-investor?" + q,
            headers={"content-type": "application/json", "authorization": "Bearer " + tok,
                     "appkey": ak, "appsecret": sk, "tr_id": "FHKST01010900"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("output") or []
    except Exception as e:
        print("flows: KIS 실패", e); return []


def main():
    today = datetime.now(KST)
    inv = load(INV, {})
    ext = load(EXT, {})

    # ── 1) 투자자별 누적 병합 ──
    added = 0
    for name, code in STOCKS.items():
        rows = kis_investor(code)
        if not rows: continue
        have = {r['date'] for r in inv.get(name, [])}
        new = []
        for r in rows:
            d = r.get('stck_bsop_date', '')
            if len(d) != 8: continue
            dt = d[:4]+"-"+d[4:6]+"-"+d[6:]
            if dt in have: continue
            def n(k):
                try: return float(str(r.get(k, 0)).replace(',', ''))
                except: return 0.0
            rec = {k: 0.0 for k in FIELDS}
            rec['date'] = dt
            rec['외국인'] = n(KIS_MAP['외국인'])
            rec['개인']   = n(KIS_MAP['개인'])
            rec['금융투자'] = n(KIS_MAP['기관'])   # 기관 전체를 대표계정에 임시 배정
            rec['_src'] = 'KIS-3분류'             # 세분화 불가 표시
            new.append(rec)
        if new:
            inv.setdefault(name, []).extend(new)
            inv[name].sort(key=lambda x: x['date'])
            added += len(new)
            print("flows: {} 신규 {}일 (~{})".format(name, len(new), new[-1]['date']))

    if added:
        with open(INV, 'w', encoding='utf-8') as f:
            json.dump(inv, f, ensure_ascii=False)
        print("flows: 투자자별 누적 저장 (+{}일)".format(added))
    else:
        print("flows: 투자자별 신규 없음")

    # ── 2) 베이시스 갱신 ──
    for back in range(0, 5):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        f = krx_futures(d)
        if not f: continue
        arr = ext.setdefault('basis_kospi200', [])
        if any(x['date'] == f['date'] for x in arr):
            print("flows: 베이시스 {} 이미 있음".format(f['date'])); break
        arr.append(f)
        arr.sort(key=lambda x: x['date'])
        with open(EXT, 'w', encoding='utf-8') as fp:
            json.dump(ext, fp, ensure_ascii=False)
        print("flows: 베이시스 {} 추가 (선물 {} / 현물 {} / 베이시스 {:+.2f})".format(
            f['date'], f['선물'], f['현물'], f['시장베이시스']))
        break


if __name__ == "__main__":
    main()
