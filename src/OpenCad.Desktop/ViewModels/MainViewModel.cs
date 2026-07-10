using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Windows.Input;
using OpenCad.Application;
using OpenCad.Domain;
using OpenCad.Infrastructure;
using OpenCad.Llm;
using OpenCad.MVVM;
using OpenCad.Viewer;
using Serilog;

namespace OpenCad.Desktop.ViewModels;

/// <summary>
/// 主 ViewModel——連接 UI 與 LLM／CAD Worker。
/// </summary>
public class MainViewModel : INotifyPropertyChanged
{
    private ICadWorker? _worker;
    private CadWorkerClient? _workerClient;
    private ILlmProvider? _llmProvider;
    private readonly List<ChatTurn> _chatHistory = new();

    private string _inputText = string.Empty;
    private string _llmStatus = "LLM：偵測中…";
    private string _modelInfoText = string.Empty;
    private string _validationText = "驗證報告：尚未執行";
    private string _massInfoText = string.Empty;
    private string _workerStatus = "Worker：連線中…";
    private string? _projectId;
    private bool _hasModel;
    private bool _isWorkerConnected;
    private bool _isBusy;
    private bool _isRightPanelVisible = true;
    private FeatureNode? _selectedFeature;
    private int _rebuildCount;

    public ObservableCollection<ChatMessage> Messages { get; } = new();
    public ObservableCollection<FeatureNode> FeatureTree { get; } = new();
    public ObservableCollection<ParameterItem> SelectedFeatureParameters { get; } = new();

    public string InputText
    {
        get => _inputText;
        set
        {
            _inputText = value;
            OnPropertyChanged();
            // SendCommand 的 CanExecute 依賴此屬性——必須通知按鈕重新查詢
            ((AsyncRelayCommand)SendCommand).RaiseCanExecuteChanged();
        }
    }

    public string LlmStatus
    {
        get => _llmStatus;
        set { _llmStatus = value; OnPropertyChanged(); }
    }

    public string ModelInfoText
    {
        get => _modelInfoText;
        set { _modelInfoText = value; OnPropertyChanged(); }
    }

    public string ValidationText
    {
        get => _validationText;
        set { _validationText = value; OnPropertyChanged(); }
    }

    public string MassInfoText
    {
        get => _massInfoText;
        set { _massInfoText = value; OnPropertyChanged(); }
    }

    public string WorkerStatus
    {
        get => _workerStatus;
        set { _workerStatus = value; OnPropertyChanged(); }
    }

    public bool HasModel
    {
        get => _hasModel;
        set { _hasModel = value; OnPropertyChanged(); }
    }

    public bool IsWorkerConnected
    {
        get => _isWorkerConnected;
        set
        {
            _isWorkerConnected = value;
            OnPropertyChanged();
            RefreshCanExecute();
        }
    }

    public bool IsBusy
    {
        get => _isBusy;
        set
        {
            _isBusy = value;
            OnPropertyChanged();
            RefreshCanExecute();
        }
    }

    public bool IsRightPanelVisible
    {
        get => _isRightPanelVisible;
        set { _isRightPanelVisible = value; OnPropertyChanged(); }
    }

    public bool HasProject => !string.IsNullOrEmpty(_projectId);

    private bool _canEditSketch;
    public bool CanEditSketch
    {
        get => _canEditSketch;
        set { _canEditSketch = value; OnPropertyChanged(); }
    }

    public FeatureNode? SelectedFeature
    {
        get => _selectedFeature;
        set
        {
            _selectedFeature = value;
            OnPropertyChanged();
            UpdateParameterPanel();
        }
    }

    public ICommand SendCommand { get; }
    public ICommand NewProjectCommand { get; }
    public ICommand OpenProjectCommand { get; }
    public ICommand SaveProjectCommand { get; }
    public ICommand SetViewCommand { get; }
    public ICommand ExportCommand { get; }
    public ICommand RebuildCommand { get; }
    public ICommand LoadExampleCommand { get; }
    public ICommand ToggleRightPanelCommand { get; }
    public ICommand UndoCommand { get; }
    public ICommand OpenLlmSettingsCommand { get; }
    public ICommand RedetectLlmCommand { get; }
    public ICommand RedoCommand { get; }
    public ICommand NewSketchCommand { get; }
    public ICommand EditSketchCommand { get; }
    public ICommand DeleteFeatureCommand { get; }
    public ICommand EditParametersCommand { get; }
    public ICommand ExportChatCommand { get; }

    /// <summary>
    /// 當 ViewModel 需要在 3D 視窗中執行 JavaScript 時觸發。
    /// </summary>
    public event Action<string>? ViewerScriptRequested;

    public MainViewModel(ICadWorker? worker = null, CadWorkerClient? workerClient = null)
    {
        _worker = worker;
        _workerClient = workerClient;

        SendCommand = new AsyncRelayCommand(SendAsync, () => !string.IsNullOrWhiteSpace(InputText));
        NewProjectCommand = new AsyncRelayCommand(NewProjectAsync, () => IsWorkerConnected);
        OpenProjectCommand = new AsyncRelayCommand(OpenProjectAsync, () => IsWorkerConnected);
        SaveProjectCommand = new RelayCommand(() => { }, () => false);  // Phase 1 恆停用
        SetViewCommand = new RelayCommand<string>(SetView);
        ExportCommand = new AsyncRelayCommand<string>(ExportAsync, fmt => HasModel && IsWorkerConnected);
        RebuildCommand = new AsyncRelayCommand(RebuildAsync, () => HasProject && IsWorkerConnected);
        LoadExampleCommand = new AsyncRelayCommand<string>(LoadExampleAsync, name => IsWorkerConnected);
        ToggleRightPanelCommand = new RelayCommand(() => IsRightPanelVisible = !IsRightPanelVisible);
        UndoCommand = new AsyncRelayCommand(UndoAsync, () => HasProject && IsWorkerConnected);
        OpenLlmSettingsCommand = new RelayCommand(OpenLlmSettings);
        RedetectLlmCommand = new AsyncRelayCommand(async () =>
        {
            LlmStatus = "LLM：偵測中…";
            await DetectLlmAsync();
        });
        RedoCommand = new AsyncRelayCommand(RedoAsync, () => HasProject && IsWorkerConnected);
        NewSketchCommand = new AsyncRelayCommand(NewSketchAsync, () => IsWorkerConnected);
        EditSketchCommand = new AsyncRelayCommand(EditSketchAsync, () => CanEditSketch && IsWorkerConnected);
        DeleteFeatureCommand = new AsyncRelayCommand(DeleteFeatureAsync, () => _selectedFeature != null && !_selectedFeature.IsDatumPlane && IsWorkerConnected);
        EditParametersCommand = new RelayCommand(EditParameters, () => _selectedFeature != null && !_selectedFeature.IsDatumPlane);
        ExportChatCommand = new AsyncRelayCommand(ExportChatAsync, () => Messages.Count > 0);

        // 歡迎訊息
        Messages.Add(ChatMessage.Assistant(
            "您好！我是 OpenCad AI 建模助手。\n" +
            "請用繁體中文描述您要設計的零件，或點擊「載入範例」開始。"));

        // 非同步初始化 Worker 連線狀態與 LLM 偵測
        _ = InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        await DetectWorkerAsync();
        await DetectLlmAsync();
    }

    /// <summary>
    /// 當 3D 視窗需要導航到新 URL 時觸發（Worker 就緒後改用同源伺服的 viewer）。
    /// </summary>
    public event Action<string>? ViewerNavigationRequested;

    /// <summary>
    /// Worker 於背景啟動完成後掛載（視窗先顯示、Worker 後就緒）。
    /// 必須在 UI 執行緒呼叫。
    /// </summary>
    public void AttachWorker(ICadWorker? worker, CadWorkerClient? workerClient, string? viewerUrl = null)
    {
        _worker = worker;
        _workerClient = workerClient;
        if (!string.IsNullOrEmpty(viewerUrl))
            ViewerNavigationRequested?.Invoke(viewerUrl);
        _ = DetectWorkerAsync();
    }

