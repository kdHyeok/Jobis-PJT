import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('career map routes into a scheduled learning plan and workspace', async () => {
  const [router, map, shell, plan, workspace] = await Promise.all([
    read('../src/router.ts'),
    read('../src/views/CareerMapView.vue'),
    read('../src/components/AppShell.vue'),
    read('../src/views/LearningPlanView.vue'),
    read('../src/views/LearningWorkspaceView.vue'),
  ])

  assert.match(router, /path:\s*["']learning-plan["']/)
  assert.match(router, /path:\s*["']learning\/:planId["']/)
  assert.match(shell, /학습 플랜/)
  assert.match(map, /학습 플랜에 등록/)
  assert.match(map, /일정 수정/)
  assert.match(plan, /학습 플랜 보기 방식/)
  assert.match(plan, /주간/)
  assert.match(plan, /월간/)
  assert.match(workspace, /LEARNING MEMORY/)
  assert.match(workspace, /JOBIS_LEARNING_SESSION/)
  assert.match(workspace, /sourceType/)
  assert.match(workspace, /accept="\.txt,\.md,text\/plain,text\/markdown"/)
  assert.match(workspace, /resourceMode === 'TEXT'/)
  assert.match(workspace, /학습 자료와 현재 범위를 확인하고 있어요/)
  assert.match(workspace, /다시 학습/)
  assert.match(workspace, /과제 제안/)
  assert.match(workspace, /퀴즈 시작/)
})

test('learning plan store retains schedule, progress, time, and memory contracts', async () => {
  const [store, sources] = await Promise.all([
    read('../src/learning-plan.ts'),
    read('../src/learning-sources.ts'),
  ])

  assert.match(store, /jobiss:learning-plan:v1/)
  assert.match(store, /startDate/)
  assert.match(store, /endDate/)
  assert.match(store, /spentMinutes/)
  assert.match(store, /resources/)
  assert.match(store, /completedCompetencyIds/)
  assert.match(store, /restart\(id/)
  assert.match(sources, /https:\/\/github\.com\/WeareSoft\/tech-interview/)
  assert.match(sources, /https:\/\/opentutorials\.org\//)
})

test('learning conversations are separated from normal career chat', async () => {
  const [store, shelf, chat, workspace] = await Promise.all([
    read('../src/learning-plan.ts'),
    read('../src/components/ConversationShelf.vue'),
    read('../src/views/ChatView.vue'),
    read('../src/views/LearningWorkspaceView.vue'),
  ])

  assert.match(store, /jobiss:learning-chats:v1/)
  assert.match(store, /forPlan\(planId/)
  assert.match(shelf, /status === "LEARNING"/)
  assert.match(shelf, /학습 채팅/)
  assert.match(chat, /conversationStatus === "LEARNING"/)
  assert.match(chat, /name: "learning"/)
  assert.match(workspace, /learningChats\.register/)
  assert.match(workspace, /learningChats\.forPlan/)
})

test('career map exposes focused preparation, learning, and safe branch customization', async () => {
  const [journeyMap, careerMap, theme] = await Promise.all([
    read('../src/components/JourneyMap.vue'),
    read('../src/views/CareerMapView.vue'),
    read('../src/styles/jobis-theme.css'),
  ])

  assert.match(journeyMap, /focus-journey__overview/)
  assert.match(journeyMap, /emit\('learn', node\)/)
  assert.match(journeyMap, /mode: 'REGENERATE'/)
  assert.match(journeyMap, /mode: 'EDIT'/)
  assert.match(careerMap, /action:\s*["']application_plan["']/)
  assert.match(careerMap, /현재 지도를 바로 덮어쓰지 말고 변경 초안을 만들어 미리보기로 보여줘/)
  assert.match(theme, /\.focus-track__flow/)
  assert.match(theme, /@media \(max-width:\s*720px\)/)
})
