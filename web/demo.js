// 演示数据只用于界面预览，与后端、真实文档及账号完全分离。
const date = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' });
const seed = [
  ['Java 基础', 'Java 的基本数据类型有哪些？', 'Java 有 byte、short、int、long、float、double、char 和 boolean 八种基本数据类型。', '基本类型保存值，引用类型保存对象引用。整数类型的取值范围由位宽决定；boolean 的存储细节取决于 JVM 实现。', 1],
  ['Java 基础', '为什么 String 是不可变的？', 'String 不提供修改已有字符串值的接口，相关内部存储由实现保护。字符串操作通常返回新对象。', '不可变性便于安全共享字符串常量、缓存哈希值和作为 Map 的键。final 类限制继承，但单独使用 final 并不能保证所有类都不可变。', 1],
  ['集合', 'ArrayList 和 LinkedList 有什么区别？', 'ArrayList 基于动态数组，随机访问高效；LinkedList 基于双向链表，定位节点通常需要遍历。', '应把定位成本计入插入删除复杂度。ArrayList 中间插入需要移动元素；LinkedList 已定位节点的链接调整很快，但按索引插入仍需先定位。', 2],
  ['集合', 'HashMap 如何解决哈希冲突？', '现代 JDK 的 HashMap 使用桶、链表，以及满足条件时的红黑树存储发生冲突的键值对。', '哈希相同不代表键相等，仍需通过 equals 比较。树化还受容量等条件限制。HashMap 本身不保证线程安全。', 2],
  ['JVM', 'JVM 运行时内存区域如何划分？', '常见划分包含堆、方法区、虚拟机栈、本地方法栈和程序计数器。', '堆与方法区通常由线程共享，栈与程序计数器具有线程独立性。方法区是规范概念，元空间是特定实现中的承载方式。', 2],
  ['并发', 'synchronized 如何实现线程同步？', 'synchronized 提供互斥与内存可见性，实例方法以当前对象为锁，静态方法以类对象为锁，代码块使用指定对象。', '同步操作围绕相同监视器建立 happens-before 关系。锁住不同对象不能保证同一临界区的互斥。', 2],
  ['并发', 'volatile 能保证复合操作的原子性吗？', '不能。volatile 提供可见性与一定的有序性，但 i++ 等复合操作仍可能发生竞争。', 'i++ 包含读取、计算和写入多个步骤。可根据场景选择原子类或锁，不能只依靠 volatile 修复竞争。', 3],
  ['数据库', '数据库事务的 ACID 是什么？', 'ACID 分别是原子性、一致性、隔离性和持久性。', '事务隔离级别会影响并发可见性。一致性依赖事务机制与应用约束共同保证，不应把它理解为仅由数据库自动保证业务正确。', 2],
  ['网络', 'TCP 为什么需要三次握手？', '三次握手帮助双方确认收发能力并同步初始序列号，建立双向连接状态。', '客户端发送 SYN，服务器回应 SYN+ACK，客户端再发送 ACK。双方初始序列号分别确认，后续传输使用序列号追踪数据。', 2],
  ['框架', 'Spring 的依赖注入解决什么问题？', '依赖注入由容器组织对象依赖，让使用者通过构造器等方式接收所需对象，减少对象创建和业务逻辑的耦合。', '构造器注入可以明确必要依赖，也便于单元测试时传入替代实现。依赖注入不会自动消除循环依赖或设计上的强耦合。', 2],
  ['Java 基础', 'equals 和 hashCode 的约定是什么？', 'equals 判断相等的对象必须具有相同 hashCode；hashCode 相同的对象不一定 equals 相等。', '重写 equals 时通常也需要重写 hashCode，以满足哈希集合的使用约定。', 2],
  ['JVM', '垃圾回收如何判断对象是否可达？', '典型 JVM 垃圾回收器通过从 GC Roots 出发的可达性分析判断对象是否仍可访问。', '对象之间的循环引用不代表它们可从 GC Roots 到达，因此循环引用本身不会阻止基于可达性的回收。', 3],
];

function initial() {
  return { day: date(), lessons: seed.slice(0, 10).map((x, i) => lesson(x, i)), quiz: [], chats: {}, saved: {}, learned: 24, kbs: [{ id: 'demo-kb', name: 'Java 面试知识库', description: '从基础到进阶，构建清晰的 Java 知识体系。此处为界面示例数据。', status: 'ready', documents: 3, concepts: 128 }] };
}
function lesson(x, i) {
  return { id: `demo-${date()}-${i}`, kb_id: 'demo-kb', kind: 'lesson', day: date(), is_review: i === 3 || i === 6, submitted: i < 3, correct: i < 3 ? true : null, snapshot: { category: x[0], title: x[1].replace('？', ''), question: x[1], answer: x[2], analysis: x[3], depth: x[4], source: '界面演示示例 · 非导入文档', prerequisites: [] } };
}
let data;
try { data = JSON.parse(localStorage.getItem('bgw-demo') || 'null'); } catch { data = null; }
if (!data || data.day !== date()) {
  const saved = data?.saved || {};
  const profile = data?.profile;
  const chats = Object.fromEntries(Object.entries(data?.chats || {}).filter(([id]) => saved[id]));
  data = { ...initial(), saved, chats, profile };
}
const persist = () => localStorage.setItem('bgw-demo', JSON.stringify(data));
const all = () => [...data.lessons, ...data.quiz];
const find = id => all().find(x => x.id === id) || data.chats[id]?.item;
const conversation = id => {
  const item = find(id);
  if (!item) throw new Error('示例题目不存在');
  data.chats[id] ||= { id, item_id: id, messages: [], snapshot: item.snapshot, item: structuredClone(item) };
  return { ...data.chats[id], item: visible(item), saved: Boolean(data.saved[id]) };
};
const visible = item => {
  const result = structuredClone(item);
  if (result.kind !== 'lesson' && !result.submitted) {
    delete result.snapshot.answer; delete result.snapshot.analysis; delete result.snapshot.accepted_answers;
  }
  return result;
};

