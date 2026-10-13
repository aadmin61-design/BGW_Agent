import test from 'node:test';
import assert from 'node:assert/strict';

// 仅测试模板与事件处理，不启动浏览器或替代视觉检查。
const events = {}, storage = new Map();
const root = { innerHTML: '', addEventListener(name, fn) { events[name] = fn; } };
const toast = { textContent: '', classList: { add() {}, remove() {} } };
const fakeInput = { value: '', focus() {}, setSelectionRange() {} };
globalThis.location = { search: '?demo=1', hash: 'dashboard', href: '' };
globalThis.localStorage = { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v) };
globalThis.document = { querySelector(selector) {
  if (selector === '#app') return root;
  if (selector === '#toast') return toast;
  if (selector === '#chat-messages') return { scrollTop: 0, scrollHeight: 100 };
  return fakeInput;
} };
globalThis.window = { addEventListener() {}, scrollTo() {} };
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.clearInterval = () => {};
globalThis.clearTimeout = () => {};
await import('../web/app.js');
const click = async dataset => events.click({ target: { closest: () => ({ dataset, disabled: false }) } });

test('dashboard makes demo status explicit and includes learning and review', () => {
  assert.match(root.innerHTML, /当前使用示例数据/);
  assert.match(root.innerHTML, /今日学习清单/);
  assert.match(root.innerHTML, /本周学习节奏/);
});
test('question opens independent tutor and bookmark persists', async () => {
  const first = JSON.parse(storage.get('bgw-demo')).lessons[0];
  await click({ item: first.id });
  assert.match(root.innerHTML, /独立对话/);
  await click({ action: 'save' });
  await click({ nav: 'bookmarks' });
  assert.match(root.innerHTML, /继续问答/);
  assert.equal(JSON.parse(storage.get('bgw-demo')).saved[first.id], true);
});
test('more lessons adds available concepts without duplicates', async () => {
  await click({ nav: 'lesson' });
  await click({ action: 'more-lesson' });
  const items = JSON.parse(storage.get('bgw-demo')).lessons;
  assert.equal(items.length, 12);
  assert.equal(new Set(items.map(x => x.id)).size, 12);
});
test('understood exposes next question and opens its independent conversation', async () => {
  const lessons = JSON.parse(storage.get('bgw-demo')).lessons;
  const index = lessons.findIndex(item => !item.submitted);
  const current = lessons[index], next = lessons[index + 1];
  await click({ item: current.id });
  assert.doesNotMatch(root.innerHTML, /data-action="next-lesson"/);
  await click({ action: 'remembered' });
  assert.match(root.innerHTML, /data-action="next-lesson"/);
  await click({ action: 'next-lesson' });
  assert.ok(root.innerHTML.includes(next.snapshot.question));
  assert.ok(!root.innerHTML.includes(current.snapshot.question));
  assert.match(root.innerHTML, /独立对话/);
});
test('quiz has 10 choices and 3 fills and submission reveals analysis', async () => {
  await click({ action: 'start-quiz' });
  const data = JSON.parse(storage.get('bgw-demo'));
  assert.equal(data.quiz.length, 13);
  assert.equal(data.quiz.filter(x => x.kind === 'choice').length, 10);
  await click({ item: data.quiz[0].id });
  assert.doesNotMatch(root.innerHTML, /标准答案：/);
  await click({ option: 'B' });
  await click({ action: 'submit-quiz' });
  assert.match(root.innerHTML, /回答正确/);
  assert.match(root.innerHTML, /标准答案：B/);
});
test('search content is escaped before insertion into HTML', async () => {
  await click({ nav: 'lesson' });
  await events.input({ target: { id: 'list-search', value: '\"><img src=x onerror=alert(1)>', selectionStart: 10 } });
  assert.doesNotMatch(root.innerHTML, /<img src=x/);
  assert.match(root.innerHTML, /&lt;img/);
});
