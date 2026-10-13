import { demoRequest } from './demo.js';
import { renderMarkdown } from './markdown.js';
import { copyCode } from './clipboard.js';
import { nextPendingLesson } from './learning.js';

const demo = new URLSearchParams(location.search).get('demo') === '1';
const root = document.getElementById?.('learning-app') || document.querySelector('#app');
const state = { user: null, page: 'dashboard', lessons: [], quiz: [], quizJob: null, quizTimer: null, quizPollError: '', quizDrafts: {}, importJobs: [], retryJob: null, bookmarks: [], kbs: [], dashboard: {}, selected: null, conversation: null, chatPending: null, filter: 'all', search: '', answer: '', authMode: 'login', authError: '', busy: false, epoch: 0, jobsTimer: null };
// 所有用户/模型/文档文本必须转义后再插入模板，防止持久化脚本注入。
const e = text => String(text ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const paths = {
  book: '<path d="M4 5h6c2 0 2 2 2 2s0-2 2-2h6v14h-6c-2 0-2 2-2 2s0-2-2-2H4z"/><path d="M12 7v14"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  quiz: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M9 10h6M9 14h6M9 18h3"/>',
  memory: '<path d="M9 4a3 3 0 0 0-5 3 4 4 0 0 0-1 7 4 4 0 0 0 5 6h2V4zm5 0a3 3 0 0 1 5 3 4 4 0 0 1 1 7 4 4 0 0 1-5 6h-2V4zM6 8l3 2M5 15l4-2M18 8l-3 2M19 15l-4-2"/>',
  bookmark: '<path d="M6 4h12v17l-6-4-6 4z"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18M8 15h2m4 0h2"/>',
  spark: '<path d="m12 3 2 6 6 3-6 2-2 7-2-7-7-2 7-3zM20 2v4M18 4h4"/>',
  leaf: '<path d="M5 19C-2 4 13 3 20 4c0 12-7 17-15 15zm0 0L16 8"/>',
  logout: '<path d="M10 4H4v16h6M10 12h11m-5-5 5 5-5 5"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  send: '<path d="m3 3 18 9-18 9 4-9-4-9zm4 9h14"/>',
  back: '<path d="M19 12H5m5-5-5 5 5 5"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  flame: '<path d="M12 2c0 6-8 8-8 14a8 8 0 0 0 16 0c0-4-3-6-4-8 0 3-2 4-3 5 0-4 1-7-1-11z"/>',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.book}</svg>`;
const btn = (text, action, cls = '', extra = '') => `<button class="btn ${cls}" data-action="${action}" ${extra}>${text}</button>`;
const brand = () => `<div class="brand"><span class="brand-mark">${icon('book')}</span><div><b>知序</b><small>KNOWLEDGE IN ORDER</small></div></div>`;
const dayString = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' });
const dateLabel = () => new Date().toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'long' });

