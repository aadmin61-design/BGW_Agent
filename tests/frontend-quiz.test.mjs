import test from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

// 实际业务控制器配合离线HTTP响应，验证后台进度与跨题作答，不调用模型。
const dom = new JSDOM('<div id="learning-app"></div><div id="toast"></div>', { url: 'http://localhost:8001/#quiz' });
globalThis.window = dom.window; globalThis.document = dom.window.document;
globalThis.location = window.location; globalThis.localStorage = window.localStorage;
window.scrollTo = () => {};
const events = {}, root = document.getElementById('learning-app');
root.addEventListener = (name, callback) => { events[name] = callback; };
const saved = { setTimeout, clearTimeout, setInterval, clearInterval, fetch };
let timerId = 0, job = null, items = [], posts = 0, failStatus = false, blockKnowledge = false;
const timers = new Map();
globalThis.setTimeout = (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; };
globalThis.clearTimeout = id => timers.delete(id);
globalThis.setInterval = () => 0; globalThis.clearInterval = () => {};
const day = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' });
const snapshot = i => ({ question: `测试第${i+1}题${i>=10 ? '____' : '？'}`, category: 'Java', title: '知识',
  options: i>=10 ? [] : ['甲', '乙', '丙', '丁'], answer: i>=10 ? '答案' : 'B', analysis: '原理', source: 'test.md' });
const visible = item => {
  const copy = structuredClone(item);
  if (!copy.submitted) { delete copy.snapshot.answer; delete copy.snapshot.analysis; }
  return copy;
};
const response = (data, status=200) => ({ ok: status<400, status, json: async () => structuredClone(data) });
globalThis.fetch = async (url, options={}) => {
  const path = url.slice(4);
  if (path === '/auth/me') return response({ id: 'a', username: '测试用户', is_admin: false });
  if (path === '/dashboard') return response({ quiz_unlocked: true, day });
  if (path === '/plans/quiz/generation') {
    if (failStatus) throw new Error('offline');
    return response({ job });
  }
  if (path === '/plans/quiz') {
    if (options.method === 'POST') {
      posts++; job = { id: 'job', day, status: 'queued', completed: 0, total: 13, more: items.length>0 };
      return response({ items: items.map(visible), job, added: 0 }, 202);
    }
    return response(items.map(visible));
  }
  if (path === '/knowledge-bases' && blockKnowledge) return new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError'))));
  if (['/plans/lesson', '/knowledge-bases', '/bookmarks'].includes(path)) return response([]);
  if (path.startsWith('/items/')) {
    const [, , id, action] = path.split('/');
    const item = items.find(row => row.id === id);
    if (action === 'conversation') return response({ item_id: id, saved: false, messages: [{ role: 'assistant', content: `题目${id}的独立对话` }] });
    if (action === 'answer') {
      item.submitted = true; item.correct = true; item.user_answer = JSON.parse(options.body).answer;
      return response(visible(item));
    }
  }
  throw new Error(`Unexpected path: ${path}`);
};
await import('../web/app.js?quiz-regression');
const click = async selector => events.click({ target: document.querySelector(selector) });
async function poll(delay = 3000) {
  const entry = [...timers.entries()].find(([, value]) => value.delay === delay);
  assert.ok(entry, 'poll was scheduled'); timers.delete(entry[0]); await entry[1].callback();
}

test('open empty list discovers automatic generation without a refresh', async () => {
  job = { id: 'auto', day, status: 'queued', completed: 0, total: 13, source: 'automatic' };
  await poll(15000);
  assert.match(root.textContent, /等待生成/);
  assert.equal(document.querySelector('[data-action="start-quiz"]').disabled, true);
  job.status = 'failed'; job.message = '模型暂不可用';
  await poll();
  assert.equal(document.querySelector('[data-action="start-quiz"]').disabled, false);
});

