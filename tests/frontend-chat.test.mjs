import test from 'node:test';
import assert from 'node:assert/strict';

// 延迟响应验证思考状态，不调用浏览器、数据库或真实大模型。
const events = {}, storage = new Map(), windowEvents = {};
const input = { value: '', focus() {} };
let markup = '', request, requests = 0;
const root = {
  get innerHTML() { return markup; },
  set innerHTML(value) { markup = value; input.value = ''; },
  addEventListener(name, fn) { events[name] = fn; },
};
const toast = { textContent: '', classList: { add() {}, remove() {} } };
globalThis.location = { search: '', hash: 'dashboard', href: '' };
globalThis.localStorage = { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v) };
globalThis.document = { addEventListener() {}, querySelector(selector) {
  if (selector === '#app') return root;
  if (selector === '#toast') return toast;
  if (selector === '#chat-messages') return { scrollTop: 0, scrollHeight: 100 };
  return input;
} };
globalThis.window = { addEventListener(name, fn) { windowEvents[name] = fn; }, scrollTo() {} };
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.clearInterval = () => {};
globalThis.clearTimeout = () => {};
globalThis.FormData = class { constructor(form) { this.values = form.values; } get(key) { return this.values[key]; } };
const { demoRequest } = await import('../web/demo.js');
const response = (data, ok = true) => ({ ok, status: ok ? 200 : 503, json: async () => data });
globalThis.fetch = async (url, options) => {
  const path = url.replace('/api', '');
  if (options.method === 'POST' && path.endsWith('/conversation')) {
    requests++;
    return new Promise((resolve, reject) => { request = { resolve, reject, path, body: JSON.parse(options.body) }; });
  }
  return response(await demoRequest(path, options));
};
await import('../web/app.js');
const click = async dataset => events.click({ target: { closest: () => ({ dataset, disabled: false }) } });
const submit = message => events.submit({ preventDefault() {}, target: { id: 'chat-form', values: { message }, querySelector: () => ({ disabled: false }) } });
const first = JSON.parse(storage.get('bgw-demo')).lessons[0];
let history = [];

test('question appears immediately before thinking animation and resolves once', async () => {
  await click({ item: first.id });
  const question = '即时提问 <script>不执行</script>';
  const pending = submit(question);
  assert.match(markup, /正在思考/);
  assert.match(markup, /thinking-dots/);
  assert.match(markup, /aria-busy="true"/);
  assert.match(markup, /id="chat-input" disabled/);
  assert.ok(markup.indexOf('即时提问') < markup.indexOf('正在思考'));
  assert.doesNotMatch(markup, /<script>不执行/);
  await submit('重复提交');
  assert.equal(requests, 1);
  history = [{ role: 'user', content: question, ordinal: 0 }, { role: 'assistant', content: '真实响应测试', ordinal: 1 }];
  request.resolve(response({ item_id: first.id, saved: false, messages: history }));
  await pending;
  assert.doesNotMatch(markup, /正在思考/);
  assert.match(markup, /aria-busy="false"/);
  assert.equal(markup.split('即时提问').length - 1, 1);
  assert.ok(markup.indexOf('即时提问') < markup.indexOf('真实响应测试'));
});

test('failure removes placeholder, keeps history and restores draft for retry', async () => {
  const pending = submit('重试草稿');
  assert.match(markup, /正在思考/);
  request.resolve(response({ detail: '暂时无法连接' }, false));
  await pending;
  assert.doesNotMatch(markup, /正在思考|重试草稿/);
  assert.match(markup, /真实响应测试/);
  assert.equal(input.value, '重试草稿');
  assert.equal(toast.textContent, '暂时无法连接');
  const retry = submit(input.value);
  history = [...history, { role: 'user', content: '重试草稿', ordinal: 2 }, { role: 'assistant', content: '重试成功', ordinal: 3 }];
  request.resolve(response({ item_id: first.id, saved: false, messages: history }));
  await retry;
  assert.equal(markup.split('重试草稿').length - 1, 1);
  assert.ok(markup.indexOf('重试草稿') < markup.indexOf('重试成功'));
});

test('late response after leaving question cannot replace another page', async () => {
  const pending = submit('离开前的提问');
  location.hash = '#lesson';
  windowEvents.popstate();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(markup, /顺着脉络/);
  request.resolve(response({ item_id: first.id, saved: false, messages: [...history, { role: 'assistant', content: '旧题迟到回复' }] }));
  await pending;
  assert.match(markup, /顺着脉络/);
  assert.doesNotMatch(markup, /旧题迟到回复|正在思考/);
});
