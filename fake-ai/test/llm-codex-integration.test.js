'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const { after, before, describe, it } = require('node:test');

describe('llm.js Codex integration', () => {
  let server;
  let llm;
  let receivedPrompt;

  before(async () => {
    server = http.createServer((request, response) => {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => { body += chunk; });
      request.on('end', () => {
        const payload = JSON.parse(body);
        receivedPrompt = payload.messages[0].content;
        const content = JSON.stringify({
          company: '테스트회사',
          role: '백엔드 개발자',
          career: '신입 가능',
          stack: ['Java', 'Spring'],
          required: ['Java 활용'],
          preferred: ['PostgreSQL 경험'],
          isJobPosting: true,
        });
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          choices: [{ message: { role: 'assistant', content } }],
        }));
      });
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

    process.env.LLM_PROVIDER = 'codex';
    process.env.CODEX_BASE_URL = `http://127.0.0.1:${server.address().port}`;
    process.env.CODEX_MODEL = 'gpt-integration';
    process.env.CODEX_REASONING_EFFORT = 'high';
    process.env.CODEX_TIMEOUT_MS = '5000';
    process.env.CODEX_AUTO_START = '0';
    llm = require('../llm');
  });

  after(async () => {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  });

  it('기존 공고 파싱 함수와 JSON 계약을 그대로 사용한다', async () => {
    const result = await llm.parseJobPosting('테스트회사 백엔드 개발자 채용');

    assert.equal(llm.PROVIDER_NAME, 'codex');
    assert.deepEqual(result, {
      company: '테스트회사',
      role: '백엔드 개발자',
      career: '신입 가능',
      stack: ['Java', 'Spring'],
      required: ['Java 활용'],
      preferred: ['PostgreSQL 경험'],
    });
    assert.match(receivedPrompt, /너는 채용공고 분석 도구의 JSON 생성기다/);
    assert.match(receivedPrompt, /테스트회사 백엔드 개발자 채용/);
  });
});
