import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Menu, X, Pause, Play, RotateCw, BookOpen, LogOut, ChevronDown } from 'lucide-react';

// 背景视频保存在项目内，通过现有静态资源服务播放，无需连接外部视频站点。
export const VIDEO_URL = '/assets/media/learning-background.mp4';
export const NAVIGATION = [
  { page: 'home', label: '首页' },
  { page: 'lesson', label: '每日学习' },
  { page: 'knowledge', label: '知识库' },
  { page: 'memory', label: '记忆计划' },
];
const knownPages = new Set(['home', 'dashboard', 'lesson', 'quiz', 'memory', 'bookmarks', 'knowledge', 'admin', 'auth', 'profile']);
const currentPage = () => { const page = window.location.hash.slice(1); return knownPages.has(page) ? page : 'home'; };
const VIDEO_SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
function savedVideoSpeed() {
  // 浏览器禁止存储或旧配置不合法时使用正常速度，不影响页面加载。
  try {
    const rate = Number(window.localStorage.getItem('zhixu-video-speed') || 1);
    return VIDEO_SPEEDS.includes(rate) ? rate : 1;
  } catch { return 1; }
}

function VideoSpeed({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const wrapper = useRef(null), trigger = useRef(null);
  useEffect(() => {
    if (!open) return;
    wrapper.current.querySelector('[aria-checked="true"]')?.focus();
    const outside = event => { if (!wrapper.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  function close() { setOpen(false); trigger.current?.focus(); }
  function keyDown(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    if (!open) { setOpen(true); return; }
    const items = [...wrapper.current.querySelectorAll('[role="menuitemradio"]')];
    const index = items.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 :
      (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }
  return <div className="video-speed" ref={wrapper} onKeyDown={keyDown}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <button ref={trigger} type="button" className="video-speed-toggle" aria-label="背景视频播放速度"
      aria-haspopup="menu" aria-expanded={open} aria-controls="video-speed-menu" onClick={() => setOpen(!open)}>
      <span>{value}×</span><ChevronDown size={14} aria-hidden="true" className={open ? 'speed-arrow is-open' : 'speed-arrow'} />
    </button>
    {open && <div id="video-speed-menu" role="menu" aria-label="播放速度" className="video-speed-menu">
      {VIDEO_SPEEDS.map(rate => <button key={rate} type="button" role="menuitemradio" aria-checked={rate === value}
        onClick={() => { onChange(rate); close(); }}>{rate}×</button>)}
    </div>}
  </div>;
}

export function HeroContent({ onNavigate, visible }) {
  return <main hidden={!visible} className="foldcraft-hero-content relative z-10 flex h-[calc(100vh-80px)] flex-col justify-between px-6 pb-10 pt-12 sm:pb-12 sm:pt-16 md:px-12 md:pb-16 md:pt-20 lg:px-16">
    <div className="max-w-3xl">
      <span className="hero-badge mb-4 block text-xs text-white/90 sm:mb-6 sm:text-sm animate-[fadeSlideUp_0.8s_ease_0.2s_both]">知识有序 · 日有所进</span>
      <h1 className="hero-heading text-3xl font-medium leading-[1.1] tracking-tight text-white sm:text-5xl md:text-6xl lg:text-7xl animate-[fadeSlideUp_0.8s_ease_0.4s_both]">学懂一个问题，<br />连接一片知识，<br />每天向前一步。</h1>
    </div>
    <div className="relative">
      <p className="hero-description mb-5 max-w-sm text-sm leading-relaxed text-white/60 sm:mb-6 sm:max-w-lg sm:text-base md:text-lg animate-[fadeSlideUp_0.8s_ease_0.7s_both]">把文档变成每天的学习计划。通过知识讲解、练习与专属助教，让学过的内容真正留下来。</p>
      <button type="button" onClick={() => onNavigate('lesson')} className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2.5 text-sm font-medium text-black transition-transform hover:scale-105 sm:px-6 sm:py-3 animate-[fadeSlideUp_0.8s_ease_0.9s_both]">开始今日学习 <ArrowRight size={16} aria-hidden="true" /></button>
    </div>
  </main>;
}

export function MobileMenu({ open, onClose, onNavigate }) {
  const panel = useRef(null);
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panel.current?.querySelector('a')?.focus();
    const handleKey = event => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key === 'Tab') {
        // 将焦点限制在菜单与始终可用的关闭按钮之间。
        const items = [...panel.current.querySelectorAll('a,button'), document.querySelector('#mobile-menu-toggle')].filter(Boolean);
        const first = items[0], last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', handleKey); };
  }, [open, onClose]);
  const choose = (event, page) => { event.preventDefault(); onClose(); onNavigate(page); };
  return <div ref={panel} id="mobile-menu" role={open ? 'dialog' : undefined} aria-modal={open ? 'true' : undefined} aria-label="移动导航" aria-hidden={!open} inert={!open ? true : undefined}
    className={`glass-mobile-menu fixed inset-x-0 top-0 z-20 w-full overflow-hidden bg-black/70 backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] md:hidden ${open ? 'h-screen opacity-100' : 'h-0 opacity-0 pointer-events-none'}`}>
    <div className={`flex h-full flex-col justify-center px-8 transition-all duration-500 delay-100 ${open ? 'translate-y-0 opacity-100' : 'translate-y-8 opacity-0'}`}>
      {NAVIGATION.map(link => <a key={link.page} href={`#${link.page}`} onClick={event => choose(event, link.page)} className="py-4 text-3xl font-medium text-white/90 transition-colors hover:text-white">{link.label}</a>)}
      <button type="button" onClick={event => choose(event, 'lesson')} className="mt-6 rounded-full bg-white px-8 py-3.5 text-center text-base font-medium text-black transition-transform hover:scale-105">进入学习空间</button>
    </div>
  </div>;
}

export default function App({ loadController = () => import('/assets/app.js?v=20261014-profile-1') }) {
  const [page, setPage] = useState(currentPage);
  const [user, setUser] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [paused, setPaused] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(savedVideoSpeed);
  const [videoFailed, setVideoFailed] = useState(false);
  const [bridgeFailed, setBridgeFailed] = useState(false);
  const bridge = useRef(null), video = useRef(null), toggle = useRef(null);
  const android = /ZhixuAndroid\//.test(window.navigator.userAgent);
  const lite = android && /ZhixuLite\/1/.test(window.navigator.userAgent);
  const home = page === 'home';
  const closeMenu = React.useCallback(() => { setMobileMenuOpen(false); toggle.current?.focus(); }, []);

  useEffect(() => {
    document.documentElement.classList.toggle('zhixu-android', android);
    document.documentElement.classList.toggle('zhixu-lite', lite);
    const update = event => { setUser(event.detail.user); };
    const route = () => {
      const next = currentPage();
      setPage(next); setMobileMenuOpen(false);
      // 内部链接已更新业务视图时不重复加载；浏览器前进/后退则同步业务视图。
      if (next !== 'home') bridge.current?.then(controller => {
        if (controller && controller.getLearningPage?.() !== next) return controller.openLearningPage(next);
      });
    };
    window.addEventListener('learning:state', update);
    window.addEventListener('hashchange', route);
    window.addEventListener('popstate', route);
    // 业务控制器只挂载一次，首页切换不会丢失正在进行的学习或问答状态。
    bridge.current = loadController().catch(() => { setBridgeFailed(true); return null; });
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (media?.matches) setPaused(true);
    return () => { window.removeEventListener('learning:state', update); window.removeEventListener('hashchange', route); window.removeEventListener('popstate', route); };
  }, []);

  useEffect(() => {
    if (!video.current) return;
    // 全站共用一个视频，切换学习模块不会隐藏或重新下载背景。
    // 忽略被新播放操作打断的旧Promise，避免快速暂停/重试后意外停播。
    let active = true;
    if (paused || videoFailed) video.current.pause();
    else video.current.play()?.catch(error => {
      if (active && error.name !== 'AbortError') setPaused(true);
    });
    return () => { active = false; };
  }, [paused, videoFailed]);

  useEffect(() => {
    // 只改变播放速度，不改变暂停状态；重载视频也保留用户选定的速度。
    if (video.current) {
      video.current.defaultPlaybackRate = playbackRate;
      video.current.playbackRate = playbackRate;
    }
    try { window.localStorage.setItem('zhixu-video-speed', String(playbackRate)); } catch {}
  }, [playbackRate, videoFailed]);

  useEffect(() => {
    const visibility = event => {
      const active = event.type === 'zhixu:visibility' ? event.detail?.active !== false : !document.hidden;
      if (!video.current) return;
      if (!active) video.current.pause();
      else if (!paused && !videoFailed) video.current.play()?.catch(error => { if (error.name !== 'AbortError') setPaused(true); });
    };
    // 动态背景开启时也暂停后台解码，返回后尊重用户手动暂停状态。
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('zhixu:visibility', visibility);
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('zhixu:visibility', visibility); };
  }, [paused, videoFailed]);

  function togglePlayback() {
    if (videoFailed) {
      // 清除失败状态并重新请求原始视频；渐变背景在加载期间保持可读。
      video.current?.load();
      setVideoFailed(false);
      setPaused(false);
    } else setPaused(value => !value);
  }

  useEffect(() => {
    const desktop = window.matchMedia?.('(min-width: 768px)');
    const resize = event => { if (event.matches) setMobileMenuOpen(false); };
    desktop?.addEventListener('change', resize);
    return () => desktop?.removeEventListener('change', resize);
  }, []);

  async function navigate(next) {
    setMobileMenuOpen(false);
    setPage(next);
    if (next === 'home') { window.location.hash = 'home'; window.scrollTo(0, 0); return; }
    const controller = await bridge.current;
    if (controller) await controller.openLearningPage(next);
    window.scrollTo(0, 0);
  }
  async function logout() { const controller = await bridge.current; if (controller) { await controller.logoutLearning(); setPage('auth'); window.location.hash = 'auth'; } }

  return <div className={home ? 'foldcraft-frame foldcraft-root relative h-screen w-full overflow-hidden bg-black font-geist' : 'foldcraft-frame relative min-h-screen w-full bg-black font-geist'}>
    <div className="video-fallback pointer-events-none fixed inset-0" />
    {!lite && <video ref={video} hidden={videoFailed} src={VIDEO_URL} autoPlay muted loop playsInline preload="auto" aria-hidden="true" onError={() => setVideoFailed(true)} className="pointer-events-none fixed inset-0 h-full w-full object-cover" style={{ objectPosition: '70% center' }} />}
    <div className={`video-scrim pointer-events-none fixed inset-0 ${home ? 'is-home' : 'is-workspace'}`} />
    <header className="foldcraft-navbar relative z-30 flex min-h-[80px] items-center justify-between px-6 py-5 md:px-12 lg:px-16">
      <div className="flex items-center">
        <a href="#home" onClick={event => { event.preventDefault(); navigate('home'); }} aria-label="知序首页" className="inline-flex items-center gap-2.5 text-lg font-semibold tracking-tight text-white sm:text-xl"><BookOpen size={20} strokeWidth={1.5} aria-hidden="true" /><span>知序</span></a>
        {/* 学习页面使用完整的功能导航，首页才显示顶部快捷导航。 */}
        {home && <nav aria-label="主导航" className="ml-10 hidden items-center gap-8 md:flex">
          {NAVIGATION.map(link => <a key={link.page} href={`#${link.page}`} onClick={event => { event.preventDefault(); navigate(link.page); }} className={`text-sm transition-colors hover:text-white ${page === link.page ? 'text-white' : 'text-white/80'}`}>{link.label}</a>)}
        </nav>}
      </div>
      <div className="hidden items-center gap-4 md:flex">
        {/* 学习页面由下方导航栏统一显示账号；首页保留账号入口，避免重复。 */}
        {home && user && <button type="button" onClick={() => navigate('profile')} className="home-profile" aria-label="个人资料">{user.display_name || user.username}</button>}
        {home && user && <button type="button" onClick={logout} className="p-2 text-white/60 transition-colors hover:text-white" aria-label="退出登录"><LogOut size={16} aria-hidden="true" /></button>}
        {home && <button type="button" onClick={() => navigate('lesson')} className="rounded-lg bg-white px-5 py-2 text-sm font-medium text-black transition-transform hover:scale-105">进入学习空间</button>}
      </div>
      <button ref={toggle} id="mobile-menu-toggle" type="button" onClick={() => setMobileMenuOpen(open => !open)} aria-label={mobileMenuOpen ? '关闭导航' : '打开导航'} aria-expanded={mobileMenuOpen} aria-controls="mobile-menu" className="relative z-50 flex h-10 w-10 items-center justify-center text-white transition-transform active:scale-90 md:hidden">
        <Menu size={22} aria-hidden="true" className={`absolute transition-all duration-300 ${mobileMenuOpen ? 'rotate-90 scale-50 opacity-0' : 'rotate-0 scale-100 opacity-100'}`} />
        <X size={22} aria-hidden="true" className={`absolute transition-all duration-300 ${mobileMenuOpen ? 'rotate-0 scale-100 opacity-100' : '-rotate-90 scale-50 opacity-0'}`} />
      </button>
    </header>
    <MobileMenu open={mobileMenuOpen} onClose={closeMenu} onNavigate={navigate} />
    <HeroContent onNavigate={navigate} visible={home} />
    <div hidden={lite} className={`video-controls flex items-center gap-3 ${home ? 'is-home' : 'is-workspace'}`}>
      <span hidden={!home} className="hidden text-[10px] tracking-[.18em] text-white/60 sm:block">LEARN. CONNECT. GROW.</span>
      <VideoSpeed value={playbackRate} onChange={setPlaybackRate} />
      <button type="button" onClick={togglePlayback} aria-label={videoFailed ? '重新加载背景视频' : paused ? '播放背景视频' : '暂停背景视频'} aria-pressed={paused} title={videoFailed ? '重新加载背景视频' : paused ? '播放背景视频' : '暂停背景视频'} className="flex h-8 w-8 items-center justify-center rounded-full border border-white/25 bg-black/15 text-white/90 transition-colors hover:bg-white/15">
        {videoFailed ? <RotateCw size={12} aria-hidden="true" /> : paused ? <Play size={12} aria-hidden="true" /> : <Pause size={12} aria-hidden="true" />}
      </button>
    </div>
    <div hidden={home} className="learning-host">
      {bridgeFailed && <div role="alert" className="mx-auto max-w-xl p-10 text-center text-sm text-neutral-600">学习空间暂时未能加载，请刷新页面后重试。</div>}
      <div id="learning-app"><div className="loading">正在打开学习空间…</div></div>
    </div>
  </div>;
}
