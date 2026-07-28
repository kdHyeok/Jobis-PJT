"""대화 오케스트레이터 (개선방안 §2 / agent_develop §3).

구성: intent(LLM 의도분류, 라벨만) → router(결정론 dispatch) → chat(실행·전달).
오케스트레이터는 판단하지 않는다 — 분류·호출·전달만 한다.
"""
