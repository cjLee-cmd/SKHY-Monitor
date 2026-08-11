# 데이터 출처 명세

> 최종 갱신: 2026-07-27 · SKHY-Monitor

## 1. 자동 수집 (10분 주기, GitHub Actions)

| 데이터 | 출처 | 인증 | 산출 파일 | 갱신 |
|---|---|---|---|---|
| 한국 본주 (000660) | 네이버 실시간 API → Yahoo 폴백 | 불필요 | `history.json` | 10분 |
| 삼성전자 (005930) | 동일 | 불필요 | `history.json` | 10분 |
| 미국 ADR (SKHY) | KIS `inquire-price` (EXCD=BAQ/NAS) | `KIS_APP_KEY/SECRET` | `history.json` | 10분 |
| USD/KRW | Yahoo `KRW=X` | 불필요 | `history.json` | 10분 |
| **투자자별 11분류** | **KIS `foreign-institution-total`** | `KIS_APP_KEY/SECRET` | `krx_investors.json` | 일 1회 |
| **코스피200 선물·베이시스** | **KRX 오픈API `drv/fut_bydd_trd`** | `KRX_AUTH_KEY` | `krx_extra.json` | 일 1회 |
| **미 국채 10/30/5년** | Yahoo `^TNX` `^TYX` `^FVX` | 불필요 | `bonds.json` | 10분 |
| **한국 국고채 (ETF 프록시)** | Yahoo `148070.KS` `114820.KS` | 불필요 | `bonds.json` | 10분 |
| **달러/엔, 달러/원** | Yahoo `JPY=X` `KRW=X` | 불필요 | `bonds.json` | 10분 |
| **해외지수** S&P500·나스닥·SOX | Yahoo `^GSPC` `^IXIC` `^SOX` | 불필요 | `market.json` | 10분 |
| **국내지수** 코스피·코스닥 | Yahoo `^KS11` `^KQ11` | 불필요 | `market.json` | 10분 |
| **변동성** VIX | Yahoo `^VIX` | 불필요 | `market.json` | 10분 |
| **원자재** 유가·금·구리 | Yahoo `CL=F` `GC=F` `HG=F` | 불필요 | `market.json` | 10분 |
| **반도체 Peer** 마이크론·TSMC·엔비디아 | Yahoo `MU` `TSM` `NVDA` | 불필요 | `market.json` | 10분 |

### KIS 투자자별 필드 매핑

| KIS 필드 | KRX 분류 | 담당 에이전트 |
|---|---|---|
| `frgn_ntby_tr_pbmn` | 외국인 | F-ACTIVE |
| `ivtr_ntby_tr_pbmn` | 금융투자 | I-DEALER |
| `fund_ntby_tr_pbmn` | 투신 | I-FUND |
| `etc_orgt_ntby_tr_pbmn` | 연기금 등 | I-PENSION |
| `insu_ntby_tr_pbmn` | 보험 | I-MINOR |
| `bank_ntby_tr_pbmn` | 은행 | I-MINOR |
| `mrbn_ntby_tr_pbmn` | 기타금융 | I-MINOR |
| `etc_corp_ntby_tr_pbmn` | 기타법인 | C-BUYBACK |
| (역산: −Σ나머지) | 개인 | R-RETAIL |

**주의**
- `FID_RANK_SORT_CLS_CODE=1` 필수 (0이면 삼성·하이닉스 미포함)
- **단위는 백만원** → ×1,000,000 변환 필요
- 상위 30종목만 반환

## 2. 반자동 (브라우저 세션 필요)

| 데이터 | 출처 | 조건 | 파일 |
|---|---|---|---|
| 과거 수급 379일 | `data.krx.co.kr` `MDCSTAT02303` | KRX 로그인 | `krx_investors.json` (정적) |
| 공매도 379일 | `MDCSTAT30001` | 〃 | `krx_extra.json` (정적) |
| 베이시스 379일 | `MDCSTAT13401` | 〃 | 〃 |
| 프로그램매매 19개월 | `MDCSTAT02601` | 〃 | 〃 |
| 레버리지 ETF 16종 | `MDCSTAT04301/04501/04705` | 〃 | 미저장 |

**갱신 방법**: 브라우저에서 `data.krx.co.kr` 로그인 후 DOM에서 `fetch()` 직접 호출.
신규 데이터는 자동 경로(1번)로 누적되므로 정적 파일 재수집은 불필요.

## 3. 참조 (수동 확인)

| 데이터 | 출처 | 용도 |
|---|---|---|
| 투자자예탁금·신용융자 | 금융투자협회 FreeSIS | R-RETAIL 여력 판정 |
| 미 10년물·유가·엔/원 | Yahoo Finance | 매크로 |
| S&P500 선물 (ES) | Yahoo `ES=F` | 개장가 산출 |
| 공시(자사주·실적) | DART, 뉴스 | C-BUYBACK 검증 |

## 4. 인증 키

`.env` (gitignore) 및 GitHub Secrets에 동일 등록.

```
KIS_APP_KEY, KIS_APP_SECRET     한국투자증권
KRX_AUTH_KEY                    KRX Data Marketplace
KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN, NTFY_TOPIC   알림
```

## 6. 실시간 투자자 수급 ⭐ (2026-08-11 확보)

HTS의 별표(*) 수치와 동일한 **장중 실시간** 추정 순매수. 마감을 기다릴 필요가 없다.

| 항목 | 값 |
|---|---|
| path | `/uapi/domestic-stock/v1/quotations/investor-trend-estimate` |
| **tr_id** | **`HHPTJ04160200`** |
| **파라미터** | **`MKSC_SHRN_ISCD=005930`** |
| 산출 파일 | `realtime_flow.json` |

**응답 필드**

| 필드 | 의미 |
|---|---|
| `bsop_hour_gb` | 시간대 구분 |
| `frgn_fake_ntby_qty` | 외국인 추정 순매수 |
| `orgn_fake_ntby_qty` | 기관 추정 순매수 |
| `sum_fake_ntby_qty` | 합계 → **개인 = −합계** (역산) |

### ⚠️ 반드시 지킬 것

- **토큰 캐시 필수** — 발급 1분 1회 제한. `.kistoken`에 저장해 재사용하지 않으면 **403**
- 값은 **추정치** — 마감 확정치와 오차 있음
- 개인은 직접 제공 안 됨 → 수급 항등식으로 역산

### ❌ 실패한 경로 (재시도 금지)

| 경로 | 실패 이유 |
|---|---|
| `inquire-investor` | 장중 전부 **0** |
| `foreign-institution-total` | 상위 30 랭킹 — 종목 **조용히 누락** |
| `FHPTJ04160200` / `FHKST644400C0` | 없는 코드 / 파라미터 불일치 |
| `FID_INPUT_ISCD` 파라미터 | `MKSC_SHRN_ISCD`만 작동 |
| 네이버·KRX 웹 | CORS·로그인 차단, 샌드박스 403 |


## 5. 검증 규칙

- **수급 항등식**: Σ(11분류) = 0 (±1e6). 위반 시 검증 에이전트가 기각.
- **단위**: 모든 수급은 **원** 단위 저장. 표시할 때만 조원 환산.
- **출처 표시**: 신규 레코드에 `_src` 필드로 수집 경로 기록.
