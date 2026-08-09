<script setup lang="ts">
import { computed } from "vue";

type ProposalOperation = {
  operationId?: string;
  action?: string;
  nodeKind?: string;
  title?: string;
  canonicalKey?: string | null;
  targetRef?: string | null;
  scopeDefinition?: string | null;
  sectionKey?: string;
  sectionMemberships?: Array<{
    chapterTitle?: string;
  }>;
};

type ProposalRelation = {
  relationId?: string;
  fromOperationId?: string;
  toOperationId?: string;
  relationType?: string;
  reason?: string;
};

const props = defineProps<{
  operations: ProposalOperation[];
  relations: ProposalRelation[];
}>();

const NODE_WIDTH = 232;
const NODE_HEIGHT = 104;
const COLUMN_GAP = 92;
const ROW_GAP = 22;
const PADDING = 28;

const blockingRelationTypes = new Set([
  "HARD_PREREQUISITE",
  "CONDITIONAL_PREREQUISITE",
  "UNLOCKS_PROJECT",
  "REQUIRES_GATE",
  "UNLOCKS_OPPORTUNITY",
  "CAREER_STAGE_ORDER",
  "STARTS_EXPERIENCE",
  "SATISFIES_EXPERIENCE_GATE",
]);

const graph = computed(() => {
  const operations = props.operations.filter((item) => item.operationId);
  const operationById = new Map(
    operations.map((item) => [item.operationId as string, item] as const),
  );
  const relations = props.relations.filter(
    (item) =>
      item.fromOperationId &&
      item.toOperationId &&
      operationById.has(item.fromOperationId) &&
      operationById.has(item.toOperationId),
  );
  const incoming = new Map<string, Set<string>>();
  const outgoing = new Map<string, Set<string>>();
  const ranks = new Map<string, number>();
  for (const operation of operations) {
    const id = operation.operationId as string;
    incoming.set(id, new Set());
    outgoing.set(id, new Set());
    ranks.set(id, 0);
  }
  for (const relation of relations) {
    if (!blockingRelationTypes.has(relation.relationType ?? "")) continue;
    const from = relation.fromOperationId as string;
    const to = relation.toOperationId as string;
    incoming.get(to)?.add(from);
    outgoing.get(from)?.add(to);
  }

  const ready = [...incoming.entries()]
    .filter(([, values]) => values.size === 0)
    .map(([id]) => id)
    .sort();
  const visited = new Set<string>();
  while (ready.length) {
    const id = ready.shift() as string;
    if (visited.has(id)) continue;
    visited.add(id);
    for (const target of [...(outgoing.get(id) ?? [])].sort()) {
      ranks.set(target, Math.max(ranks.get(target) ?? 0, (ranks.get(id) ?? 0) + 1));
      incoming.get(target)?.delete(id);
      if (incoming.get(target)?.size === 0) ready.push(target);
    }
    ready.sort();
  }

  const columns = new Map<number, ProposalOperation[]>();
  for (const operation of operations) {
    const rank = ranks.get(operation.operationId as string) ?? 0;
    const column = columns.get(rank) ?? [];
    column.push(operation);
    columns.set(rank, column);
  }
  for (const column of columns.values()) {
    column.sort((left, right) =>
      `${left.nodeKind}:${left.title}`.localeCompare(`${right.nodeKind}:${right.title}`, "ko"),
    );
  }

  const positioned = operations.map((operation) => {
    const rank = ranks.get(operation.operationId as string) ?? 0;
    const column = columns.get(rank) ?? [];
    const row = column.indexOf(operation);
    return {
      ...operation,
      id: operation.operationId as string,
      x: PADDING + rank * (NODE_WIDTH + COLUMN_GAP),
      y: PADDING + row * (NODE_HEIGHT + ROW_GAP),
      rank,
    };
  });
  const positionById = new Map(positioned.map((item) => [item.id, item] as const));
  const maxRank = Math.max(0, ...positioned.map((item) => item.rank));
  const maxRows = Math.max(1, ...[...columns.values()].map((items) => items.length));
  return {
    nodes: positioned,
    edges: relations.map((relation) => ({
      ...relation,
      from: positionById.get(relation.fromOperationId as string)!,
      to: positionById.get(relation.toOperationId as string)!,
      blocking: blockingRelationTypes.has(relation.relationType ?? ""),
    })),
    width: PADDING * 2 + (maxRank + 1) * NODE_WIDTH + maxRank * COLUMN_GAP,
    height: PADDING * 2 + maxRows * NODE_HEIGHT + (maxRows - 1) * ROW_GAP,
  };
});

function edgePath(edge: (typeof graph.value.edges)[number]) {
  const fromX = edge.from.x + NODE_WIDTH;
  const fromY = edge.from.y + NODE_HEIGHT / 2;
  const toX = edge.to.x;
  const toY = edge.to.y + NODE_HEIGHT / 2;
  const bend = Math.max(34, Math.abs(toX - fromX) * 0.42);
  return `M ${fromX} ${fromY} C ${fromX + bend} ${fromY}, ${toX - bend} ${toY}, ${toX} ${toY}`;
}

function nodeTitle(operation: ProposalOperation) {
  return operation.title ?? operation.canonicalKey ?? operation.targetRef ?? "이름 없는 단계";
}

function nodeMeta(operation: ProposalOperation) {
  return operation.sectionMemberships?.[0]?.chapterTitle
    ?? operation.sectionKey
    ?? operation.nodeKind
    ?? "로드맵 단계";
}

