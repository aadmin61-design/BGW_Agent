// 采用可核对原文的经典名言，避免把自拟文案误署为名人语录。
const QUOTES = [
  { text: '学而时习之，不亦说乎？', author: '孔子', source: '《论语·学而》', url: 'https://ctext.org/analects/xue-er/ens' },
  { text: '学而不思则罔，思而不学则殆。', author: '孔子', source: '《论语·为政》', url: 'https://ctext.org/analects/wei-zheng/ens' },
  { text: '温故而知新，可以为师矣。', author: '孔子', source: '《论语·为政》', url: 'https://ctext.org/analects/wei-zheng/ens' },
  { text: '知之为知之，不知为不知，是知也。', author: '孔子', source: '《论语·为政》', url: 'https://ctext.org/analects/wei-zheng/ens' },
  { text: '知之者不如好之者，好之者不如乐之者。', author: '孔子', source: '《论语·雍也》', url: 'https://ctext.org/analects/yong-ye/ens' },
  { text: '锲而不舍，金石可镂。', author: '荀子', source: '《荀子·劝学》', url: 'https://ctext.org/xunzi/quan-xue/zh' },
  { text: '君子博学而日参省乎己，则智明而行无过矣。', author: '荀子', source: '《荀子·劝学》', url: 'https://ctext.org/xunzi/quan-xue/zh' },
  { text: '学不可以已。', author: '荀子', source: '《荀子·劝学》', url: 'https://ctext.org/xunzi/quan-xue/zh' },
];

export function dailyQuote(date = new Date()) {
  // UTC+8零点切换；同一天所有用户和设备一致，刷新页面不会随机换句。
  const day = Math.floor((date.getTime() + 8 * 3600000) / 86400000);
  const index = ((day % QUOTES.length) + QUOTES.length) % QUOTES.length;
  return QUOTES[index];
}
