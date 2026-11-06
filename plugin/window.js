// Webview controller — PT serves interface/index.html via the `this-sm:` scheme.

function htmlWindow() {}

htmlWindow.prototype.cleanUp = function () {
  this.webview.unregisterEvent("closed", this, this.windowClosed);
};

htmlWindow.prototype.show = function () {
  if (webViewManager.getWebView(this.webviewId) == null) {
    this.webview = webViewManager.createWebView(
      "Packet Tracer MCP",
      "this-sm:index.html",
      800,
      500
    );
    this.webviewId = this.webview.getWebViewId();
    this.webview.registerEvent("closed", this, this.windowClosed);
    this.webview.setMinimumWidth(400);
    this.webview.setMinimumHeight(300);
  }

  // hide()/show() forces PT to re-focus an already-open webview.
  this.webview.hide();
  this.webview.show();
};

htmlWindow.prototype.windowClosed = function (src, args) {
  this.webviewId = "";
  this.webview.unregisterEvent("closed", this, this.windowClosed);
};
