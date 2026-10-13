import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';

const folder = fileURLToPath(new URL('../data/android-web-tests/', import.meta.url));
await mkdir(folder, { recursive: true });
const output = folder + '/app.mjs';
await build({ entryPoints: [fileURLToPath(new URL('../frontend/App.jsx', import.meta.url))], outfile: output,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', jsx: 'automatic', external: ['/assets/*'] });
const { default: App } = await import(pathToFileURL(output));
const dom = new JSDOM('<html><body><div id="app"></div></body></html>', { url: 'https://example.test/#home', pretendToBeVisual: true });
globalThis.window = dom.window; globalThis.document = dom.window.document;
Object.defineProperty(window.navigator, 'userAgent', { value: 'Android ZhixuAndroid/1.0.0 ZhixuLite/1' });
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.scrollTo = () => {};
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let controllers = 0, plays = 0, page = 'home';
window.HTMLMediaElement.prototype.play = () => { plays++; return Promise.resolve(); };
const controller = { getLearningPage: () => page, openLearningPage: async value => { page = value; } };
const root = createRoot(document.getElementById('app'));
await act(async () => root.render(React.createElement(App, { loadController: async () => { controllers++; return controller; } })));

test('Android economy mode mounts no video or video requests', () => {
  assert.equal(document.querySelector('video'), null);
  assert.equal(plays, 0);
  assert.ok(document.documentElement.classList.contains('zhixu-android'));
  assert.ok(document.documentElement.classList.contains('zhixu-lite'));
  assert.equal(document.querySelector('.video-controls').hidden, true);
});
test('Android navigation reuses the controller for all services', async () => {
  for (const next of ['lesson', 'quiz', 'memory', 'bookmarks', 'knowledge', 'admin']) {
    await act(async () => { window.history.replaceState(null, '', '#' + next); window.dispatchEvent(new window.HashChangeEvent('hashchange')); });
    assert.equal(page, next);
    assert.equal(document.querySelector('.learning-host').hidden, false);
  }
  assert.equal(controllers, 1);
  assert.equal(document.querySelector('video'), null);
});
