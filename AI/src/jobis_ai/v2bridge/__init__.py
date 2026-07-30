"""서비스 v2 백엔드(feat/be/jobiss-service-v2) ↔ 판정 엔진 브릿지.

  · models.py  — HTTP 계약 스키마 (정본: 팀 저장소 ai-server/app/models.py 의 사본)
  · mapping.py — 엔진 산출물 → 계약 변환 (판단 없음, 결정론)
  · service.py — 엔진 호출 어댑터 (세션 구성·되묻기 자동 응답·실패 전파)
  · app.py     — FastAPI 앱 (인증·오류 코드는 팀 ai-server 와 동일)

계약·운영 문서: docs/v2bridge.md
"""
