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
# KIS foreign-institution-total → KRX 11분류 완전 대응
KIS_MAP = {
    '금융투자':   'ivtr_ntby_tr_pbmn',
    '보험':      'insu_ntby_tr_pbmn',
    '투신':      'fund_ntby_tr_pbmn',
    '은행':      'bank_ntby_tr_pbmn',
    '기타금융':   'mrbn_ntby_tr_pbmn',
    '연기금':     'etc_orgt_ntby_tr_pbmn',
    '기타법인':   'etc_corp_ntby_tr_pbmn',
    '외국인':     'frgn_ntby_tr_pbmn',
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


def kis_detail():
    """KIS foreign-institution-total — 기관 7분류 + 외국인 + 기타법인 (당일)."""
    try:
        from fetch_prices import load_dotenv, kis_token, KIS_BASE
    except ImportError:
        return {}
    load_dotenv()
    ak, sk = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not (ak and sk): return {}
    try:
        tok = kis_token(ak, sk)
        q = ("FID_COND_MRKT_DIV_CODE=V&FID_COND_SCR_DIV_CODE=16449&FID_INPUT_ISCD=0000"
             "&FID_DIV_CLS_CODE=0&FID_RANK_SORT_CLS_CODE=1&FID_ETC_CLS_CODE=0")
        req = urllib.request.Request(
            KIS_BASE + "/uapi/domestic-stock/v1/quotations/foreign-institution-total?" + q,
            headers={"content-type": "application/json", "authorization": "Bearer " + tok,
                     "appkey": ak, "appsecret": sk, "tr_id": "FHPTJ04400000"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rows = json.load(r).get("output") or []
    except Exception as e:
        print("flows: KIS 상세 실패", e); return {}
    out = {}
    for r in rows:
        code = str(r.get('mksc_shrn_iscd', '')).strip()
        for name, c in STOCKS.items():
            if code == c: out[name] = r
    return out


def kis_investor(code):
    """폴백 — 3분류만 (상세 실패 시)."""
    try:
        from fetch_prices import load_dotenv, kis_token, KIS_BASE
    except ImportError:
        return []
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
    except Exception:
        return []


def main():
    today = datetime.now(KST)
    inv = load(INV, {})
    ext = load(EXT, {})

    # ── 1) 투자자별 누적 병합 (11분류 상세) ──
    detail = kis_detail()
    today_str = today.strftime('%Y-%m-%d')
    added = 0
    for name, code in STOCKS.items():
        have = {r['date'] for r in inv.get(name, [])}
        if today_str in have:
            continue
        d = detail.get(name)
        if not d:
            continue
        def n(k):
            try: return float(str(d.get(k, 0)).replace(',', ''))
            except: return 0.0
        rec = {k: 0.0 for k in FIELDS}
        rec['date'] = today_str
        for kr, kis in KIS_MAP.items():
            rec[kr] = n(kis) * 1000000   # KIS 단위: 백만원 → 원
        # 개인 = -(나머지 합)  ← 수급 항등식으로 역산
        rec['개인'] = -sum(rec[k] for k in FIELDS if k != '개인')
        rec['_src'] = 'KIS-11분류'
        inv.setdefault(name, []).append(rec)
        inv[name].sort(key=lambda x: x['date'])
        added += 1
        print("flows: {} {} 추가 (외국인 {:+.2f}조 / 금융투자 {:+.2f}조 / 개인 {:+.2f}조)".format(
            name, today_str, rec['외국인']/1e12, rec['금융투자']/1e12, rec['개인']/1e12))

    if added:
        with open(INV, 'w', encoding='utf-8') as f:
            json.dump(inv, f, ensure_ascii=False)
        print("flows: 투자자별 저장 (+{}일, 11분류)".format(added))
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
