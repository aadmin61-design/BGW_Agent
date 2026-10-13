import { Marked, createDOMPurify, hljs } from './vendor/markdown-vendor.js';

const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const autodetect = ['java', 'javascript', 'typescript', 'python', 'sql', 'bash', 'json', 'xml', 'css', 'yaml'];
const parser = new Marked({ gfm: true, breaks: true, async: false, renderer: {
  // 模型输出的原生HTML作为文字显示，避免它自行创建按钮或活动内容。
  html({ text }) { return escape(text); },
  code({ text, lang }) {
    const hint = (lang || '').trim().split(/\s+/)[0].toLowerCase();
    const known = hint && hljs.getLanguage(hint);
    let label = known ? hint : hint && /^[\w+.-]{1,32}$/.test(hint) ? hint : 'text';
    let highlighted = escape(text);
    if (text.length <= 50000) {
      if (known) highlighted = hljs.highlight(text, { language: hint, ignoreIllegals: true }).value;
      else if (!hint) {
        const detected = hljs.highlightAuto(text, autodetect);
        highlighted = detected.value;
        label = detected.language || 'text';
      }
    }
    return `<section class="code-block"><div class="code-toolbar"><span class="code-language">${escape(label)}</span><button type="button" class="copy-code" data-copy-code="" aria-label="复制代码">复制</button></div><pre><code class="hljs language-${escape(known ? hint : 'plaintext')}">${highlighted}</code></pre></section>`;
  },
  link({ href, title, tokens }) {
    const caption = this.parser.parseInline(tokens);
    return `<a href="${escape(href)}"${title ? ` title="${escape(title)}"` : ''} target="_blank" rel="noopener noreferrer">${caption}</a>`;
  },
} });
let purifier, purifierWindow;
const cache = new Map();

export function renderMarkdown(value) {
  const source = String(value ?? '').replace(/^[\u200B-\u200F\uFEFF]+/, '');
  if (!globalThis.window?.document) return `<p>${escape(source).replace(/\n/g, '<br>')}</p>`;
  if (purifierWindow !== window) { purifierWindow = window; purifier = createDOMPurify(window); cache.clear(); }
  if (!purifier.isSupported) return `<p>${escape(source).replace(/\n/g, '<br>')}</p>`;
  if (cache.has(source)) return cache.get(source);
  // 对最终高亮HTML进行净化，只允许排版标签和本地生成的复制按钮。
  const html = purifier.sanitize(parser.parse(source), {
    ALLOWED_TAGS: ['p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'del', 'ul', 'ol', 'li', 'blockquote', 'hr', 'a', 'section', 'div', 'span', 'pre', 'code', 'button', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'input'],
    ALLOWED_ATTR: ['class', 'href', 'title', 'target', 'rel', 'type', 'aria-label', 'data-copy-code', 'start', 'align', 'disabled', 'checked'],
    ALLOW_DATA_ATTR: false,
  });
  if (source.length <= 50000) { if (cache.size >= 64) cache.delete(cache.keys().next().value); cache.set(source, html); }
  return html;
}
