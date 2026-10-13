import test from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { nextPendingLesson } from '../web/learning.js';
import { copyCode } from '../web/clipboard.js';

// 使用离线DOM验证真实Markdown库、高亮和复制，不启动浏览器或调用模型。
const dom = new JSDOM('<!doctype html><html><body></body></html>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
const feedbackTimers = [];
globalThis.setTimeout = fn => { feedbackTimers.push(fn); return feedbackTimers.length; };
const { renderMarkdown } = await import('../web/markdown.js');
const render = text => { document.body.innerHTML = renderMarkdown(text); return document.body; };
const lesson = (id, submitted = false, day = '2026-10-12') => ({ id, submitted, day, kind: 'lesson' });

test('headings, bold, lists, inline code, quotes and tables render as HTML', () => {
  const body = render('## 核心概念\n\n**自动装箱**和 `Integer`\n\n- 第一项\n- 第二项\n\n> 说明\n\n| 类型 | 含义 |\n| --- | --- |\n| int | 基本类型 |');
  assert.equal(body.querySelector('h2').textContent, '核心概念');
  assert.equal(body.querySelector('strong').textContent, '自动装箱');
  assert.equal(body.querySelector('p code').textContent, 'Integer');
  assert.equal(body.querySelectorAll('li').length, 2);
  assert.equal(body.querySelector('blockquote').textContent.trim(), '说明');
  assert.equal(body.querySelectorAll('table tbody tr').length, 1);
});

test('Java and SQL code blocks have real token highlighting and separate copy buttons', () => {
  const body = render('```java\npublic class Demo {\n    String name = "知序";\n}\n```\n\n```sql\nSELECT id FROM users WHERE id = 1;\n```');
  assert.equal(body.querySelectorAll('[data-copy-code]').length, 2);
  assert.ok(body.querySelector('code.language-java .hljs-keyword'));
  assert.ok(body.querySelector('code.language-sql .hljs-keyword'));
  assert.equal(body.querySelector('.code-language').textContent, 'java');
  assert.ok(body.querySelector('code').textContent.includes('    String name = "知序";'));
});

test('unknown languages keep escaped plain text and remain copyable', () => {
  const body = render('```unknown-language\n<x> & "value"\n```');
  assert.equal(body.querySelector('code').textContent, '<x> & "value"');
  assert.equal(body.querySelector('.code-language').textContent, 'unknown-language');
  assert.ok(body.querySelector('[data-copy-code]'));
  assert.equal(body.querySelector('code x'), null);
});

test('HTML, script URLs and forged copy buttons cannot execute or become active', () => {
  const body = render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[危险](javascript:alert(1))\n\n<button data-copy-code onclick="alert(1)">伪造</button>\n\n```html\n</code><script>alert(2)</script>\n```');
  assert.equal(body.querySelectorAll('script,img,[onclick],[onerror]').length, 0);
  assert.equal(body.querySelectorAll('[data-copy-code]').length, 1);
  assert.equal(body.querySelector('a')?.getAttribute('href'), null);
  assert.equal(body.querySelector('code').textContent, '</code><script>alert(2)</script>');
});

test('external links include protections for a new tab', () => {
  const link = render('[官方文档](https://docs.example.com/java)').querySelector('a');
  assert.equal(link.target, '_blank');
  assert.match(link.rel, /noopener/);
  assert.match(link.rel, /noreferrer/);
});

test('copy restores original code including indentation, newlines and special characters', async () => {
  const body = render('```java\nString text = "<&>";\n    int count = 1;\n```');
  let copied;
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => { copied = text; } }, configurable: true });
  const button = body.querySelector('[data-copy-code]');
  await copyCode(button);
  assert.equal(copied, 'String text = "<&>";\n    int count = 1;');
  assert.equal(button.textContent, '已复制');
  feedbackTimers.pop()();
  assert.equal(button.textContent, '复制');
});

test('copy falls back on HTTP or denied clipboard permission and leaves no temporary input', async () => {
  const body = render('```text\n  缩进\n第二行 & 值\n```');
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => { throw new Error('denied'); } }, configurable: true });
  let copied;
  document.execCommand = command => { assert.equal(command, 'copy'); copied = body.querySelector('textarea').value; return true; };
  await copyCode(body.querySelector('[data-copy-code]'));
  assert.equal(copied, '  缩进\n第二行 & 值');
  assert.equal(body.querySelector('textarea'), null);
  document.execCommand = () => false;
  await assert.rejects(copyCode(body.querySelector('[data-copy-code]')), /无法自动复制/);
  assert.equal(body.querySelector('textarea'), null);
});

test('next question follows order and skips completed lessons, quizzes and old days', () => {
  const items = [lesson('a', true), lesson('b', true), { ...lesson('quiz'), kind: 'choice' }, lesson('old', false, '2026-10-11'), lesson('c'), lesson('d')];
  assert.equal(nextPendingLesson(items, 'a', '2026-10-12').id, 'c');
  assert.equal(nextPendingLesson(items, 'c', '2026-10-12').id, 'd');
});

test('next question wraps to missed lessons and ends when all have been completed', () => {
  assert.equal(nextPendingLesson([lesson('a'), lesson('b', true)], 'b', '2026-10-12').id, 'a');
  assert.equal(nextPendingLesson([lesson('a', true), lesson('b', true)], 'b', '2026-10-12'), null);
});