    private async Task DetectWorkerAsync()
    {
        if (_worker == null)
        {
            IsWorkerConnected = false;
            WorkerStatus = "Worker：未連線";
            return;
        }

        try
        {
            var healthy = await _worker.CheckHealthAsync();
            IsWorkerConnected = healthy;
            WorkerStatus = healthy ? "Worker：已連線" : "Worker：未連線";
        }
        catch
        {
            IsWorkerConnected = false;
            WorkerStatus = "Worker：未連線";
        }
    }

    /// <summary>
    /// 開啟 LLM 設定檔（~/.opencad/settings.json）——不存在時先建立範本。
    /// 修改後用「重新偵測 LLM」套用，不需重啟。
    /// </summary>
    private void OpenLlmSettings()
    {
        try
        {
            var path = Services.AppSettings.EnsureSettingsFile();
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = path,
                UseShellExecute = true,
            });
            Messages.Add(ChatMessage.Assistant(
                $"已開啟 LLM 設定檔：{path}\n\n" +
                "設定範例（OpenAI-compatible，如 LiteLLM Gateway）：\n" +
                "{\n  \"llm\": {\n    \"provider\": \"openai\",\n" +
                "    \"base_url\": \"http://<gateway>:4000/v1\",\n" +
                "    \"api_key\": \"sk-…\",\n    \"model\": \"coding-cloud\"\n  }\n}\n\n" +
                "儲存後點「檔案 → 重新偵測 LLM」即可套用。"));
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"開啟設定檔失敗：{ex.Message}"));
        }
    }

    private async Task DetectLlmAsync()
    {
        // 優先使用 ~/.opencad/settings.json 的設定（支援 LiteLLM Gateway 等
        // OpenAI-compatible 端點）；未設定時自動偵測本機 Ollama
        var settings = Services.AppSettings.Load().Llm;
        var provider = settings.Provider.ToLowerInvariant();

        if (provider == "none")
        {
            _llmProvider = null;
            LlmStatus = "LLM：已停用（設定檔）";
            return;
        }

        if (provider == "openai" || (provider == "auto" && !string.IsNullOrEmpty(settings.BaseUrl)))
        {
            var openai = new OpenAiCompatibleLlmProvider(settings.BaseUrl, settings.ApiKey, settings.Model);
            if (await openai.CheckConnectivityAsync())
            {
                _llmProvider = openai;
                var host = Uri.TryCreate(settings.BaseUrl, UriKind.Absolute, out var u) ? u.Host : settings.BaseUrl;
                LlmStatus = $"LLM：{settings.Model}（{host}）已連線";
                return;
            }
            _llmProvider = null;
            LlmStatus = $"LLM：設定的端點無法連線（{settings.BaseUrl}）";
            return;
        }

        try
        {
            using var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            var resp = await http.GetAsync("http://127.0.0.1:11434/api/tags");
            if (resp.IsSuccessStatusCode)
            {
                var body = await resp.Content.ReadAsStringAsync();
                var json = JsonDocument.Parse(body);
                var models = json.RootElement.GetProperty("models");
                if (models.GetArrayLength() > 0)
                {
                    var modelName = models[0].GetProperty("name").GetString() ?? "unknown";
                    _llmProvider = new OllamaLlmProvider("http://127.0.0.1:11434", modelName);
                    LlmStatus = $"LLM：{modelName} 已連線";
                    return;
                }
            }
        }
        catch { }

        _llmProvider = null;
        LlmStatus = "LLM：未偵測到 Ollama（僅手動模式）";
    }

    private async Task NewProjectAsync()
    {
        if (_worker == null) return;
        try
        {
            IsBusy = true;
            _projectId = await _worker.CreateProjectAsync("新專案");
            FeatureTree.Clear();
            ClearHistory();
            HasModel = false;
            ModelInfoText = "";
            ValidationText = "驗證報告：尚未執行";
            MassInfoText = "";
            ViewerScriptRequested?.Invoke("clearHighlight();");
            Messages.Add(ChatMessage.Assistant("已建立新專案。"));
            RefreshCanExecute();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"建立專案失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 開啟現有專案（B1）。
    /// </summary>
    /// <summary>
    /// 以專案 ID 開啟既有專案：載入 graph、重建、刷新特徵樹與 3D 顯示。
    /// </summary>
    private async Task OpenProjectByIdAsync(string projectId)
    {
        if (_worker == null) return;
        try
        {
            IsBusy = true;
            // 先確認專案存在
            await _worker.GetProjectAsync(projectId);
            _projectId = projectId;
            ClearHistory();
            RefreshCanExecute();
            Messages.Add(ChatMessage.Assistant($"已開啟專案 {projectId}，重建中…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Log.Error(ex, "開啟專案失敗 {Pid}", projectId);
            Messages.Add(ChatMessage.Error($"開啟專案失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    private async Task OpenProjectAsync()
    {
        if (_worker == null) return;
        try
        {
            IsBusy = true;
            var rawJson = await _worker.ListProjectsAsync();
            var projects = JsonSerializer.Deserialize<JsonElement>(rawJson);

            // 建立選擇清單文字
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("可用的專案：");
            if (projects.TryGetProperty("projects", out var projArr))
            {
                int idx = 1;
                foreach (var p in projArr.EnumerateArray())
                {
                    var name = p.TryGetProperty("name", out var nEl) ? nEl.GetString() ?? "?" : "?";
                    var count = p.TryGetProperty("feature_count", out var cEl) ? cEl.GetInt32() : 0;
                    var pid = p.TryGetProperty("project_id", out var idEl) ? idEl.GetString() ?? "" : "";
                    sb.AppendLine($"  {idx}. {name}（{count} 特徵）— {pid}");
                    idx++;
                }
            }
            sb.AppendLine("\n請在聊天框輸入專案 ID 以開啟。");
            Messages.Add(ChatMessage.Assistant(sb.ToString()));
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"列出專案失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    private async Task LoadExampleAsync(string? exampleName)
    {
        if (_worker == null || string.IsNullOrEmpty(exampleName)) return;
        try
        {
            IsBusy = true;

            // 讀取範例 features.json
            var exampleDir = FindExamplesDir();
            if (exampleDir == null)
            {
                Log.Error("載入範例失敗：找不到範例目錄（BaseDirectory={Dir}）", AppContext.BaseDirectory);
                Messages.Add(ChatMessage.Error("找不到範例目錄。"));
                return;
            }

            var featuresPath = Path.Combine(exampleDir, exampleName, "features.json");
            if (!File.Exists(featuresPath))
            {
                Log.Error("載入範例失敗：找不到 {Path}", featuresPath);
                Messages.Add(ChatMessage.Error($"找不到範例：{exampleName}"));
                return;
            }

            var json = await File.ReadAllTextAsync(featuresPath);
            var data = JsonDocument.Parse(json);

            // 建立新專案
            _projectId = await _worker.CreateProjectAsync(exampleName);
            FeatureTree.Clear();
            ClearHistory();

            // 逐特徵發送 create_feature 命令
            var features = data.RootElement.GetProperty("features");
            foreach (var feat in features.EnumerateArray())
            {
                var feature = JsonSerializer.Deserialize<Feature>(feat.GetRawText(),
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                if (feature == null) continue;

                var command = new CadCommand
                {
                    Action = "create_feature",
                    Feature = feature,
                };

                var result = await _worker.ApplyCommandAsync(_projectId, command);
                if (result.Status == "error")
                {
                    Log.Error("載入範例失敗：特徵 {Fid} — {Code} {Msg}", feature.FeatureId, result.ErrorCode, result.EngineMessage);
                    Messages.Add(ChatMessage.Error(
                        $"特徵 {feature.FeatureId} 建立失敗：{result.ErrorCode} — {result.EngineMessage}"));
                    return;
                }
            }

            Messages.Add(ChatMessage.Assistant($"已載入範例「{exampleName}」，共 {features.GetArrayLength()} 個特徵。"));

            // 重建
            await RebuildAsync();
            RefreshCanExecute();
        }
        catch (Exception ex)
        {
            Log.Error(ex, "載入範例失敗");
            Messages.Add(ChatMessage.Error($"載入範例失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    private async Task RebuildAsync()
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;
            ViewerScriptRequested?.Invoke("clearHighlight();");

            var rebuild = await _worker.RebuildAsync(_projectId);

            // Repair loop — if rebuild fails with structured error, ask LLM for a fix
            // Worker 失敗時回傳 status="failed"（結構化錯誤），一律以非 "success" 判定失敗
            if (rebuild.Status != "success" && _llmProvider != null)
            {
                rebuild = await TryRepairAsync(rebuild);
            }

            if (rebuild.Status != "success")
            {
                Log.Error("重建失敗：{Code} {Msg}", rebuild.ErrorCode, rebuild.EngineMessage);
                Messages.Add(ChatMessage.Error(
                    $"重建失敗：{rebuild.ErrorCode} — {rebuild.EngineMessage}"));
                return;
            }

            // 驗證
            ValidationReport? report = null;
            try
            {
                report = await _worker.ValidateAsync(_projectId);
                var icon = report.IsValid ? "✓" : "✗";
                ValidationText = $"驗證{icon}　實體 {report.SolidCount}　" +
                    $"尺寸 {report.SizeX:F0}×{report.SizeY:F0}×{report.SizeZ:F0} mm　" +
                    $"體積 {report.Volume:F0} mm³　孔數 {report.HoleCount}";
                if (report.Warnings.Count > 0)
                    ValidationText += $"\n警告：{string.Join("、", report.Warnings)}";
                if (report.Errors.Count > 0)
                    ValidationText += $"\n錯誤：{string.Join("、", report.Errors)}";
            }
            catch (Exception ex)
            {
                ValidationText = $"驗證失敗：{ex.Message}";
            }

            // 匯出 GLB 預覽——preview.glb 端點只回傳已生成的檔案，
            // 必須先實際匯出，否則 404
            await _worker.ExportAsync(_projectId, "glb");

            _rebuildCount++;
            if (_workerClient != null)
                _workerClient.RebuildCount = _rebuildCount;

            var previewUrl = _worker.GetPreviewUrl(_projectId);
            ViewerScriptRequested?.Invoke(ViewerBridge.BuildLoadScript(previewUrl));

            // 更新特徵樹
            await UpdateFeatureTreeAsync();

            HasModel = true;
            ModelInfoText = report != null
                ? $"尺寸 {report.SizeX:F0}×{report.SizeY:F0}×{report.SizeZ:F0} mm　體積 {report.Volume:F0} mm³　孔數 {report.HoleCount}"
                : "模型已重建";

            // 質量屬性
            if (rebuild.MassProperties != null)
            {
                var mp = rebuild.MassProperties;
                var bb = mp.BoundingBoxMm;
                MassInfoText = $"材質 {mp.Material}　密度 {mp.DensityGcm3:F2} g/cm³　" +
                    $"質量 {mp.MassG:F2} g　體積 {mp.VolumeMm3:F0} mm³　表面積 {mp.SurfaceAreaMm2:F0} mm²" +
                    (bb != null ? $"\n邊界框 {bb.SizeX:F1}×{bb.SizeY:F1}×{bb.SizeZ:F1} mm" : "");
            }
            else
            {
                MassInfoText = string.Empty;
            }
        }
        catch (Exception ex)
        {
            Log.Error(ex, "重建失敗");
            Messages.Add(ChatMessage.Error($"重建失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// Repair Agent 迴圈——當重建失敗時，將錯誤碼餵給 LLM 產生修正命令，最多重試 3 次。
    /// </summary>
    private async Task<RebuildResult> TryRepairAsync(RebuildResult failedRebuild)
    {
        const int maxRetries = 3;
        var rebuild = failedRebuild;

        for (int attempt = 1; attempt <= maxRetries; attempt++)
        {
            if (string.IsNullOrEmpty(rebuild.ErrorCode))
                break;

            Log.Information("Repair Agent 第 {Attempt} 次嘗試：{Code} {Msg}",
                attempt, rebuild.ErrorCode, rebuild.EngineMessage);
            Messages.Add(ChatMessage.Assistant(
                $"🔧 修正嘗試 {attempt}/{maxRetries}：{rebuild.ErrorCode} — {rebuild.EngineMessage}"));

            try
            {
                // 取得目前特徵圖給 LLM
                var graphJson = await _worker!.GetProjectAsync(_projectId!);

                // 要求 LLM 產生修正命令
                var repairCmd = await _llmProvider!.RepairCommandAsync(
                    rebuild.ErrorCode!, rebuild.EngineMessage ?? "", graphJson);

                Messages.Add(ChatMessage.Assistant(
                    $"修正方案：{repairCmd.Action}" +
                    (repairCmd.TargetFeatureId != null ? $" → {repairCmd.TargetFeatureId}" : "")));

                // 套用修正命令
                var cmdResult = await _worker.ApplyCommandAsync(_projectId!, repairCmd);
                if (cmdResult.Status == "error")
                {
                    Log.Warning("修正命令失敗：{Msg}", cmdResult.EngineMessage);
                    continue;
                }

                // 重新重建
                rebuild = await _worker.RebuildAsync(_projectId!);
                if (rebuild.Status == "success")
                {
                    Messages.Add(ChatMessage.Assistant($"✓ 修正成功（第 {attempt} 次嘗試）"));
                    return rebuild;
                }
            }
            catch (Exception ex)
            {
                Log.Warning(ex, "Repair Agent 第 {Attempt} 次嘗試失敗", attempt);
            }
        }

        // 超過最大重試次數——回傳最後一次失敗結果
        Messages.Add(ChatMessage.Error($"修正失敗——已嘗試 {maxRetries} 次"));
        return rebuild;
    }

    private async Task ExportAsync(string? format)
    {
        if (_worker == null || _projectId == null || string.IsNullOrEmpty(format)) return;
        try
        {
            IsBusy = true;
            var path = await _worker.ExportAsync(_projectId, format);
            Messages.Add(ChatMessage.Assistant($"已匯出 {format.ToUpper()}：{path}"));
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"匯出失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 匯出對話歷史為 Markdown + JSON，方便分析 LLM 意圖判斷效果。
    /// 匯出內容包含：每則訊息的種類、文字、計畫步驟、修改差異，
    /// 以及內部 LLM 對話歷史 (_chatHistory)。
    /// </summary>
    private async Task ExportChatAsync()
    {
        try
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("# OpenCad 對話匯出");
            sb.AppendLine();
            sb.AppendLine($"- 匯出時間：{DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            sb.AppendLine($"- 專案 ID：{_projectId ?? "（無）"}");
            sb.AppendLine($"- 訊息數量：{Messages.Count}");
            sb.AppendLine();

            // ── 一、UI 訊息完整紀錄 ──
            sb.AppendLine("---");
            sb.AppendLine("## 一、UI 對話紀錄");
            sb.AppendLine();
            for (int i = 0; i < Messages.Count; i++)
            {
                var msg = Messages[i];
                var kindLabel = msg.Kind switch
                {
                    MessageKind.User => "👤 使用者",
                    MessageKind.Assistant => "🤖 助手",
                    MessageKind.Error => "❌ 錯誤",
                    MessageKind.Plan => "📋 計畫",
                    MessageKind.Diff => "📝 修改差異",
                    _ => msg.Kind.ToString(),
                };
                sb.AppendLine($"### [{i + 1}] {kindLabel}");
                sb.AppendLine();
                if (!string.IsNullOrEmpty(msg.Text))
                {
                    sb.AppendLine(msg.Text);
                    sb.AppendLine();
                }

                if (msg.Plan != null)
                {
                    sb.AppendLine("**計畫步驟：**");
                    if (msg.Plan.Steps != null && msg.Plan.Steps.Count > 0)
                    {
                        for (int s = 0; s < msg.Plan.Steps.Count; s++)
                            sb.AppendLine($"{s + 1}. {msg.Plan.Steps[s].Description}");
                    }
                    else
                    {
                        sb.AppendLine("（無步驟）");
                    }
                    sb.AppendLine();
                    if (msg.Plan.MissingInfo != null && msg.Plan.MissingInfo.Count > 0)
                    {
                        sb.AppendLine("**缺少資訊：**");
                        foreach (var mi in msg.Plan.MissingInfo)
                            sb.AppendLine($"- {mi}");
                        sb.AppendLine();
                    }
                }

                if (msg.Diff != null)
                {
                    sb.AppendLine($"**目標特徵：** {msg.Diff.FeatureId}");
                    sb.AppendLine();
                    if (msg.Diff.Before != null && msg.Diff.Before.Count > 0)
                    {
                        sb.AppendLine("**修改前：**");
                        foreach (var kv in msg.Diff.Before)
                            sb.AppendLine($"- `{kv.Key}` = {kv.Value}");
                        sb.AppendLine();
                    }
                    if (msg.Diff.After != null && msg.Diff.After.Count > 0)
                    {
                        sb.AppendLine("**修改後：**");
                        foreach (var kv in msg.Diff.After)
                            sb.AppendLine($"- `{kv.Key}` = {kv.Value}");
                        sb.AppendLine();
                    }
                }
            }

            // ── 二、LLM 內部歷史 ──
            sb.AppendLine("---");
            sb.AppendLine("## 二、LLM 內部對話歷史（送給 LLM 的 context）");
            sb.AppendLine();
            sb.AppendLine("| # | Role | Content |");
            sb.AppendLine("|---|------|---------|");
            for (int i = 0; i < _chatHistory.Count; i++)
            {
                var turn = _chatHistory[i];
                var content = turn.Content.Replace("|", "\\|").Replace("\n", " ");
                if (content.Length > 200)
                    content = content[..200] + "…";
                sb.AppendLine($"| {i + 1} | {turn.Role} | {content} |");
            }
            sb.AppendLine();

            // ── 三、Feature Tree 快照 ──
            sb.AppendLine("---");
            sb.AppendLine("## 三、特徵樹快照");
            sb.AppendLine();
            void DumpTree(IEnumerable<FeatureNode> nodes, int indent)
            {
                foreach (var n in nodes)
                {
                    var prefix = new string(' ', indent * 2);
                    sb.AppendLine($"{prefix}- {n.TypeIcon} {n.DisplayName} (`{n.FeatureId}`, type={n.FeatureType})");
                    DumpTree(n.Children, indent + 1);
                }
            }
            DumpTree(FeatureTree, 0);
            sb.AppendLine();

            // ── JSON 格式（方便程式化分析） ──
            sb.AppendLine("---");
            sb.AppendLine("## 四、JSON 格式");
            sb.AppendLine();
            sb.AppendLine("```json");
            var jsonPayload = new
            {
                exported_at = DateTime.Now.ToString("o"),
                project_id = _projectId,
                messages = Messages.Select((m, i) => new
                {
                    index = i,
                    kind = m.Kind.ToString(),
                    text = m.Text,
                    plan = m.Plan != null ? new
                    {
                        summary = m.Plan.Summary,
                        steps = m.Plan.Steps?.Select(s => s.Description).ToList(),
                        missing_info = m.Plan.MissingInfo?.ToList(),
                    } : null,
                    diff = m.Diff != null ? new
                    {
                        feature_id = m.Diff.FeatureId,
                        description = m.Diff.Description,
                        before = m.Diff.Before,
                        after = m.Diff.After,
                    } : null,
                }).ToList(),
                llm_history = _chatHistory.Select(t => new { role = t.Role, content = t.Content }).ToList(),
                feature_tree = FeatureTree.Select(n => new
                {
                    id = n.FeatureId,
                    name = n.DisplayName,
                    type = n.FeatureType,
                    parameters = n.Parameters.ToDictionary(p => p.Key, p => p.Value),
                    children = n.Children,
                }).ToList(),
            };
            sb.AppendLine(System.Text.Json.JsonSerializer.Serialize(jsonPayload,
                new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
            sb.AppendLine("```");

            // 寫入檔案到桌面
            var fileName = $"opencad-chat-{DateTime.Now:yyyyMMdd-HHmmss}.md";
            var desktopPath = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
            var fullPath = Path.Combine(desktopPath, fileName);
            await File.WriteAllTextAsync(fullPath, sb.ToString());

            Messages.Add(ChatMessage.Assistant($"已匯出對話紀錄：{fullPath}"));
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"匯出對話失敗：{ex.Message}"));
        }
    }

    private async Task SendAsync()
    {
        if (string.IsNullOrWhiteSpace(InputText)) return;

        var request = InputText;
        Messages.Add(ChatMessage.User(request));
        AddHistory("user", request);
        InputText = string.Empty;

        // 輸入為專案 ID（GUID）時直接開啟該專案——配合「開啟專案」清單的操作方式
        if (Guid.TryParse(request.Trim(), out _))
        {
            await OpenProjectByIdAsync(request.Trim());
            return;
        }

        // ── 本地意圖攔截：復原/重做/刪除/視角 等操作直接執行，不送 LLM ──
        if (TryHandleLocalIntent(request))
            return;

        if (_llmProvider == null)
        {
            Messages.Add(ChatMessage.Assistant(
                "目前未偵測到 Ollama LLM 服務，無法透過 AI 建模。\n" +
                "請使用工具列的「載入範例」按鈕手動載入模型，或安裝 Ollama 並啟動模型。"));
            return;
        }

        try
        {
            IsBusy = true;

            if (_projectId == null && _worker != null)
            {
                _projectId = await _worker.CreateProjectAsync("AI 建模");
                RefreshCanExecute();
            }

            // 分支：已有特徵 → 語意修改流程（A1），否則 → 計畫建立流程
            // 注意：FeatureTree 內含常駐的基準面/原點節點，須排除才能正確判斷「是否有真實特徵」
            if (FeatureTree.Any(n => !n.IsDatumPlane) && _worker != null && _projectId != null)
            {
                await SendUpdateAsync(request);
            }
            else
            {
                var context = new DesignContext
                {
                    UserRequest = request,
                    CurrentProjectId = _projectId,
                    History = new List<ChatTurn>(_chatHistory),
                };

                var plan = await _llmProvider.CreatePlanAsync(context);
                AddHistory("assistant", $"[計畫] {plan.Summary}");

                // 顯示計畫卡片
                // 一次性卡片：套用/取消後停用按鈕，防止重複執行
                var planMsg = ChatMessage.FromPlan(plan);
                planMsg.ApplyPlanCommand = new RelayCommand(() =>
                {
                    if (!planMsg.IsActionable) return;
                    planMsg.IsActionable = false;
                    AddHistory("user", "[套用計畫]");
                    _ = ApplyPlanAsync(plan);
                });
                planMsg.CancelPlanCommand = new RelayCommand(() =>
                {
                    if (!planMsg.IsActionable) return;
                    planMsg.IsActionable = false;
                    AddHistory("user", "[取消計畫]");
                    Messages.Add(ChatMessage.Assistant("已取消建模計畫。"));
                });
                Messages.Add(planMsg);

                // 如果缺少資訊，提示使用者
                if (plan.MissingInfo.Count > 0)
                {
                    Messages.Add(ChatMessage.Assistant(
                        "缺少資訊：\n" + string.Join("\n", plan.MissingInfo)));
                }
            }
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"LLM 處理失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    // ── 本地意圖攔截 ──
    // 使用者輸入「復原」「重做」「刪除XX」「視角」等操作時，直接執行對應 UI 命令，
    // 不送 LLM——這些操作有確定性的 UI 對應，LLM 只會增加延遲和誤判。
    private bool TryHandleLocalIntent(string request)
    {
        var trimmed = request.Trim();

        // 復原 / 撤銷
        if (IntentMatcher.IsUndo(trimmed))
        {
            if (HasProject && IsWorkerConnected)
            {
                _ = UndoAsync();
            }
            else
            {
                Messages.Add(ChatMessage.Assistant("目前沒有開啟的專案，無法復原。"));
            }
            return true;
        }

        // 重做 / 取消復原
        if (IntentMatcher.IsRedo(trimmed))
        {
            if (HasProject && IsWorkerConnected)
            {
                _ = RedoAsync();
            }
            else
            {
                Messages.Add(ChatMessage.Assistant("目前沒有開啟的專案，無法重做。"));
            }
            return true;
        }

        // 視角操作
        var viewKeyword = IntentMatcher.MatchView(trimmed);
        if (viewKeyword != null)
        {
            SetView(viewKeyword);
            return true;
        }

        // 縮放至適合
        if (IntentMatcher.IsZoomToFit(trimmed))
        {
            ViewerScriptRequested?.Invoke("zoomFit()");
            Messages.Add(ChatMessage.Assistant("已縮放至適合。"));
            return true;
        }

        // 基準面顯示/隱藏
        if (IntentMatcher.IsDatumPlaneToggle(trimmed))
        {
            ViewerScriptRequested?.Invoke("onToggleDatumPlanes()");
            Messages.Add(ChatMessage.Assistant("已切換基準面顯示。"));
            return true;
        }

        // 重建
        if (IntentMatcher.IsRebuild(trimmed))
        {
            if (HasProject && IsWorkerConnected)
            {
                _ = RebuildAsync();
            }
            return true;
        }

        return false;
    }

    private async Task ApplyPlanAsync(DesignPlan plan)
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;

            // 逐步驟確定性地建立特徵——LLM 只產生計畫，特徵由計畫直接映射，
            // 並自動串接 input（pad/revolve 接最近的 sketch，其餘接前一個特徵）
            string? lastSketchId = null;
            string? lastFeatureId = null;
            var index = 0;

            foreach (var step in plan.Steps)
            {
                index++;
                // 計畫的 feature_type 是 snake_case（如 linear_pattern）
                var enumName = step.FeatureType.Replace("_", "");
                if (!Enum.TryParse<FeatureType>(enumName, true, out var featType))
                {
                    Messages.Add(ChatMessage.Error($"未知特徵類型：{step.FeatureType}"));
                    continue;
                }

                // LLM 可能輸出 {"type":"XY"} 或 {"base":"XY"}——統一正規化為 base 格式
                var plane = NormalizePlane(step.Plane);

                // pad/revolve 沒有前置草圖時：若步驟自帶 sketch_entities，
                // 確定性拆出草圖特徵；否則計畫不完整，中止並回報（避免建出必然重建失敗的特徵）
                if (featType is FeatureType.Pad or FeatureType.Revolve && lastSketchId == null)
                {
                    if (step.SketchEntities is { Count: > 0 })
                    {
                        var autoSketchId = $"sketch_{index}_auto";
                        var sketchResult = await _worker.ApplyCommandAsync(_projectId, new CadCommand
                        {
                            Action = "create_feature",
                            Feature = new Feature
                            {
                                FeatureId = autoSketchId,
                                Type = FeatureType.Sketch,
                                Name = $"草圖（自步驟 {index} 拆出）",
                                Parameters = new(),
                                SketchEntities = step.SketchEntities,
                                Plane = plane,
                            },
                        });
                        if (sketchResult.Status == "error")
                        {
                            Messages.Add(ChatMessage.Error(
                                $"特徵 {autoSketchId} 建立失敗：{sketchResult.ErrorCode} — {sketchResult.EngineMessage}"));
                            return;
                        }
                        lastSketchId = autoSketchId;
                    }
                    else
                    {
                        Messages.Add(ChatMessage.Error(
                            $"計畫第 {index} 步（{step.FeatureType}）缺少輸入草圖，計畫不完整——請重新描述需求以產生含草圖步驟的計畫。"));
                        return;
                    }
                }

                var featureId = $"{step.FeatureType}_{index}";
                var input = featType switch
                {
                    FeatureType.Sketch => null,
                    FeatureType.Pad or FeatureType.Revolve => lastSketchId,
                    _ => lastFeatureId,
                };

                // pocket 是雙輸入特徵：input=基礎實體、references=挖孔輪廓草圖
                //（_build_pocket 從 references 找 sketch——放 input 進去會靜默不挖）
                var references = featType == FeatureType.Pocket && lastSketchId != null
                    ? new List<string> { lastSketchId }
                    : input != null ? new List<string> { input } : new();

                var command = new CadCommand
                {
                    Action = "create_feature",
                    Feature = new Feature
                    {
                        FeatureId = featureId,
                        Type = featType,
                        Name = step.Description,
                        Input = input,
                        References = references,
                        Parameters = step.Parameters,
                        // 只有 sketch 特徵保留 sketch_entities；pad/revolve 的實體已拆至草圖
                        SketchEntities = featType == FeatureType.Sketch ? step.SketchEntities ?? new() : new(),
                        StandardParts = step.StandardParts ?? new(),
                        Plane = plane,
                    },
                };

                var result = await _worker.ApplyCommandAsync(_projectId, command);
                if (result.Status == "error")
                {
                    Messages.Add(ChatMessage.Error(
                        $"特徵 {featureId} 建立失敗：{result.ErrorCode} — {result.EngineMessage}"));
                    return;
                }

                if (featType == FeatureType.Sketch)
                    lastSketchId = featureId;
                else
                    lastFeatureId = featureId;
            }

            Messages.Add(ChatMessage.Assistant("計畫已套用，開始重建…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"套用計畫失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 將 LLM 計畫的 plane 正規化為引擎契約格式 {"base": "XY|XZ|YZ", "offset": n}。
    /// 容忍 LLM 以 "type" 為鍵或小寫平面名。
    /// </summary>
    private static Dictionary<string, object> NormalizePlane(Dictionary<string, object>? plane)
    {
        var result = new Dictionary<string, object> { ["base"] = "XY", ["offset"] = 0 };
        if (plane == null) return result;

        object? baseVal = null;
        if (plane.TryGetValue("base", out var b)) baseVal = b;
        else if (plane.TryGetValue("type", out var t)) baseVal = t;

        var baseStr = baseVal?.ToString()?.Trim().ToUpperInvariant();
        if (baseStr is "XY" or "XZ" or "YZ")
            result["base"] = baseStr;

        if (plane.TryGetValue("offset", out var offset) && offset != null)
            result["offset"] = offset;

        return result;
    }

    /// <summary>
    /// 語意修改流程（A1）：取得特徵圖 → LLM 產生命令 → 顯示差異卡片（A2）→ 使用者確認後套用。
    /// </summary>
    private async Task SendUpdateAsync(string userRequest)
    {
        if (_worker == null || _projectId == null || _llmProvider == null) return;

        try
        {
            // 取得目前特徵圖 JSON
            var featureGraphJson = await _worker.GetProjectAsync(_projectId);

            // LLM 產生命令（update/create/delete/set_material/rebuild）
            var command = await _llmProvider.CreateUpdateCommandAsync(userRequest, featureGraphJson, new List<ChatTurn>(_chatHistory));

            var isCreate = command.Action == "create_feature" && command.Feature != null;
            var isDelete = command.Action == "delete_feature";
            var isSetMaterial = command.Action == "set_material";
            var isRebuild = command.Action == "rebuild";

            // rebuild：LLM 對不支援功能的回應——直接重建，顯示 reasoning
            if (isRebuild)
            {
                Messages.Add(ChatMessage.Assistant(command.Reasoning ?? "已重建模型。"));
                AddHistory("assistant", command.Reasoning ?? "已重建模型。");
                await RebuildAsync();
                return;
            }

            // set_material：直接套用，不需 diff 卡片
            if (isSetMaterial)
            {
                var matName = command.Parameters?.GetValueOrDefault("material")?.ToString() ?? "";
                AddHistory("assistant", $"[材質] {matName}: {command.Reasoning}");
                Messages.Add(ChatMessage.Assistant($"已變更材質為 {matName}，開始重建…"));
                await ApplyDiffAsync(command);
                return;
            }

            // delete_feature：需要 target_feature_id
            if (isDelete && string.IsNullOrEmpty(command.TargetFeatureId))
            {
                Messages.Add(ChatMessage.Assistant("無法判斷要刪除的特徵，請更具體描述。"));
                AddHistory("assistant", "無法判斷要刪除的特徵。");
                return;
            }

            // update_feature：需要 target_feature_id
            if (!isCreate && !isDelete && string.IsNullOrEmpty(command.TargetFeatureId))
            {
                Messages.Add(ChatMessage.Assistant("無法判斷要修改的特徵，請更具體描述。"));
                AddHistory("assistant", "無法判斷要修改的特徵。");
                return;
            }

            // ── 建構差異卡片 ──
            ModificationDiff diff;
            string historyTarget;

            if (isCreate)
            {
                var feat = command.Feature!;
                // 防呆：LLM 沒給 ID 或 ID 撞名時自動改名
                if (string.IsNullOrEmpty(feat.FeatureId))
                    feat.FeatureId = $"{feat.Type}_{DateTime.UtcNow.Ticks % 10000}";
                while (ExtractFeatureParams(featureGraphJson, feat.FeatureId).Count > 0)
                    feat.FeatureId += "_n";
                historyTarget = feat.FeatureId;
                AddHistory("assistant", $"[新增] {feat.FeatureId} ({feat.Type}): {command.Reasoning}");

                // 新增特徵的差異卡片：Before 空、After 為新特徵的參數
                var afterCreate = new Dictionary<string, object>
                {
                    ["type"] = feat.Type.ToString().ToLowerInvariant(),
                    ["input"] = feat.Input ?? "",
                };
                if (feat.References != null && feat.References.Count > 0)
                    afterCreate["references"] = string.Join(", ", feat.References);
                if (feat.SketchEntities != null && feat.SketchEntities.Count > 0)
                    afterCreate["sketch_entities"] = $"{feat.SketchEntities.Count} 個草圖實體";
                foreach (var kvp in feat.Parameters)
                    afterCreate[kvp.Key] = kvp.Value;

                diff = new ModificationDiff
                {
                    FeatureId = feat.FeatureId,
                    Before = new(),
                    After = afterCreate,
                    Description = command.Reasoning,
                };
            }
            else if (isDelete)
            {
                historyTarget = command.TargetFeatureId!;
                AddHistory("assistant", $"[刪除] {command.TargetFeatureId}: {command.Reasoning}");

                var delBeforeParams = ExtractFeatureParams(featureGraphJson, command.TargetFeatureId!);
                diff = new ModificationDiff
                {
                    FeatureId = command.TargetFeatureId!,
                    Before = delBeforeParams,
                    After = new() { ["_deleted"] = true },
                    Description = command.Reasoning ?? "刪除特徵",
                };
            }
            else
            {
                // update_feature
                historyTarget = command.TargetFeatureId!;
                AddHistory("assistant", $"[修改] {command.TargetFeatureId} ({command.Action}): {command.Reasoning}");

                // 取得修改前的特徵資料（用於 diff）
                var beforeParams = ExtractFeatureParams(featureGraphJson, command.TargetFeatureId!);

                // 建構修改後的參數預覽（parameters 與 standard_parts 都要反映）
                var afterParams = new Dictionary<string, object>(beforeParams);
                if (command.Parameters != null)
                {
                    foreach (var kvp in command.Parameters)
                        afterParams[kvp.Key] = kvp.Value;
                }
                if (command.StandardParts != null && command.StandardParts.Count > 0)
                {
                    afterParams["standard_parts"] = JsonSerializer.Serialize(command.StandardParts);
                }

                diff = new ModificationDiff
                {
                    FeatureId = command.TargetFeatureId!,
                    Before = beforeParams,
                    After = afterParams,
                    Description = command.Reasoning,
                };
            }

            // 顯示差異卡片（A2）
            // 一次性卡片：套用/取消後停用按鈕，防止重複執行
            var diffMsg = ChatMessage.FromDiff(diff);
            diffMsg.ApplyDiffCommand = new RelayCommand(() =>
            {
                if (!diffMsg.IsActionable) return;
                diffMsg.IsActionable = false;
                AddHistory("user", $"[套用修改] {historyTarget}");
                _ = ApplyDiffAsync(command);
            });
            diffMsg.CancelDiffCommand = new RelayCommand(() =>
            {
                if (!diffMsg.IsActionable) return;
                diffMsg.IsActionable = false;
                AddHistory("user", "[取消修改]");
                Messages.Add(ChatMessage.Assistant("已取消修改。"));
            });
            Messages.Add(diffMsg);
        }
        catch (Exception ex)
        {
            Log.Error(ex, "語意修改流程失敗");
            Messages.Add(ChatMessage.Error($"修改流程失敗：{ex.Message}"));
        }
    }

    /// <summary>
    /// 套用差異命令（A2 確認後）。
    /// </summary>
    private async Task ApplyDiffAsync(CadCommand command)
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error(
                    $"修改失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            Messages.Add(ChatMessage.Assistant("修改已套用，開始重建…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"套用修改失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 復原（A4）。
    /// </summary>
    private async Task UndoAsync()
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;
            var success = await _worker.UndoAsync(_projectId);
            if (success)
            {
                Messages.Add(ChatMessage.Assistant("已復原。"));
                await RebuildAsync();
            }
            else
            {
                Messages.Add(ChatMessage.Assistant("已是最早版本，無法復原。"));
            }
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"復原失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 重做（A4）。
    /// </summary>
    private async Task RedoAsync()
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;
            var success = await _worker.RedoAsync(_projectId);
            if (success)
            {
                Messages.Add(ChatMessage.Assistant("已重做。"));
                await RebuildAsync();
            }
            else
            {
                Messages.Add(ChatMessage.Assistant("已是最新版本，無法重做。"));
            }
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"重做失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 新建草圖並進入編輯模式（§2.2 入口 2）。
    /// </summary>
    private async Task NewSketchAsync()
    {
        if (_worker == null) return;
        try
        {
            IsBusy = true;

            if (_projectId == null)
            {
                _projectId = await _worker.CreateProjectAsync("AI 建模");
                RefreshCanExecute();
            }

            // 決定草圖基準面——若選取的是基準面節點，使用該面；否則預設 XY
            string planeBase = "XY";
            if (_selectedFeature != null && _selectedFeature.IsDatumPlane && _selectedFeature.PlaneBase != null)
                planeBase = _selectedFeature.PlaneBase;

            // 產生 sketch_N ID：取現存草圖編號最大值 +1，避免刪除後重號
            int sketchNum = 1;
            foreach (var node in FeatureTree)
            {
                if (node.IsDatumPlane || node.FeatureType != "sketch") continue;
                var m = System.Text.RegularExpressions.Regex.Match(node.FeatureId, @"^sketch_(\d+)$");
                if (m.Success && int.TryParse(m.Groups[1].Value, out var n) && n >= sketchNum)
                    sketchNum = n + 1;
            }
            var sketchId = $"sketch_{sketchNum}";
            var command = new CadCommand
            {
                Action = "create_feature",
                Feature = new Feature
                {
                    FeatureId = sketchId,
                    Type = FeatureType.Sketch,
                    Name = $"草圖 {sketchNum}",
                    Parameters = new(),
                    SketchEntities = new(),
                    Plane = new() { ["base"] = planeBase, ["offset"] = 0 },
                },
            };

            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"建立草圖失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            await UpdateFeatureTreeAsync();
            Messages.Add(ChatMessage.Assistant($"已建立空草圖「{sketchId}」（基準面 {planeBase}），進入編輯模式…"));

            // 進入草圖編輯模式；viewer.html 的 enterSketchMode 接收 { "base": "XY", "offset": 0 }
            var planeJson = JsonSerializer.Serialize(command.Feature.Plane);
            EnterSketchEditor(sketchId, "[]", planeJson);
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"建立草圖失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 編輯既有草圖（§2.2 入口 1）。
    /// </summary>
    private async Task EditSketchAsync()
    {
        if (_worker == null || _projectId == null || _selectedFeature == null) return;
        try
        {
            IsBusy = true;

            // 從 Worker 取得特徵圖，取出 sketch_entities 和 plane
            var rawJson = await _worker.GetProjectAsync(_projectId);
            var projectInfo = JsonSerializer.Deserialize<JsonElement>(rawJson);
            string entitiesJson = "[]";
            string planeJson = "{\"base\":\"XY\",\"offset\":0}";

            if (projectInfo.TryGetProperty("features", out var featuresEl))
            {
                JsonElement? targetFeat = null;
                if (featuresEl.ValueKind == JsonValueKind.Array)
                {
                    foreach (var f in featuresEl.EnumerateArray())
                    {
                        if (f.TryGetProperty("feature_id", out var idEl) &&
                            idEl.GetString() == _selectedFeature.FeatureId)
                        {
                            targetFeat = f;
                            break;
                        }
                    }
                }
                else if (featuresEl.ValueKind == JsonValueKind.Object)
                {
                    if (featuresEl.TryGetProperty(_selectedFeature.FeatureId, out var f))
                        targetFeat = f;
                }

                if (targetFeat.HasValue)
                {
                    if (targetFeat.Value.TryGetProperty("sketch_entities", out var seEl))
                        entitiesJson = seEl.GetRawText();
                    if (targetFeat.Value.TryGetProperty("plane", out var planeEl))
                        planeJson = planeEl.GetRawText();
                }
            }

            EnterSketchEditor(_selectedFeature.FeatureId, entitiesJson, planeJson);
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"進入草圖編輯失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 送出 enterSketchMode JS 進入草圖編輯器。
    /// </summary>
    private void EnterSketchEditor(string featureId, string entitiesJson, string? planeJson = null)
    {
        ViewerScriptRequested?.Invoke(ViewerBridge.BuildEnterSketchScript(featureId, entitiesJson, planeJson));
    }

    /// <summary>
    /// 收到 viewer 的 sketch_committed 訊息後提交草圖變更（§2.4）。
    /// </summary>
    public async Task CommitSketchAsync(string featureId, string entitiesJson)
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;

            var entities = JsonSerializer.Deserialize<List<Dictionary<string, object>>>(entitiesJson)
                ?? new List<Dictionary<string, object>>();

            var command = new CadCommand
            {
                Action = "update_feature",
                TargetFeatureId = featureId,
                SketchEntities = entities,
            };

            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"草圖更新失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            Messages.Add(ChatMessage.Assistant("草圖已更新，開始重建…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"草圖提交失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 取消草圖編輯——只需退出 viewer 草圖模式。
    /// </summary>
    public void CancelSketch()
    {
        ViewerScriptRequested?.Invoke(ViewerBridge.BuildExitSketchScript());
    }

    /// <summary>
    /// 刪除目前選取的特徵。
    /// </summary>
    private async Task DeleteFeatureAsync()
    {
        if (_selectedFeature == null || _selectedFeature.IsDatumPlane || _worker == null || _projectId == null) return;

        var featureId = _selectedFeature.FeatureId;
        IsBusy = true;
        try
        {
            var command = new CadCommand
            {
                Action = "delete_feature",
                TargetFeatureId = featureId,
            };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "has_dependencies")
            {
                Messages.Add(ChatMessage.Error(
                    $"特徵「{featureId}」被其他特徵依賴，無法直接刪除。請先刪除依賴它的特徵。"));
                return;
            }
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"刪除失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            Messages.Add(ChatMessage.Assistant($"已刪除特徵「{featureId}」，重建中…"));
            _selectedFeature = null;
            await UpdateFeatureTreeAsync();
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"刪除特徵失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 編輯參數——捲動參數面板到頂部並聚焦（供右鍵選單使用）。
    /// </summary>
    private void EditParameters()
    {
        if (_selectedFeature == null || _selectedFeature.IsDatumPlane) return;
        // 參數面板已在左下方顯示，選取特徵時自動更新；
        // 此命令確保右鍵「編輯參數」時面板可見。
        OnPropertyChanged(nameof(SelectedFeatureParameters));
    }

    /// <summary>
    /// 從特徵圖 JSON 中取出指定特徵的參數（用於 diff before）。
    /// </summary>
    private static Dictionary<string, object> ExtractFeatureParams(string featureGraphJson, string featureId)
    {
        var result = new Dictionary<string, object>();
        try
        {
            var doc = JsonDocument.Parse(featureGraphJson);
            if (doc.RootElement.TryGetProperty("features", out var featuresEl))
            {
                // 新版 graph 格式 {schema_version, features:[...]}——先解開包裝
                // （與 UpdateFeatureTreeAsync 相同的相容處理）
                if (featuresEl.ValueKind == JsonValueKind.Object &&
                    featuresEl.TryGetProperty("features", out var innerEl))
                {
                    featuresEl = innerEl;
                }

                JsonElement? targetFeat = null;
                if (featuresEl.ValueKind == JsonValueKind.Array)
                {
                    foreach (var f in featuresEl.EnumerateArray())
                    {
                        if (f.TryGetProperty("feature_id", out var idEl) && idEl.GetString() == featureId)
                        {
                            targetFeat = f;
                            break;
                        }
                    }
                }
                else if (featuresEl.ValueKind == JsonValueKind.Object)
                {
                    if (featuresEl.TryGetProperty(featureId, out var f))
                        targetFeat = f;
                }

                if (targetFeat.HasValue && targetFeat.Value.TryGetProperty("parameters", out var paramsEl))
                {
                    foreach (var p in paramsEl.EnumerateObject())
                        result[p.Name] = FormatJsonValue(p.Value);
                }
                // standard_parts 也納入 diff（M3→M5 這類修改改的是標準件）
                if (targetFeat.HasValue && targetFeat.Value.TryGetProperty("standard_parts", out var spEl) &&
                    spEl.ValueKind == JsonValueKind.Object && spEl.EnumerateObject().Any())
                {
                    result["standard_parts"] = FormatJsonValue(spEl);
                }
            }
        }
        catch { }
        return result;
    }

    private async Task UpdateFeatureTreeAsync()
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            var rawJson = await _worker.GetProjectAsync(_projectId);
            var projectInfo = JsonSerializer.Deserialize<JsonElement>(rawJson);
            FeatureTree.Clear();

            // 基準面節點（SolidWorks 慣例——常駐特徵樹頂端，非特徵）
            FeatureTree.Add(new FeatureNode
            {
                FeatureId = "__plane_xy",
                DisplayName = "上基準面 (XY)",
                FeatureType = "datum_plane",
                IsDatumPlane = true,
                PlaneBase = "XY",
            });
            FeatureTree.Add(new FeatureNode
            {
                FeatureId = "__plane_xz",
                DisplayName = "前基準面 (XZ)",
                FeatureType = "datum_plane",
                IsDatumPlane = true,
                PlaneBase = "XZ",
            });
            FeatureTree.Add(new FeatureNode
            {
                FeatureId = "__plane_yz",
                DisplayName = "右基準面 (YZ)",
                FeatureType = "datum_plane",
                IsDatumPlane = true,
                PlaneBase = "YZ",
            });
            FeatureTree.Add(new FeatureNode
            {
                FeatureId = "__origin",
                DisplayName = "原點",
                FeatureType = "origin",
                IsDatumPlane = true,
            });

            if (projectInfo.TryGetProperty("features", out var featuresEl))
            {
                // 新版 graph 格式為 {schema_version, features: [...]}——先解開包裝
                if (featuresEl.ValueKind == JsonValueKind.Object &&
                    featuresEl.TryGetProperty("features", out var innerEl))
                {
                    featuresEl = innerEl;
                }

                // features 可能是 dict 或 array 格式
                if (featuresEl.ValueKind == JsonValueKind.Array)
                {
                    foreach (var feat in featuresEl.EnumerateArray())
                    {
                        var node = ParseFeatureNode(feat);
                        if (node != null) FeatureTree.Add(node);
                    }
                }
                else if (featuresEl.ValueKind == JsonValueKind.Object)
                {
                    foreach (var prop in featuresEl.EnumerateObject())
                    {
                        var node = ParseFeatureNode(prop.Value);
                        if (node != null) FeatureTree.Add(node);
                    }
                }
            }
        }
        catch { }
    }

    private static FeatureNode? ParseFeatureNode(JsonElement featEl)
    {
        try
        {
            var fid = featEl.TryGetProperty("feature_id", out var idEl) ? idEl.GetString() ?? "" : "";
            var name = featEl.TryGetProperty("name", out var nEl) ? nEl.GetString() ?? fid : fid;
            var type = featEl.TryGetProperty("type", out var tEl) ? tEl.GetString() ?? "" : "";

            // 若草圖有指定基準面，在顯示名稱後加 @XY/@XZ/@YZ
            string planeSuffix = "";
            if (type == "sketch" && featEl.TryGetProperty("plane", out var planeEl))
            {
                if (planeEl.TryGetProperty("base", out var baseEl))
                {
                    var baseStr = baseEl.GetString();
                    if (!string.IsNullOrEmpty(baseStr))
                        planeSuffix = $"@{baseStr}";
                }
            }

            var node = new FeatureNode
            {
                FeatureId = fid,
                DisplayName = $"{name} ({type}{planeSuffix})",
                FeatureType = type,
            };

            // 抽出實際參數供參數面板顯示。
            // 只有純量數值參數可編輯；feature_id/type/input/standard_parts/陣列唯讀
            static ParameterItem ReadOnlyItem(string key, string value) =>
                new() { Key = key, Value = value, OriginalValue = value, IsEditable = false };

            node.Parameters.Add(ReadOnlyItem("feature_id", fid));
            node.Parameters.Add(ReadOnlyItem("type", type));
            if (featEl.TryGetProperty("input", out var inEl) && inEl.ValueKind == JsonValueKind.String)
                node.Parameters.Add(ReadOnlyItem("input", inEl.GetString() ?? ""));
            if (featEl.TryGetProperty("parameters", out var paramsEl) && paramsEl.ValueKind == JsonValueKind.Object)
            {
                foreach (var p in paramsEl.EnumerateObject())
                {
                    var text = FormatJsonValue(p.Value);
                    var editable = double.TryParse(text, out _);
                    node.Parameters.Add(new ParameterItem
                    {
                        Key = p.Name,
                        Value = text,
                        OriginalValue = text,
                        IsEditable = editable,
                    });
                }
            }
            if (featEl.TryGetProperty("standard_parts", out var spEl) &&
                spEl.ValueKind == JsonValueKind.Object && spEl.EnumerateObject().Any())
                node.Parameters.Add(ReadOnlyItem("standard_parts", FormatJsonValue(spEl)));
            if (featEl.TryGetProperty("plane", out var planeEl2) && planeEl2.ValueKind == JsonValueKind.Object)
                node.Parameters.Add(ReadOnlyItem("plane", FormatJsonValue(planeEl2)));

            return node;
        }
        catch { return null; }
    }

    private static string FormatJsonValue(JsonElement el) => el.ValueKind switch
    {
        JsonValueKind.String => el.GetString() ?? "",
        JsonValueKind.Number => el.GetRawText(),
        JsonValueKind.True or JsonValueKind.False => el.GetRawText(),
        _ => el.GetRawText(),
    };

    private void UpdateParameterPanel()
    {
        SelectedFeatureParameters.Clear();
        if (_selectedFeature == null || _selectedFeature.IsDatumPlane)
        {
            CanEditSketch = false;
            ((AsyncRelayCommand)DeleteFeatureCommand).RaiseCanExecuteChanged();
            ((RelayCommand)EditParametersCommand).RaiseCanExecuteChanged();

            if (_selectedFeature != null && _selectedFeature.IsDatumPlane)
            {
                ViewerScriptRequested?.Invoke($"highlightDatumPlane('{_selectedFeature.FeatureId}');");
            }
            else
            {
                ViewerScriptRequested?.Invoke("highlightDatumPlane(null);");
            }
            return;
        }

        var featureId = _selectedFeature.FeatureId;
        // 清除基準面高亮
        ViewerScriptRequested?.Invoke("highlightDatumPlane(null);");
        
        foreach (var p in _selectedFeature.Parameters)
        {
            if (p.IsEditable)
                p.ApplyCommand = new AsyncRelayCommand(() => ApplyParameterEditAsync(featureId, p));
            SelectedFeatureParameters.Add(p);
        }

        // 草圖類型特徵才顯示「編輯草圖」按鈕
        CanEditSketch = _selectedFeature.FeatureType.Equals("sketch", StringComparison.OrdinalIgnoreCase);

        // 更新右鍵選單命令可用狀態
        ((AsyncRelayCommand)DeleteFeatureCommand).RaiseCanExecuteChanged();
        ((RelayCommand)EditParametersCommand).RaiseCanExecuteChanged();

        // 高亮對應 mesh
        ViewerScriptRequested?.Invoke($"highlightByName('{featureId}');");
    }

    /// <summary>
    /// 套用參數面板的單一參數編輯——與 LLM 走完全相同的 update_feature 命令路徑。
    /// </summary>
    private async Task ApplyParameterEditAsync(string featureId, ParameterItem item)
    {
        if (_worker == null || _projectId == null) return;

        // 數值驗證：非數字或長度類負值在 UI 端先擋
        if (!double.TryParse(item.Value, out var number))
        {
            Messages.Add(ChatMessage.Error($"參數 {item.Key} 必須是數值：「{item.Value}」無效。"));
            return;
        }
        if (number <= 0 && item.Key is "length" or "width" or "height" or "depth" or "diameter" or "radius" or "thickness")
        {
            Messages.Add(ChatMessage.Error($"參數 {item.Key} 必須大於 0。"));
            return;
        }

        try
        {
            IsBusy = true;
            var command = new CadCommand
            {
                Action = "update_feature",
                TargetFeatureId = featureId,
                Parameters = new Dictionary<string, object> { [item.Key] = number },
            };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error(
                    $"參數更新失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            item.OriginalValue = item.Value;
            Messages.Add(ChatMessage.Assistant($"已將 {featureId}.{item.Key} 改為 {number}，重建中…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Log.Error(ex, "參數編輯套用失敗");
            Messages.Add(ChatMessage.Error($"參數更新失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    private void SetView(string? view)
    {
        if (view is { } v)
        {
            ViewerScriptRequested?.Invoke(ViewerBridge.BuildSetViewScript(v));
        }
    }

    private string? FindExamplesDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 10 && dir != null; i++)
        {
            var candidate = Path.Combine(dir.FullName, "examples");
            if (Directory.Exists(candidate))
                return candidate;
            dir = dir.Parent;
        }
        return null;
    }

    private void AddHistory(string role, string content)
    {
        if (string.IsNullOrWhiteSpace(content)) return;
        
        // 單輪截 2000 字元
        var truncated = content.Length > 2000 ? content[..2000] : content;
        _chatHistory.Add(new ChatTurn { Role = role, Content = truncated });
        
        // 保留最近 10 輪 (10 輪對話 = 20 個 turn)
        while (_chatHistory.Count > 20)
            _chatHistory.RemoveAt(0);
            
        // 總量上限 8000 字元 (累計 turn 長度)
        while (_chatHistory.Count > 0 && _chatHistory.Sum(t => t.Content.Length) > 8000)
            _chatHistory.RemoveAt(0);
    }

    private void ClearHistory()
    {
        _chatHistory.Clear();
    }

    public void SelectDatumPlane(string name)
    {
        var node = FeatureTree.FirstOrDefault(n => n.FeatureId == name);
        if (node != null)
        {
            SelectedFeature = node;
        }
    }

    private void RefreshCanExecute()
    {
        ((AsyncRelayCommand)SendCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)NewProjectCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RebuildCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand<string>)ExportCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand<string>)LoadExampleCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)UndoCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RedoCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)NewSketchCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)EditSketchCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)DeleteFeatureCommand).RaiseCanExecuteChanged();
        ((RelayCommand)EditParametersCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)ExportChatCommand).RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(HasProject));
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    protected virtual void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}