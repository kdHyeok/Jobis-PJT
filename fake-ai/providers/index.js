'use strict';

const { createCodexProvider } = require('./codex');

const PROVIDER_ALIASES = new Map([
  ['claude', 'claude'],
  ['codex', 'codex'],
  ['gpt', 'codex'],
]);

function normalizeProvider(value) {
  const requested = String(value || 'claude').trim().toLowerCase();
  const normalized = PROVIDER_ALIASES.get(requested);
  if (!normalized) {
    throw new Error(
      `지원하지 않는 LLM_PROVIDER="${requested}". claude, codex 또는 gpt 중 하나를 사용하세요.`,
    );
  }
  return normalized;
}

/**
 * 기존 Claude 실행 함수를 그대로 주입받고, 선택이 Codex일 때만 새 HTTP provider를 만든다.
 * 이 계층 위의 프롬프트·큐·JSON 파싱·폴백 계약은 provider를 몰라도 된다.
 */
function createProvider({ runClaude, timeoutMs, env = process.env }) {
  if (typeof runClaude !== 'function') {
    throw new TypeError('runClaude 함수가 필요합니다.');
  }

  const name = normalizeProvider(env.LLM_PROVIDER);
  if (name === 'claude') {
    return { name, run: runClaude };
  }

  return createCodexProvider({ timeoutMs, env });
}

module.exports = { createProvider, normalizeProvider };
