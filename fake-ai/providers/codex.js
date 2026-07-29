'use strict';

const http = require('http');
const https = require('https');
const { createCodexSidecar } = require('./codex-sidecar');

const DEFAULT_BASE_URL = 'http://127.0.0.1:8001';
const DEFAULT_MODEL = 'gpt-5.4';
const DEFAULT_REASONING_EFFORT = 'medium';
const MAX_RESPONSE_BYTES = 10 * 1024 * 1024;
const REASONING_EFFORTS = new Set([
  'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra',
]);

function positiveNumber(value, fallback, name) {
  const parsed = value === undefined || value === '' ? fallback : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name}은(는) 0보다 큰 숫자여야 합니다.`);
  }
  return parsed;
}

function chatCompletionsUrl(rawBaseUrl) {
  let base;
  try {
    base = new URL(String(rawBaseUrl || DEFAULT_BASE_URL));
  } catch (_) {
    throw new Error('CODEX_BASE_URL이 올바른 URL이 아닙니다.');
  }
  if (!['http:', 'https:'].includes(base.protocol)) {
    throw new Error('CODEX_BASE_URL은 http:// 또는 https:// URL이어야 합니다.');
  }

  const root = base.pathname.replace(/\/+$/, '');
  base.pathname = root.endsWith('/v1')
    ? `${root}/chat/completions`
    : `${root}/v1/chat/completions`;
  base.search = '';
  base.hash = '';
  return base;
}

function errorMessage(body, statusCode) {
  try {
    const parsed = JSON.parse(body);
    return String(parsed?.error?.message || parsed?.message || `HTTP ${statusCode}`);
  } catch (_) {
    return `HTTP ${statusCode}`;
  }
}

/**
 * 로컬 codex-openai-server에 OpenAI Chat Completions 계약으로 요청한다.
 * OAuth·토큰 갱신·Responses SSE 처리는 참조 adapter가 담당하고, 여기서는 모델과
 * reasoning effort를 호출별 설정으로 전달한 뒤 최종 텍스트만 돌려준다.
 */
function createCodexProvider({
  timeoutMs,
  env = process.env,
  sidecarFactory = createCodexSidecar,
}) {
  const endpoint = chatCompletionsUrl(env.CODEX_BASE_URL);
  const model = String(env.CODEX_MODEL || DEFAULT_MODEL).trim();
  if (!model) throw new Error('CODEX_MODEL은 비어 있을 수 없습니다.');

  const reasoningEffort = String(
    env.CODEX_REASONING_EFFORT || DEFAULT_REASONING_EFFORT,
  ).trim().toLowerCase();
  if (!REASONING_EFFORTS.has(reasoningEffort)) {
    throw new Error(
      `지원하지 않는 CODEX_REASONING_EFFORT="${reasoningEffort}". `
      + 'minimal, low, medium, high, xhigh, max, ultra 중 하나를 사용하세요.',
    );
  }

  const requestTimeoutMs = positiveNumber(
    env.CODEX_TIMEOUT_MS,
    positiveNumber(timeoutMs, 200000, 'LLM_TIMEOUT_MS'),
    'CODEX_TIMEOUT_MS',
  );
  const sidecar = sidecarFactory({ endpoint, env });
  // node server.js 시작과 함께 준비를 시작하고, 첫 모델 요청은 준비 완료까지 기다린다.
  sidecar.ensureReady();

  async function run(prompt) {
    if (!await sidecar.ensureReady()) {
      console.log('  [LLM:codex] sidecar를 준비하지 못해 기존 폴백으로 전환합니다.');
      return null;
    }
    const payload = JSON.stringify({
      model,
      messages: [{ role: 'user', content: String(prompt || '') }],
      reasoning_effort: reasoningEffort,
      timeout: requestTimeoutMs / 1000,
      stream: false,
    });

    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      const transport = endpoint.protocol === 'https:' ? https : http;
      const request = transport.request(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Content-Length': Buffer.byteLength(payload),
        },
      }, (response) => {
        response.setEncoding('utf8');
        let body = '';
        let size = 0;
        response.on('data', (chunk) => {
          size += Buffer.byteLength(chunk);
          if (size > MAX_RESPONSE_BYTES) {
            response.destroy(new Error('Codex 응답이 허용 크기를 초과했습니다.'));
            return;
          }
          body += chunk;
        });
        response.on('error', (error) => {
          console.log(`  [LLM:codex] 응답 오류: ${error.message}`);
          finish(null);
        });
        response.on('end', () => {
          if (settled) return;
          if ((response.statusCode || 500) < 200 || (response.statusCode || 500) >= 300) {
            console.log(
              `  [LLM:codex] 요청 실패: ${errorMessage(body, response.statusCode).slice(0, 300)}`,
            );
            finish(null);
            return;
          }
          try {
            const parsed = JSON.parse(body);
            const content = parsed?.choices?.[0]?.message?.content;
            if (typeof content !== 'string' || !content.trim()) {
              console.log('  [LLM:codex] 응답에 choices[0].message.content가 없습니다.');
              finish(null);
              return;
            }
            finish(content);
          } catch (error) {
            console.log(`  [LLM:codex] JSON 응답 파싱 실패: ${error.message}`);
            finish(null);
          }
        });
      });

      request.setTimeout(requestTimeoutMs, () => {
        request.destroy(new Error(`Codex 요청 시간 초과(${requestTimeoutMs}ms)`));
      });
      request.on('error', (error) => {
        console.log(`  [LLM:codex] 연결 오류: ${error.message}`);
        finish(null);
      });
      request.end(payload);
    });
  }

  return {
    name: 'codex',
    model,
    reasoningEffort,
    endpoint: endpoint.toString(),
    sidecar,
    run,
  };
}

module.exports = {
  createCodexProvider,
  chatCompletionsUrl,
  REASONING_EFFORTS,
};
