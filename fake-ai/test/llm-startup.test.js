'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { describe, it } = require('node:test');

const fakeAiRoot = path.resolve(__dirname, '..');

function loadLlm(env) {
  const childEnv = { ...process.env };
  for (const [name, value] of Object.entries(env)) {
    if (value === null) delete childEnv[name];
    else childEnv[name] = value;
  }
  return spawnSync(
    process.execPath,
    ['-e', 'const llm=require("./llm"); console.log(JSON.stringify({enabled:llm.ENABLED,provider:llm.PROVIDER_NAME,max:llm.MAX_CONCURRENT}));'],
    {
      cwd: fakeAiRoot,
      env: childEnv,
      encoding: 'utf8',
    },
  );
}

function lastJson(stdout) {
  const line = stdout.trim().split(/\r?\n/).at(-1);
  return JSON.parse(line);
}

describe('llm.js startup policy', () => {
  it('비활성 모드는 잘못된 Codex 설정을 검증하지 않고 폴백으로 기동한다', () => {
    const result = loadLlm({
      LLM_DISABLED: '1',
      LLM_PROVIDER: 'codex',
      CODEX_REASONING_EFFORT: 'invalid',
      CODEX_TIMEOUT_MS: 'invalid',
    });

    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(lastJson(result.stdout), {
      enabled: false,
      provider: 'disabled',
      max: 2,
    });
  });

  it('Codex 기본 동시성은 1이고 명시한 값은 존중한다', () => {
    const defaults = loadLlm({
      LLM_DISABLED: '0',
      LLM_PROVIDER: 'codex',
      LLM_MAX_CONCURRENT: null,
      CODEX_REASONING_EFFORT: 'medium',
      CODEX_TIMEOUT_MS: '5000',
      CODEX_AUTO_START: '0',
    });
    const configured = loadLlm({
      LLM_DISABLED: '0',
      LLM_PROVIDER: 'codex',
      LLM_MAX_CONCURRENT: '3',
      CODEX_REASONING_EFFORT: 'medium',
      CODEX_TIMEOUT_MS: '5000',
      CODEX_AUTO_START: '0',
    });

    assert.equal(defaults.status, 0, defaults.stderr);
    assert.equal(configured.status, 0, configured.stderr);
    assert.equal(lastJson(defaults.stdout).max, 1);
    assert.equal(lastJson(configured.stdout).max, 3);
  });
});
