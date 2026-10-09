// NAVO TAXI — © 2026 Jovliyev Akobir Olimjon o‘g‘li. Barcha huquqlar himoyalangan. Ruxsatsiz nusxalash, tarqatish va sotish taqiqlanadi.
package uz.navo.taksopark;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebSettings;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Map;

/** Small offline-first shell. No JavaScript/native bridge and no location permission. */
public final class MainActivity extends Activity {
  private WebView web;
  private static final String HOST = "appassets.androidplatform.net";
  @Override public void onCreate(Bundle saved) {
    super.onCreate(saved);
    getWindow().setStatusBarColor(Color.rgb(18,18,18));
    getWindow().setNavigationBarColor(Color.rgb(18,18,18));
    web = new WebView(this);
    web.setBackgroundColor(Color.rgb(242,242,239));
    setContentView(web);
    WebSettings settings = web.getSettings();
    settings.setJavaScriptEnabled(true);
    settings.setDomStorageEnabled(true);
    settings.setAllowFileAccess(false);
    settings.setAllowContentAccess(false);
    settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
    settings.setSupportMultipleWindows(false);
    settings.setSafeBrowsingEnabled(true);
    web.setWebViewClient(new WebViewClient() {
      @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        Uri u = request.getUrl();
        if (!HOST.equals(u.getHost())) return null;
        String name = u.getPath();
        if (name == null || name.equals("/")) name = "/index.html";
        if (name.contains("..")) return missing();
        String mime = name.endsWith(".mjs") || name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : name.endsWith(".svg") ? "image/svg+xml" : name.endsWith(".woff2") ? "font/woff2" : name.endsWith(".png") ? "image/png" : "text/html";
        try {
          Map<String,String> headers = new HashMap<>();
          headers.put("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self'; connect-src 'self' https:; object-src 'none'; base-uri 'self'");
          headers.put("X-Content-Type-Options", "nosniff");
          return new WebResourceResponse(mime,"UTF-8",200,"OK",headers,getAssets().open(name.substring(1)));
        } catch(Exception e) { return missing(); }
      }
      @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        Uri u = request.getUrl();
        if ("https".equals(u.getScheme()) && HOST.equals(u.getHost())) return false;
        if ("tel".equals(u.getScheme())) {
          try { startActivity(new Intent(Intent.ACTION_DIAL,u)); } catch(Exception ignored) {}
        } else if ("https".equals(u.getScheme())) {
          try { startActivity(new Intent(Intent.ACTION_VIEW,u)); } catch(Exception ignored) {}
        }
        return true;
      }
    });
    web.loadUrl("https://"+HOST+"/index.html");
  }
  private WebResourceResponse missing() {
    return new WebResourceResponse("text/plain","UTF-8",404,"Not Found",null,new ByteArrayInputStream("Not found".getBytes()));
  }
  @Override public void onBackPressed() {
    new AlertDialog.Builder(this).setTitle("Ilovadan chiqish?")
      .setMessage("Saqlangan demo buyurtmalaringiz keyingi kirishda ham qoladi.")
      .setNegativeButton("Qolish",(dialog,which)->dialog.dismiss())
      .setPositiveButton("Chiqish",(dialog,which)->finish()).show();
  }
  @Override protected void onDestroy() { web.destroy(); super.onDestroy(); }
}