async function api(path, method = 'GET', body) {
  const options = { method, credentials: 'same-origin' };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) { options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
  if (demo) return demoRequest(path, options);
  const controller = new AbortController();
  // 短请求有等待上限，助教保留较长等待；网络异常不能无限停留在加载页。
  options.signal = controller.signal;
  const timeout = setTimeout(() => controller.abort(), path.endsWith('/conversation') && method === 'POST' ? 150000 : 20000);
  try {
    const response = await fetch(`/api${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (controller.signal.aborted) throw new Error('连接超时');
    if (!response.ok) {
      if (response.status === 401 && state.user) { state.user = null; renderAuth(); }
      const detail = Array.isArray(data.detail) ? '输入格式不符合要求，请检查后重试。' : data.detail;
      throw new Error(detail || '请求失败，请稍后重试');
    }
    return data;
  } catch (err) {
    if (controller.signal.aborted) throw new Error('连接超时，请重试；已提交的后台测验任务会继续处理。');
    throw err;
  } finally { clearTimeout(timeout); }
}

let toastTimer;
function toast(message) {
  const el = document.querySelector('#toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 4500);
}

const titles = { dashboard: '学习概览', lesson: '每日学习', quiz: '每日测验', memory: '记忆计划', bookmarks: '我的收藏', knowledge: '知识库', admin: '知识库管理', detail: '学习空间' };
function shell(content) {
  notifyFrame();
  const nav = [['dashboard', '学习概览'], ['lesson', '每日学习'], ['quiz', '每日测验'], ['memory', '记忆计划'], ['bookmarks', '我的收藏'], ['knowledge', '知识库']];
  if (state.user.is_admin) nav.push(['admin', '知识库管理']);
  root.innerHTML = `<main class="workspace"><header class="workspace-tools"><nav class="workspace-tabs" aria-label="学习功能">${nav.map(([page, label]) => `<button class="${state.page === page ? 'active' : ''}" data-nav="${page}">${label}</button>`).join('')}</nav><div class="workspace-profile"><span>${e(state.user.username)}</span><span class="avatar">${e(state.user.username.slice(0, 1))}</span><button data-action="logout" aria-label="退出登录">${icon('logout')}</button></div></header>${demo ? `<div class="demo-banner"><span>当前使用示例数据 · 不读取真实文档，不调用大模型</span><button data-action="exit-demo">进入正式模式 ${icon('arrow')}</button></div>` : ''}<div class="content">${content}<footer class="footer"><span>© ${new Date().getFullYear()} 知序 · 每一天，多懂一点</span><span>LEARN. CONNECT. GROW.</span></footer></div></main>`;
}

function notifyFrame() {
  if (typeof window.dispatchEvent === 'function' && typeof window.CustomEvent === 'function')
    window.dispatchEvent(new window.CustomEvent('learning:state', { detail: { user: state.user, page: state.page } }));
}

function renderAuth() {
  state.page = 'auth';
  clearTimeout(state.quizTimer);
  state.quizDrafts = {}; state.quizJob = null;
  notifyFrame();
  clearInterval(state.jobsTimer);
  const register = state.authMode === 'register';
  root.innerHTML = `<main class="auth-layout"><section class="auth-art">${brand()}<div class="auth-copy"><div class="eyebrow">A LITTLE EVERY DAY</div><h1>知识有序，<br>成长有迹。</h1><p>把零散的知识，变成清晰的学习路径。<br>每天理解一点，让每一次学习都留下痕迹。</p></div></section><section class="auth-form-wrap"><form class="auth-form" id="auth-form"><span class="eyebrow">YOUR LEARNING SPACE</span><h2>${register ? '开启你的学习旅程' : '欢迎回来'}</h2><p>${register ? '创建账号，让知识一点点积累。' : '今天，又是让知识扎根的一天。'}</p><label class="field">用户名<input name="username" autocomplete="username" placeholder="输入用户名" required minlength="3" maxlength="64"></label><label class="field">密码<input name="password" type="password" autocomplete="${register ? 'new-password' : 'current-password'}" placeholder="至少 8 个字符" required minlength="8" maxlength="128"></label>${state.authError ? `<div class="form-error" role="alert">${e(state.authError)}</div>` : ''}<button class="btn" type="submit">${register ? '创建账号' : '登录学习空间'} ${icon('arrow')}</button><p class="auth-switch">${register ? '已有账号？' : '还没有账号？'} <button type="button" data-action="auth-switch">${register ? '去登录' : '创建账号'}</button></p><button class="auth-demo" type="button" data-action="demo">先看看学习空间</button></form></section></main>`;
}

function lessonRows(items, limit) {
  return items.slice(0, limit ?? items.length).map((item, i) => `<button class="lesson-row" data-item="${e(item.id)}"><span class="lesson-num">${item.submitted ? icon('check') : String(i + 1).padStart(2, '0')}</span><span class="lesson-text"><h3>${e(item.snapshot.question)}</h3><span class="lesson-meta"><span class="badge">${e(item.snapshot.category)}</span><span>${item.kind === 'choice' ? '单项选择' : item.kind === 'fill' ? '填空题' : ['基础理解', '核心概念', '深入理解', '进阶实践', '原理剖析'][item.snapshot.depth - 1] || '知识学习'}</span>${item.is_review ? '<span class="badge amber">记忆强化</span>' : '<span>· 新知识</span>'}</span></span><span class="row-state ${item.submitted ? 'complete' : ''}">${item.submitted ? icon('check') + (item.kind === 'lesson' ? '已学习' : item.correct ? '回答正确' : '需要巩固') : icon('clock') + '待完成'}</span>${icon('chevron')}</button>`).join('');
}

function dashboardView() {
  const d = state.dashboard, percent = Math.round((d.lesson_done || 0) / (d.lesson_total || 10) * 100);
  const history = d.history || [], max = Math.max(10, ...history.map(x => x.count));
  const bars = Array.from({ length: 7 }, (_, i) => { const day = new Date(); day.setDate(day.getDate() - 6 + i); const ds = day.toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' }); const count = history.find(x => x.day === ds)?.count || 0; return `<div class="bar-col"><div class="bar ${i === 6 ? 'today' : ''}" style="height:${Math.max(3, count / max * 55)}px" title="${count} 项完成"></div><small>${['日', '一', '二', '三', '四', '五', '六'][day.getDay()]}</small></div>`; }).join('');
  return `<section class="welcome"><div><div class="eyebrow">YOUR DAILY LEARNING</div><h1>今天，也向前一步。</h1><p>从理解一个概念开始，让知识成为自己的底气。</p></div><span class="date-chip">${icon('calendar')}${dateLabel()}</span></section><div class="dashboard-grid"><div class="main-stack"><section class="hero"><div class="hero-content"><span class="eyebrow">TODAY’S LEARNING JOURNEY</span><h2>每天 10 个知识点，<br><span>让成长有迹可循。</span></h2><p>循着知识的脉络，由浅入深。<br>与你的专属助教一起，把问题真正弄懂。</p>${btn(`开始今日学习 ${icon('arrow')}`, 'start-lesson')}</div></section><div class="stats"><article class="stat"><div class="stat-head">${icon('book')}累计学习知识</div><div class="stat-value"><b>${d.learned || 0}</b><span>个</span></div><div class="stat-footer"><span>已完成的知识点</span><em>持续积累中</em></div></article><article class="stat"><div class="stat-head">${icon('memory')}待巩固知识</div><div class="stat-value"><b>${d.due || 0}</b><span>个</span></div><div class="stat-footer"><span>到期复习优先安排</span><em>温故知新</em></div></article><article class="stat"><div class="stat-head">${icon('quiz')}今日测验正确率</div><div class="stat-value"><b>${d.accuracy === null || d.accuracy === undefined ? '—' : d.accuracy}</b><span>${d.accuracy == null ? '' : '%'}</span></div><div class="stat-footer"><span>${d.quiz_done || 0} / ${d.quiz_total || 13} 题已完成</span><em>${d.quiz_unlocked ? '检验理解' : '次日解锁'}</em></div></article></div><section><div class="section-head"><h2>今日学习清单 <small>${state.lessons.length ? `${state.lessons.length} 个知识点` : '等待开启'}</small></h2><button class="text-link" data-nav="lesson">查看全部 ${icon('arrow')}</button></div><div class="panel">${state.lessons.length ? lessonRows(state.lessons, 5) : empty('从今天的第一个知识点开始', '导入知识库后，点击开始学习生成今日计划。', 'book')}${state.lessons.length ? `<div class="more-row"><button data-action="more-lesson">${icon('plus')}再学一点，添加更多内容</button></div>` : ''}</div></section><section class="review-banner"><span class="review-icon">${icon('quiz')}</span><div><h3>${d.quiz_unlocked ? '把昨天学到的，变成今天记得的。' : '学过的知识，值得再见一次。'}</h3><p>${d.quiz_unlocked ? '10 道选择题 + 3 道填空题，检验与巩固你的理解。' : '完成今日学习后，第二天解锁专属知识测验。'}</p></div><button class="text-link" data-action="start-quiz">${d.quiz_unlocked ? '开始测验' : '了解测验'} ${icon('arrow')}</button></section></div><aside class="right-stack"><section class="panel daily-progress"><div class="panel-title"><h3>今日学习进度</h3>${icon('spark')}</div><div class="ring"><svg viewBox="0 0 142 142"><circle class="ring-track" cx="71" cy="71" r="60"/><circle class="ring-fill" cx="71" cy="71" r="60" stroke-dasharray="${percent / 100 * 377} 377"/></svg><div><strong>${percent}<span>%</span></strong><small>一点点，也很了不起</small></div></div><div class="progress-legend"><span><i></i>已学习 ${d.lesson_done || 0} 个</span><span><i></i>待学习 ${Math.max(0, (d.lesson_total || 10) - (d.lesson_done || 0))} 个</span></div><div class="progress-line"><span>今日目标</span><strong>理解，比速度重要</strong></div></section><section class="panel activity"><div class="panel-title"><h3>本周学习节奏</h3>${icon('calendar')}</div><div class="bars">${bars}</div><p class="activity-note">${icon('leaf')}每一次回来，都在为成长添一笔。</p></section><section class="panel insight"><span class="eyebrow">${icon('spark')}A MOMENT TO THINK</span><blockquote>“学习不是把知识装进头脑，<br>而是让它在思考中生根。”</blockquote><small>保持好奇，也给自己一点时间。</small></section></aside></div>`;
}

function empty(title, description, symbol = 'book') { return `<div class="empty">${icon(symbol)}<h3>${e(title)}</h3><p>${e(description)}</p></div>`; }
function pageHead(title, text, eyebrow) { return `<div class="page-head"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${text}</p></div>`; }
const quizGenerating = () => ['queued', 'running'].includes(state.quizJob?.status);
const shouldPollQuiz = () => quizGenerating() || (!state.quiz.length && state.dashboard.quiz_unlocked && !state.quizJob);
function quizGenerationHTML() {
  if (state.quizPollError) return `<div class="generation-note" role="alert">${e(state.quizPollError)} ${btn('重新查看进度', 'refresh-quiz', 'secondary')}</div>`;
  const job = state.quizJob;
  if (quizGenerating()) return `<div class="generation-note" role="status" aria-live="polite"><span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span><strong>${job.status === 'queued' ? '等待生成' : '正在生成'} · ${job.completed} / ${job.total} 题</strong><progress aria-label="测验生成进度" max="${job.total}" value="${job.completed}"></progress><p>可以先浏览其他页面，完成后会自动显示。</p></div>`;
  if (job?.status === 'failed') return `<div class="generation-note generation-error" role="alert">${e(job.message)} 点击下方按钮可重新生成。</div>`;
  return '';
}
function plansView(kind) {
  const quiz = kind === 'quiz', items = quiz ? state.quiz : state.lessons;
  const filtered = items.filter(x => (state.filter === 'all' || state.filter === 'pending' && !x.submitted || state.filter === 'done' && x.submitted || state.filter === 'review' && x.is_review) && x.snapshot.question.toLowerCase().includes(state.search.toLowerCase()));
  return pageHead(quiz ? '让理解，经得起检验。' : '顺着脉络，一点点深入。', quiz ? '每天北京时间（UTC+8）06:00自动准备，也可手动生成。错题会进入更频繁的复习安排。' : '前置知识优先，到期知识再见。每一题都配有答案、分析和独立助教。', quiz ? 'PRACTICE & UNDERSTAND' : 'LEARN IN ORDER') + `<div class="tool-row">${[['all', '全部'], ['pending', '待完成'], ['done', '已完成'], ['review', '记忆强化']].map(([value, label]) => `<button class="filter ${state.filter === value ? 'active' : ''}" data-filter="${value}">${label}</button>`).join('')}<input class="search" id="list-search" value="${e(state.search)}" placeholder="搜索今日内容…" aria-label="搜索今日内容"></div>${quiz ? `<div id="quiz-generation-status">${quizGenerationHTML()}</div>` : ''}<section class="panel full-list">${filtered.length ? lessonRows(filtered) : empty(items.length ? '没有匹配的内容' : quiz && !state.dashboard.quiz_unlocked ? '明天，检验今天的理解' : '你的今日清单还未开启', items.length ? '试试其他筛选或搜索词。' : quiz ? '完成学习后的第二天可生成 10 道选择题和 3 道填空题。' : '点击下方按钮，开始今日学习。', quiz ? 'quiz' : 'book')}<div class="more-row">${btn(`${icon('plus')}${items.length ? quiz ? '更多练习 · 添加 13 题' : '更多学习 · 添加 10 条' : quiz ? '生成今日测验' : '生成今日学习'}`, items.length ? `more-${kind}` : `start-${kind}`, 'secondary', quiz && quizGenerating() ? 'disabled' : '')}</div></section>`;
}

function knowledgeView() {
  return pageHead('你的知识，从这里出发。', '知识库由管理员统一维护。学习记录、练习和对话只属于你。', 'YOUR KNOWLEDGE LIBRARY') + (state.kbs.length ? `<div class="kb-grid">${state.kbs.map(k => `<article class="panel kb-card">${icon('database')}<div class="inline-buttons"><h3>${e(k.name)}</h3><span class="badge ${k.status === 'ready' ? '' : 'amber'}">${({ ready: '可学习', empty: '等待导入', indexing: '整理中', deleting: '删除中' })[k.status] || e(k.status)}</span></div><p>${e(k.description || '每一份资料，都可以成为成长的起点。')}</p><div class="meta"><span>${k.documents} 份文档</span><span>${k.concepts} 个知识点</span></div>${btn('开始学习 ' + icon('arrow'), 'start-lesson', 'secondary')}</article>`).join('')}</div>` : empty('还没有知识库', state.user.is_admin ? '请前往知识库管理，创建知识库并导入资料。' : '管理员导入资料后，会在这里展示。', 'database'));
}

function bookmarksView() {
  return pageHead('值得留下的，不止答案。', '收藏题目与完整对话。即使每日刷新，也可以回到这里继续追问。', 'KEEP YOUR DISCOVERIES') + `<div class="panel">${state.bookmarks.length ? state.bookmarks.map(c => `<article class="bookmark-row"><div><span class="badge">${e(c.snapshot.category)}</span><h3 style="margin-top:9px">${e(c.snapshot.question)}</h3><p>${c.messages.length} 条对话 · 题目与对话已保存</p></div>${btn('继续问答 ' + icon('arrow'), 'open-bookmark', 'secondary', `data-id="${e(c.item_id)}"`)}</article>`).join('') : empty('把理解过程也留下来', '在任意题目的助教面板点击收藏，即可保存题目和对话。', 'bookmark')}</div>`;
}

function memoryView(rows) {
  return pageHead('再次相遇，记得更牢。', '按 1、3、7、14、30、60 天安排间隔复习；答错后回到次日复习。', 'REMEMBER WITH TIME') + `<div class="panel table-wrap">${rows.length ? `<table class="memory-table"><thead><tr><th>知识点</th><th>分类</th><th>下次复习</th><th>复习阶段</th><th>错题次数</th></tr></thead><tbody>${rows.map(r => `<tr><td>${e(r.title)}</td><td><span class="badge">${e(r.category)}</span></td><td>${r.next_review <= dayString() ? '<span class="badge amber">今日到期</span>' : e(r.next_review)}</td><td>${r.stage + 1} / 6</td><td>${r.mistakes}</td></tr>`).join('')}</tbody></table>` : empty('知识刚开始生根', '完成学习后，这里会显示你的专属复习计划。', 'memory')}</div>`;
}

function jobsHTML(jobs) {
  return jobs.length ? jobs.map(j => {
    const inactive = ['failed', 'partial'].includes(j.status);
    return `<div class="job"><strong>${({ queued: '等待中', running: '处理中', completed: '已完成', partial: '部分完成', failed: '未完成' })[j.status] || e(j.status)}</strong> · ${j.completed}/${j.total} 文件 · ${j.chunks} 片段<p>${e(j.message)}</p><progress value="${j.completed}" max="${j.total || 1}" aria-label="导入进度"></progress>${inactive ? `<div class="job-actions">${btn('重启任务', 'restart-job', 'secondary', `data-id="${e(j.id)}"`)}${j.has_sources ? btn('重新选择文档', 'choose-job-files', 'secondary', `data-id="${e(j.id)}"`) : ''}${btn('删除任务', 'delete-job', 'danger', `data-id="${e(j.id)}"`)}</div><form id="retry-job-form-${e(j.id)}" class="job-retry-form" data-job-id="${e(j.id)}" ${state.retryJob === j.id ? '' : 'hidden'}><p>${j.has_sources ? '选择要重新导入的资料。' : '此旧任务未保存文件位置，请重新选择同一批文档或目录。'}已成功入库的文档会自动跳过。</p><label class="field">重新上传文档<input name="files" type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt,.rst,.csv,.json,.yaml,.yml,.java,.log"></label><label class="field">或填写服务器本地文件、目录<input name="path" placeholder="服务器授权目录内的文件路径"></label><div class="inline-buttons"><button type="submit" class="btn">重新开始导入</button>${btn('取消', 'cancel-job-retry', 'secondary', `data-id="${e(j.id)}"`)}</div></form>` : ''}</div>`;
  }).join('') : '<p class="pending-note">提交文档后，导入进度会在这里显示。</p>';
}
function adminView(jobs) {
  return pageHead('让资料，成为可学习的知识。', '创建知识库后上传文档，或导入指定的本地目录。文档将被解析、分类、建立前置关系并向量化。', 'KNOWLEDGE WORKSPACE') + `<div class="admin-layout"><form id="create-kb-form" class="panel admin-form"><h3>新增知识库</h3><label class="field">知识库名称<input name="name" required maxlength="120" placeholder="例如：Java 面试知识库"></label><label class="field">知识库说明<textarea name="description" maxlength="2000" placeholder="这份知识库包含什么？"></textarea></label><button type="submit" class="btn">${icon('plus')}创建知识库</button></form><form id="import-form" class="panel admin-form"><h3>导入知识文档</h3><label class="field">选择知识库<select name="kb_id" required><option value="">请选择知识库</option>${state.kbs.filter(k => k.status !== 'deleting').map(k => `<option value="${e(k.id)}" ${k.status === 'indexing' ? 'disabled' : ''}>${e(k.name)}${k.status === 'indexing' ? ' · 处理中' : ''}</option>`).join('')}</select></label><label class="field">直接上传文档<input name="files" type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt,.rst,.csv,.json,.yaml,.yml,.java,.log"></label><p class="pending-note">支持 PDF、DOCX、Markdown、TXT 等。单文件最大 30 MB；扫描 PDF 请先 OCR。上传文档优先于目录。</p><label class="field">或导入服务器本地目录<input name="path" placeholder="服务器授权的导入目录"></label><button type="submit" class="btn">${icon('database')}开始解析与入库</button></form></div><section class="panel jobs"><div class="section-head"><h2>导入任务</h2><small>自动更新进度</small></div><div id="jobs-list">${jobsHTML(jobs)}</div></section><section style="margin-top:26px"><div class="section-head"><h2>已有知识库</h2></div><div class="kb-grid">${state.kbs.map(k => `<article class="panel kb-card"><h3>${e(k.name)}</h3><p>${k.documents} 份文档 · ${k.concepts} 个知识点 · ${e(k.status)}</p>${btn('删除知识库', 'delete-kb', 'danger', `data-id="${e(k.id)}" ${k.status === 'indexing' ? 'disabled' : ''}`)}</article>`).join('')}</div></section>`;
}

function chatMessagesHTML() {
  const messages = (state.conversation?.messages || []).map(m => `<div class="message ${m.role === 'user' ? 'user' : 'assistant'}">${m.role === 'user' ? e(m.content) : `<div class="markdown-body">${renderMarkdown(m.content)}</div>`}${m.sources?.length ? `<div class="chat-source">${m.sources.map(s => `[${s.index}] ${e(s.source)}`).join('<br>')}</div>` : ''}</div>`).join('');
  if (state.chatPending?.itemId !== state.selected?.id) return messages;
  // 提问立即入屏；占位动画随真实请求结束而消失，不伪造模型回复。
  return messages + `<div class="message user pending-question">${e(state.chatPending.message)}</div><div class="message thinking" role="status" aria-live="polite"><span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>正在思考…</span></div>`;
}

async function sendChat(message) {
  const itemId = state.selected.id;
  const epoch = state.epoch;
  const pending = { itemId, message };
  state.chatPending = pending;
  renderPage();
  let failed = false;
  try {
    const conversation = await api(`/items/${itemId}/conversation`, 'POST', { message });
    // 离开题目后返回的响应不得覆盖其他题目的独立会话。
    if (state.page === 'detail' && state.selected?.id === itemId && state.epoch === epoch) state.conversation = conversation;
  } catch (err) {
    failed = true;
    throw err;
  } finally {
    if (state.chatPending === pending) state.chatPending = null;
    if (state.user && state.page === 'detail' && state.selected?.id === itemId && state.epoch === epoch) {
      renderPage();
      const input = document.querySelector('#chat-input');
      // 失败时恢复原问题，便于重试；临时问题不留在历史中造成重复。
      if (failed) input.value = message;
      input.focus();
    }
  }
}

function lessonContinuationHTML(item) {
  if (item.kind !== 'lesson' || !item.submitted || item.day !== dayString()) return '';
  // 完成后由用户主动进入下一题，不自动跳转打断阅读或问答。
  const next = nextPendingLesson(state.lessons, item.id, dayString());
  return next ? btn('下一问 ' + icon('arrow'), 'next-lesson') : btn('查看学习清单 ' + icon('arrow'), 'finish-lessons', 'secondary');
}

function saveQuizDraft() {
  const item = state.selected;
  if (state.page !== 'detail' || !item || item.kind === 'lesson' || item.submitted) return;
  if (item.kind === 'fill') state.answer = document.querySelector('#fill-answer')?.value ?? state.answer;
  state.quizDrafts[item.id] = state.answer;
}

function quizNavigationHTML(item) {
  const index = state.quiz.findIndex(row => row.id === item.id);
  if (item.kind === 'lesson' || item.day !== dayString() || index < 0) return '';
  // 可以跳题但不自动提交；第一题和最后一题明确禁用越界按钮。
  return `<nav class="quiz-navigation" aria-label="测验题目导航">${btn(icon('back') + '上一题', 'previous-quiz', 'secondary', index === 0 ? 'disabled' : '')}<span>第 ${index + 1} / ${state.quiz.length} 题</span>${btn('下一题' + icon('arrow'), 'next-quiz', 'secondary', index === state.quiz.length - 1 ? 'disabled' : '')}</nav>`;
}

function detailView() {
  const item = state.selected, snap = item.snapshot, quiz = item.kind !== 'lesson';
  const answer = quiz ? item.kind === 'choice' ? `<div class="options">${(snap.options || []).map((option, i) => { const letter = 'ABCD'[i]; return `<button class="option ${state.answer === letter ? 'selected' : ''} ${item.submitted && snap.answer === letter ? 'correct' : ''} ${item.submitted && item.user_answer === letter && !item.correct ? 'wrong' : ''}" data-option="${letter}" ${item.submitted ? 'disabled' : ''}><span class="option-letter">${letter}</span>${e(option)}</button>`; }).join('')}</div>` : `<label class="field">填写你的答案<input id="fill-answer" class="fill-answer" value="${e(item.user_answer || state.answer)}" placeholder="想一想，再写下答案…" ${item.submitted ? 'disabled' : ''}></label>` : `<div class="answer-section"><h3>${icon('book')}参考答案</h3><div class="prose markdown-body">${renderMarkdown(snap.answer)}</div></div>`;
  return `<button class="back" data-nav="${state.bookmarks.some(c => c.item_id === item.id) && item.day !== dayString() ? 'bookmarks' : quiz ? 'quiz' : 'lesson'}">${icon('back')}返回学习清单</button><div class="detail-grid"><article class="panel question-card"><div class="detail-meta"><span class="badge">${e(snap.category)}</span><span class="badge gray">${quiz ? item.kind === 'choice' ? '选择题' : '填空题' : `深度 ${snap.depth} / 5`}</span>${item.is_review ? '<span class="badge amber">记忆强化</span>' : ''}<small>${item.day === dayString() ? '今日学习' : '已收藏题目'}</small></div><h2>${e(snap.question)}</h2>${answer}${item.submitted && quiz ? `<div class="result ${item.correct ? '' : 'wrong'}">${item.correct ? '回答正确，继续保持。' : '这次没答对，已加入针对性复习。'} 标准答案：${e(snap.answer)}</div>` : ''}${!quiz || item.submitted ? `<section class="answer-section"><h3>${icon('spark')}理解与分析</h3><div class="prose markdown-body">${renderMarkdown(snap.analysis)}</div></section>` : ''}<div class="source-note">${icon('database')} 知识来源：${e(snap.source || '题目快照')}${snap.prerequisites?.length ? `<br>前置知识：${e(snap.prerequisites.join('、'))}` : ''}</div><div class="answer-actions">${item.submitted ? `<span class="badge">${icon('check')}已完成${!item.correct ? ' · 下次重点巩固' : ''}</span>` : item.day === dayString() ? quiz ? btn('提交答案 ' + icon('check'), 'submit-quiz') : btn('我理解了 ' + icon('check'), 'remembered') + btn('还不熟悉，重点复习', 'forgotten', 'secondary') : ''}${lessonContinuationHTML(item)}${btn(icon('bookmark') + (state.conversation?.saved ? '已收藏' : '收藏题目与对话'), 'save', 'secondary')}</div>${quizNavigationHTML(item)}</article><aside class="panel chat-panel"><header class="chat-header"><span class="chat-avatar">${icon('spark')}</span><div><h3>你的专属学习助教</h3><small>独立对话 · 只围绕当前题目</small></div><button class="save-btn ${state.conversation?.saved ? 'saved' : ''}" data-action="save" aria-label="收藏题目与对话">${icon('bookmark')}</button></header><div class="chat-messages" id="chat-messages" aria-busy="${state.chatPending?.itemId === item.id}"><div class="chat-intro">${demo ? '这是助教界面的演示。正式模式会使用知识库资料回答，并列出来源。' : '哪里还没弄懂？可以让我换一种方式解释，或者给你一个具体的例子。'}</div>${chatMessagesHTML()}</div><div class="chat-prompts"><button ${state.chatPending?.itemId === item.id ? 'disabled' : ''} data-prompt="用一个例子帮我理解这道题">举个例子</button><button ${state.chatPending?.itemId === item.id ? 'disabled' : ''} data-prompt="这道题最容易混淆的地方是什么？">常见误区</button><button ${state.chatPending?.itemId === item.id ? 'disabled' : ''} data-prompt="能用更简单的话解释吗？">换种方式解释</button></div><form id="chat-form" class="chat-form"><label class="sr-only" for="chat-input">向当前题目助教提问</label><textarea id="chat-input" ${state.chatPending?.itemId === item.id ? 'disabled' : ''} name="message" rows="1" maxlength="4000" required placeholder="关于这道题，我想问…"></textarea><button type="submit" ${state.chatPending?.itemId === item.id ? 'disabled' : ''} aria-label="发送问题">${icon('send')}</button></form><p class="chat-footnote">未收藏对话在次日刷新，收藏后可继续问答。</p></aside></div>`;
}

async function navigate(page, updateHash = true) {
  saveQuizDraft();
  state.retryJob = null;
  clearTimeout(state.quizTimer);
  clearInterval(state.jobsTimer);
  const epoch = ++state.epoch; state.page = page; state.filter = 'all'; state.search = '';
  if (updateHash) location.hash = page;
  shell('<div class="loading">正在打开你的学习空间…</div>');
  try {
    const tasks = [api('/dashboard'), api('/plans/lesson'), api('/plans/quiz'), api('/knowledge-bases'), api('/bookmarks')];
    const [dashboard, lessons, quiz, kbs, bookmarks] = await Promise.all(tasks);
    if (epoch !== state.epoch) return;
    Object.assign(state, { dashboard, lessons, quiz, kbs, bookmarks });
    if (page === 'quiz') {
      const status = await api('/plans/quiz/generation');
      if (epoch !== state.epoch) return;
      state.quizJob = status.job; state.quizPollError = '';
    }
    if (page === 'memory') {
      const rows = await api('/memory'); if (epoch === state.epoch) shell(memoryView(rows));
    } else if (page === 'admin') {
      if (!state.user.is_admin) return navigate('dashboard');
      const jobs = await api('/admin/jobs'); if (epoch !== state.epoch) return;
      state.importJobs = jobs;
      shell(adminView(jobs));
      // 编辑重试文件或提交操作时保留表单，轮询不能覆盖已选文件与输入。
      state.jobsTimer = setInterval(async () => { try { const current = await api('/admin/jobs'); if (state.epoch === epoch && state.page === 'admin') { state.importJobs = current; if (!state.retryJob && !state.busy && document.querySelector('#jobs-list')) document.querySelector('#jobs-list').innerHTML = jobsHTML(current); } } catch { clearInterval(state.jobsTimer); } }, 4000);
    } else { renderPage(); if (page === 'quiz') pollQuizGeneration(); }
  } catch (err) { if (state.user && epoch === state.epoch) shell(empty('学习空间暂时未能打开', err.message)); toast(err.message); }
}

function renderPage() {
  const views = { dashboard: dashboardView, lesson: () => plansView('lesson'), quiz: () => plansView('quiz'), knowledge: knowledgeView, bookmarks: bookmarksView, detail: detailView };
  shell((views[state.page] || dashboardView)());
  if (state.page === 'detail') { const el = document.querySelector('#chat-messages'); el.scrollTop = el.scrollHeight; }
}

async function openItem(id, bookmark = false) {
  saveQuizDraft();
  const epoch = state.epoch;
  const conversation = await api(`/items/${id}/conversation`);
  if (state.epoch !== epoch) return;
  let item = [...state.lessons, ...state.quiz].find(x => x.id === id);
  if (!item && bookmark) item = conversation.item || { id, day: 'saved', kind: conversation.snapshot.options?.length ? 'choice' : 'lesson', submitted: true, correct: true, snapshot: conversation.snapshot };
  if (!item) throw new Error('题目不存在，请刷新清单');
  state.selected = item; state.conversation = conversation; state.answer = item.submitted ? item.user_answer || '' : state.quizDrafts[item.id] ?? item.user_answer ?? ''; state.page = 'detail';
  ++state.epoch;
  clearTimeout(state.quizTimer);
  clearInterval(state.jobsTimer); renderPage(); window.scrollTo(0, 0);
}

function pollQuizGeneration() {
  clearTimeout(state.quizTimer);
  if (state.page !== 'quiz' || !shouldPollQuiz() || !state.user) return;
  const epoch = state.epoch;
  state.quizTimer = setTimeout(async () => {
    try {
      const status = await api('/plans/quiz/generation');
      if (state.epoch !== epoch || state.page !== 'quiz') return;
      const previousStatus = state.quizJob?.status;
      state.quizJob = status.job; state.quizPollError = '';
      if (!quizGenerating()) {
        const [quiz, dashboard] = await Promise.all([api('/plans/quiz'), api('/dashboard')]);
        if (state.epoch !== epoch) return;
        const changed = quiz.length !== state.quiz.length || previousStatus !== state.quizJob?.status;
        Object.assign(state, { quiz, dashboard });
        if (changed) renderPage();
        pollQuizGeneration();
      } else {
        // 更新进度区域即可，不打断搜索框输入，也不会刷新别的题目或页面。
        if (previousStatus !== state.quizJob?.status) renderPage();
        else {
          const statusElement = document.querySelector('#quiz-generation-status');
          if (statusElement) statusElement.innerHTML = quizGenerationHTML();
        }
        pollQuizGeneration();
      }
    } catch (err) {
      if (state.epoch !== epoch || !state.user) return;
      state.quizPollError = '暂时无法读取测验状态，请重新查看。'; renderPage();
    }
  }, quizGenerating() ? 3000 : 15000);
}

async function generatePlan(kind, more = false) {
  const epoch = state.epoch;
  if (kind === 'quiz' && !state.dashboard.quiz_unlocked) { await navigate('quiz'); toast('完成学习后的第二天解锁测验。'); return; }
  const result = await api(`/plans/${kind}`, 'POST', { more });
  // React导航允许离开等待页面，迟到的生成结果不能把用户强制带回旧页面。
  if (state.epoch !== epoch) return;
  if (kind === 'quiz' && result.job) {
    state.quizJob = result.job; state.quizPollError = ''; state.quiz = result.items;
    if (state.page === 'quiz') { renderPage(); pollQuizGeneration(); }
    else await navigate('quiz');
    return;
  }
  await navigate(kind);
  if (result.message) toast(result.message);
  else if (more) toast(`已添加 ${result.added} 条${kind === 'quiz' ? '练习' : '学习内容'}`);
  if (!more && result.items.length && kind === 'lesson') await openItem(result.items.find(x => !x.submitted)?.id || result.items[0].id);
}

async function perform(action, element) {
  if (action === 'menu') { document.querySelector('.sidebar')?.classList.toggle('open'); document.querySelector('.menu-overlay')?.classList.toggle('open'); return; }
  if (action === 'demo') { location.href = '/?demo=1'; return; }
  if (action === 'exit-demo') { location.href = '/'; return; }
  if (action === 'auth-switch') { state.authMode = state.authMode === 'login' ? 'register' : 'login'; state.authError = ''; renderAuth(); return; }
  if (action === 'logout') { if (demo) { location.href = '/'; return; } await api('/auth/logout', 'POST'); state.user = null; state.quizDrafts = {}; state.quizJob = null; clearTimeout(state.quizTimer); state.epoch++; renderAuth(); return; }
  if (action.startsWith('start-') || action.startsWith('more-')) { await generatePlan(action.split('-')[1], action.startsWith('more-')); return; }
  if (action === 'open-bookmark') { await openItem(element.dataset.id, true); return; }
  if (action === 'restart-job' || action === 'choose-job-files') {
    const id = element.dataset.id;
    const job = state.importJobs.find(row => row.id === id);
    if (!job) throw new Error('任务不存在，请刷新任务列表。');
    if (action === 'choose-job-files' || !job.has_sources) {
      if (state.retryJob && state.retryJob !== id) {
        const previous = document.getElementById(`retry-job-form-${state.retryJob}`);
        if (previous) previous.hidden = true;
      }
      state.retryJob = id;
      // 直接打开当前行的表单，不重绘页面，保留管理员正在填写的内容。
      const form = document.getElementById(`retry-job-form-${id}`);
      if (form) { form.hidden = false; form.querySelector('input')?.focus(); }
      return;
    }
    await api(`/admin/jobs/${id}/restart`, 'POST', {});
    await navigate('admin'); toast('任务已重新启动，已成功入库的文档会自动跳过。'); return;
  }
  if (action === 'cancel-job-retry') {
    state.retryJob = null;
    const form = document.getElementById(`retry-job-form-${element.dataset.id}`);
    if (form) form.hidden = true;
    return;
  }
  if (action === 'delete-job') {
    await api(`/admin/jobs/${element.dataset.id}`, 'DELETE');
    await navigate('admin'); toast('任务记录已删除，知识库内容保留。'); return;
  }
  if (action === 'refresh-quiz') { await navigate('quiz'); return; }
  if (action === 'previous-quiz' || action === 'next-quiz') {
    const index = state.quiz.findIndex(item => item.id === state.selected?.id);
    const next = state.quiz[index + (action === 'next-quiz' ? 1 : -1)];
    if (index >= 0 && next) await openItem(next.id);
    return;
  }
  if (action === 'next-lesson') {
    // 重新读取计划，兼容另一个窗口已完成题目、手动追加或日期切换。
    state.lessons = await api('/plans/lesson');
    const next = nextPendingLesson(state.lessons, state.selected.id, dayString());
    if (next) await openItem(next.id);
    else { await navigate('lesson'); toast('当前清单已完成，可以添加更多学习内容。'); }
    return;
  }
  if (action === 'finish-lessons') { await navigate('lesson'); toast('当前清单已完成，可以添加更多学习内容。'); return; }
  if (action === 'save') {
    const result = await api(`/items/${state.selected.id}/save`, 'POST', { saved: !state.conversation.saved });
    state.conversation.saved = result.saved; state.bookmarks = await api('/bookmarks'); renderPage(); toast(result.saved ? '题目与对话已收藏，可在之后继续问答。' : '已取消收藏'); return;
  }
  if (['remembered', 'forgotten', 'submit-quiz'].includes(action)) {
    const item = state.selected;
    if (action === 'submit-quiz') {
      if (item.kind === 'fill') state.answer = document.querySelector('#fill-answer').value;
      if (!state.answer.trim()) throw new Error('请先选择或填写答案');
    }
    // 一并提交选项版本，旧页面不能按调整前的位置提交答案。
    const result = await api(`/items/${item.id}/answer`, 'POST', { answer: state.answer, remembered: action !== 'forgotten', option_order_version: item.snapshot.option_order_version });
    state.selected = result;
    delete state.quizDrafts[item.id];
    const array = item.kind === 'lesson' ? state.lessons : state.quiz;
    const index = array.findIndex(x => x.id === item.id); if (index >= 0) array[index] = result;
    state.dashboard = await api('/dashboard'); renderPage(); toast(result.correct ? '已完成，知识正在一点点积累。' : '已安排次日重点复习。'); return;
  }
  if (action === 'delete-kb') {
    const kb = state.kbs.find(x => x.id === element.dataset.id);
    if (!confirm(`确定删除“${kb.name}”及其知识数据？已收藏题目与对话会保留。此操作无法撤销。`)) return;
    await api(`/admin/knowledge-bases/${kb.id}`, 'DELETE'); await navigate('admin'); toast('知识库已删除');
  }
}

root.addEventListener('click', async event => {
  const copy = event.target.closest('[data-copy-code]');
  // 复制无需重绘页面，也不被助教的等待状态阻塞。
  if (copy?.dataset.copyCode !== undefined) {
    if (copy.disabled) return;
    copy.disabled = true;
    try { await copyCode(copy); toast('代码已复制'); }
    catch (err) { toast(err.message); }
    finally { copy.disabled = false; }
    return;
  }
  const el = event.target.closest('[data-nav],[data-action],[data-item],[data-filter],[data-option],[data-prompt]');
  if (!el || el.disabled || state.busy) return;
  if (el.dataset.nav) { await navigate(el.dataset.nav); return; }
  if (el.dataset.filter) { state.filter = el.dataset.filter; renderPage(); return; }
  if (el.dataset.option) { state.answer = el.dataset.option; renderPage(); return; }
  if (el.dataset.prompt) { const input = document.querySelector('#chat-input'); input.value = el.dataset.prompt; input.focus(); return; }
  state.busy = true; el.disabled = true;
  try { if (el.dataset.item) await openItem(el.dataset.item); else await perform(el.dataset.action, el); }
  catch (err) { toast(err.message); }
  finally { state.busy = false; el.disabled = false; }
});
root.addEventListener('input', event => {
  if (event.target.id === 'fill-answer') { state.answer = event.target.value; saveQuizDraft(); }
  if (event.target.id === 'list-search') {
    state.search = event.target.value; const pos = event.target.selectionStart; renderPage();
    const input = document.querySelector('#list-search'); input.focus(); input.setSelectionRange(pos, pos);
  }
});
root.addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy) return;
  state.busy = true; const form = event.target, button = form.querySelector('button[type="submit"]'); if (button) button.disabled = true;
  try {
    const fields = new FormData(form);
    if (form.id === 'auth-form') {
      state.user = await api(`/auth/${state.authMode}`, 'POST', { username: fields.get('username'), password: fields.get('password') });
      state.authError = ''; await navigate('dashboard');
    } else if (form.id === 'chat-form') {
      const message = fields.get('message').trim(); if (!message) throw new Error('请输入问题');
      await sendChat(message);
    } else if (form.id === 'create-kb-form') {
      await api('/admin/knowledge-bases', 'POST', { name: fields.get('name').trim(), description: fields.get('description') });
      await navigate('admin'); toast('知识库已创建，现在可以导入资料。');
    } else if (form.id.startsWith('retry-job-form-')) {
      const id = form.dataset.jobId, files = form.querySelector('input[type=file]').files;
      if (files.length) {
        const body = new FormData(); for (const file of files) body.append('files', file);
        await api(`/admin/jobs/${id}/upload-retry`, 'POST', body);
      } else {
        const path = String(fields.get('path') || '').trim();
        if (!path) throw new Error('请选择文档或填写本地文件、目录。');
        await api(`/admin/jobs/${id}/restart`, 'POST', { path });
      }
      state.retryJob = null; await navigate('admin'); toast('任务已重新启动，已完成的文档会自动跳过。');
    } else if (form.id === 'import-form') {
      const kb = fields.get('kb_id');
      const files = form.querySelector('input[type=file]').files;
      if (files.length) { const body = new FormData(); for (const f of files) body.append('files', f); await api(`/admin/knowledge-bases/${kb}/upload`, 'POST', body); }
      else await api(`/admin/knowledge-bases/${kb}/import-local`, 'POST', { path: fields.get('path') });
      await navigate('admin'); toast('导入已提交，可在任务列表查看进度。');
    }
  } catch (err) {
    if (form.id === 'auth-form') { state.authError = err.message; renderAuth(); }
    else toast(err.message);
  } finally { state.busy = false; if (button) button.disabled = false; }
});

// 跨日主动刷新今日计划；收藏中的旧题保持可访问。
let activeDay = dayString();
setInterval(() => { const day = dayString(); if (day !== activeDay && state.user) { activeDay = day; if (state.page !== 'detail' || !state.conversation?.saved) { toast('新的一天开始了，学习空间已刷新。'); navigate('dashboard'); } } }, 30000);
window.addEventListener('popstate', () => { if (document.getElementById?.('learning-app')) return; const page = location.hash.slice(1); if (state.user && titles[page] && page !== 'detail') navigate(page, false); });

// 首页保持单屏展示；业务模块可预加载，但不将首页地址改成学习概览。
export async function openLearningPage(page = 'lesson') {
  if (!state.user) { location.hash = 'auth'; renderAuth(); return; }
  await navigate(titles[page] && page !== 'detail' ? page : 'dashboard');
}
export async function logoutLearning() { await perform('logout'); }
export function getLearningPage() { return state.page; }
const initialPage = location.hash.slice(1);
try { state.user = await api('/auth/me'); await navigate(titles[initialPage] && initialPage !== 'detail' ? initialPage : 'dashboard', Boolean(titles[initialPage]) && initialPage !== 'detail'); }
catch { renderAuth(); }