export async function demoRequest(path, options = {}) {
  const method = options.method || 'GET';
  const body = options.body && typeof options.body === 'string' ? JSON.parse(options.body) : {};
  let result;
  if (path === '/auth/me') result = { username: '学习者', id: 'demo', is_admin: true, ...(data.profile || {}) };
  else if (path === '/profile' && method === 'PATCH') {
    data.profile = { display_name: body.display_name, bio: body.bio, avatar_url: body.avatar_remove ? null : body.avatar_png || data.profile?.avatar_url || null };
    result = { username: '学习者', id: 'demo', is_admin: true, ...data.profile };
  }
  else if (path === '/dashboard') {
    const n = data.lessons.filter(i => i.submitted).length;
    result = { day: date(), learned: data.learned, due: 5, mistakes: 3, lesson_done: n, lesson_total: data.lessons.length, quiz_done: data.quiz.filter(i => i.submitted).length, quiz_total: data.quiz.length, accuracy: data.quiz.some(i => i.submitted) ? Math.round(data.quiz.filter(i => i.correct).length / data.quiz.filter(i => i.submitted).length * 100) : null, quiz_unlocked: true, history: [4, 7, 5, 9, 6, 8, n].map((count, i) => { const d = new Date(); d.setDate(d.getDate() - 6 + i); return { day: d.toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' }), count }; }) };
  } else if (path === '/knowledge-bases') result = data.kbs;
  else if (path === '/memory') result = seed.slice(0, 8).map((x, i) => { const d = new Date(); d.setDate(d.getDate() + Math.floor(i / 2)); return { title: x[1], category: x[0], stage: i % 4, mistakes: i % 3, next_review: d.toLocaleDateString('en-CA'), first_learned: date() }; });
  else if (path === '/bookmarks') result = Object.keys(data.saved).filter(id => data.saved[id]).map(id => conversation(id));
  else if (path === '/plans/quiz/generation') result = { job: null };
  else if (path.startsWith('/plans/')) {
    const kind = path.split('/')[2];
    if (method === 'POST') {
      if (kind === 'lesson' && body.more) {
        const start = data.lessons.length;
        data.lessons.push(...seed.slice(start, start + 10).map((x, i) => ({ ...lesson(x, start + i), submitted: false })));
        result = { added: data.lessons.length - start, items: data.lessons.map(visible), message: data.lessons.length === start ? '示例知识已全部加入。正式模式会从已导入知识库中继续选择。' : '' };
      } else if (kind === 'quiz') {
        const start = data.quiz.length;
        if (start === 0 || body.more) {
          for (let i = 0; i < 13; i++) {
            const fill = i >= 10;
            data.quiz.push({ id: `quiz-${date()}-${start + i}`, kind: fill ? 'fill' : 'choice', day: date(), is_review: true, submitted: false, snapshot: { ...data.lessons[i % 10].snapshot, question: fill ? 'Java 中，提供可见性但不能保证 i++ 原子性的关键字是____。' : '以下关于 Java 字符串的说法，哪一项正确？', options: fill ? [] : ['String 的值可以通过已有实例直接修改', 'String 的不可变性有助于安全共享', 'final 能保证任何类都不可变', '所有字符串操作都会修改原有对象'], answer: fill ? 'volatile' : 'B', accepted_answers: [], analysis: fill ? seed[6][3] : seed[1][3] } });
          }
        }
        result = { items: data.quiz.map(visible), added: data.quiz.length - start };
      } else result = { items: data.lessons.map(visible), added: 0 };
    } else result = (kind === 'lesson' ? data.lessons : data.quiz).map(visible);
  } else if (path.startsWith('/items/')) {
    const [, , id, action] = path.split('/');
    const item = find(id);
    if (action === 'answer') {
      item.submitted = true; item.user_answer = body.answer;
      item.correct = item.kind === 'lesson' ? body.remembered : (body.answer || '').trim().toLowerCase() === item.snapshot.answer.toLowerCase();
      result = visible(item);
    } else if (action === 'save') { data.saved[id] = body.saved; conversation(id); result = { saved: body.saved }; }
    else if (action === 'conversation') {
      if (method === 'POST') throw new Error('演示模式不调用大模型。请登录正式账号后使用独立 Agent 问答。');
      result = conversation(id);
    }
  } else if (path === '/admin/jobs') result = [];
  else if (path.startsWith('/admin/')) throw new Error('演示模式不修改真实知识库。请使用管理员账号登录。');
  else throw new Error('演示模式不支持此操作');
  persist();
  return structuredClone(result);
}
