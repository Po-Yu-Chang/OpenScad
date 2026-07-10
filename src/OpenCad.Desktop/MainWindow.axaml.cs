using System;
using System.Collections.Specialized;
using System.IO;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using AvaloniaWebView;
using OpenCad.Viewer;

namespace OpenCad.Desktop;

public partial class MainWindow : Window
{
    private DispatcherTimer? _messagePollTimer;
    private WebView? _webView;
    private ScrollViewer? _chatScroll;

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
        if (webView != null)
        {
            _webView = webView;

            // 訂閱 ViewModel 的 ViewerScriptRequested 事件
            if (DataContext is ViewModels.MainViewModel vm)
            {
                vm.ViewerScriptRequested += async script =>
                {
                    try { await webView.ExecuteScriptAsync(script); }
                    catch { /* WebView 尚未就緒 */ }
                };

                // 訂閱 Messages 集合變更——自動捲到底
                vm.Messages.CollectionChanged += OnMessagesChanged;

                // Worker 就緒後導航到同源伺服的 viewer（避免 file:// 的 CORS 限制）
                vm.ViewerNavigationRequested += url =>
                {
                    Dispatcher.UIThread.Post(() => webView.Url = new Uri(url));
                };
            }

            // 先載入本地 viewer.html 作為佔位；Worker 就緒後會切換到 http 同源版本
            var htmlPath = Path.Combine(AppContext.BaseDirectory, "viewer.html");
            if (File.Exists(htmlPath))
            {
                webView.Url = new Uri(htmlPath);
            }
        }

        _chatScroll = this.FindControl<ScrollViewer>("PART_ChatScroll");

        // 訊息輪詢計時器
        _messagePollTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(200) };
        _messagePollTimer.Tick += OnMessagePoll;
        _messagePollTimer.Start();

        // 鍵盤綁定：Enter 送出、Shift+Enter 換行——只在提示輸入框內生效
        var promptInput = this.FindControl<TextBox>("PART_PromptInput");
        promptInput?.AddHandler(KeyDownEvent, OnPromptKeyDown, Avalonia.Interactivity.RoutingStrategies.Tunnel);
    }

    private void OnPromptKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && e.KeyModifiers != KeyModifiers.Shift)
        {
            if (DataContext is ViewModels.MainViewModel vm &&
                !string.IsNullOrWhiteSpace(vm.InputText))
            {
                vm.SendCommand.Execute(null);
                e.Handled = true;
            }
        }
    }

    private void OnMessagesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        // 在 UI 執行緒自動捲到底
        Dispatcher.UIThread.Post(() =>
        {
            if (_chatScroll != null)
            {
                _chatScroll.ScrollToEnd();
            }
        });
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

            var inner = json.Trim('"');
            inner = inner.Replace("\\\"", "\"").Replace("\\\\", "\\");
            var messages = System.Text.Json.JsonSerializer.Deserialize<string[]>(inner);
            if (messages == null) return;

            foreach (var msgJson in messages)
            {
                var msg = ViewerBridge.ParseMessage(msgJson);
                if (msg == null) continue;

                if (msg.Type == ViewerBridge.MessageType.Loaded)
                {
                    if (DataContext is ViewModels.MainViewModel vm)
                    {
                        vm.HasModel = true;
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