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
    private readonly string? _engine;
    private readonly string? _freecadDir;

    /// <param name="workerPath">cad-worker 目錄路徑</param>
    /// <param name="pythonPath">Python 可執行檔路徑（如 python3）</param>
    /// <param name="engine">引擎選擇："build123d"（預設）或 "freecad"</param>
    /// <param name="freecadDir">FreeCAD 安裝目錄（engine=freecad 時使用）</param>
    /// <param name="logger">Serilog logger</param>
    public CadWorkerProcess(string workerPath, string pythonPath = "python",
        string? engine = null, string? freecadDir = null, ILogger? logger = null)
    {
        _workerPath = workerPath;
        _pythonPath = pythonPath;
        _engine = engine;
        _freecadDir = freecadDir;
        _logger = logger ?? Log.Logger;
        
        // WP1-0R: 驗證引擎設定與 Python 路徑
        ValidateEngineAndPythonPath();
    }

    /// <summary>
    /// 工作階段 Token——StartAsync 成功後可用於建構 CadWorkerClient。
    /// </summary>
    public string? SessionToken => _sessionToken;

    /// <summary>
    /// Worker 監聽的埠——每次啟動隨機挑選空閒埠，
    /// 避免殭屍 Worker 佔用固定埠導致綁定失敗。
    /// </summary>
    public int Port { get; private set; }
    
    /// <summary>
    /// 驗證引擎設定與 Python 路徑的相容性
    /// </summary>
    private void ValidateEngineAndPythonPath()
    {
        if (_engine == "freecad")
        {
            // 檢查是否使用 FreeCAD 的 Python
            if (!_pythonPath.Contains("FreeCAD") && !_pythonPath.Contains("freecad"))
            {
                _logger.Warning("引擎設為 freecad 但 Python 路徑似乎不是 FreeCAD 的 Python: {Path}", _pythonPath);
            }
            
            // 檢查 Python 可執行檔是否存在
            if (!File.Exists(_pythonPath))
            {
                _logger.Error("引擎設為 freecad 但找不到指定的 Python 可執行檔: {Path}", _pythonPath);
            }
        }
        else if (_engine == "build123d")
        {
            // 對於 build123d 引擎，使用系統 Python 是正常的
            _logger.Information("使用 build123d 引擎，Python 路徑: {Path}", _pythonPath);
        }
    }

    /// <summary>
    /// 3D Viewer 靜態檔案目錄（viewer.html＋assets）。
    /// 設定後 Worker 會以 /viewer 路徑伺服，讓 viewer 與 GLB 同源。
    /// </summary>
    public string? ViewerDir { get; set; }

    private static int FindFreePort()
    {
        var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    /// <summary>
    /// 啟動 CAD Worker 子程序。以健康檢查通過為啟動成功的依據
    /// （Token 檔案出現不代表埠綁定成功）。
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
        Port = FindFreePort();

        // WP1-0R: 驗證引擎設定與 Python 路徑
        if (_engine == "freecad" && !File.Exists(_pythonPath))
        {
            _logger.Error("引擎設為 freecad 但找不到指定的 Python 可執行檔: {Path}", _pythonPath);
            return false;
        }

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
        // 透過環境變數傳遞 Token 檔案路徑、埠號與父程序 PID
        // （Worker 監看父程序，主程式被強制關閉時自我終止，不留殭屍）
        startInfo.Environment["OPENCAD_TOKEN_FILE"] = _tokenFilePath;
        startInfo.Environment["OPENCAD_WORKER_PORT"] = Port.ToString();
        startInfo.Environment["OPENCAD_PARENT_PID"] = Environment.ProcessId.ToString();
        if (!string.IsNullOrEmpty(ViewerDir))
            startInfo.Environment["OPENCAD_VIEWER_DIR"] = ViewerDir;

        // WP1-0R: 引擎選擇——傳遞給 Worker
        if (!string.IsNullOrEmpty(_engine))
            startInfo.Environment["OPENCAD_ENGINE"] = _engine;
        if (!string.IsNullOrEmpty(_freecadDir))
            startInfo.Environment["FREECAD_DIR"] = _freecadDir;

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

            // Token 出現不代表埠綁定成功——必須以健康檢查確認
            if (!await WaitForHealthAsync(timeoutMs: 15000))
            {
                _logger.Error("CAD Worker 健康檢查失敗（埠 {Port}）", Port);
                return false;
            }

            _logger.Information("CAD Worker 已啟動 (PID: {Pid}, 埠: {Port})", _process.Id, Port);
            return true;
        }
        catch (Exception ex)
        {
            _logger.Error(ex, "啟動 CAD Worker 失敗");
            return false;
        }
    }

    private async Task<bool> WaitForHealthAsync(int timeoutMs)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (DateTime.UtcNow < deadline)
        {
            if (_process?.HasExited == true)
            {
                _logger.Error("CAD Worker 已結束（結束碼 {Code}）——可能是埠綁定失敗", _process.ExitCode);
                return false;
            }
            try
            {
                var resp = await http.GetAsync($"http://127.0.0.1:{Port}/api/health");
                if (resp.IsSuccessStatusCode)
                {
                    // WP1-0R: 驗證引擎設定與實際使用的引擎是否一致
                    if (!string.IsNullOrEmpty(_engine))
                    {
                        var healthContent = await resp.Content.ReadAsStringAsync();
                        if (_engine == "freecad" && healthContent.Contains("\"unavailable\""))
                        {
                            _logger.Error("引擎設為 freecad 但 Worker health 顯示引擎不可用: {Health}", healthContent);
                            return false;
                        }
                        else if (_engine == "freecad" && !healthContent.Contains("\"freecad\"") && !healthContent.Contains("\"engine\":\"freecad\""))
                        {
                            _logger.Warning("引擎設為 freecad 但 Worker health 未回報 freecad 引擎: {Health}", healthContent);
                        }
                        else if (_engine == "build123d" && !healthContent.Contains("\"build123d\"") && !healthContent.Contains("\"engine\":\"build123d\""))
                        {
                            _logger.Warning("引擎設為 build123d 但 Worker health 未回報 build123d 引擎: {Health}", healthContent);
                        }
                    }
                    return true;
                }
            }
            catch
            {
                // 尚未就緒，稍後重試
            }
            await Task.Delay(300);
        }
        return false;
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