'use strict';

const fs = require('fs');
const http = require('http');
const https = require('https');
const path = require('path');
const { spawn } = require('child_process');

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);

function positiveNumber(value, fallback, name) {
  const parsed = value === undefined || value === '' ? fallback : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name}은(는) 0보다 큰 숫자여야 합니다.`);
  }
  return parsed;
}

function booleanValue(value, fallback, name) {
  if (value === undefined || value === '') return fallback;
  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
  throw new Error(`${name}은(는) 1/0 또는 true/false 값이어야 합니다.`);
}

function defaultAdapterPath() {
  return path.resolve(__dirname, '..');
}

function healthUrl(endpoint) {
  return new URL('/health', endpoint.origin);
}

function checkHealth(url, timeoutMs = 1000) {
  return new Promise((resolve) => {
    const transport = url.protocol === 'https:' ? https : http;
    const request = transport.get(url, (response) => {
      response.resume();
      resolve((response.statusCode || 500) >= 200 && (response.statusCode || 500) < 300);
    });
    request.setTimeout(timeoutMs, () => request.destroy());
    request.on('error', () => resolve(false));
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 로컬 Codex OpenAI adapter를 uv 자식 프로세스로 관리한다.
 * 이미 떠 있는 sidecar는 소유하지 않고 재사용하며, 직접 띄운 프로세스만 종료한다.
 */
function createCodexSidecar({
  endpoint,
  env = process.env,
  spawnImpl = spawn,
  healthCheck = checkHealth,
  exists = fs.existsSync,
  processRef = process,
}) {
  const local = LOOPBACK_HOSTS.has(endpoint.hostname);
  const requestedAutoStart = booleanValue(env.CODEX_AUTO_START, true, 'CODEX_AUTO_START');
  const autoStart = requestedAutoStart && local;
  const adapterPath = path.resolve(env.CODEX_ADAPTER_PATH || defaultAdapterPath());
  const startupTimeoutMs = positiveNumber(
    env.CODEX_STARTUP_TIMEOUT_MS,
    30000,
    'CODEX_STARTUP_TIMEOUT_MS',
  );
  const health = healthUrl(endpoint);
  const uvCommand = String(env.CODEX_UV_COMMAND || 'uv').trim();
  if (!uvCommand) throw new Error('CODEX_UV_COMMAND는 비어 있을 수 없습니다.');

  let child = null;
  let readyPromise = null;
  let stopping = false;
  let exitHookRegistered = false;

  function stop() {
    stopping = true;
    if (child && child.exitCode === null && !child.killed) {
      try { child.kill(); } catch (_) {}
    }
    if (exitHookRegistered && typeof processRef.removeListener === 'function') {
      processRef.removeListener('exit', stop);
      exitHookRegistered = false;
    }
  }

  async function start() {
    if (!autoStart) return true;
    if (await healthCheck(health, 1000)) {
      console.log(`  [LLM:codex] 기존 sidecar 재사용: ${health.origin}`);
      return true;
    }

    const pyproject = path.join(adapterPath, 'pyproject.toml');
    if (!exists(pyproject)) {
      console.log(`  [LLM:codex] adapter를 찾지 못했습니다: ${pyproject}`);
      return false;
    }

    const port = endpoint.port || (endpoint.protocol === 'https:' ? '443' : '80');
    const host = endpoint.hostname === 'localhost' ? '127.0.0.1' : endpoint.hostname;
    const args = [
      'run',
      '--project', adapterPath,
      '--managed-python',
      '--extra', 'server',
      '--frozen',
      'codex-openai-server',
      '--host', host,
      '--port', port,
    ];

    console.log(`  [LLM:codex] uv sidecar 시작: ${host}:${port}`);
    try {
      child = spawnImpl(uvCommand, args, {
        cwd: adapterPath,
        env,
        shell: false,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      console.log(`  [LLM:codex] uv 실행 실패: ${error.message}`);
      return false;
    }

    let spawnError = null;
    child.on('error', (error) => { spawnError = error; });
    child.on('exit', (code, signal) => {
      if (!stopping) {
        console.log(`  [LLM:codex] sidecar 종료(code=${code}, signal=${signal || '-'})`);
      }
      readyPromise = null;
    });
    child.stdout?.on('data', (chunk) => {
      const text = String(chunk).trim();
      if (text) console.log(`  [Codex sidecar] ${text}`);
    });
    child.stderr?.on('data', (chunk) => {
      const text = String(chunk).trim();
      if (text) console.log(`  [Codex sidecar] ${text}`);
    });

    if (typeof processRef.once === 'function') {
      processRef.once('exit', stop);
      exitHookRegistered = true;
    }

    const deadline = Date.now() + startupTimeoutMs;
    while (Date.now() < deadline) {
      if (spawnError) {
        console.log(`  [LLM:codex] uv 실행 오류: ${spawnError.message}`);
        stop();
        return false;
      }
      if (child.exitCode !== null) return false;
      if (await healthCheck(health, 1000)) {
        console.log(`  [LLM:codex] sidecar 준비 완료: ${health.origin}`);
        return true;
      }
      await delay(250);
    }

    console.log(`  [LLM:codex] sidecar 준비 시간 초과(${startupTimeoutMs}ms)`);
    stop();
    return false;
  }

  function ensureReady() {
    if (readyPromise) return readyPromise;
    const pending = start()
      .catch((error) => {
        console.log(`  [LLM:codex] sidecar 준비 오류: ${error.message}`);
        return false;
      })
      .then((ready) => {
        if (!ready && readyPromise === pending) readyPromise = null;
        return ready;
      });
    readyPromise = pending;
    return pending;
  }

  return {
    autoStart,
    adapterPath,
    healthUrl: health.toString(),
    ensureReady,
    stop,
  };
}

module.exports = {
  createCodexSidecar,
  checkHealth,
  defaultAdapterPath,
  healthUrl,
};