test('generate returns to usable quiz list with progress instead of full-page loading', async () => {
  await click('[data-action="start-quiz"]');
  assert.equal(posts, 1);
  assert.match(root.textContent, /等待生成.*0 \/ 13/);
  assert.match(root.textContent, /可以先浏览其他页面/);
  assert.equal(document.querySelector('[data-action="start-quiz"]').disabled, true);
  assert.equal(document.querySelector('.loading'), null);
  await click('[data-nav="knowledge"]');
  assert.match(root.textContent, /你的知识，从这里出发/);
  assert.equal(job.status, 'queued');
  await click('[data-nav="quiz"]');
  assert.match(root.textContent, /等待生成/);
});

test('poll completion updates all 13 questions and unlocks more generation', async () => {
  job.status = 'running'; job.completed = 4;
  await poll();
  assert.equal(document.querySelector('progress').value, 4);
  items = Array.from({ length: 13 }, (_, i) => ({ id: `q${i}`, day, kind: i>=10 ? 'fill' : 'choice', snapshot: snapshot(i), submitted: false }));
  job.status = 'completed'; job.completed = 13;
  await poll();
  assert.equal(document.querySelectorAll('[data-item]').length, 13);
  assert.equal(document.querySelector('[data-action="more-quiz"]').disabled, false);
  assert.equal(document.querySelector('progress'), null);
});

test('previous and next preserve choices and independent conversations without submitting', async () => {
  await click('[data-item="q0"]');
  assert.equal(document.querySelector('[data-action="previous-quiz"]').disabled, true);
  await click('[data-option="B"]');
  await click('[data-action="next-quiz"]');
  assert.match(document.querySelector('.quiz-navigation').textContent, /第 2 \/ 13 题/);
  assert.match(document.querySelector('.chat-messages').textContent, /q1的独立对话/);
  assert.doesNotMatch(document.querySelector('.chat-messages').textContent, /q0的独立对话/);
  await click('[data-action="previous-quiz"]');
  assert.ok(document.querySelector('[data-option="B"]').classList.contains('selected'));
  assert.equal(items[0].submitted, false);
  assert.equal(document.querySelector('.result'), null);
});

test('fill draft survives switching and last question disables next', async () => {
  await click('[data-nav="quiz"]');
  await click('[data-item="q11"]');
  const input = document.querySelector('#fill-answer'); input.value = '我的草稿';
  await events.input({ target: input });
  await click('[data-action="next-quiz"]');
  assert.equal(document.querySelector('[data-action="next-quiz"]').disabled, true);
  await click('[data-action="previous-quiz"]');
  assert.equal(document.querySelector('#fill-answer').value, '我的草稿');
  assert.equal(items[11].submitted, false);
  await click('[data-action="submit-quiz"]');
  await click('[data-action="next-quiz"]');
  await click('[data-action="previous-quiz"]');
  assert.equal(document.querySelector('#fill-answer').value, '我的草稿');
  assert.equal(document.querySelector('#fill-answer').disabled, true);
  assert.match(root.textContent, /回答正确/);
});

test('poll failure offers explicit refresh and generation failure offers retry', async () => {
  await click('[data-nav="quiz"]');
  await click('[data-action="more-quiz"]');
  failStatus = true;
  await poll();
  assert.ok(document.querySelector('[data-action="refresh-quiz"]'));
  failStatus = false; job.status = 'failed'; job.message = '生成失败，请重试';
  await click('[data-action="refresh-quiz"]');
  assert.match(root.textContent, /生成失败，请重试/);
  assert.equal(document.querySelector('[data-action="more-quiz"]').disabled, false);
});

test('stalled page fetch exits loading after timeout with an error', async () => {
  blockKnowledge = true;
  const pending = click('[data-nav="knowledge"]');
  // 所有并行请求启动后仅触发网络等待计时器，不真实等待20秒。
  await new Promise(resolve => setImmediate(resolve));
  for (const [id, timer] of [...timers]) if (timer.delay === 20000) { timers.delete(id); timer.callback(); }
  await pending;
  assert.equal(document.querySelector('.loading'), null);
  assert.match(root.textContent, /连接超时/);
});

test.after(() => { Object.assign(globalThis, saved); dom.window.close(); });
