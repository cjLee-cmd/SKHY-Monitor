"""에이전트 개별 피드백 — 알고리즘 수정 없이 컨텍스트만 갱신한다.

사용:
  python3 feedback.py list
  python3 feedback.py show R-RETAIL
  python3 feedback.py confirm R-RETAIL "당일동행 -0.61 재측정" --n 378
  python3 feedback.py refute  F-PASSIVE "코스피 -20%인데 순매도 지속"
  python3 feedback.py param   I-DEALER 베이시스상관_전체 0.21 --src KRX --n 400
  python3 feedback.py ask     C-BUYBACK "90조 집행 공시 확인 필요"
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
KST=timezone(timedelta(hours=9))
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'agents')

def path(aid):
    for sub in ('market','meta'):
        p=os.path.join(BASE,sub,aid+'.json')
        if os.path.exists(p): return p
    return None

def load(aid):
    p=path(aid)
    if not p: print(f"없는 에이전트: {aid}"); sys.exit(1)
    return json.load(open(p,encoding='utf-8')), p

def save(a,p):
    a['version']=a.get('version',1)+1
    a['updated']=datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    json.dump(a,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=1)

def log(a,kind,note,extra=None):
    e={"at":datetime.now(KST).strftime('%Y-%m-%d %H:%M'),"kind":kind,"note":note}
    if extra: e.update(extra)
    a.setdefault('revisions',[]).append(e)

def recalc(a):
    """신뢰도 = (confirmed+1)/(confirmed+refuted+2)  — 라플라스 보정"""
    sc=a.get('scorecard',{})
    c,r=sc.get('confirmed',0),sc.get('refuted',0)
    a['confidence']=round((c+1)/(c+r+2),3)

def main():
    if len(sys.argv)<2: print(__doc__); return
    cmd=sys.argv[1]

    if cmd=='list':
        rows=[]
        for sub in ('market','meta'):
            d=os.path.join(BASE,sub)
            for f in sorted(os.listdir(d)):
                a=json.load(open(os.path.join(d,f),encoding='utf-8'))
                rows.append((sub,a))
        print(f"{'ID':<12}{'이름':<14}{'신뢰도':>7}{'검증':>10}{'ver':>5}{'미해결':>7}")
        print("-"*60)
        for sub,a in rows:
            sc=a.get('scorecard',{})
            conf=a.get('confidence')
            cf=f"{conf:.2f}" if conf is not None else "—"
            v=f"{sc.get('confirmed',0)}/{sc.get('refuted',0)}" if sc else "—"
            print(f"{a['id']:<12}{a['name']:<14}{cf:>7}{v:>10}{a.get('version',1):>5}"
                  f"{len(a.get('open_questions',[])):>7}")
        return

    if cmd=='show':
        a,_=load(sys.argv[2])
        print(json.dumps(a,ensure_ascii=False,indent=1))
        return

    aid=sys.argv[2]; a,p=load(aid)

    if cmd in ('confirm','refute'):
        note=sys.argv[3] if len(sys.argv)>3 else ''
        sc=a.setdefault('scorecard',{"confirmed":0,"refuted":0,"pending":0})
        sc['confirmed' if cmd=='confirm' else 'refuted'] += 1
        log(a,cmd,note)
        recalc(a)
        save(a,p)
        st="⚠️ 재검토 필요" if a['confidence']<0.4 else "정상"
        print(f"{aid}: {cmd} 기록 | 신뢰도 {a['confidence']:.3f} ({st}) | v{a['version']}")

    elif cmd=='param':
        key,val=sys.argv[3],sys.argv[4]
        try: val=float(val)
        except: pass
        ex={}
        for i,t in enumerate(sys.argv):
            if t=='--src': ex['src']=sys.argv[i+1]
            if t=='--n': ex['n']=int(sys.argv[i+1])
        old=a['parameters'].get(key)
        a['parameters'][key]=dict({"v":val},**ex)
        log(a,'param',f"{key}: {old} → {val}")
        save(a,p)
        print(f"{aid}.{key} 갱신 | v{a['version']}")

    elif cmd=='ask':
        q=sys.argv[3]
        a.setdefault('open_questions',[]).append(q)
        log(a,'ask',q)
        save(a,p)
        print(f"{aid} 미해결 추가: {q}")

    else:
        print(__doc__)

if __name__=='__main__': main()
