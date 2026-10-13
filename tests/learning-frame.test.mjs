import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { JSDOM } from 'jsdom';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

// 离线集成测试连接真实业务控制器与React外壳，数据使用独立演示存储。
const folder = fileURLToPath(new URL('../data/component-tests/', import.meta.url));
await mkdir(folder, { recursive: true });
const output = join(folder, 'learning-frame.mjs');
await build({ entryPoints: [fileURLToPath(new URL('../frontend/App.jsx', import.meta.url))], outfile: output,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', jsx: 'automatic', external: ['/assets/*'] });
const { default: App } = await import(pathToFileURL(output));
const dom = new JSDOM('<!doctype html><html><body><div id="app"></div><div id="toast"></div></body></html>', { url: 'http://localhost:8001/?demo=1#home' });
globalThis.window = dom.window; globalThis.document = dom.window.document;
globalThis.location = window.location; globalThis.localStorage = window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const nativeSetInterval = globalThis.setInterval;
globalThis.setInterval = () => 0;
window.matchMedia = query => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} });
window.scrollTo = () => {};
window.HTMLMediaElement.prototype.play = () => Promise.resolve();
window.HTMLMediaElement.prototype.pause = () => {};
let ready;
const loadController = () => { ready = import('../web/app.js?learning-frame'); return ready; };
const root = createRoot(document.getElementById('app'));
await act(async () => root.render(React.createElement(App, { loadController })));
await act(async () => await ready);
const settle = () => new Promise(resolve => setTimeout(resolve, 15));
async function click(selector) { await act(async () => { document.querySelector(selector).click(); await settle(); }); }

test('initial homepage remains visible while business data preloads in its own container', () => {
  assert.equal(location.hash, '#home');
  assert.equal(document.querySelector('.learning-host').hidden, true);
  assert.ok(document.querySelector('#learning-app').textContent.includes('当前使用示例数据'));
  assert.ok(document.querySelector('#learning-app').textContent.includes('今日学习清单'));
  assert.equal(document.querySelectorAll('#app').length, 1);
});

test('hero opens daily learning and knowledge navigation retains the business module', async () => {
  await click('.foldcraft-hero-content button');
  assert.equal(location.hash, '#lesson');
  assert.equal(document.querySelector('.learning-host').hidden, false);
  assert.ok(document.querySelector('#learning-app').textContent.includes('顺着脉络'));
  await click('nav[aria-label="主导航"] a[href="#knowledge"]');
  assert.equal(location.hash, '#knowledge');
  assert.ok(document.querySelector('#learning-app').textContent.includes('你的知识，从这里出发'));
});

test('question, next question and independent chat still work inside React layout', async () => {
  await click('nav[aria-label="主导航"] a[href="#lesson"]');
  const lesson = JSON.parse(localStorage.getItem('bgw-demo')).lessons.find(item => !item.submitted);
  await click(`#learning-app [data-item="${lesson.id}"]`);
  assert.ok(document.querySelector('#learning-app').textContent.includes('独立对话'));
  await click('#learning-app [data-action="remembered"]');
  assert.ok(document.querySelector('#learning-app [data-action="next-lesson"]'));
  await click('#learning-app [data-action="next-lesson"]');
  assert.ok(!document.querySelector('.question-card').textContent.includes(lesson.snapshot.question));
});

test('back navigation synchronizes route and business content without replacing React root', async () => {
  await act(async () => { window.history.replaceState(null, '', '#knowledge'); window.dispatchEvent(new window.PopStateEvent('popstate')); await settle(); });
  assert.ok(document.querySelector('#learning-app').textContent.includes('你的知识，从这里出发'));
  await click('a[aria-label="知序首页"]');
  assert.equal(location.hash, '#home');
  assert.equal(document.querySelector('.learning-host').hidden, true);
  assert.ok(document.querySelector('h1').textContent.includes('学懂一个问题'));
});

test.after(async () => { await act(async () => root.unmount()); globalThis.setInterval = nativeSetInterval; dom.window.close(); });
