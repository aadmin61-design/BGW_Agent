package com.zhixu.learning;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

final class UrlPolicy {
    private UrlPolicy() {}
    static String normalise(String value) {
        try {
            URI uri = new URI(value.trim());
            String path = uri.getRawPath();
            // API使用站点根路径；拒绝账号、查询参数及伪装成域名的页面地址。
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                || (uri.getPort() != -1 && uri.getPort() != 443)
                || (path != null && !path.isEmpty() && !path.equals("/"))) {
                throw new IllegalArgumentException("请填写完整HTTPS站点地址，不带账号、页面路径或参数");
            }
            return "https://" + uri.getHost().toLowerCase(Locale.ROOT) + "/";
        } catch (URISyntaxException | NullPointerException error) {
            throw new IllegalArgumentException("服务器地址格式不正确");
        }
    }
    static boolean sameOrigin(String base, String value) {
        try {
            URI a = URI.create(base), b = URI.create(value);
            return "https".equalsIgnoreCase(b.getScheme()) && b.getHost() != null
                && a.getHost().equalsIgnoreCase(b.getHost()) && b.getUserInfo() == null
                && (b.getPort() == -1 || b.getPort() == 443);
        } catch (IllegalArgumentException | NullPointerException error) { return false; }
    }
    static boolean video(String value) {
        try { return URI.create(value).getPath().toLowerCase(Locale.ROOT).endsWith(".mp4"); }
        catch (RuntimeException error) { return false; }
    }
}
