"""ntfy 알림 테스트. 토픽은 .env 또는 환경변수에서 읽는다(출력하지 않음).

사용: python3 test_ntfy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_prices import load_dotenv
from signal_engine import ntfy_send

load_dotenv()
if not os.environ.get("NTFY_TOPIC"):
    print("NTFY_TOPIC 이 없습니다. .env 에 추가하세요.")
    sys.exit(1)

ok = ntfy_send(
    "SKHY 매수 신호 (테스트)",
    "프리미엄 30.52%  (밴드 30% 돌파)\n"
    "한국 1,837,000원  /  ADR $160.24\n"
    "07-14 10:00 KST\n"
    "※ 실제 알림이 아니라 연결 테스트입니다.",
    True,
)
print("✅ 발송 성공 — 아이폰/맥을 확인하세요." if ok else "❌ 발송 실패")
