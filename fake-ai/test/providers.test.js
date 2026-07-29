'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const { after, before, describe, it } = require('node:test');

const { createProvider, normalizeProvider } = require('../providers');
const { createCodexProvider } = require('../providers/codex');

describe('provider router', () => {
  it('환경변수가 없으면 기존 Claude 함수를 그대로 사용한다', async () => {
    const runClaude = async (prompt) => `claude:${prompt}`;
    const provider = createProvider({ runClaude, timeoutMs: 1000, env: {} });

    assert.equal(provider.name, 'claude');
    assert.strictEqual(provider.run, runClaude);
    assert.equal(await provider.run('hello'), 'claude:hello');
  });

  it('claude를 명시해도 기존 Claude 함수를 그대로 사용한다', () => {
    const runClaude = async () => 'ok';
    const provider = createProvider({
      runClaude,
      timeoutMs: 1000,
      env: { LLM_PROVIDER: 'claude' },
    });

    assert.strictEqual(provider.run, runClaude);
  });

  it('gpt를 codex alias로 인식한다', () => {
    assert.equal(normalizeProvider('gpt'), 'codex');
    assert.equal(normalizeProvider('CODEX'), 'codex');
  });

  it('알 수 없는 provider는 시작 시 거부한다', () => {
    assert.throws(() => normalizeProvider('unknown'), /지원하지 않는 LLM_PROVIDER/);
  });
});

describe('Codex HTTP provider', () => {
  let server;
  let baseUrl;
  let received;

  before(async () => {
    server = http.createServer((request, response) => {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => { body += chunk; });
      request.on('end', () => {
        const parsedBody = JSON.parse(body);
        received = {
          method: request.method,
          url: request.url,
          body: parsedBody,
        };
        const prompt = parsedBody.messages?.[0]?.content;
        if (prompt === '__http_error__') {
          response.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({ error: { message: 'mock failure' } }));
          return;
        }
        if (prompt === '__bad_json__') {
          response.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
          response.end('not-json');
          return;
        }
        if (prompt === '__missing_content__') {
          response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({ choices: [{ message: { role: 'assistant' } }] }));
          return;
        }
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          choices: [{ message: { role: 'assistant', content: '{"ok":true}' } }],
        }));
      });
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    baseUrl = `http://127.0.0.1:${server.address().port}`;
  });

  after(async () => {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  });

  it('모델·추론 깊이·timeout과 전체 프롬프트를 sidecar에 전달한다', async () => {
    const provider = createCodexProvider({
      timeoutMs: 200000,
      env: {
        CODEX_BASE_URL: baseUrl,
        CODEX_MODEL: 'gpt-test',
        CODEX_REASONING_EFFORT: 'xhigh',
        CODEX_TIMEOUT_MS: '5000',
        CODEX_AUTO_START: '0',
      },
    });

    const content = await provider.run('첫 줄\n둘째 줄');

    assert.equal(content, '{"ok":true}');
    assert.equal(received.method, 'POST');
    assert.equal(received.url, '/v1/chat/completions');
    assert.deepEqual(received.body, {
      model: 'gpt-test',
      messages: [{ role: 'user', content: '첫 줄\n둘째 줄' }],
      reasoning_effort: 'xhigh',
      timeout: 5,
      stream: false,
    });
  });

  it('지원하지 않는 추론 깊이는 시작 시 거부한다', () => {
    assert.throws(
      () => createCodexProvider({
        timeoutMs: 1000,
        env: {
          CODEX_BASE_URL: baseUrl,
          CODEX_REASONING_EFFORT: 'deep',
          CODEX_AUTO_START: '0',
        },
      }),
      /지원하지 않는 CODEX_REASONING_EFFORT/,
    );
  });

  it('sidecar 오류와 잘못된 응답은 기존 폴백 계약에 맞게 null을 반환한다', async () => {
    const provider = createCodexProvider({
      timeoutMs: 5000,
      env: { CODEX_BASE_URL: `${baseUrl}/v1`, CODEX_AUTO_START: '0' },
    });

    assert.equal(await provider.run('__http_error__'), null);
    assert.equal(await provider.run('__bad_json__'), null);
    assert.equal(await provider.run('__missing_content__'), null);
  });

  it('자동 기동에 실패하면 HTTP 호출 없이 기존 폴백 계약으로 돌아간다', async () => {
    let readyCalls = 0;
    const provider = createCodexProvider({
      timeoutMs: 5000,
      env: { CODEX_BASE_URL: baseUrl },
      sidecarFactory: () => ({
        ensureReady: async () => { readyCalls++; return false; },
        stop: () => {},
      }),
    });

    assert.equal(await provider.run('호출하면 안 됨'), null);
    assert.equal(readyCalls, 2);
  });
});
