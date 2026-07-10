using System;
using System.IO;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using AvaloniaWebView;
using OpenCad.Application;
using OpenCad.Infrastructure;
using OpenCad.Viewer;
using Serilog;

namespace OpenCad.Desktop;

public class App : Avalonia.Application
{
    private CadWorkerProcess? _workerProcess;
    private ICadWorker? _cadWorker;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void RegisterServices()
    {
        base.RegisterServices();
        AvaloniaWebViewBuilder.Initialize(default);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // 視窗必須在啟動流程中同步建立——Avalonia 只在啟動當下顯示
            // desktop.MainWindow，事後才指定的視窗不會被顯示。
            var vm = new ViewModels.MainViewModel();
            desktop.MainWindow = new MainWindow { DataContext = vm };
            desktop.ShutdownRequested += OnShutdownRequested;

            // Worker 啟動需時約 10 秒——在背景進行，完成後掛載到 ViewModel
            _ = InitializeWorkerAsync(vm);
        }
        base.OnFrameworkInitializationCompleted();
    }

    private async Task InitializeWorkerAsync(ViewModels.MainViewModel vm)
    {
        try
        {
            var workerDir = FindWorkerDir();
            if (workerDir == null)
            {
                Log.Warning("找不到 cad-worker 目錄——Worker 功能將停用");
                await Dispatcher.UIThread.InvokeAsync(() => vm.AttachWorker(null, null));
                return;
            }

            _workerProcess = new CadWorkerProcess(workerDir, "python")
            {
                // 讓 Worker 伺服 viewer 靜態檔案（與 GLB 同源，避免 CORS）
                ViewerDir = AppContext.BaseDirectory,
            };
            var started = await _workerProcess.StartAsync();
            if (!started || string.IsNullOrEmpty(_workerProcess.SessionToken))
            {
                Log.Warning("CAD Worker 啟動失敗——Worker 功能將停用");
                _workerProcess?.Dispose();
                _workerProcess = null;
                await Dispatcher.UIThread.InvokeAsync(() => vm.AttachWorker(null, null));
                return;
            }

            var client = new CadWorkerClient($"http://127.0.0.1:{_workerProcess.Port}", _workerProcess.SessionToken);
            _cadWorker = client;
            Log.Information("CAD Worker 已連線");
            var viewerUrl = $"http://127.0.0.1:{_workerProcess.Port}/viewer/viewer.html";
            await Dispatcher.UIThread.InvokeAsync(() => vm.AttachWorker(client, client, viewerUrl));
        }
        catch (Exception ex)
        {
            Log.Error(ex, "初始化 CAD Worker 失敗");
            await Dispatcher.UIThread.InvokeAsync(() => vm.AttachWorker(null, null));
        }
    }

    /// <summary>
    /// 尋找 cad-worker 目錄——從 AppContext.BaseDirectory 逐層往上走，
    /// 或讀取 OPENCAD_WORKER_DIR 環境變數。
    /// </summary>
    private string? FindWorkerDir()
    {
        var envDir = Environment.GetEnvironmentVariable("OPENCAD_WORKER_DIR");
        if (!string.IsNullOrEmpty(envDir) && File.Exists(Path.Combine(envDir, "run_worker.py")))
            return envDir;

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 10 && dir != null; i++)
        {
            var candidate = Path.Combine(dir.FullName, "cad-worker", "run_worker.py");
            if (File.Exists(candidate))
                return Path.Combine(dir.FullName, "cad-worker");
            dir = dir.Parent;
        }
        return null;
    }

    private void OnShutdownRequested(object? sender, ShutdownRequestedEventArgs e)
    {
        _workerProcess?.Dispose();
    }
}