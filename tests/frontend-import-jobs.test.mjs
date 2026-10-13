import test from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

// 离线验证管理员任务按钮与重传表单，不导入真实文件、不调用模型。
const dom = new JSDOM('<div id="learning-app"></div><div id="toast"></div>', { url: 'http://localhost:8001/#admin' });
globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.location = window.location;
const saved = { FormData, fetch, setTimeout, clearTimeout, setInterval, clearInterval };
globalThis.FormData = window.FormData; window.scrollTo = () => {};
const events = {}, root = document.getElementById('learning-app');
root.addEventListener = (name, callback) => { events[name] = callback; };
const intervals = new Map(); let timerId = 0;
globalThis.setTimeout = () => 0; globalThis.clearTimeout = () => {};
globalThis.setInterval = (callback, delay) => { const id = ++timerId; intervals.set(id, { callback, delay }); return id; };
globalThis.clearInterval = id => intervals.delete(id);
let jobs = ['source', 'legacy', 'delete', 'cancel', 'upload', 'running', 'complete'].map(id => ({ id, kb_id: 'kb',
  status: id === 'running' ? 'running' : id === 'complete' ? 'completed' : id === 'upload' ? 'partial' : 'failed',
  has_sources: id === 'source', completed: 0, total: 1, chunks: 0, message: '测试任务' }));
const operations = [];
const kbs = [{ id: 'kb', name: '保留知识库', status: 'ready', documents: 1, concepts: 23 }];
const response = data => ({ ok: true, status: 200, json: async () => structuredClone(data) });
globalThis.fetch = async (url, options={}) => {
  const path = url.slice(4);
  if (path === '/auth/me') return response({ id: 'admin', username: '管理员', is_admin: true });
  if (path === '/dashboard') return response({});
  if (['/plans/lesson', '/plans/quiz', '/bookmarks'].includes(path)) return response([]);
  if (path === '/knowledge-bases') return response(kbs);
  if (path === '/admin/jobs') return response(jobs);
  if (path.startsWith('/admin/jobs/')) {
    operations.push({ path, method: options.method, body: options.body });
    const id = path.split('/')[3];
    if (options.method === 'DELETE') jobs = jobs.filter(job => job.id !== id);
    else { const job = jobs.find(row => row.id === id); job.status = 'queued'; job.has_sources = true; }
    return response({ job_id: id, ok: true });
  }
  throw new Error(`Unexpected request: ${path}`);
};
await import('../web/app.js?import-jobs-regression');
const click = async (action, id) => events.click({ target: document.querySelector(`[data-action="${action}"][data-id="${id}"]`) });
const submit = async form => events.submit({ target: form, preventDefault() {} });

test('only failed or partial jobs expose restart and delete controls', () => {
  assert.equal(document.querySelectorAll('[data-action="restart-job"]').length, 5);
  assert.equal(document.querySelectorAll('[data-action="delete-job"]').length, 5);
  assert.equal(document.querySelector('[data-action="restart-job"][data-id="running"]'), null);
  assert.equal(document.querySelector('[data-action="delete-job"][data-id="complete"]'), null);
});

test('stored source restart posts once and refreshes queued task', async () => {
  await click('restart-job', 'source');
  assert.equal(operations.at(-1).path, '/admin/jobs/source/restart');
  assert.deepEqual(JSON.parse(operations.at(-1).body), {});
  assert.equal(document.querySelector('[data-action="restart-job"][data-id="source"]'), null);
});

test('legacy restart opens source form and polling preserves user input', async () => {
  await click('restart-job', 'legacy');
  const form = document.getElementById('retry-job-form-legacy');
  assert.equal(form.hidden, false);
  assert.match(form.textContent, /旧任务未保存文件位置/);
  form.querySelector('[name="path"]').value = 'F:/Java八股文/original.md';
  await [...intervals.values()].find(timer => timer.delay === 4000).callback();
  assert.equal(document.getElementById('retry-job-form-legacy'), form);
  assert.equal(form.querySelector('[name="path"]').value, 'F:/Java八股文/original.md');
  await submit(form);
  assert.equal(operations.at(-1).path, '/admin/jobs/legacy/restart');
  assert.equal(JSON.parse(operations.at(-1).body).path, 'F:/Java八股文/original.md');
});

test('retry form accepts documents and prefers upload to directory', async () => {
  await click('restart-job', 'upload');
  const form = document.getElementById('retry-job-form-upload');
  Object.defineProperty(form.querySelector('input[type=file]'), 'files', { value: [new window.File(['content'], 'original.md', { type: 'text/markdown' })] });
  form.querySelector('[name="path"]').value = 'F:/Java八股文';
  await submit(form);
  const request = operations.at(-1);
  assert.equal(request.path, '/admin/jobs/upload/upload-retry');
  assert.equal(request.body.getAll('files').length, 1);
  assert.equal(request.body.get('files').name, 'original.md');
});

test('delete removes only selected task and cancel closes retry form', async () => {
  await click('restart-job', 'cancel');
  const form = document.getElementById('retry-job-form-cancel');
  assert.equal(form.hidden, false);
  await click('cancel-job-retry', 'cancel');
  assert.equal(form.hidden, true);
  await click('delete-job', 'delete');
  assert.equal(operations.at(-1).path, '/admin/jobs/delete');
  assert.equal(operations.at(-1).method, 'DELETE');
  assert.equal(jobs.some(job => job.id === 'delete'), false);
  assert.equal(kbs[0].concepts, 23);
  assert.ok(root.textContent.includes('保留知识库'));
});

test.after(() => { Object.assign(globalThis, saved); dom.window.close(); });
