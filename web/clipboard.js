export async function copyCode(button) {
  const code = button.closest('.code-block')?.querySelector('code');
  if (!code) throw new Error('未找到可复制的代码');
  // textContent还原高亮标签中的纯文本，保留缩进、换行和特殊字符。
  const value = code.textContent;
  let copied = false;
  if (globalThis.navigator?.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(value); copied = true; } catch { /* 非安全来源或权限不足时尝试兼容复制。 */ }
  }
  if (!copied) {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    textarea.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    const focused = document.activeElement;
    document.body.append(textarea);
    try {
      textarea.select();
      textarea.setSelectionRange(0, value.length);
      copied = Boolean(document.execCommand?.('copy'));
    } finally {
      textarea.remove();
      focused?.focus({ preventScroll: true });
    }
  }
  if (!copied) throw new Error('无法自动复制，请选中代码手动复制');
  button.textContent = '已复制';
  setTimeout(() => { button.textContent = '复制'; }, 1600);
}
