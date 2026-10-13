# Ubuntu + Milvus Lite 部署

本目录提供当前服务器采用的原生部署模板：Ubuntu 24.04、Python 3.12、MySQL、Milvus Lite、FastAPI 和 Nginx。后台由 systemd 管理，本机关机或退出远程连接不会停止服务器进程。

## 首次安装

1. 准备服务器上的 `/opt/zhixu` 项目目录和 `zhixu` 系统用户。
2. 按需安装 Python venv、MySQL 和 Nginx；在项目内创建 `.venv` 并安装本目录 `requirements.txt`。Linux 锁文件固定 Lite 及兼容的 setuptools 版本。
3. 从根目录 `.env.example` 创建私有 `.env`，填写自己的阿里云密钥、MySQL 专用账号密码和随机 JWT 密钥。确认 MySQL 数据库和账号已经存在。
4. 将 `VECTOR_URI` 设置为 `/opt/zhixu/data/knowledge.db`，上传目录为 `/opt/zhixu/uploads`，授权导入目录为 `/opt/zhixu/imports`。
5. 运行 `scripts/manage.py init-db` 和 `scripts/manage.py create-admin --username admin`，通过隐藏输入设置管理员密码。迁移已有数据库时不重复创建原有账号。
6. 创建 `data`、`uploads`、`imports` 和 `.cache` 目录，由 `zhixu` 持有；私有目录权限为 700，`.env` 为 600，项目根目录和 `web` 为 755 以供 Nginx 访问。
7. 将 `zhixu.service` 放到 `/etc/systemd/system/`，按部署位置检查项目路径。只运行单 worker。Lite 在初始化时删除并重建 `.cache/milvus`，`ReadWritePaths` 必须包含 `.cache` 父目录，而非只开放子目录。
8. 修改 `nginx.conf` 的 `server_name` 为自己的域名或公网 IP，安装为 Nginx 站点；检查已有默认站点不会抢占你的入口。
9. 检查 Nginx 配置，启用并启动 MySQL、Nginx 和 `zhixu.service`。公网仅开放网站入口，MySQL 和 FastAPI 内部端口不对外开放。

```bash
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now mysql nginx zhixu
curl http://127.0.0.1:8001/api/health
```

健康接口应包含 `status=ready`、`database=true` 和 `vector=true`。HTTP 阶段 `COOKIE_SECURE=false`；配置有效 HTTPS 后设为 `true`，同时设置正确的 `CORS_ORIGINS`。

## 迁移与备份

`bootstrap.sh` 是已有项目的首次迁移脚本，需要服务器私有 `.env`、迁移清单及备份数据，不能在缺少备份的全新克隆目录中直接运行。它拒绝覆盖已有数据库账号或非空数据库。

`scripts/cloud_migrate.py` 可导出和恢复本项目的 MySQL 表、向量及上传资料。真实备份不属于公开源码，保存在独立私有位置。所有数据迁移后在服务器入口继续使用，避免两个副本分别写入。

日常备份同时保存 MySQL、Lite 文件和文档；拷贝 Lite 文件前停止应用，或使用一致的 SQLite 备份方式。不能让额外诊断进程直接打开在线服务的同一个 Lite 文件。`scripts/probe_lite.py` 使用独立快照及工作目录，不复用在线缓存。

## 验证与维护

`scripts/verify_server.py --model` 使用服务器内临时账号通过真实 HTTP 接口检查注册、登录、隔离和检索问答，完成后精确清理测试数据。可用 `--base-url` 指定网站入口，以验证 Nginx 代理。迁移账号检查依赖私有 `migration/snapshot.json`。

代码更新时先备份，再替换源码和前端产物，重启 `zhixu`；不重复执行数据库初始化。每日测验使用 `Asia/Shanghai`，06:00 自动调度。

长文导入新增`import_checkpoints`和`import_pieces`临时缓存表，启动时只创建缺失表，不覆盖原有用户或知识。失败后使用管理员“重启任务”继续未完成片段；更新服务前应等待正在运行的导入结束。原文整体抽取、向量写入和正式发布成功后清理临时片段，保留摘要及完成状态。DOCX纯位图不自动OCR。

管理员接口`GET /api/admin/knowledge-bases/{id}/integrity`在在线进程内逐条核对SQL片段和向量的ID、知识库、来源及正文，返回计数；未就绪知识库返回409。完整原文核验见`scripts/verify_full_import.py`，显式追加`--model`才执行真实助教测试。

`scripts/repair_quiz_options.py` 默认预览旧选择题调整数量，`--apply` 先备份再修改今日未作答、未收藏且没有聊天内容的题目；已完成及已有对话题目保持原样，重复执行不会重新打乱已更新题目。

Workbench 策略 JSON 是权限模板，使用前替换 `<ACCOUNT_ID>`、`<INSTANCE_ID>` 和地域，并在自己的阿里云账号中审查后授权。
