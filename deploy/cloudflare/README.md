# 备案期间临时Cloudflare入口

使用Cloudflare Quick Tunnel提供随机`trycloudflare.com` HTTPS地址，应用、MySQL、Milvus Lite、后台队列及文档仍运行在原服务器。临时隧道不需要Cloudflare账号或域名，进程重建时地址变化；无可用性保证，固定生产入口应换成账号管理的命名隧道。官方说明：https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

程序采用Cloudflare官方`cloudflared-linux-amd64`独立文件，不创建新的Python环境。下载固定版本后核对官方SHA256，安装在`/opt/zhixu/.tools/cloudflared/cloudflared`。二进制和运行数据不进入源码仓库。

把`nginx-loopback.conf`安装为`/etc/nginx/sites-available/zhixu-tunnel`并创建启用链接，检查`nginx -t`后热重载。它只监听`127.0.0.1:8080`，转发到原API和静态资源；原备案域名由单独维护路由返回503，不能继续代理学习平台。

把`cloudflared-quick.service`安装到`/etc/systemd/system/`，执行`systemctl daemon-reload`和`systemctl enable --now cloudflared-quick`。服务使用HTTP/2、IPv4和自动重启，本机关机不会影响服务器隧道。`curl http://127.0.0.1:20241/ready`应返回200；当前入口可从该服务日志中读取`https://*.trycloudflare.com`，不要重启隧道来查询地址。

仅通过Cloudflare提供网站时，备份后停用`sites-enabled/default`及原公网网站的启用链接，保留`zhixu-tunnel`。`nginx -t`通过后热重载；`ss -lntp`应只显示本机8080入口，不应再有公网80/443网站监听。网站不需要开放新的入站端口；服务器出站网络和维护连接仍需保留。还原公网网站前先按实际备案及证书状态配置。

HTTPS入口启用`COOKIE_SECURE=true`，Nginx专用本机入口将外部Host和HTTPS协议传给FastAPI，保留登录及同源校验。旧HTTP/IP入口不能使用Secure会话Cookie。修改服务器私有`.env`前先备份，不输出其他配置及密钥。

`data/cloudflare-tunnel-status.json`是核验时的地址快照。隧道重建后执行`python3 scripts/refresh_tunnel_status.py`，从该服务当前运行实例的日志读取地址，验证HTTPS主页、健康接口与内部隧道状态后原子更新快照；旧记录先备份。历史业务核验结果不会冒用为新网址的核验结果。不能把旧快照当作始终有效的固定网址，不要在公开README中硬编码临时地址。

隧道对Nginx使用`Wants`和启动顺序依赖，不使用`Requires`：系统安全更新重启Nginx时，隧道可等待源站恢复，无需连带重建临时网址。更新此单元后执行`systemctl daemon-reload`即可加载依赖变更，避免为读取地址而重启隧道。系统安全更新仍正常运行；服务器重启或隧道自身重建仍会更换临时地址。

验证主页、健康、静态资源、视频Range、注册登录与问答；测试账号按精确ID清理。导入和测验生成通过后台队列立即返回，不在公网请求中等待整篇模型处理。Quick Tunnel不支持SSE，当前助教使用普通HTTP问答，无需SSE。Cloudflare对长请求及上传大小有限制，参见https://developers.cloudflare.com/fundamentals/reference/connection-limits/。
