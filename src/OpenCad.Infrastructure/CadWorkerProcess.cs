using System.Diagnostics;
using Serilog;

namespace OpenCad.Infrastructure;

/// <summary>
/// CAD Worker 生命週期管理——啟動、監控與終止 Python Worker 子程序。
/// Worker Crash 不應造成桌面主程式關閉。
/// </summary>
public class CadWorkerProcess : IDisposable
{
    private Process? _process;
    private readonly string _workerPath;
    private readonly string _pythonPath;
    private readonly ILogger _logger;
    private string? _sessionToken;
    private string? _tokenFilePath;

    /// <param name="workerPath">cad-worker 目錄路徑</param>
    /// <param name="pythonPath">Python 可執行檔路徑（如 python3）</param>
    public CadWorkerProcess(string workerPath, string pythonPath = "python", ILogger? logger = null)
    {
        _workerPath = workerPath;
        _pythonPath = pythonPath;
        _logger = logger ?? Log.Logger;
    }

    /// <summary>
    /// 工作階段 Token——StartAsync 成功後可用於建構 CadWorkerClient。
    /// </summary>
    public string? SessionToken => _sessionToken;

    /// <summary>
    /// 啟動 CAD Worker 子程序。
    /// </summary>
    public async Task<bool> StartAsync()
    {
        var scriptPath = Path.Combine(_workerPath, "run_worker.py");
        if (!File.Exists(scriptPath))
        {
            _logger.Error("找不到 CAD Worker 腳本: {Path}", scriptPath);
            return false;
        }

        // 產生 Token 檔案路徑——Worker 會將 Session Token 寫入此檔案
        _tokenFilePath = Path.Combine(Path.GetTempPath(), $"opencad_token_{Guid.NewGuid():N}.txt");

        var startInfo = new ProcessStartInfo
        {
            FileName = _pythonPath,
            Arguments = $"\"{scriptPath}\"",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = _workerPath,
        };
        // 透過環境變數傳遞 Token 檔案路徑
        startInfo.Environment["OPENCAD_TOKEN_FILE"] = _tokenFilePath;

        try
        {
            _process = new Process { StartInfo = startInfo };
            _process.OutputDataReceived += (_, e) =>
            {
                if (!string.IsNullOrEmpty(e.Data))
                    _logger.Information("[CAD Worker] {Line}", e.Data);
            };
            _process.ErrorDataReceived += (_, e) =>
            {
                if (!string.IsNullOrEmpty(e.Data))
                    _logger.Error("[CAD Worker] {Line}", e.Data);
            };

            _process.Start();
            _process.BeginOutputReadLine();
            _process.BeginErrorReadLine();

            // 等待 Worker 啟動並寫入 Token 檔案
            if (!await WaitForTokenAsync(timeoutMs: 10000))
            {
                _logger.Error("CAD Worker 啟動逾時——無法取得工作階段 Token");
                return false;
            }

            if (_process.HasExited)
            {
                _logger.Error("CAD Worker 啟動後立即結束，結束碼: {Code}", _process.ExitCode);
                return false;
            }

            _logger.Information("CAD Worker 已啟動 (PID: {Pid})", _process.Id);
            return true;
        }
        catch (Exception ex)
        {
            _logger.Error(ex, "啟動 CAD Worker 失敗");
            return false;
        }
    }

    private async Task<bool> WaitForTokenAsync(int timeoutMs)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (DateTime.UtcNow < deadline)
        {
            if (_process?.HasExited == true)
                return false;
            if (_tokenFilePath != null && File.Exists(_tokenFilePath))
            {
                try
                {
                    _sessionToken = File.ReadAllText(_tokenFilePath).Trim();
                    if (!string.IsNullOrEmpty(_sessionToken))
                    {
                        _logger.Information("已取得 CAD Worker 工作階段 Token");
                        return true;
                    }
                }
                catch
                {
                    // 檔案可能正在寫入中，稍後重試
                }
            }
            await Task.Delay(200);
        }
        return false;
    }

    /// <summary>
    /// 停止 CAD Worker。
    /// </summary>
    public void Stop()
    {
        if (_process is { } p && !p.HasExited)
        {
            try
            {
                p.Kill(entireProcessTree: true);
                _logger.Information("CAD Worker 已停止");
            }
            catch (Exception ex)
            {
                _logger.Error(ex, "停止 CAD Worker 失敗");
            }
        }
        // 清理 Token 檔案
        if (_tokenFilePath != null && File.Exists(_tokenFilePath))
        {
            try { File.Delete(_tokenFilePath); } catch { }
        }
    }

    public bool IsRunning => _process is { HasExited: false };

    public void Dispose()
    {
        Stop();
        _process?.Dispose();
        GC.SuppressFinalize(this);
    }
}