"""웹 브릿지 — 웹(Spring 백엔드 + static UI)이 이미 쓰는 계약 그대로 진짜 에이전트를 물린다.

기존 구성은 웹백엔드 → fake-ai(node, :8000) 였다. 이 패키지는 그 자리에 그대로 들어가는
FastAPI 서버다. 웹의 UI·DB·백엔드 코드는 한 줄도 바꾸지 않는다:

    chat.html ─STOMP─ Spring(FakeAgentClient) ─WS :8000─ webbridge ─→ jobis_ai(오케스트레이터·판정 그래프)

계약(메시지 형태)은 protocol.py, 판정 결과 → 웹 리포트 변환은 adapter.py 에 모여 있다.
"""
