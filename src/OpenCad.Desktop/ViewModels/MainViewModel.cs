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
    private OllamaLlmProvider? _llmProvider;

    private string _inputText = string.Empty;
    private string _llmStatus = "LLM：偵測中…";
    private string _modelInfoText = string.Empty;
    private string _validationText = "驗證報告：尚未執行";
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
        OpenProjectCommand = new RelayCommand(() => { }, () => false);  // Phase 1 恆停用
        SaveProjectCommand = new RelayCommand(() => { }, () => false);  // Phase 1 恆停用
        SetViewCommand = new RelayCommand<string>(SetView);
        ExportCommand = new AsyncRelayCommand<string>(ExportAsync, fmt => HasModel && IsWorkerConnected);
        RebuildCommand = new AsyncRelayCommand(RebuildAsync, () => HasProject && IsWorkerConnected);
        LoadExampleCommand = new AsyncRelayCommand<string>(LoadExampleAsync, name => IsWorkerConnected);
        ToggleRightPanelCommand = new RelayCommand(() => IsRightPanelVisible = !IsRightPanelVisible);

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

    private async Task DetectLlmAsync()
    {
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
            HasModel = false;
            ModelInfoText = "";
            ValidationText = "驗證報告：尚未執行";
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
            if (rebuild.Status == "error")
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
        }
        catch (Exception ex)
        {
            Log.Error(ex, "重建失敗");
            Messages.Add(ChatMessage.Error($"重建失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
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

    private async Task SendAsync()
    {
        if (string.IsNullOrWhiteSpace(InputText)) return;

        var request = InputText;
        Messages.Add(ChatMessage.User(request));
        InputText = string.Empty;

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

            var context = new DesignContext
            {
                UserRequest = request,
                CurrentProjectId = _projectId,
            };

            var plan = await _llmProvider.CreatePlanAsync(context);

            // 顯示計畫卡片
            Messages.Add(ChatMessage.FromPlan(plan,
                new RelayCommand(() => _ = ApplyPlanAsync(plan)),
                new RelayCommand(() => { })));

            // 如果缺少資訊，提示使用者
            if (plan.MissingInfo.Count > 0)
            {
                Messages.Add(ChatMessage.Assistant(
                    "缺少資訊：\n" + string.Join("\n", plan.MissingInfo)));
            }
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"LLM 處理失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
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

                var featureId = $"{step.FeatureType}_{index}";
                var input = featType switch
                {
                    FeatureType.Sketch => null,
                    FeatureType.Pad or FeatureType.Revolve => lastSketchId,
                    _ => lastFeatureId,
                };

                var command = new CadCommand
                {
                    Action = "create_feature",
                    Feature = new Feature
                    {
                        FeatureId = featureId,
                        Type = featType,
                        Name = step.Description,
                        Input = input,
                        References = input != null ? new List<string> { input } : new(),
                        Parameters = step.Parameters,
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

    private async Task UpdateFeatureTreeAsync()
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            var rawJson = await _worker.GetProjectAsync(_projectId);
            var projectInfo = JsonSerializer.Deserialize<JsonElement>(rawJson);
            FeatureTree.Clear();

            if (projectInfo.TryGetProperty("features", out var featuresEl))
            {
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

            var node = new FeatureNode
            {
                FeatureId = fid,
                DisplayName = $"{name} ({type})",
                FeatureType = type,
            };

            // 抽出實際參數供參數面板顯示
            node.Parameters.Add(new ParameterItem { Key = "feature_id", Value = fid });
            node.Parameters.Add(new ParameterItem { Key = "type", Value = type });
            if (featEl.TryGetProperty("input", out var inEl) && inEl.ValueKind == JsonValueKind.String)
                node.Parameters.Add(new ParameterItem { Key = "input", Value = inEl.GetString() ?? "" });
            if (featEl.TryGetProperty("parameters", out var paramsEl) && paramsEl.ValueKind == JsonValueKind.Object)
            {
                foreach (var p in paramsEl.EnumerateObject())
                    node.Parameters.Add(new ParameterItem { Key = p.Name, Value = FormatJsonValue(p.Value) });
            }
            if (featEl.TryGetProperty("standard_parts", out var spEl) &&
                spEl.ValueKind == JsonValueKind.Object && spEl.EnumerateObject().Any())
                node.Parameters.Add(new ParameterItem { Key = "standard_parts", Value = FormatJsonValue(spEl) });

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
        if (_selectedFeature == null) return;

        foreach (var p in _selectedFeature.Parameters)
            SelectedFeatureParameters.Add(p);

        // 高亮對應 mesh
        ViewerScriptRequested?.Invoke($"highlightByName('{_selectedFeature.FeatureId}');");
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

    private void RefreshCanExecute()
    {
        ((AsyncRelayCommand)SendCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)NewProjectCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RebuildCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand<string>)ExportCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand<string>)LoadExampleCommand).RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(HasProject));
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    protected virtual void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}