// 沿今日清单顺序找下一道未完成的学习题；末尾回看前面遗漏的题目。
export function nextPendingLesson(items, currentId, day) {
  const index = items.findIndex(item => item.id === currentId);
  const ordered = index < 0 ? items : [...items.slice(index + 1), ...items.slice(0, index)];
  return ordered.find(item => item.id !== currentId && item.kind === 'lesson' && item.day === day && !item.submitted) || null;
}
