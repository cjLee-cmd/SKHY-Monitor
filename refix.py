import json, os, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_prices import load_dotenv, kis_token, http_json, KIS_BASE, RATIO, KST

load_dotenv()
ak, sk = os.environ['KIS_APP_KEY'], os.environ['KIS_APP_SECRET']
tok = kis_token(ak, sk)

url = (KIS_BASE + "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
       "?AUTH=&EXCD=BAQ&SYMB=SKHY&NMIN=5&PINC=1&NEXT=&NREC=120&FILL=&KEYB=")
res = http_json(url, headers={"content-type": "application/json",
    "authorization": "Bearer " + tok, "appkey": ak, "appsecret": sk,
    "tr_id": "HHDFS76950200"})
rows = res.get('output2') or []

chart = {}
for r in rows:
    d, t, last = r.get('xymd'), r.get('xhms'), r.get('last')
    if not (d and t and last):
        continue
    dt = datetime.strptime(d + t.zfill(6), "%Y%m%d%H%M%S").replace(
        tzinfo=timezone(timedelta(hours=-4)))
    chart[int(dt.timestamp())] = float(last)

ks = sorted(chart)
print('분봉 {}건 | 범위(KST): {} ~ {}'.format(len(chart),
    datetime.fromtimestamp(ks[0], KST).strftime('%m-%d %H:%M'),
    datetime.fromtimestamp(ks[-1], KST).strftime('%m-%d %H:%M')))
print()

hist = json.load(open('docs/data/history.json', encoding='utf-8'))
fixed = 0
for r in hist:
    if r.get('adr_source') != 'KIS/NAS':
        continue
    t = datetime.fromisoformat(r['ts']).astimezone(KST)
    hm = t.hour * 60 + t.minute
    if not (9 * 60 <= hm < 17 * 60):
        continue
    target = int(datetime.fromisoformat(r['ts']).timestamp())
    near = min(chart, key=lambda k: abs(k - target))
    if abs(near - target) > 400:
        print('  {} 분봉 없음(스킵)'.format(r['ts_kst']))
        continue
    new_adr = chart[near]
    parity = r['kr_price'] * RATIO / r['usdkrw']
    new_prem = (new_adr / parity - 1) * 100
    print('  {} | ADR ${:.2f} -> ${:.2f} | 프리미엄 {:+.2f}% -> {:+.2f}%'.format(
        r['ts_kst'], r['adr_price'], new_adr, r['premium_pct'], new_prem))
    r['adr_price'] = round(new_adr, 4)
    r['premium_pct'] = round(new_prem, 2)
    r['adr_session'] = 'daytime'
    r['adr_source'] = 'KIS/BAQ(refix)'
    fixed += 1

print('\n복구 {}건'.format(fixed))
if fixed:
    with open('docs/data/history.json', 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    print('✅ 적용 완료')
