using System;
using System.IO;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using AvaloniaWebView;
using OpenCad.Viewer;

namespace OpenCad.Desktop;

public partial class MainWindow : Window
{
    // DispatcherTimer 在 UI 執行緒觸發——WebView／FindControl 等 UI 存取才合法
    private DispatcherTimer? _messagePollTimer;
    private WebView? _webView;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Closed += OnClosed;
    }

    private void InitializeComponent()
    {
        AvaloniaXamlLoader.Load(this);
    }

    private void OnLoaded(object? sender, EventArgs e)
    {
        var webView = this.FindControl<WebView>("PART_Viewer");
        if (webView == null) return;
        _webView = webView;

        // 訂閱 ViewModel 的 ViewerScriptRequested 事件
        if (DataContext is ViewModels.MainViewModel vm)
        {
            vm.ViewerScriptRequested += async script =>
            {
                try { await webView.ExecuteScriptAsync(script); }
                catch { /* WebView 尚未就緒 */ }
            };
        }

        // 載入本地 viewer.html（使用 file:// 協定，確保離線可用且相對路徑正確）
        var htmlPath = Path.Combine(AppContext.BaseDirectory, "viewer.html");
        if (File.Exists(htmlPath))
        {
            webView.Url = new Uri(htmlPath);
        }

        // 啟動訊息輪詢計時器（每 200ms 檢查一次，UI 執行緒觸發）
        _messagePollTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(200) };
        _messagePollTimer.Tick += OnMessagePoll;
        _messagePollTimer.Start();
    }

    private async void OnMessagePoll(object? sender, EventArgs e)
    {
        var webView = _webView;
        if (webView == null) return;

        try
        {
            var json = await webView.ExecuteScriptAsync("window.opencadDrainMessages ? window.opencadDrainMessages() : '[]'");
            if (string.IsNullOrWhiteSpace(json) || json == "[]" || json == "\"[]\"")
                return;

            // ExecuteScriptAsync 返回的是 JSON 字串（含引號），需先去除外層引號再反序列化
            var inner = json.Trim('"');
            // 處理 JSON 編碼的引號
            inner = inner.Replace("\\\"", "\"").Replace("\\\\", "\\");
            var messages = System.Text.Json.JsonSerializer.Deserialize<string[]>(inner);
            if (messages == null) return;

            foreach (var msgJson in messages)
            {
                var msg = ViewerBridge.ParseMessage(msgJson);
                if (msg == null) continue;

                // DispatcherTimer 已在 UI 執行緒，直接更新 ViewModel
                if (msg.Type == ViewerBridge.MessageType.Loaded)
                {
                    if (DataContext is ViewModels.MainViewModel vm)
                    {
                        vm.HasModel = true;
                        vm.ModelInfoText = "3D 模型已載入";
                    }
                }
                else if (msg.Type == ViewerBridge.MessageType.Error)
                {
                    if (DataContext is ViewModels.MainViewModel vm)
                    {
                        vm.ModelInfoText = $"載入錯誤: {msg.ErrorMessage}";
                    }
                }
            }
        }
        catch
        {
            // WebView 尚未就緒——忽略
        }
    }

    /// <summary>
    /// 在 WebView 中執行 JavaScript（供 ViewModel 使用）。
    /// </summary>
    public async Task ExecuteViewerScriptAsync(string script)
    {
        if (_webView != null)
            await _webView.ExecuteScriptAsync(script);
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        _messagePollTimer?.Stop();
        _messagePollTimer = null;
    }
}