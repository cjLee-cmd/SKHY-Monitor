import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_prices import load_dotenv, kis_token, KIS_BASE
load_dotenv()
ak=os.environ["KIS_APP_KEY"]; sk=os.environ["KIS_APP_SECRET"]
tok=kis_token(ak,sk)
H={"content-type":"application/json","authorization":"Bearer "+tok,"appkey":ak,"appsecret":sk}
def call(path,tr,params,label):
    q="&".join(f"{k}={v}" for k,v in params.items())
    try:
        req=urllib.request.Request(KIS_BASE+path+"?"+q, headers=dict(H,tr_id=tr))
        with urllib.request.urlopen(req,timeout=15) as r: d=json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  ❌ {label:<24} HTTP {e.code}"); return
    except Exception as e:
        print(f"  ❌ {label:<24} {type(e).__name__}"); return
    if d.get("rt_cd")!="0":
        print(f"  ❌ {label:<24} {d.get('msg1','')[:34]}"); return
    rows=None
    for k in ("output","output1","output2"):
        v=d.get(k)
        if isinstance(v,list) and v: rows=v; break
        if isinstance(v,dict) and v: rows=[v]; break
    print(f"  ✅ {label:<24} {len(rows) if rows else 0}건")
    if rows:
        r=rows[0]
        show={k:v for k,v in list(r.items())[:8]}
        print(f"     {show}")

print("KIS 채권/금리 데이터 탐색")
# 국내 채권 지수
call("/uapi/domestic-bond/v1/quotations/inquire-daily-itemchartprice","FHKBJ773401C0",
     {"FID_COND_MRKT_DIV_CODE":"B","FID_INPUT_ISCD":"KR103501GA34",
      "FID_INPUT_DATE_1":"20260701","FID_INPUT_DATE_2":"20260727","FID_PERIOD_DIV_CODE":"D"},"국고채 일봉")
# 금리 종합
call("/uapi/domestic-bond/v1/quotations/inquire-price","FHKBJ773400C0",
     {"FID_COND_MRKT_DIV_CODE":"B","FID_INPUT_ISCD":"KR103501GA34"},"국고채 현재가")
# 업종/지수 (금리지수)
for cd,lab in [("0001","코스피"),("5001","국고채지수?")]:
    call("/uapi/domestic-stock/v1/quotations/inquire-index-price","FHPUP02100000",
         {"FID_COND_MRKT_DIV_CODE":"U","FID_INPUT_ISCD":cd},f"지수 {lab}")
