# SKHY-Monitor

SK하이닉스 한국 본주(000660)와 미국 ADR(SKHY)의 **가격 괴리(ADR 프리미엄)** 를
GitHub Actions로 10분마다 자동 수집합니다. 내 PC가 꺼져 있어도 GitHub 서버에서 계속 돕니다.

## 계산식

```
패리티(한국 환산가, USD) = 본주가(KRW) × 0.1 ÷ USD/KRW
프리미엄(%)            = ADR 가격 ÷ 패리티 − 1
```

ADR 1주 = 보통주 0.1주입니다.

## 구성

| 경로 | 역할 |
|---|---|
| `fetch_prices.py` | Yahoo Finance에서 본주·ADR·환율 수집 → JSON 누적 |
| `.github/workflows/collect.yml` | 10분 cron + 자동 커밋 |
| `docs/index.html` | 대시보드 (GitHub Pages) |
| `docs/data/history.json` | 누적 데이터 (최근 30일치) |

## 설정

1. **Actions**: 레포 Actions 탭 → `Collect SK Hynix prices` → `Run workflow`로 수동 테스트
2. **Pages**: Settings → Pages → Source `Deploy from a branch`, Branch `main` / `/docs` → Save

## 주의

- **Private 레포는 Actions 무료 한도가 월 2,000분**입니다. 10분 주기 ≈ 월 4,300분 이므로
  한도를 초과합니다. Public으로 전환하면 Actions와 Pages 모두 무제한 무료입니다.
- Public 전환이 어려우면 cron을 `*/30`으로 늘리세요(월 약 1,440분).
- 60일간 커밋이 없으면 GitHub가 스케줄을 자동 중지합니다.
- 무료 러너 특성상 cron은 정확히 10분이 아니라 5~15분 사이로 흔들릴 수 있습니다.

시세는 지연될 수 있으며, 본 레포는 참고용입니다. 투자 판단의 근거로 사용하지 마세요.
