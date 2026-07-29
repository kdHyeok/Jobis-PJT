'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const path = require('node:path');
const { describe, it } = require('node:test');

const {
  createCodexSidecar,
  defaultAdapterPath,
} = require('../providers/codex-sidecar');

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.exitCode = null;
  child.killed = false;
  child.kill = () => {
    child.killed = true;
    child.exitCode = 0;
    child.emit('exit', 0, null);
    return true;
  };
  return child;
}

describe('Codex uv sidecar manager', () => {
  it('bundled adapter defaults to the fake-ai directory', () => {
    assert.equal(defaultAdapterPath(), path.resolve(__dirname, '..'));
  });

  it('이미 준비된 로컬 sidecar는 새 프로세스 없이 재사용한다', async () => {
    let spawnCount = 0;
    const manager = createCodexSidecar({
      endpoint: new URL('http://127.0.0.1:8001/v1/chat/completions'),
      env: {},
      spawnImpl: () => { spawnCount++; return fakeChild(); },
      healthCheck: async () => true,
      exists: () => false,
      processRef: new EventEmitter(),
    });

    assert.equal(await manager.ensureReady(), true);
    assert.equal(spawnCount, 0);
  });

  it('sidecar가 없으면 uv managed Python으로 시작하고 준비될 때까지 기다린다', async () => {
    const spawned = [];
    const child = fakeChild();
    let healthCalls = 0;
    const processRef = new EventEmitter();
    const adapterPath = path.resolve('C:\\workspace\\codex-adapter');
    const manager = createCodexSidecar({
      endpoint: new URL('http://127.0.0.1:8001/v1/chat/completions'),
      env: {
        CODEX_ADAPTER_PATH: adapterPath,
        CODEX_UV_COMMAND: 'uv-test',
        CODEX_STARTUP_TIMEOUT_MS: '5000',
      },
      spawnImpl: (command, args, options) => {
        spawned.push({ command, args, options });
        return child;
      },
      healthCheck: async () => ++healthCalls >= 2,
      exists: (file) => file === path.join(adapterPath, 'pyproject.toml'),
      processRef,
    });

    assert.equal(await manager.ensureReady(), true);
    assert.equal(spawned.length, 1);
    assert.equal(spawned[0].command, 'uv-test');
    assert.deepEqual(spawned[0].args, [
      'run',
      '--project', adapterPath,
      '--managed-python',
      '--extra', 'server',
      '--frozen',
      'codex-openai-server',
      '--host', '127.0.0.1',
      '--port', '8001',
    ]);
    assert.equal(spawned[0].options.cwd, adapterPath);
    assert.equal(spawned[0].options.shell, false);

    manager.stop();
    assert.equal(child.killed, true);
  });

  it('원격 Codex URL과 자동 기동 비활성 설정은 프로세스를 시작하지 않는다', async () => {
    for (const [endpoint, env] of [
      ['https://codex.example.com/v1/chat/completions', {}],
      ['http://127.0.0.1:8001/v1/chat/completions', { CODEX_AUTO_START: '0' }],
    ]) {
      let spawnCount = 0;
      const manager = createCodexSidecar({
        endpoint: new URL(endpoint),
        env,
        spawnImpl: () => { spawnCount++; return fakeChild(); },
        healthCheck: async () => false,
        exists: () => true,
        processRef: new EventEmitter(),
      });

      assert.equal(await manager.ensureReady(), true);
      assert.equal(spawnCount, 0);
    }
  });
});
