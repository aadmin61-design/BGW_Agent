import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { JSDOM } from 'jsdom';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

// 验证真实React组件的菜单及业务桥接，不启动浏览器、不调用后端或模型。
const folder = fileURLToPath(new URL('../data/component-tests/', import.meta.url));
await mkdir(folder, { recursive: true });
const output = join(folder, 'foldcraft.mjs');
await build({ entryPoints: [fileURLToPath(new URL('../frontend/App.jsx', import.meta.url))], outfile: output,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', jsx: 'automatic', external: ['/assets/*'] });
const { default: App, VIDEO_URL } = await import(pathToFileURL(output));
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost:8001/#home' });
globalThis.window = dom.window; globalThis.document = dom.window.document;
const stylesheet = document.createElement('style');
stylesheet.textContent = await readFile(fileURLToPath(new URL('../web/dist/main.css', import.meta.url)), 'utf8');
document.head.append(stylesheet);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const media = [];
window.matchMedia = query => {
  const listeners = new Set();
  const item = { matches: false, media: query, addEventListener: (_, fn) => listeners.add(fn), removeEventListener: (_, fn) => listeners.delete(fn), trigger(matches) { for (const fn of listeners) fn({ matches }); } };
  media.push(item); return item;
};
window.scrollTo = () => {};
let plays = 0, pauses = 0, reloads = 0;
window.HTMLMediaElement.prototype.play = () => { plays++; return Promise.resolve(); };
window.HTMLMediaElement.prototype.pause = () => { pauses++; };
window.HTMLMediaElement.prototype.load = () => { reloads++; };
const requests = [];
let loaded = 0;
const controller = {
  openLearningPage: async page => { requests.push(page); },
  logoutLearning: async () => { requests.push('logout'); },
};
const loadController = async () => { loaded++; return controller; };
const root = createRoot(document.getElementById('root'));
await act(async () => { root.render(React.createElement(App, { loadController })); });
const click = async selector => act(async () => document.querySelector(selector).click());

test('hero is a full-screen learning homepage with supplied video and staggered text', () => {
  assert.ok(document.querySelector('.foldcraft-root.h-screen'));
  const video = document.querySelector('video');
  assert.equal(video.getAttribute('src'), VIDEO_URL);
  assert.equal(video.autoplay, true); assert.equal(video.muted, true); assert.equal(video.loop, true);
  assert.equal(video.hasAttribute('playsinline'), true);
  assert.equal(video.style.objectPosition, '70% center');
  assert.equal(video.preload, 'auto');
  assert.equal(window.getComputedStyle(video).position, 'fixed');
  assert.ok(document.querySelector('h1').textContent.includes('学懂一个问题'));
  assert.equal(document.querySelectorAll('h1 br').length, 2);
  assert.match(document.querySelector('h1').className, /fadeSlideUp/);
  assert.equal(document.querySelector('.learning-host').hidden, true);
  assert.equal(window.getComputedStyle(document.querySelector('.learning-host')).display, 'none');
  assert.equal(loaded, 1);
});

test('background lifecycle pauses video decoding and foreground resumes playback', async () => {
  const pausedBefore = pauses, playedBefore = plays;
  await act(async () => window.dispatchEvent(new window.CustomEvent('zhixu:visibility', { detail: { active: false } })));
  assert.equal(pauses, pausedBefore + 1);
  await act(async () => window.dispatchEvent(new window.CustomEvent('zhixu:visibility', { detail: { active: true } })));
  assert.equal(plays, playedBefore + 1);
});

test('speed changes preserve pause state and persist for subsequent visits', async () => {
  const video = document.querySelector('video');
  await click('button[aria-label="暂停背景视频"]');
  const playsBeforeChange = plays;
  await click('button[aria-label="背景视频播放速度"]');
  assert.ok(document.querySelector('.speed-arrow.is-open'));
  await click('[role="menuitemradio"]');
  assert.equal(document.querySelector('[aria-label="背景视频播放速度"]').getAttribute('aria-expanded'), 'false');
  assert.equal(video.playbackRate, 0.5);
  assert.equal(video.defaultPlaybackRate, 0.5);
  assert.equal(window.localStorage.getItem('zhixu-video-speed'), '0.5');
  assert.equal(plays, playsBeforeChange);
  assert.ok(document.querySelector('button[aria-label="播放背景视频"]'));
  await click('button[aria-label="播放背景视频"]');
  assert.equal(video.playbackRate, 0.5);
  // 恢复默认速度，避免影响后续组件场景。
  await click('button[aria-label="背景视频播放速度"]');
  await click('[role="menuitemradio"]:nth-child(3)');
});

test('mobile menu toggles icons, manages focus and closes with Escape', async () => {
  await click('#mobile-menu-toggle');
  assert.equal(document.querySelector('#mobile-menu-toggle').getAttribute('aria-expanded'), 'true');
  assert.equal(document.querySelector('#mobile-menu').getAttribute('aria-hidden'), 'false');
  assert.ok(document.querySelector('#mobile-menu-toggle .lucide-menu').classList.contains('rotate-90'));
  assert.equal(document.body.style.overflow, 'hidden');
  assert.equal(document.activeElement.textContent, '首页');
  await act(async () => document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  assert.equal(document.querySelector('#mobile-menu-toggle').getAttribute('aria-expanded'), 'false');
  assert.equal(document.activeElement.id, 'mobile-menu-toggle');
  assert.equal(document.body.style.overflow, '');
});

test('mobile learning link closes overlay and opens existing learning module', async () => {
  const video = document.querySelector('video');
  const pausesBeforeNavigation = pauses;
  await click('#mobile-menu-toggle');
  await click('#mobile-menu a[href="#lesson"]');
  assert.equal(requests.at(-1), 'lesson');
  assert.equal(document.querySelector('#mobile-menu-toggle').getAttribute('aria-expanded'), 'false');
  assert.equal(document.querySelector('.learning-host').hidden, false);
  assert.equal(document.querySelector('.foldcraft-hero-content').hidden, true);
  assert.equal(window.getComputedStyle(document.querySelector('.foldcraft-hero-content')).display, 'none');
  assert.equal(loaded, 1);
  assert.equal(document.querySelector('video'), video);
  assert.equal(video.hidden, false);
  assert.equal(pauses, pausesBeforeNavigation);
  assert.ok(document.querySelector('button[aria-label="暂停背景视频"]'));
});

test('dashboard route keeps the shared background playing', async () => {
  const pausesBeforeNavigation = pauses, playsBeforeNavigation = plays;
  await act(async () => {
    window.location.hash = 'dashboard';
    window.dispatchEvent(new window.HashChangeEvent('hashchange'));
  });
  assert.equal(requests.at(-1), 'dashboard');
  assert.equal(document.querySelector('.learning-host').hidden, false);
  assert.equal(document.querySelector('video').hidden, false);
  assert.equal(pauses, pausesBeforeNavigation);
  assert.equal(plays, playsBeforeNavigation);
});

test('returning home retains the learning container and hero CTA works', async () => {
  const container = document.querySelector('#learning-app');
  await click('a[aria-label="知序首页"]');
  assert.equal(document.querySelector('.foldcraft-hero-content').hidden, false);
  assert.equal(document.querySelector('#learning-app'), container);
  assert.equal(loaded, 1);
  await click('.foldcraft-hero-content button');
  assert.equal(requests.at(-1), 'lesson');
});

test('desktop resize closes mobile overlay and restores page scrolling', async () => {
  await click('#mobile-menu-toggle');
  await act(async () => media.find(item => item.media === '(min-width: 768px)').trigger(true));
  assert.equal(document.querySelector('#mobile-menu-toggle').getAttribute('aria-expanded'), 'false');
  assert.equal(document.body.style.overflow, '');
});

test('failed video falls back without blocking content and can be retried', async () => {
  await click('a[aria-label="知序首页"]');
  await click('button[aria-label="暂停背景视频"]');
  assert.ok(document.querySelector('button[aria-label="播放背景视频"]'));
  await act(async () => document.querySelector('video').dispatchEvent(new window.Event('error')));
  assert.equal(document.querySelector('video').hidden, true);
  assert.equal(document.querySelector('.foldcraft-hero-content').hidden, false);
  assert.equal(document.querySelector('button[aria-label="重新加载背景视频"]').disabled, false);
  const playsBeforeRetry = plays;
  await click('button[aria-label="重新加载背景视频"]');
  assert.equal(reloads, 1);
  assert.equal(document.querySelector('video').hidden, false);
  assert.equal(plays, playsBeforeRetry + 1);
  assert.ok(document.querySelector('button[aria-label="暂停背景视频"]'));
});

test('blocked autoplay allows manual playback without hiding the video', async () => {
  await click('button[aria-label="暂停背景视频"]');
  window.HTMLMediaElement.prototype.play = () => Promise.reject(new window.DOMException('Blocked autoplay', 'NotAllowedError'));
  await click('button[aria-label="播放背景视频"]');
  assert.equal(document.querySelector('video').hidden, false);
  assert.ok(document.querySelector('button[aria-label="播放背景视频"]'));
  window.HTMLMediaElement.prototype.play = () => { plays++; return Promise.resolve(); };
  await click('button[aria-label="播放背景视频"]');
  assert.ok(document.querySelector('button[aria-label="暂停背景视频"]'));
});

test.after(async () => { await act(async () => root.unmount()); dom.window.close(); });
