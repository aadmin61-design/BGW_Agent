#!/usr/bin/env bash
# 原生部署只安装MySQL、Nginx和项目虚拟环境，避免完整Milvus容器开销。
set -euo pipefail
# Workbench断开后继续部署，并将最终退出码保存在私密运维目录。
trap 'code=$?; printf "%s\n" "$code" > /root/zhixu-migration/deploy.exit' EXIT
APP_ROOT=/opt/zhixu
test "$(id -u)" = 0 || { echo '请使用root执行部署'; exit 1; }
test -f "$APP_ROOT/.env" || { echo '缺少服务器专用配置'; exit 1; }
test -f "$APP_ROOT/migration/manifest.json" || { echo '缺少迁移清单'; exit 1; }
if systemctl is-active --quiet zhixu; then
  echo '已有运行中的知序服务，请使用更新流程'; exit 1
fi
export DEBIAN_FRONTEND=noninteractive
# 2GiB实例增加交换空间缓解安装或解析峰值，不覆盖已有交换文件。
if [ "$(awk '/MemTotal/{print $2}' /proc/meminfo)" -lt 3145728 ] && [ "$(awk '/SwapTotal/{print $2}' /proc/meminfo)" -eq 0 ]; then
  if [ ! -e /var/lib/zhixu-swapfile ]; then
    fallocate -l 2G /var/lib/zhixu-swapfile
    chmod 600 /var/lib/zhixu-swapfile
    mkswap /var/lib/zhixu-swapfile
    swapon /var/lib/zhixu-swapfile
    grep -q '^/var/lib/zhixu-swapfile ' /etc/fstab || printf '/var/lib/zhixu-swapfile none swap sw 0 0\n' >> /etc/fstab
  fi
fi
apt-get update
apt-get install -y python3-venv python3-dev build-essential mysql-server nginx curl
id zhixu >/dev/null 2>&1 || useradd --system --home-dir "$APP_ROOT" --shell /usr/sbin/nologin zhixu
mkdir -p "$APP_ROOT"/{data,uploads,imports} "$APP_ROOT/.cache/milvus"
# 小内存实例限制数据库缓冲区；不降低事务持久化等级。
install -m 644 "$APP_ROOT/deploy/ubuntu-lite/mysql.cnf" /etc/mysql/mysql.conf.d/zhixu.cnf
systemctl restart mysql
python3 -m venv "$APP_ROOT/.venv"
"$APP_ROOT/.venv/bin/python" -m pip install --no-cache-dir -r "$APP_ROOT/deploy/ubuntu-lite/requirements.txt"
cd "$APP_ROOT"
"$APP_ROOT/.venv/bin/python" deploy/ubuntu-lite/setup_database.py
"$APP_ROOT/.venv/bin/python" scripts/cloud_migrate.py restore "$APP_ROOT/migration"
chown -R zhixu:zhixu "$APP_ROOT"
chmod 755 "$APP_ROOT" "$APP_ROOT/web"
chmod 700 "$APP_ROOT/data" "$APP_ROOT/uploads" "$APP_ROOT/imports"
chmod 700 "$APP_ROOT/.cache" "$APP_ROOT/.cache/milvus"
chmod 600 "$APP_ROOT/.env"
chmod 700 "$APP_ROOT/migration"
install -m 644 "$APP_ROOT/deploy/ubuntu-lite/zhixu.service" /etc/systemd/system/zhixu.service
# 单台新服务器使用项目站点，不覆盖其他自定义Nginx配置。
install -m 644 "$APP_ROOT/deploy/ubuntu-lite/nginx.conf" /etc/nginx/sites-available/zhixu
ln -sfn /etc/nginx/sites-available/zhixu /etc/nginx/sites-enabled/zhixu
nginx -t
systemctl daemon-reload
systemctl enable --now mysql nginx zhixu
systemctl reload nginx
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8001/api/health | "$APP_ROOT/.venv/bin/python" -c 'import sys,json; report=json.load(sys.stdin); assert report["database"] and report["vector"] is True'; then
    echo '知序数据库、向量检索和API已就绪'; exit 0
  fi
  sleep 2
done
echo '应用启动失败，请检查systemctl status zhixu'; exit 1
