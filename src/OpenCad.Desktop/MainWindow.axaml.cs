using System;
using System.Collections.Specialized;
using System.IO;
using System.Linq;
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

                // 縮圖擷取：執行 JS 並取回 dataURL
                vm.ViewerScriptEvaluateRequested += async script =>
                {
                    try { return await webView.ExecuteScriptAsync(script); }
                    catch { return null; }
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
        // 先 -= 再 +=：Loaded 若重入不會重複掛載（重複掛載會造成一次 Enter 送出兩次）
        var promptInput = this.FindControl<TextBox>("PART_PromptInput");
        if (promptInput != null)
        {
            _promptInput = promptInput;
            promptInput.KeyDown -= OnPromptKeyDown;
            promptInput.KeyDown += OnPromptKeyDown;
        }
    }

    private TextBox? _promptInput;
    private Avalonia.Controls.Presenters.TextPresenter? _promptPresenter;
    private bool _presenterHooked;
    private DateTime _lastImeCommitUtc = DateTime.MinValue;
    private string _lastPreedit = string.Empty;

    /// <summary>
    /// 取得輸入框的 TextPresenter 並訂閱 PreeditText 變化——
    /// 中文輸入法（注音/拼音）組字中 PreeditText 非空；
    /// 由非空→空的瞬間即「選字完成（commit）」，該次 Enter 不得觸發送出。
    /// </summary>
    private Avalonia.Controls.Presenters.TextPresenter? GetPromptPresenter()
    {
        if (_promptPresenter == null && _promptInput != null)
        {
            _promptPresenter = Avalonia.VisualTree.VisualExtensions
                .GetVisualDescendants(_promptInput)
                .OfType<Avalonia.Controls.Presenters.TextPresenter>()
                .FirstOrDefault();

            if (_promptPresenter != null && !_presenterHooked)
            {
                _presenterHooked = true;
                _promptPresenter.PropertyChanged += (_, args) =>
                {
                    if (args.Property.Name != nameof(Avalonia.Controls.Presenters.TextPresenter.PreeditText))
                        return;
                    var newVal = args.NewValue as string ?? string.Empty;
                    // 非空 → 空 ＝ 組字剛提交
                    if (!string.IsNullOrEmpty(_lastPreedit) && string.IsNullOrEmpty(newVal))
                        _lastImeCommitUtc = DateTime.UtcNow;
                    _lastPreedit = newVal;
                };
            }
        }
        return _promptPresenter;
    }

    private void OnPromptKeyDown(object? sender, KeyEventArgs e)
    {
        // Handle Enter key for sending message (without Shift modifier)
        if (e.Key == Key.Enter && e.KeyModifiers == KeyModifiers.None)
        {
            // IME 防護 1：組字中（候選字未確認）——Enter 是選字，不是送出
            var presenter = GetPromptPresenter();
            if (!string.IsNullOrEmpty(presenter?.PreeditText))
                return;

            // IME 防護 2：剛完成選字的同一顆 Enter（commit 後 KeyDown 才到達）——不送出
            if ((DateTime.UtcNow - _lastImeCommitUtc).TotalMilliseconds < 150)
            {
                e.Handled = true;   // 也不要讓 TextBox 插入換行
                return;
            }

            if (DataContext is ViewModels.MainViewModel vm &&
                !string.IsNullOrWhiteSpace(vm.InputText))
            {
                e.Handled = true;
                vm.SendCommand.Execute(null);
            }
        }
        // Allow Shift+Enter to create new line (don't handle it here)
        else if (e.Key == Key.Enter && e.KeyModifiers == KeyModifiers.Shift)
        {
            // Let the TextBox handle Shift+Enter for new line insertion
            return;
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

                if (DataContext is ViewModels.MainViewModel vm)
                {
                    switch (msg.Type)
                    {
                        case ViewerBridge.MessageType.Loaded:
                            vm.HasModel = true;
                            break;
                        case ViewerBridge.MessageType.Error:
                            vm.ModelInfoText = $"載入錯誤: {msg.ErrorMessage}";
                            break;
                        case ViewerBridge.MessageType.SketchCommitted:
                            if (msg.FeatureId != null && msg.EntitiesJson != null)
                                _ = vm.CommitSketchAsync(msg.FeatureId, msg.EntitiesJson, msg.ConstraintsJson);
                            break;
                        case ViewerBridge.MessageType.SketchCancelled:
                            vm.CancelSketch();
                            break;
                        case ViewerBridge.MessageType.SketchSolve:
                            if (msg.FeatureId != null && msg.EntitiesJson != null)
                                _ = vm.SolveSketchAsync(msg.FeatureId, msg.EntitiesJson, msg.ConstraintsJson);
                            break;
                        case ViewerBridge.MessageType.DatumPlaneClicked:
                            if (msg.DatumPlaneName != null)
                                vm.SelectDatumPlane(msg.DatumPlaneName);
                            break;
                        case ViewerBridge.MessageType.FaceSelected:
                            if (msg.SourceFeatureId != null)
                                _ = vm.HandleFaceSelectedAsync(msg.SourceFeatureId, msg.Centroid);
                            break;
                        case ViewerBridge.MessageType.MeasurementResult:
                            vm.AddMeasurement(
                                msg.MeasurementType ?? "distance",
                                msg.MeasurementValue,
                                msg.MeasurementUnit ?? "mm",
                                msg.MeasurementDescription ?? "");
                            break;
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