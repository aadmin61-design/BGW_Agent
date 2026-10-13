# 知序 Android

Android 8.0及以上的原生Java客户端，通过单个系统WebView使用现有知序服务。没有打包浏览器引擎、React Native运行时、视频或知识库文件。应用名称为“知序”，应用ID为`com.zhixu.learning`，手机竖屏、横屏、平板及分屏使用同一套响应式布局。

## 功能

- 使用原服务器账号注册、登录，学习、测验、记忆计划、收藏及独立助教问答保持与网站一致。
- 管理员可使用系统文档选择器多选并上传PDF、DOCX、Markdown等文档，也可使用既有服务器目录导入；不申请全盘存储权限。
- 保留题目切换、Markdown、高亮代码、复制、收藏及管理任务功能；网页更新通常无需重新安装App。
- 原生菜单提供导航、刷新及服务器设置；更换临时隧道后填写新HTTPS地址，切换服务器会清理本App旧站点会话与网页存储，之后重新登录。
- 原生返回键优先回到题目清单，外部HTTPS链接使用浏览器；没有向网页暴露JavascriptInterface。
- 下载通过系统保存位置选择器和64KiB缓冲流式保存，不在主线程加载整个文件。

## 性能与内存

默认省资源模式不挂载或下载背景视频，禁用重度背景模糊并使用系统字体，保留页面色彩和半透明层次；设置中可以恢复动态背景。一个WebView复用所有模块，系统默认HTTP缓存复用静态资源，切换路由不新建浏览器对象。

后台暂停WebView、视频和网页定时器，并停止导入/测验轮询；前台恢复当前视图，不丢弃未提交输入。横屏、分屏和键盘变化不重建Activity；系统栏及刘海按真实Insets留白，内容使用动态可用高度，不假定16:9屏幕。严重后台内存压力或渲染器退出时释放WebView并显示恢复提示，已提交数据仍在服务器，未提交草稿可能需要重新输入。

保存状态只记录URL，不序列化大量浏览历史或Bitmap；销毁时解除网络观察、选择器回调、下载线程和WebView引用。APK不包含服务端密钥、用户密码或文档数据；关闭明文网络、混合内容、SSL绕过、第三方Cookie及文件URL访问，保持Safe Browsing。

这些是实现措施，实际设备内存占用与帧率取决于系统WebView及页面内容，需在真机上进一步量测。

## 构建

工具清单位于`requirements-build.txt`。不自动安装SDK/JDK；使用已有工具环境：

```bash
cd android
./gradlew testReleaseUnitTest lintRelease assembleRelease
```

Windows使用`gradlew.bat`，SDK位置通过不提交的`local.properties`或已有`ANDROID_HOME`指定。Gradle Wrapper和分发包摘要固定版本。CI使用GitHub托管机器已有的JDK17、SDK36及Build Tools35，不调用sdkmanager安装新环境。

仓库工作流`Build Zhixu Android`生成APK、SHA256及测试/Lint报告。没有签名配置时输出`zhixu-unsigned.apk`，它不能安装，供构建审查。获得用户签名授权后，通过GitHub Secrets注入`ZHIXU_SIGNING_STORE`（PKCS12的Base64）、`ZHIXU_KEYSTORE_PASSWORD`、`ZHIXU_KEY_ALIAS`，输出经apksigner验证的`zhixu.apk`。私钥及密码不进入代码、日志或构建产物，CI结束清理临时密钥。稳定私钥用于后续覆盖安装升级，需单独安全备份。

## 验证范围

URL策略的JVM单元测试检查HTTPS、站点地址规范化及会话同源边界。网页测试检查安卓省资源模式无视频、模块切换复用控制器、后台停止轮询及系统返回。Android编译和Lint由CI运行；没有连接真机时，不把静态检查称为真机性能测试。建议在320/360/412dp宽度、横屏、键盘展开、分屏和低内存设备上检查登录、文档上传、问答、代码复制、收藏、断网重连和切题。
