package com.zhixu.learning;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Insets;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PICK_FILES = 101, SAVE_DOWNLOAD = 102;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService downloadWorker = Executors.newSingleThreadExecutor();
    private SharedPreferences preferences;
    private LinearLayout root;
    private FrameLayout content;
    private LinearLayout errorPanel;
    private TextView hostLabel, errorLabel;
    private ProgressBar progress;
    private WebView webView;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private ValueCallback<Uri[]> fileCallback;
    private boolean multipleFiles;
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback networkCallback;
    private String baseUrl, lastUrl, pendingDownload, pendingFileName;
    private volatile boolean lite = true;
    private boolean resumed, rendererReleased;
    private long backPressedAt;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences("client", MODE_PRIVATE);
        try { baseUrl = UrlPolicy.normalise(preferences.getString("server", BuildConfig.DEFAULT_SERVER_URL)); }
        catch (IllegalArgumentException ignored) { baseUrl = UrlPolicy.normalise(BuildConfig.DEFAULT_SERVER_URL); }
        lite = preferences.getBoolean("lite", true);
        lastUrl = state == null ? preferences.getString("last_page", baseUrl) : state.getString("page", baseUrl);
        if (!UrlPolicy.sameOrigin(baseUrl, lastUrl)) lastUrl = baseUrl;
        buildLayout();
        createWebView();
        observeNetwork();
        // 新版系统使用预测返回；旧版仍走onBackPressed。
        if (Build.VERSION.SDK_INT >= 33) getOnBackInvokedDispatcher().registerOnBackInvokedCallback(0, this::back);
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private Button button(String text, String description) {
        Button button = new Button(this);
        button.setText(text); button.setTextColor(Color.WHITE); button.setTextSize(19);
        button.setPadding(0, 0, 0, 0); button.setMinWidth(0); button.setMinimumWidth(0);
        button.setBackgroundColor(Color.TRANSPARENT); button.setContentDescription(description);
        return button;
    }
    private void buildLayout() {
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(16, 46, 52));
        LinearLayout bar = new LinearLayout(this); bar.setGravity(Gravity.CENTER_VERTICAL);
        Button backButton = button("‹", "返回上一页"); backButton.setOnClickListener(v -> back());
        bar.addView(backButton, new LinearLayout.LayoutParams(dp(48), dp(52)));
        LinearLayout title = new LinearLayout(this); title.setOrientation(LinearLayout.VERTICAL);
        TextView name = new TextView(this); name.setText("知序"); name.setTextSize(17); name.setTextColor(Color.WHITE);
        hostLabel = new TextView(this); hostLabel.setTextSize(10); hostLabel.setTextColor(Color.rgb(191, 213, 210));
        hostLabel.setSingleLine(); hostLabel.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        hostLabel.setText(Uri.parse(baseUrl).getHost()); title.addView(name); title.addView(hostLabel);
        bar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button more = button("⋮", "功能导航与服务器设置"); more.setOnClickListener(this::menu);
        bar.addView(more, new LinearLayout.LayoutParams(dp(48), dp(52)));
        root.addView(bar);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100); root.addView(progress, new LinearLayout.LayoutParams(-1, dp(2)));
        content = new FrameLayout(this); root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
        errorPanel = new LinearLayout(this); errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setGravity(Gravity.CENTER); errorPanel.setPadding(dp(24), dp(24), dp(24), dp(24));
        errorPanel.setBackgroundColor(Color.rgb(16, 46, 52));
        errorLabel = new TextView(this); errorLabel.setTextColor(Color.WHITE); errorLabel.setTextSize(16);
        errorLabel.setGravity(Gravity.CENTER); errorPanel.addView(errorLabel);
        Button retry = button("重新连接", "重新连接当前服务器"); retry.setTextSize(15);
        retry.setOnClickListener(v -> reload()); errorPanel.addView(retry);
        Button address = button("修改服务器地址", "修改已失效的临时地址"); address.setTextSize(15);
        address.setOnClickListener(v -> settings()); errorPanel.addView(address);
        content.addView(errorPanel, new FrameLayout.LayoutParams(-1, -1)); errorPanel.setVisibility(View.GONE);
        setContentView(root);
        // 按系统栏、刘海和键盘的真实尺寸留白，不假定手机比例或固定屏幕高度。
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        else root.setFitsSystemWindows(true);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, keyboard.bottom));
            } else view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
    }

    private void createWebView() {
        if (webView != null || isDestroyed()) return;
        WebView view;
        try { view = new WebView(this); }
        catch (RuntimeException error) { showError("系统WebView不可用，请启用或更新Android System WebView后重试。"); return; }
        webView = view;
        view.setBackgroundColor(Color.rgb(16, 46, 52));
        WebSettings options = view.getSettings();
        options.setJavaScriptEnabled(true); options.setDomStorageEnabled(true);
        options.setUseWideViewPort(true); options.setLoadWithOverviewMode(true);
        options.setBuiltInZoomControls(false); options.setDisplayZoomControls(false);
        options.setSupportMultipleWindows(false); options.setJavaScriptCanOpenWindowsAutomatically(false);
        options.setMediaPlaybackRequiresUserGesture(true);
        options.setCacheMode(WebSettings.LOAD_DEFAULT);
        options.setAllowFileAccess(false); options.setAllowContentAccess(true);
        options.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW); options.setSafeBrowsingEnabled(true);
        options.setUserAgentString(options.getUserAgentString() + " ZhixuAndroid/" + BuildConfig.VERSION_NAME
            + (lite ? " ZhixuLite/1" : ""));
        options.setTextZoom(Math.max(80, Math.min(200, Math.round(getResources().getConfiguration().fontScale * 100))));
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        // 单一WebView复用会话；后台允许系统回收渲染器，并提供可恢复的错误界面。
        view.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, true);
        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView current, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (UrlPolicy.sameOrigin(baseUrl, url)) return false;
                if (request.hasGesture() && "https".equalsIgnoreCase(request.getUrl().getScheme())) external(url);
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView current, WebResourceRequest request) {
                if (lite && UrlPolicy.sameOrigin(baseUrl, request.getUrl().toString())
                    && "/assets/media/learning-background.mp4".equals(request.getUrl().getPath()))
                    return new WebResourceResponse("video/mp4", null, new ByteArrayInputStream(new byte[0]));
                if (lite && ("fonts.googleapis.com".equals(request.getUrl().getHost()) || "fonts.gstatic.com".equals(request.getUrl().getHost())))
                    return new WebResourceResponse("text/css", "UTF-8", new ByteArrayInputStream(new byte[0]));
                return null;
            }
            @Override public void onPageStarted(WebView current, String url, android.graphics.Bitmap icon) {
                if (current != webView) return;
                if (!UrlPolicy.sameOrigin(baseUrl, url)) { current.stopLoading(); showError("页面跳转到其他服务器，已停止加载。"); return; }
                progress.setVisibility(View.VISIBLE);
            }
            @Override public void onPageFinished(WebView current, String url) {
                if (current != webView || !UrlPolicy.sameOrigin(baseUrl, url)) return;
                lastUrl = url; progress.setVisibility(View.GONE);
                hostLabel.setText(Uri.parse(baseUrl).getHost());
                CookieManager.getInstance().flush(); lifecycle(resumed);
            }
            @Override public void onReceivedError(WebView current, WebResourceRequest request, WebResourceError error) {
                if (current == webView && request.isForMainFrame()) showError("暂时无法连接学习服务。请检查网络，或更新已变化的临时地址。");
            }
            @Override public void onReceivedHttpError(WebView current, WebResourceRequest request, WebResourceResponse response) {
                if (current == webView && request.isForMainFrame() && response.getStatusCode() >= 400)
                    showError("学习入口暂不可用（" + response.getStatusCode() + "），请重试或更新服务器地址。");
            }
            @Override public void onReceivedSslError(WebView current, SslErrorHandler handler, SslError error) {
                handler.cancel(); showError("连接未通过HTTPS证书验证。请检查服务器地址或证书后重试。");
            }
            @Override public boolean onRenderProcessGone(WebView current, android.webkit.RenderProcessGoneDetail detail) {
                // 已退出的渲染器不能再使用，移除并销毁，避免整个App崩溃。
                if (current == webView) {
                    if (fileCallback != null) { fileCallback.onReceiveValue(null); fileCallback = null; }
                    hideCustomView();
                    webView = null; content.removeView(current); current.destroy(); rendererReleased = true;
                    showError("页面因系统内存回收而关闭。点击重新连接，已提交的学习记录仍保留。");
                }
                return true;
            }
        });
        view.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView current, int value) {
                if (current == webView) { progress.setProgress(value); progress.setVisibility(value == 100 ? View.GONE : View.VISIBLE); }
            }
            @Override public boolean onShowFileChooser(WebView current, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback; multipleFiles = params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE;
                // 通过系统文档选择器授予单文件访问，不申请整个存储权限，也不预读文档到内存。
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*"); intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multipleFiles);
                try { startActivityForResult(intent, PICK_FILES); }
                catch (ActivityNotFoundException error) { fileCallback.onReceiveValue(null); fileCallback = null; toast("未找到系统文件选择器"); }
                return true;
            }
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
            @Override public void onShowCustomView(View view, CustomViewCallback callback) {
                if (customView != null) { callback.onCustomViewHidden(); return; }
                customView = view; customViewCallback = callback;
                content.addView(view, new FrameLayout.LayoutParams(-1, -1));
            }
            @Override public void onHideCustomView() { hideCustomView(); }
        });
        view.setDownloadListener((url, ua, disposition, mime, length) -> {
            if (!UrlPolicy.sameOrigin(baseUrl, url)) { toast("只允许下载当前服务器提供的文件"); return; }
            pendingDownload = url;
            pendingFileName = android.webkit.URLUtil.guessFileName(url, disposition, mime).replaceAll("[\\\\/\\p{Cntrl}]", "_");
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType(mime == null ? "application/octet-stream" : mime); intent.putExtra(Intent.EXTRA_TITLE, pendingFileName);
            try { startActivityForResult(intent, SAVE_DOWNLOAD); }
            catch (ActivityNotFoundException error) { pendingDownload = null; toast("未找到文件保存程序"); }
        });
        content.addView(view, 0, new FrameLayout.LayoutParams(-1, -1));
        view.loadUrl(lastUrl);
    }

    private void showError(String message) {
        errorLabel.setText(message); errorPanel.setVisibility(View.VISIBLE); errorPanel.bringToFront(); progress.setVisibility(View.GONE);
    }
    private void reload() {
        errorPanel.setVisibility(View.GONE);
        if (webView == null) createWebView(); else webView.loadUrl(lastUrl);
        rendererReleased = false;
    }
    private void toast(String text) { if (!isDestroyed()) Toast.makeText(this, text, Toast.LENGTH_SHORT).show(); }
    private void external(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (ActivityNotFoundException error) { toast("未找到浏览器"); }
    }
    private void menu(View anchor) {
        if (webView == null) { showMenu(anchor, false); return; }
        webView.evaluateJavascript("Boolean(document.querySelector('[data-nav=\"admin\"]'))", result -> {
            if (!isDestroyed()) showMenu(anchor, "true".equals(result));
        });
    }
    private void showMenu(View anchor, boolean administrator) {
        PopupMenu menu = new PopupMenu(this, anchor);
        String[] labels = {"学习概览", "每日学习", "每日测验", "记忆计划", "我的收藏", "知识库", "知识库管理", "刷新页面", "服务器与性能设置"};
        for (int i = 0; i < labels.length; i++) if (i != 6 || administrator) menu.getMenu().add(0, i, i, labels[i]);
        menu.setOnMenuItemClickListener(item -> {
            int id = item.getItemId();
            if (id == 8) settings();
            else if (id == 7) new AlertDialog.Builder(this).setMessage("刷新会重新加载当前页面，未提交内容可能丢失。")
                .setPositiveButton("刷新", (dialog, which) -> reload()).setNegativeButton("取消", null).show();
            else if (webView != null) {
                String[] pages = {"dashboard", "lesson", "quiz", "memory", "bookmarks", "knowledge", "admin"};
                webView.evaluateJavascript("window.location.hash=" + JSONObject.quote(pages[id]), null);
            }
            return true;
        }); menu.show();
    }
    private void settings() {
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(dp(22), dp(12), dp(22), 0);
        TextView label = new TextView(this); label.setText("填写你的知序服务器HTTPS地址。临时隧道地址变化后在这里更新，更换服务器需重新登录。"); panel.addView(label);
        EditText address = new EditText(this); address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setSingleLine(); address.setText(baseUrl); panel.addView(address);
        android.widget.CheckBox economy = new android.widget.CheckBox(this); economy.setText("省资源模式：关闭背景视频与重度模糊"); economy.setChecked(lite); panel.addView(economy);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("服务器与性能设置").setView(panel)
            .setPositiveButton("保存", null).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(value -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String endpoint;
            try { endpoint = UrlPolicy.normalise(address.getText().toString()); }
            catch (IllegalArgumentException error) { address.setError(error.getMessage()); return; }
            boolean changed = !baseUrl.equals(endpoint);
            if (!changed && lite == economy.isChecked()) { dialog.dismiss(); return; }
            final String chosen = endpoint; final boolean chosenLite = economy.isChecked();
            new AlertDialog.Builder(this).setMessage("这会重新打开学习空间，未提交内容可能丢失。是否保存？")
                .setPositiveButton("保存并打开", (confirmation, which) -> {
                    baseUrl = chosen; lite = chosenLite; lastUrl = baseUrl;
                    preferences.edit().putString("server", baseUrl).putString("last_page", lastUrl).putBoolean("lite", lite).apply();
                    destroyWebView(); hostLabel.setText(Uri.parse(baseUrl).getHost()); errorPanel.setVisibility(View.GONE);
                    if (changed) {
                        WebStorage.getInstance().deleteAllData();
                        CookieManager.getInstance().removeAllCookies(ignored -> { if (!isDestroyed()) createWebView(); });
                    } else createWebView();
                    dialog.dismiss();
                }).setNegativeButton("取消", null).show();
        })); dialog.show();
    }

    @Override protected void onActivityResult(int request, int result, Intent intent) {
        super.onActivityResult(request, result, intent);
        if (request == PICK_FILES && fileCallback != null) {
            Set<Uri> selected = new LinkedHashSet<>();
            if (result == RESULT_OK && intent != null) {
                if (intent.getClipData() != null) for (int i = 0; i < Math.min(intent.getClipData().getItemCount(), 100); i++) selected.add(intent.getClipData().getItemAt(i).getUri());
                else if (intent.getData() != null) selected.add(intent.getData());
            }
            selected.removeIf(uri -> !"content".equals(uri.getScheme()));
            ArrayList<Uri> values = new ArrayList<>(selected);
            if (!multipleFiles && values.size() > 1) values = new ArrayList<>(values.subList(0, 1));
            fileCallback.onReceiveValue(values.isEmpty() ? null : values.toArray(new Uri[0])); fileCallback = null;
        } else if (request == SAVE_DOWNLOAD) {
            String url = pendingDownload; pendingDownload = null;
            if (result == RESULT_OK && intent != null && intent.getData() != null && url != null) download(url, intent.getData());
        }
    }
    private void download(String url, Uri destination) {
        String origin = baseUrl, cookies = CookieManager.getInstance().getCookie(url);
        android.content.ContentResolver resolver = getApplicationContext().getContentResolver();
        toast("正在保存文件");
        downloadWorker.submit(() -> {
            HttpURLConnection connection = null;
            try {
                // 下载在单一后台线程中流式复制，限制缓冲区为64KiB，不在主线程读取大文件。
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setConnectTimeout(20000); connection.setReadTimeout(20000); connection.setInstanceFollowRedirects(false);
                if (UrlPolicy.sameOrigin(origin, url) && cookies != null) connection.setRequestProperty("Cookie", cookies);
                if (connection.getResponseCode() != 200) throw new java.io.IOException("download_unavailable");
                try (InputStream input = connection.getInputStream(); OutputStream output = resolver.openOutputStream(destination)) {
                    if (output == null) throw new java.io.IOException("destination_unavailable");
                    byte[] buffer = new byte[65536]; int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (Thread.currentThread().isInterrupted()) throw new java.io.InterruptedIOException();
                        output.write(buffer, 0, count);
                    }
                }
                main.post(() -> toast("文件已保存"));
            } catch (Exception error) {
                try { android.provider.DocumentsContract.deleteDocument(resolver, destination); } catch (Exception ignored) {}
                main.post(() -> toast("保存失败，请检查网络后重试"));
            } finally { if (connection != null) connection.disconnect(); }
        });
    }
    private void observeNetwork() {
        connectivity = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) { main.post(() -> { if (!isDestroyed()) hostLabel.setText(Uri.parse(baseUrl).getHost()); }); }
            @Override public void onLost(Network network) { main.post(() -> { if (!isDestroyed()) hostLabel.setText("网络已断开，页面与已提交记录保留"); }); }
        };
        try { connectivity.registerDefaultNetworkCallback(networkCallback); } catch (RuntimeException ignored) { networkCallback = null; }
    }
    private void lifecycle(boolean visible) {
        if (webView == null || !UrlPolicy.sameOrigin(baseUrl, webView.getUrl())) return;
        webView.evaluateJavascript("window.dispatchEvent(new CustomEvent('zhixu:visibility',{detail:{active:" + visible + "}}));", null);
    }
    @Override protected void onResume() {
        super.onResume(); resumed = true;
        if (webView != null) { webView.onResume(); webView.resumeTimers(); lifecycle(true); }
        else if (rendererReleased) { errorPanel.setVisibility(View.VISIBLE); }
    }
    @Override protected void onPause() {
        lifecycle(false); resumed = false;
        if (webView != null) { webView.onPause(); webView.pauseTimers(); }
        CookieManager.getInstance().flush();
        super.onPause();
    }
    @Override protected void onStop() {
        if (webView != null && UrlPolicy.sameOrigin(baseUrl, webView.getUrl())) lastUrl = webView.getUrl();
        if (lastUrl.length() <= 2048) preferences.edit().putString("last_page", lastUrl).apply();
        super.onStop();
    }
    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (webView != null) webView.getSettings().setTextZoom(Math.max(80, Math.min(200, Math.round(configuration.fontScale * 100))));
        root.requestApplyInsets();
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        // 只保存当前URL，避免WebView整段历史超过Android的1MiB状态上限。
        state.putString("page", lastUrl.length() <= 2048 ? lastUrl : baseUrl); super.onSaveInstanceState(state);
    }
    @Override public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        if (!resumed && level >= TRIM_MEMORY_COMPLETE && webView != null) {
            if (UrlPolicy.sameOrigin(baseUrl, webView.getUrl())) lastUrl = webView.getUrl();
            destroyWebView(); rendererReleased = true;
        }
    }
    private void hideCustomView() {
        if (customView == null) return;
        content.removeView(customView); customView = null;
        if (customViewCallback != null) customViewCallback.onCustomViewHidden(); customViewCallback = null;
    }
    private void destroyWebView() {
        if (fileCallback != null) { fileCallback.onReceiveValue(null); fileCallback = null; }
        hideCustomView();
        if (webView != null) {
            WebView old = webView; webView = null;
            old.stopLoading(); content.removeView(old); old.setWebChromeClient(null); old.destroy();
        }
    }
    private void back() {
        if (customView != null) { hideCustomView(); return; }
        if (webView == null || errorPanel.getVisibility() == View.VISIBLE) { exitOrToast(); return; }
        WebView current = webView;
        current.evaluateJavascript("window.zhixuAndroidBack ? window.zhixuAndroidBack() : false", result -> {
            if (webView != current || isDestroyed() || "true".equals(result)) return;
            if (current.canGoBack()) current.goBack(); else exitOrToast();
        });
    }
    private void exitOrToast() {
        long now = android.os.SystemClock.elapsedRealtime();
        if (now - backPressedAt < 2000) finish();
        else { backPressedAt = now; toast("再按一次返回退出知序"); }
    }
    @Override public void onBackPressed() { back(); }
    @Override protected void onDestroy() {
        if (networkCallback != null) try { connectivity.unregisterNetworkCallback(networkCallback); } catch (RuntimeException ignored) {}
        downloadWorker.shutdownNow(); main.removeCallbacksAndMessages(null); destroyWebView();
        super.onDestroy();
    }
}
