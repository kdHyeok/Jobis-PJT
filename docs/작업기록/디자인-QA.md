# Career map to learning flow design QA

- Source: JOBIS learning-plan Figma wireframes supplied by the user.
- Implementation: `http://localhost:8088/app/map`, `/app/learning-plan`, and `/app/learning/:planId`.
- Compared in one pass: source canvas capture and live 8088 learning-memory drawer capture under `artifacts/design-qa/`.

## Flow checks

- Career-map competency drawer exposes estimated time and schedule registration.
- Saving a schedule changes the same drawer to show the selected period and `일정 수정`.
- Weekly and monthly learning-plan views are available.
- A dated learning item opens the learning workspace.
- The learning workspace uses the existing chat job API for scoped questions, assignments, and one-question-at-a-time quizzes.
- Completion immediately updates the matching roadmap competency in the same browser, with `다시 학습` and learning-source regeneration controls.
- Provisional and catalog-review-pending capabilities are excluded from the actionable roadmap projection.

## Visual and responsive checks

- Drawer hierarchy, dimmed backdrop, outlined cards, blue primary action, and compact resource rows match the wireframe direction.
- Existing JOBIS sidebar and topbar remain intact across the new routes.
- At desktop width, the collapsible syllabus and large chat workspace do not overlap.
- Weekly calendar entries use stable subject colors so separate topics remain distinguishable.
- At narrow widths, calendar columns scroll rather than compressing text into unreadable cards.
- Browser console produced no errors or warnings during the tested flow.
- The conversation shelf now separates normal career conversations under `진행 중` from learning-only conversations under `학습 채팅`.
- Existing learning conversations are recognized from their learning-session marker, while newly created sessions are registered to their learning-plan item and reopen that workspace.
- Learning chat rows display the subject title instead of the internal session marker.

## Known contract boundary

Schedule, elapsed-time, completion, and resource-memory state use browser local storage because the backend currently exposes learning-guide generation but no learning-plan persistence API. The map reads the same local completion overlay; cross-device persistence remains outside this frontend-only contract.

final result: passed