function actionLabel(action?: string) {
  return action === "REUSE_NODE" ? "기존 단계" : "새 단계";
}
</script>

<template>
  <div class="roadmap-proposal-graph">
    <div class="roadmap-proposal-graph__summary">
      <span><strong>{{ graph.nodes.length }}</strong>개 단계</span>
      <span><strong>{{ graph.edges.length }}</strong>개 연결</span>
      <span class="roadmap-proposal-graph__legend roadmap-proposal-graph__legend--solid">필수 순서</span>
      <span class="roadmap-proposal-graph__legend roadmap-proposal-graph__legend--dashed">추천·보조 연결</span>
    </div>
    <div
      v-if="graph.nodes.length"
      class="roadmap-proposal-graph__viewport"
      role="img"
      :aria-label="`로드맵 초안 ${graph.nodes.length}개 단계와 ${graph.edges.length}개 관계 그래프`"
    >
      <svg
        class="roadmap-proposal-graph__canvas"
        :width="graph.width"
        :height="graph.height"
        :viewBox="`0 0 ${graph.width} ${graph.height}`"
      >
        <defs>
          <marker id="proposal-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
        </defs>
        <g class="roadmap-proposal-graph__edges">
          <path
            v-for="(edge, index) in graph.edges"
            :key="edge.relationId ?? `${edge.fromOperationId}:${edge.toOperationId}:${index}`"
            :d="edgePath(edge)"
            :class="{ 'is-supporting': !edge.blocking }"
            marker-end="url(#proposal-arrow)"
          >
            <title>{{ edge.relationType }} · {{ edge.reason }}</title>
          </path>
        </g>
        <foreignObject
          v-for="node in graph.nodes"
          :key="node.id"
          :x="node.x"
          :y="node.y"
          :width="NODE_WIDTH"
          :height="NODE_HEIGHT"
        >
          <article class="roadmap-proposal-graph__node" :class="`is-${(node.nodeKind ?? 'unknown').toLowerCase()}`">
            <div>
              <span>{{ actionLabel(node.action) }}</span>
              <small>{{ nodeMeta(node) }}</small>
            </div>
            <strong>{{ nodeTitle(node) }}</strong>
            <p>{{ node.scopeDefinition ?? node.nodeKind ?? "관계 그래프에 포함된 단계입니다." }}</p>
          </article>
        </foreignObject>
      </svg>
    </div>
    <p v-else class="roadmap-proposal-graph__empty">표시할 로드맵 단계가 없습니다.</p>
  </div>
</template>

<style scoped>
.roadmap-proposal-graph {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.roadmap-proposal-graph__summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  color: #5a6373;
  font-size: 12px;
}

.roadmap-proposal-graph__summary strong {
  color: #172033;
}

.roadmap-proposal-graph__legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.roadmap-proposal-graph__legend::before {
  width: 22px;
  border-top: 2px solid #2489c5;
  content: "";
}

.roadmap-proposal-graph__legend--dashed::before {
  border-top-style: dashed;
  border-top-color: #9b7ad8;
}

.roadmap-proposal-graph__viewport {
  overflow: auto;
  max-height: 640px;
  border: 1px solid #d8e4ed;
  border-radius: 18px;
  background:
    radial-gradient(circle at 1px 1px, rgba(48, 121, 166, 0.13) 1px, transparent 0) 0 0 / 18px 18px,
    #f8fbfd;
}

.roadmap-proposal-graph__canvas {
  display: block;
  min-width: 100%;
}

.roadmap-proposal-graph__edges path {
  fill: none;
  stroke: #2489c5;
  stroke-width: 2;
  opacity: 0.72;
}

.roadmap-proposal-graph__edges path.is-supporting {
  stroke: #9b7ad8;
  stroke-dasharray: 7 6;
  opacity: 0.55;
}

.roadmap-proposal-graph__edges marker path {
  fill: #2489c5;
}

.roadmap-proposal-graph__node {
  box-sizing: border-box;
  display: grid;
  align-content: start;
  width: 100%;
  height: 100%;
  gap: 7px;
  overflow: hidden;
  padding: 12px 14px;
  border: 1px solid #b9d6e7;
  border-radius: 15px;
  background: #fff;
  box-shadow: 0 5px 0 rgba(31, 91, 127, 0.1);
  color: #172033;
}

.roadmap-proposal-graph__node > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.roadmap-proposal-graph__node span {
  padding: 3px 7px;
  border-radius: 999px;
  background: #e8f5fc;
  color: #096da8;
  font-size: 9px;
  font-weight: 800;
}

.roadmap-proposal-graph__node small {
  overflow: hidden;
  color: #7b8493;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.roadmap-proposal-graph__node strong {
  overflow: hidden;
  font-size: 13px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.roadmap-proposal-graph__node p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: #626b78;
  font-size: 10px;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.roadmap-proposal-graph__node.is-target_project {
  border-color: #8f75c6;
  background: #fbf8ff;
}

.roadmap-proposal-graph__node.is-career_gate {
  border-color: #e2ad59;
  background: #fffaf0;
}

.roadmap-proposal-graph__node.is-opportunity {
  border-color: #4bb98b;
  background: #f2fcf8;
}

.roadmap-proposal-graph__empty {
  margin: 0;
  padding: 18px;
  border: 1px dashed #c9d5de;
  border-radius: 14px;
  color: #727b88;
  text-align: center;
}
</style>
