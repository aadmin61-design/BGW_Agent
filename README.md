# 知序 · Java 知识学习助手

基于知识库的每日学习、测验和间隔复习平台，支持手机与电脑。此仓库保存服务器当前运行版本的源码、前端静态产物、隔离测试和 Ubuntu 部署模板。

## 功能

- 导入 PDF、DOCX、Markdown、TXT 等资料，分类提取知识点及前置依赖，写入 MySQL 和 Milvus。
- 每天学习默认 10 个知识点，包含问题、答案、解析和来源，可追加学习内容。
- 完成学习的第二天解锁测验：10 道选择题、3 道填空题；北京时间每天 06:00 自动生成，也支持手动生成和追加。
- 按 1、3、7、14、30、60 天安排复习，错题进入针对性强化。
- 每道题拥有独立助教对话；未收藏对话跨日重置，收藏保留题目、对话和来源。
- 注册、登录、用户数据隔离，以及管理员知识库、文档导入和中断任务管理。
- 长文逐片段保存抽取进度，失败重启复用已完成结果；整篇抽取和向量写入成功后才发布正式知识点。
- DOCX正文、表格、嵌套表格、内容控件和文本框文字按文档顺序读取；兼容回退分支自动去重。
- 助教回答支持 Markdown、代码高亮和复制，发送时显示思考动画；学习及答题页面支持切题。
- 选择题选项在生成后随机排列并持久化，每批 10 题的正确位置 A/B/C/D 各出现 2～3 次；解析同步调整，旧页面不能按过期选项顺序提交。

## 技术栈

前端：React、Tailwind CSS、Lucide React，配合 ES modules 业务控制器。后端：FastAPI、LangChain、LangGraph。结构化数据使用 MySQL；向量检索支持 Milvus 网络服务和 Linux 上的 Milvus Lite。大模型通过阿里云千问兼容接口调用。

当前服务器采用 Ubuntu 24.04、Python 3.12、MySQL、Milvus Lite 和 Nginx，后台由 systemd 单进程管理。前端构建产物和背景视频随源码提供，网站运行时无需 Node.js。

## 本地预览

使用现有 Python 环境，依赖清单位于项目中：

```bash
python -m pip install -r requirements.txt
python scripts/preview.py
```

访问 `http://127.0.0.1:8001/?demo=1`。演示模式使用示例数据，不调用模型或连接数据库。它用于查看界面，不替代真实服务。

## 配置和运行

```bash
cp .env.example .env
# 在本地 .env 中填写自己的 MySQL、阿里云模型配置和 JWT_SECRET。
python scripts/manage.py init-db
python scripts/manage.py create-admin --username admin
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --workers 1
```

管理员密码通过终端隐藏输入；公开注册创建普通用户。MySQL 数据库及账号需要事先准备，`init-db` 创建表结构。服务器的环境配置、密码、数据库备份、知识库原文及用户学习记录均不包含在本仓库。

Linux 使用 Lite 时安装 `deploy/ubuntu-lite/requirements.txt`，通过 `VECTOR_URI` 设置 `.db` 文件路径；使用远程 Milvus 时把 `VECTOR_URI` 改为对应 HTTP 地址并配置 token。Lite 不支持直接在 Windows 上运行，可在 Windows 开发时使用网络 Milvus。

Ubuntu 生产环境部署见 [部署说明](deploy/ubuntu-lite/README.md)。Lite 初始化会删除并重建工作目录下的 `.cache/milvus`，因此 systemd 必须允许专用 `.cache` 父目录写入；应用源代码保持只读。运行数据库和向量文件需要长期保存，不能只部署前端页面。

## 前端开发

```bash
npm ci
npm run build:web
npm run build:vendor
npm run test:web
```

React 页面源代码位于 `frontend/`，业务控制器位于 `web/app.js`。`web/dist/` 和 `web/vendor/` 提供可直接运行的静态产物及第三方许可证；Geist 字体通过 Google Fonts 加载。背景视频来源记录在 `web/media/README.md`。

## 测试

```bash
python -m pytest tests -q
npm run test:web
```

单元测试使用隔离数据库和模型替身，不连接实际知识库或调用真实模型。真实服务器检查由 `scripts/verify_server.py --model` 提供：它通过在线 HTTP 接口创建临时测试账号、验证问答，完成后清理测试数据；在服务器部署目录内显式执行。

完整导入可用`scripts/verify_full_import.py --kb-id <ID> --path <原文路径>`核对原文摘要、全部片段、依赖关系和向量一致性。显式追加`--model`会在独立临时账号下验证文档前、中、后知识点的在线助教问答，并清理测试数据。脚本仅输出统计，不输出会话密钥或正文；不要从其他进程直接打开正在使用的Lite文件。

## 目录

```text
backend/             API、数据模型、知识导入、助教图、复习和测验队列
frontend/            React 页面、视频背景、导航及移动菜单
web/                 页面控制器、静态产物、Markdown 组件及媒体
scripts/             运行、迁移、验证与维护工具
deploy/ubuntu-lite/  Ubuntu + MySQL + Milvus Lite + Nginx 部署模板
tests/               隔离的后端与前端测试
```

## 使用边界

知识库由管理员统一维护，用户的计划、进度、答案、对话和收藏独立保存。资料不足时不补造知识。扫描 PDF 需要先 OCR；DOCX 图片不自动识别。导入使用单 worker 的后台任务，按文档提交和去重。此版本使用单进程 Lite 文件，适合小规模部署，不能由多个进程同时直接打开同一个向量文件。

抽取最多两路并发，每个结果及时保存到临时缓存；模型等待期间不持有正式知识表事务。模型JSON模式的提示包含实际字段约束，输出经Pydantic校验并对短暂故障有限重试。页面分别显示抽取与向量进度。原文、上传副本、提取缓存、实际配置及用户资料不进入公开仓库。

公网部署通过 Nginx 统一提供前后端入口；数据库端口只监听服务器内部。配置域名和有效证书后启用 HTTPS，再将 `COOKIE_SECURE` 设为 `true`。
