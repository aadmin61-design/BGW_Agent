package com.zhixu.learning;
import org.junit.Test;
import static org.junit.Assert.*;

public class UrlPolicyTest {
    @Test public void acceptsEditableHttpsAndCanonicalisesDefaultPort() {
        assertEquals("https://new.trycloudflare.com/", UrlPolicy.normalise(" https://NEW.trycloudflare.com:443/ "));
        assertEquals("https://zhixubgw.xyz/", UrlPolicy.normalise("https://zhixubgw.xyz"));
    }
    @Test public void rejectsWrongProtocolsCredentialsAndPageUrls() {
        for (String value : new String[]{"http://site.test", "javascript:alert(1)", "https://owner:password@site.test",
            "https://site.test/api", "https://site.test/?key=secret", "https://site.test/#lesson", "https://site.test:8080"}) {
            assertThrows(IllegalArgumentException.class, () -> UrlPolicy.normalise(value));
        }
    }
    @Test public void sessionCannotLeakToOtherHostOrScheme() {
        String base = "https://safe.test/";
        assertTrue(UrlPolicy.sameOrigin(base, "https://safe.test/api/items?x=1#lesson"));
        assertFalse(UrlPolicy.sameOrigin(base, "https://safe.test.evil.test/"));
        assertFalse(UrlPolicy.sameOrigin(base, "https://evil@safe.test/"));
        assertFalse(UrlPolicy.sameOrigin(base, "http://safe.test/"));
        assertFalse(UrlPolicy.sameOrigin(base, "content://safe.test/file"));
    }
}
