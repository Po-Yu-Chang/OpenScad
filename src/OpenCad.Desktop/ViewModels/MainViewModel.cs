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

    /// <summary>#2：目前尚未套用的提案卡（計畫／差異／批次）。收到新 prompt 時作廢它，避免殘留可點按鈕造成重複套用。</summary>
    private ChatMessage? _pendingCard;

    public ObservableCollection<ChatMessage> Messages { get; } = new();
    public ObservableCollection<FeatureNode> FeatureTree { get; } = new();
    public ObservableCollection<ParameterItem> SelectedFeatureParameters { get; } = new();

    // WP1-4: 量測結果
    public ObservableCollection<MeasurementResult> Measurements { get; } = new();

    // WP1-4: 選取過濾器
    private SelectionFilter _selectionFilter = SelectionFilter.All;
    public SelectionFilter SelectionFilter
    {
        get => _selectionFilter;
        set
        {
            _selectionFilter = value;
            OnPropertyChanged();
            // 通知 viewer 變更 raycast 層
            var filterStr = value.ToString().ToLowerInvariant();
            ViewerScriptRequested?.Invoke($"setSelectionFilter('{filterStr}');");
        }
    }

    // WP1-4: 顯示模式
    private DisplayMode _displayMode = DisplayMode.Shaded;
    public DisplayMode DisplayModeProp
    {
        get => _displayMode;
        set
        {
            _displayMode = value;
            OnPropertyChanged();
            var modeStr = value switch
            {
                DisplayMode.Shaded => "shaded",
                DisplayMode.ShadedWithEdges => "shaded-with-edges",
                DisplayMode.Wireframe => "wireframe",
                DisplayMode.Transparent => "transparent",
                _ => "shaded",
            };
            ViewerScriptRequested?.Invoke($"setDisplayMode('{modeStr}');");
        }
    }

    // WP1-4: 量測模式
    private bool _isMeasuring;
    public bool IsMeasuring
    {
        get => _isMeasuring;
        set
        {
            _isMeasuring = value;
            OnPropertyChanged();
            ViewerScriptRequested?.Invoke(value ? "enterMeasureMode();" : "exitMeasureMode();");
        }
    }

    // WP1-4: 隔離的特徵 ID（null = 不隔離）
    private string? _isolatedFeatureId;
    public string? IsolatedFeatureId
    {
        get => _isolatedFeatureId;
        set
        {
            _isolatedFeatureId = value;
            OnPropertyChanged();
            if (value != null)
                ViewerScriptRequested?.Invoke($"isolateFeature('{value}');");
            else
                ViewerScriptRequested?.Invoke("clearIsolate();");
        }
    }

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
    public ICommand SuppressFeatureCommand { get; }
    public ICommand UnsuppressFeatureCommand { get; }
    public ICommand RollbackToHereCommand { get; }
    public ICommand RollbackToEndCommand { get; }
    public ICommand ExportChatCommand { get; }
    public ICommand CreateDatumPlaneCommand { get; }

    // WP1-4: Property Manager / 量測 / 選取 / 顯示模式 命令
    public ICommand ToggleMeasureCommand { get; }
    public ICommand ApplyAllParametersCommand { get; }
    public ICommand IsolateFeatureCommand { get; }
    public ICommand HideFeatureCommand { get; }
    public ICommand ShowAllFeaturesCommand { get; }
    public ICommand SetSelectionFilterCommand { get; }
    public ICommand SetDisplayModeCommand { get; }

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
        SuppressFeatureCommand = new AsyncRelayCommand(SuppressFeatureAsync, () => _selectedFeature != null && !_selectedFeature.IsDatumPlane && IsWorkerConnected);
        UnsuppressFeatureCommand = new AsyncRelayCommand(UnsuppressFeatureAsync, () => _selectedFeature != null && !_selectedFeature.IsDatumPlane && IsWorkerConnected);
        RollbackToHereCommand = new AsyncRelayCommand(RollbackToHereAsync, () => _selectedFeature != null && !_selectedFeature.IsDatumPlane && IsWorkerConnected);
        RollbackToEndCommand = new AsyncRelayCommand(RollbackToEndAsync, () => IsWorkerConnected);
        ExportChatCommand = new AsyncRelayCommand(ExportChatAsync, () => Messages.Count > 0);
        CreateDatumPlaneCommand = new AsyncRelayCommand(CreateDatumPlaneDialogAsync, () => IsWorkerConnected);

        // WP1-4: 量測/選取/顯示模式命令
        ToggleMeasureCommand = new RelayCommand(() => IsMeasuring = !IsMeasuring);
        ApplyAllParametersCommand = new AsyncRelayCommand(ApplyAllParametersAsync, () => SelectedFeatureParameters.Any(p => p.IsDirty) && IsWorkerConnected);
        IsolateFeatureCommand = new AsyncRelayCommand(IsolateFeatureAsync, () => _selectedFeature != null && IsWorkerConnected);
        HideFeatureCommand = new AsyncRelayCommand(HideFeatureAsync, () => _selectedFeature != null && IsWorkerConnected);
        ShowAllFeaturesCommand = new AsyncRelayCommand(ShowAllFeaturesAsync, () => IsWorkerConnected);
        SetSelectionFilterCommand = new RelayCommand<SelectionFilter>(f => SelectionFilter = f);
        SetDisplayModeCommand = new RelayCommand<DisplayMode>(m => DisplayModeProp = m);

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

            // GLB 已在 rebuild 時由逐面 tessellation 產生（與 display_map 同路徑）。
            // ExportAsync("glb") 確保檔案就緒（若 rebuild 已產生則直接回傳既有檔案）。
            await _worker.ExportAsync(_projectId, "glb");

            _rebuildCount++;
            if (_workerClient != null)
                _workerClient.RebuildCount = _rebuildCount;

            var previewUrl = await _worker.GetPreviewUrlAsync(_projectId);
            var displayMapUrl = await _worker.GetDisplayMapUrlAsync(_projectId);
            ViewerScriptRequested?.Invoke(ViewerBridge.BuildLoadScript(previewUrl, displayMapUrl));

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
    /// Repair Agent 迴圈——當重建失敗時，將錯誤碼餵給 LLM 產生修正命令。
    /// WP-H1：低風險 2 次重試（地雷 #16），修復類型白名單：格式修正、唯一可推導 reference。
    /// </summary>
    private async Task<RebuildResult> TryRepairAsync(RebuildResult failedRebuild)
    {
        const int maxRetries = 2;
        // WP-H1 修復白名單（地雷 #16）——只允許「格式修正」與「唯一可推導」類低風險修復。
        // 改尺寸類（FILLET_RADIUS_TOO_LARGE 等）與改參照類（FEATURE_REFERENCE_NOT_FOUND）
        // 不得自動套用——只能提出建議由使用者確認。
        var repairWhitelist = new HashSet<string>
        {
            "SKETCH_NOT_CLOSED",
            "INVALID_STANDARD_PART",
        };
        var rebuild = failedRebuild;
        string? lastErrorCode = null;
        string? lastRepairJson = null;

        for (int attempt = 1; attempt <= maxRetries; attempt++)
        {
            if (string.IsNullOrEmpty(rebuild.ErrorCode))
                break;

            // WP-H1：非白名單錯誤不自動修復，直接出卡片讓使用者決定
            if (!repairWhitelist.Contains(rebuild.ErrorCode))
            {
                Messages.Add(ChatMessage.Assistant(
                    $"⚠️ 錯誤類型 {rebuild.ErrorCode} 不在自動修復白名單中，需手動處理：{rebuild.EngineMessage}"));
                break;
            }

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

                // 地雷 #16：同一錯誤＋同一命令不得反覆重試
                var repairJson = System.Text.Json.JsonSerializer.Serialize(repairCmd);
                if (rebuild.ErrorCode == lastErrorCode && repairJson == lastRepairJson)
                {
                    Messages.Add(ChatMessage.Assistant("⚠️ LLM 產生了與上次相同的修正命令，停止重試"));
                    break;
                }
                lastErrorCode = rebuild.ErrorCode;
                lastRepairJson = repairJson;

                Messages.Add(ChatMessage.Assistant(
                    $"修正方案：{repairCmd.Action}" +
                    (repairCmd.TargetFeatureId != null ? $" → {repairCmd.TargetFeatureId}" : "")));

                // 套用修正命令，再以 staging dry-run 驗證「修正後」的 graph——
                // 驗證失敗就 undo 還原，不污染正式模型（dry-run 在套用前跑只會驗到舊圖）
                var cmdResult = await _worker.ApplyCommandAsync(_projectId!, repairCmd);
                if (cmdResult.Status == "error")
                {
                    Log.Warning("修正命令失敗：{Msg}", cmdResult.EngineMessage);
                    continue;
                }

                var dryRunResult = await _worker.RebuildStagingAsync(_projectId!);
                if (dryRunResult.Status != "success")
                {
                    Log.Warning("Dry-run 驗證修正後仍失敗，undo 還原：{Msg}", dryRunResult.EngineMessage);
                    await _worker.UndoAsync(_projectId!);
                    rebuild = new RebuildResult
                    {
                        Status = dryRunResult.Status,
                        ErrorCode = dryRunResult.ErrorCode ?? rebuild.ErrorCode,
                        EngineMessage = dryRunResult.EngineMessage,
                    };
                    continue;
                }

                // 重新重建
                rebuild = await _worker.RebuildAsync(_projectId!);
                if (rebuild.Status == "success")
                {
                    // 比較修正前後的參數值，告知使用者實際使用的值
                    var repairNote = DescribeRepairChange(repairCmd, graphJson);
                    Messages.Add(ChatMessage.Assistant(
                        $"✓ 修正成功（第 {attempt} 次嘗試）{repairNote}"));
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

    /// <summary>
    /// 產生修正變更的說明文字，讓使用者知道實際使用的參數值。
    /// </summary>
    private static string DescribeRepairChange(CadCommand repairCmd, string graphJsonBefore)
    {
        try
        {
            if (repairCmd.Action != "update_feature" || repairCmd.TargetFeatureId == null)
                return "";

            using var doc = JsonDocument.Parse(graphJsonBefore);
            if (!doc.RootElement.TryGetProperty("features", out var graphEl) ||
                !graphEl.TryGetProperty("features", out var featsEl))
                return "";

            if (!featsEl.TryGetProperty(repairCmd.TargetFeatureId, out var featEl))
                return "";

            var featType = featEl.TryGetProperty("type", out var tEl) ? tEl.GetString() : "";
            var parts = new List<string>();

            if (repairCmd.Parameters != null)
            {
                foreach (var kv in repairCmd.Parameters)
                {
                    // 取得修正前的值
                    var beforeVal = "";
                    if (featEl.TryGetProperty("parameters", out var paramsEl) &&
                        paramsEl.TryGetProperty(kv.Key, out var beforeEl))
                    {
                        beforeVal = beforeEl.GetRawText();
                    }

                    var afterVal = kv.Value?.ToString() ?? "";
                    if (!string.IsNullOrEmpty(beforeVal) && beforeVal != afterVal)
                    {
                        parts.Add($"{kv.Key}: {beforeVal} → {afterVal}");
                    }
                }
            }

            if (parts.Count > 0)
                return $"（參數已調整：{string.Join(", ", parts)}）";
        }
        catch { }
        return "";
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
                    if (n.Parameters != null && n.Parameters.Count > 0)
                    {
                        foreach (var p in n.Parameters)
                            sb.AppendLine($"{prefix}  * {p.Key}: {p.Value}");
                    }
                    DumpTree(n.Children, indent + 1);
                }
            }
            DumpTree(FeatureTree, 0);
            sb.AppendLine();

            // ── 四、JSON 格式（方便程式化分析） ──
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
                        steps = m.Plan.Steps?.Select(s => new {
                            description = s.Description,
                            type = s.FeatureType,
                            parameters = s.Parameters,
                            sketch_entities = s.SketchEntities,
                            plane = s.Plane
                        }).ToList(),
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

        // #2：上一張提案卡若尚未套用，收到新 prompt 即作廢它——
        // 否則舊卡片的「套用」按鈕仍可點，會造成重複套用或狀態錯亂。
        if (_pendingCard is { IsActionable: true })
        {
            _pendingCard.IsActionable = false;
            Messages.Add(ChatMessage.Assistant("（已略過上一個未套用的提案）"));
        }
        _pendingCard = null;

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
                _pendingCard = planMsg;

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

        // 全部取消 / 清空 / 重新開始
        if (IntentMatcher.IsClearAll(trimmed))
        {
            if (HasProject && IsWorkerConnected)
            {
                _ = ClearAllAsync();
            }
            else
            {
                Messages.Add(ChatMessage.Assistant("目前沒有開啟的專案，無法清空。"));
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

            // 收集所有命令——不逐一套用，而是透過 staging/rollback 交易一次套用
            // 確保 LLM 計畫要嘛完整套用，要完全不套用——不會留下半成品
            var commands = new List<CadCommand>();
            string? lastSketchId = null;
            string? lastFeatureId = null;
            var index = 0;
            // P0：datum 產生的 id 依提示詞慣例編號（datum_plane_1…），供後續 sketch 的 plane.base=""datum:…"" 對上
            var datumCounts = new Dictionary<string, int>();

            foreach (var step in plan.Steps)
            {
                index++;

                // P0：datum 為 reference geometry，不是 create_feature 特徵——
                // 路由到基準幾何 API（在特徵交易之前建立），不進入命令列表也不做 Enum 解析。
                if (step.FeatureType.StartsWith("datum_", StringComparison.OrdinalIgnoreCase))
                {
                    datumCounts.TryGetValue(step.FeatureType, out var dn);
                    datumCounts[step.FeatureType] = ++dn;
                    await CreateDatumFromStepAsync(step, $"{step.FeatureType}_{dn}");
                    continue;
                }

                // 計畫的 feature_type 是 snake_case（如 linear_pattern）
                var enumName = step.FeatureType.Replace("_", "");
                if (!Enum.TryParse<FeatureType>(enumName, true, out var featType))
                {
                    Messages.Add(ChatMessage.Error($"未知特徵類型：{step.FeatureType}"));
                    continue;
                }

                // LLM 可能輸出 {"type":"XY"} 或 {"base":"XY"}——統一正規化為 base 格式
                var plane = NormalizePlane(step.Plane);

                // sketch 步驟必須包含 sketch_entities，否則建立空草圖會導致 pad 失敗
                if (featType == FeatureType.Sketch &&
                    (step.SketchEntities == null || step.SketchEntities.Count == 0))
                {
                    Messages.Add(ChatMessage.Error(
                        $"計畫第 {index} 步（sketch）缺少 sketch_entities——LLM 未產生草圖幾何，請重新描述需求。"));
                    return;
                }

                // pad/revolve 沒有前置草圖時：若步驟自帶 sketch_entities，
                // 確定性拆出草圖特徵；否則計畫不完整，中止並回報
                if (featType is FeatureType.Pad or FeatureType.Revolve && lastSketchId == null)
                {
                    if (step.SketchEntities is { Count: > 0 })
                    {
                        var autoSketchId = $"sketch_{index}_auto";
                        commands.Add(new CadCommand
                        {
                            Action = "create_feature",
                            Feature = new Feature
                            {
                                FeatureId = autoSketchId,
                                Type = FeatureType.Sketch,
                                Name = $"草圖（自步驟 {index} 拆出）",
                                Parameters = new(),
                                SketchEntities = step.SketchEntities,
                                Constraints = step.Constraints ?? new(),
                                Plane = plane,
                            },
                        });
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
                var references = featType == FeatureType.Pocket && lastSketchId != null
                    ? new List<string> { lastSketchId }
                    : input != null ? new List<string> { input } : new();

                commands.Add(new CadCommand
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
                        SketchEntities = featType == FeatureType.Sketch ? step.SketchEntities ?? new() : new(),
                        Constraints = featType == FeatureType.Sketch ? step.Constraints ?? new() : new(),
                        StandardParts = step.StandardParts ?? new(),
                        Plane = plane,
                    },
                });

                if (featType == FeatureType.Sketch)
                    lastSketchId = featureId;
                else
                    lastFeatureId = featureId;
            }

            if (commands.Count == 0)
            {
                Messages.Add(ChatMessage.Error("計畫沒有可執行的步驟。"));
                return;
            }

            // 本地驗證——在送出 Worker 前攔截格式錯誤
            foreach (var cmd in commands)
            {
                var errors = CommandValidator.Validate(cmd);
                if (errors.Count > 0)
                {
                    Messages.Add(ChatMessage.Error($"命令驗證失敗：{string.Join("；", errors)}"));
                    return;
                }
            }

            // 交易式套用——staging graph 上試跑，重建成功才 commit
            var planResult = await _worker.ApplyPlanAsync(_projectId, commands, plan.Summary);
            if (planResult.Status == "error")
            {
                Messages.Add(ChatMessage.Error(
                    $"計畫套用失敗（已回滾，特徵圖未變更）：{planResult.ErrorCode} — {planResult.EngineMessage}"));
                return;
            }

            Messages.Add(ChatMessage.Assistant(
                $"計畫已套用（{planResult.AppliedCount} 步），開始重建…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"套用計畫失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// P0：把計畫中的 datum 步驟建立為 reference geometry（datum_plane/axis/point）。
    /// datum 不屬 create_feature 特徵，走專用 API，於特徵交易之前建立。
    /// </summary>
    private async Task CreateDatumFromStepAsync(DesignStep step, string datumId)
    {
        if (_worker == null || _projectId == null) return;

        var kind = step.FeatureType switch
        {
            "datum_axis" => "axis",
            "datum_point" => "point",
            _ => "plane",
        };
        var definition = step.Parameters != null
            ? new Dictionary<string, object>(step.Parameters)
            : new Dictionary<string, object>();
        var name = string.IsNullOrWhiteSpace(step.Description) ? datumId : step.Description;

        try
        {
            var result = await _worker.CreateReferenceGeometryAsync(_projectId, datumId, name, kind, definition);
            if (result != null)
                Messages.Add(ChatMessage.Assistant($"已建立基準幾何 {datumId}（{kind}）。"));
            else
                Messages.Add(ChatMessage.Error(
                    $"建立基準幾何 {datumId} 失敗——後續依賴此基準的草圖可能無法定位。"));
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"建立基準幾何 {datumId} 失敗：{ex.Message}"));
        }
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

            // LLM 產生一批命令（可多個）或反問
            var batch = await _llmProvider.CreateUpdateCommandAsync(userRequest, featureGraphJson, new List<ChatTurn>(_chatHistory));

            // #3：需求不明確 → 反問，不硬產生命令
            if (batch.Commands.Count == 0)
            {
                var q = string.IsNullOrWhiteSpace(batch.Clarification)
                    ? "無法判斷要執行的修改，請更具體描述。"
                    : batch.Clarification!;
                Messages.Add(ChatMessage.Assistant(q));
                AddHistory("assistant", q);
                return;
            }

            // #1：一句多動作 → 交易式彙總套用（全成功才 commit）
            if (batch.Commands.Count > 1)
            {
                ShowMultiCommandPlan(userRequest, batch.Commands);
                return;
            }

            // 單一命令 → 沿用差異卡片（A2）
            await ShowSingleCommandDiffAsync(batch.Commands[0], featureGraphJson);
        }
        catch (Exception ex)
        {
            Log.Error(ex, "語意修改流程失敗");
            Messages.Add(ChatMessage.Error($"修改流程失敗：{ex.Message}"));
        }
    }

    /// <summary>
    /// 單一命令的差異卡片（A2 確認後套用）。
    /// </summary>
    private async Task ShowSingleCommandDiffAsync(CadCommand command, string featureGraphJson)
    {
        try
        {
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
            _pendingCard = diffMsg;
        }
        catch (Exception ex)
        {
            Log.Error(ex, "語意修改流程失敗");
            Messages.Add(ChatMessage.Error($"修改流程失敗：{ex.Message}"));
        }
    }

    /// <summary>
    /// 多命令修改（#1）：顯示彙總卡片，確認後以 staging 交易一次套用（全成功才 commit）。
    /// </summary>
    private void ShowMultiCommandPlan(string userRequest, List<CadCommand> commands)
    {
        var display = commands.Where(c => c.Action != "rebuild").ToList();
        if (display.Count == 0)
        {
            Messages.Add(ChatMessage.Assistant("沒有可套用的修改。"));
            return;
        }

        var plan = new DesignPlan
        {
            Summary = $"{display.Count} 項修改：{userRequest}",
            Steps = display.Select(c => new DesignStep
            {
                Description = string.IsNullOrWhiteSpace(c.Reasoning)
                    ? DescribeCommand(c)
                    : $"{DescribeCommand(c)} — {c.Reasoning}",
                FeatureType = c.Feature?.Type.ToString().ToLowerInvariant() ?? c.Action,
            }).ToList(),
        };

        AddHistory("assistant", $"[批次修改] {plan.Summary}");

        var planMsg = ChatMessage.FromPlan(plan);
        planMsg.ApplyPlanCommand = new RelayCommand(() =>
        {
            if (!planMsg.IsActionable) return;
            planMsg.IsActionable = false;
            AddHistory("user", "[套用批次修改]");
            _ = ApplyCommandBatchAsync(commands, plan.Summary);
        });
        planMsg.CancelPlanCommand = new RelayCommand(() =>
        {
            if (!planMsg.IsActionable) return;
            planMsg.IsActionable = false;
            AddHistory("user", "[取消批次修改]");
            Messages.Add(ChatMessage.Assistant("已取消修改。"));
        });
        Messages.Add(planMsg);
        _pendingCard = planMsg;
    }

    /// <summary>用一句話描述一個命令，供彙總卡片顯示。</summary>
    private static string DescribeCommand(CadCommand c) => c.Action switch
    {
        "create_feature" => $"新增 {c.Feature?.Type.ToString().ToLowerInvariant()} {c.Feature?.FeatureId}",
        "update_feature" => $"修改 {c.TargetFeatureId}",
        "delete_feature" => $"刪除 {c.TargetFeatureId}",
        "set_material" => $"變更材質 {c.Parameters?.GetValueOrDefault("material")}",
        _ => c.Action,
    };

    /// <summary>
    /// 交易式套用一批命令（staging + rollback）——全成功才 commit，然後重建。（#1）
    /// </summary>
    private async Task ApplyCommandBatchAsync(List<CadCommand> commands, string label)
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;

            // rebuild 不是 apply_plan 接受的 action，過濾掉
            var toApply = commands.Where(c => c.Action != "rebuild").ToList();
            foreach (var cmd in toApply)
            {
                var errors = CommandValidator.Validate(cmd);
                if (errors.Count > 0)
                {
                    Messages.Add(ChatMessage.Error($"命令驗證失敗：{string.Join("；", errors)}"));
                    return;
                }
            }
            if (toApply.Count == 0)
            {
                await RebuildAsync();
                return;
            }

            var planResult = await _worker.ApplyPlanAsync(_projectId, toApply, label);
            if (planResult.Status == "error")
            {
                Messages.Add(ChatMessage.Error(
                    $"批次修改失敗（已回滾，特徵圖未變更）：{planResult.ErrorCode} — {planResult.EngineMessage}"));
                return;
            }

            Messages.Add(ChatMessage.Assistant($"已套用 {planResult.AppliedCount} 項修改，開始重建…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"套用批次修改失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
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

            // 本地驗證——在送出 Worker 前攔截格式錯誤
            var errors = CommandValidator.Validate(command);
            if (errors.Count > 0)
            {
                Messages.Add(ChatMessage.Error($"命令驗證失敗：{string.Join("；", errors)}"));
                return;
            }

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
    /// 清除所有使用者建立的特徵（保留基準面/原點）。
    /// </summary>
    private async Task ClearAllAsync()
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;

            // 原子性清除——單一交易，一個 undo 步驟
            // 不同於逐一刪除，這會建立一個空白 graph 的 revision，
            // 讓使用者可以一次 Undo 回到清除前的完整狀態
            var success = await _worker.ResetProjectAsync(_projectId);
            if (!success)
            {
                Messages.Add(ChatMessage.Error("清空失敗——Worker 未回應成功。"));
                return;
            }

            Messages.Add(ChatMessage.Assistant("已清除全部特徵，模型已重置。（可一次復原回到清除前狀態）"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"清空失敗：{ex.Message}"));
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
            // WP1-3: 若選取的是基準幾何中的 datum plane，使用 datum: 引用
            else if (_selectedFeature?.ReferenceGeometryId is string datumId)
            {
                planeBase = $"datum:{datumId}";
            }

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
    public async Task CommitSketchAsync(string featureId, string entitiesJson, string? constraintsJson = null)
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            IsBusy = true;

            var entities = JsonSerializer.Deserialize<List<Dictionary<string, object>>>(entitiesJson)
                ?? new List<Dictionary<string, object>>();

            List<Dictionary<string, object>>? constraints = null;
            if (constraintsJson != null)
            {
                constraints = JsonSerializer.Deserialize<List<Dictionary<string, object>>>(constraintsJson);
            }

            var command = new CadCommand
            {
                Action = "update_feature",
                TargetFeatureId = featureId,
                SketchEntities = entities,
                Constraints = constraints,
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
    /// 收到 viewer 的 sketch_solve 訊息後呼叫求解端點（WP1-2，互動式，不進入歷史）。
    /// </summary>
    public async Task SolveSketchAsync(string featureId, string entitiesJson, string? constraintsJson)
    {
        if (_worker == null || _projectId == null) return;
        try
        {
            var entities = JsonSerializer.Deserialize<List<Dictionary<string, object>>>(entitiesJson)
                ?? new List<Dictionary<string, object>>();
            var constraints = (constraintsJson != null)
                ? JsonSerializer.Deserialize<List<Dictionary<string, object>>>(constraintsJson) ?? new()
                : new List<Dictionary<string, object>>();

            var result = await _worker.SolveSketchAsync(_projectId, featureId, entities, constraints);
            if (result != null)
            {
                // result 已是 JSON 字串——再 Serialize 會變成帶引號的字串常值，
                // viewer 端 opencadSolverResult 收到 string 而非物件（求解結果永遠套不上）
                ViewerScriptRequested?.Invoke(ViewerBridge.BuildSolverResultScript(result));
            }
        }
        catch (Exception ex)
        {
            // Solve failure = stay in place (silent fail)
            System.Diagnostics.Debug.WriteLine($"Sketch solve failed: {ex.Message}");
        }
    }

    /// <summary>
    /// WP1-4: 接收 viewer 的量測結果（viewer overlay 已即時顯示；這裡入集合供 UI/紀錄使用）。
    /// </summary>
    public void AddMeasurement(string type, double value, string unit, string description)
    {
        Measurements.Add(new MeasurementResult
        {
            Type = type,
            Value = value,
            Unit = unit,
            Description = description,
        });
    }

    /// <summary>
    /// 取消草圖編輯——只需退出 viewer 草圖模式。
    /// </summary>
    public void CancelSketch()
    {
        ViewerScriptRequested?.Invoke(ViewerBridge.BuildExitSketchScript());
    }

    /// <summary>
    /// WP1-3: 建立基準面（datum plane）——面偏移。
    /// </summary>
    public async Task CreateDatumPlaneAsync(string sourceRef, double offsetMm, string name = "")
    {
        if (_worker == null || _projectId == null) return;
        IsBusy = true;
        try
        {
            var datumId = $"datum_plane_{DateTime.Now:HHmmss}";
            var definition = new Dictionary<string, object>
            {
                ["method"] = "offset",
                ["source_ref"] = sourceRef,
                ["offset_mm"] = offsetMm,
            };
            var result = await _worker.CreateReferenceGeometryAsync(_projectId, datumId, name, "plane", definition);
            if (result != null)
            {
                await UpdateFeatureTreeAsync();
                Messages.Add(ChatMessage.Assistant($"已建立基準面「{name}」（偏移 {offsetMm}mm）。"));
            }
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"建立基準面失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// WP1-3: 基準面建立對話框——提示使用者輸入偏移量。
    /// </summary>
    private async Task CreateDatumPlaneDialogAsync()
    {
        // 簡化：使用預設值（XY 面，偏移 10mm）——未來接 Avalonia 對話框
        await CreateDatumPlaneAsync("face:f1.top", 10.0, "偏移基準面");
    }

    /// <summary>
    /// WP1-3: 刪除基準幾何。
    /// </summary>
    public async Task DeleteReferenceGeometryAsync(string rgId)
    {
        if (_worker == null || _projectId == null) return;
        IsBusy = true;
        try
        {
            var actualId = rgId;
            var ok = await _worker.DeleteReferenceGeometryAsync(_projectId, actualId);
            if (ok)
            {
                await UpdateFeatureTreeAsync();
                Messages.Add(ChatMessage.Assistant($"已刪除基準幾何「{actualId}」。"));
            }
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"刪除基準幾何失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 刪除目前選取的特徵。
    /// </summary>
    private async Task DeleteFeatureAsync()
    {
        if (_selectedFeature == null || _worker == null || _projectId == null) return;

        var featureId = _selectedFeature.FeatureId;

        // WP1-3: 基準幾何刪除
        if (_selectedFeature.ReferenceGeometryId is string rgIdToDelete)
        {
            await DeleteReferenceGeometryAsync(rgIdToDelete);
            return;
        }

        // 內建基準面不可刪除
        if (_selectedFeature.IsDatumPlane) return;

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
    /// 抑制選取的特徵——v2 suppress_feature 命令。
    /// </summary>
    private async Task SuppressFeatureAsync()
    {
        if (_selectedFeature == null || _selectedFeature.IsDatumPlane || _worker == null || _projectId == null) return;

        var featureId = _selectedFeature.FeatureId;
        IsBusy = true;
        try
        {
            var command = new CadCommand { Action = "suppress_feature", TargetFeatureId = featureId };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"抑制失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }
            Messages.Add(ChatMessage.Assistant($"已抑制特徵「{featureId}」，重建中…"));
            await UpdateFeatureTreeAsync();
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"抑制特徵失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 取消抑制選取的特徵——v2 unsuppress_feature 命令。
    /// </summary>
    private async Task UnsuppressFeatureAsync()
    {
        if (_selectedFeature == null || _selectedFeature.IsDatumPlane || _worker == null || _projectId == null) return;

        var featureId = _selectedFeature.FeatureId;
        IsBusy = true;
        try
        {
            var command = new CadCommand { Action = "unsuppress_feature", TargetFeatureId = featureId };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"取消抑制失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }
            Messages.Add(ChatMessage.Assistant($"已取消抑制特徵「{featureId}」，重建中…"));
            await UpdateFeatureTreeAsync();
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"取消抑制失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 回溯到選取特徵——v2 set_rollback 命令，rollback_position = 特徵的 order。
    /// </summary>
    private async Task RollbackToHereAsync()
    {
        if (_selectedFeature == null || _selectedFeature.IsDatumPlane || _worker == null || _projectId == null) return;

        var order = _selectedFeature.Order;
        IsBusy = true;
        try
        {
            var command = new CadCommand
            {
                Action = "set_rollback",
                Parameters = new Dictionary<string, object> { ["rollback_position"] = order },
            };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"回溯失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }
            Messages.Add(ChatMessage.Assistant($"已回溯到特徵「{_selectedFeature.DisplayName}」(order={order})，重建中…"));
            await UpdateFeatureTreeAsync();
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"回溯失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// 回到末端——v2 set_rollback 命令，rollback_position = null（重建全部）。
    /// </summary>
    private async Task RollbackToEndAsync()
    {
        if (_worker == null || _projectId == null) return;

        IsBusy = true;
        try
        {
            var command = new CadCommand
            {
                Action = "set_rollback",
                Parameters = new Dictionary<string, object> { ["rollback_position"] = null! },
            };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"回到末端失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }
            Messages.Add(ChatMessage.Assistant("已回到末端，重建全部特徵…"));
            await UpdateFeatureTreeAsync();
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Messages.Add(ChatMessage.Error($"回到末端失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
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

            // WP1-3: 基準幾何資料夾——datum plane/axis/point
            var refGeomNodes = new List<FeatureNode>();
            if (projectInfo.TryGetProperty("features", out var featuresEl2) &&
                featuresEl2.ValueKind == JsonValueKind.Object &&
                featuresEl2.TryGetProperty("reference_geometry", out var rgEl) &&
                rgEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var rg in rgEl.EnumerateArray())
                {
                    var rgId = rg.TryGetProperty("id", out var rgIdEl) ? rgIdEl.GetString() ?? "" : "";
                    var rgName = rg.TryGetProperty("name", out var rgNameEl) ? rgNameEl.GetString() ?? rgId : rgId;
                    var rgKind = rg.TryGetProperty("kind", out var rgKindEl) ? rgKindEl.GetString() ?? "" : "";
                    refGeomNodes.Add(new FeatureNode
                    {
                        FeatureId = $"__rg_{rgId}",  // 僅作樹節點唯一鍵；判別/取 id 一律用 ReferenceGeometryId
                        ReferenceGeometryId = rgId,
                        DisplayName = $"{rgName} ({rgKind})",
                        FeatureType = $"datum_{rgKind}",
                        IsDatumPlane = rgKind == "plane",
                    });
                }
            }
            if (refGeomNodes.Count > 0)
            {
                FeatureTree.Add(new FeatureNode
                {
                    FeatureId = "__ref_geom_folder",
                    DisplayName = "基準幾何",
                    FeatureType = "folder",
                    IsDatumPlane = true,
                });
                foreach (var n in refGeomNodes) FeatureTree.Add(n);
            }

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
                State = featEl.TryGetProperty("state", out var stateEl) && stateEl.ValueKind == JsonValueKind.String
                    ? stateEl.GetString() ?? "active"
                    : "active",
                Order = featEl.TryGetProperty("order", out var orderEl) && orderEl.ValueKind == JsonValueKind.Number
                    ? orderEl.GetInt32()
                    : 0,
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
            ((AsyncRelayCommand)SuppressFeatureCommand).RaiseCanExecuteChanged();
            ((AsyncRelayCommand)UnsuppressFeatureCommand).RaiseCanExecuteChanged();
            ((AsyncRelayCommand)RollbackToHereCommand).RaiseCanExecuteChanged();
            ((AsyncRelayCommand)RollbackToEndCommand).RaiseCanExecuteChanged();

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
        ((AsyncRelayCommand)SuppressFeatureCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)UnsuppressFeatureCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RollbackToHereCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RollbackToEndCommand).RaiseCanExecuteChanged();

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

    /// <summary>
    /// WP1-4: 一次套用所有已編輯的參數（Apply All）。
    /// </summary>
    private async Task ApplyAllParametersAsync()
    {
        if (_worker == null || _projectId == null || _selectedFeature == null) return;

        var dirtyItems = SelectedFeatureParameters.Where(p => p.IsDirty).ToList();
        if (dirtyItems.Count == 0) return;

        try
        {
            IsBusy = true;
            var updates = new Dictionary<string, object>();
            foreach (var item in dirtyItems)
            {
                if (double.TryParse(item.Value, out var number))
                {
                    if (number <= 0 && item.Key is "length" or "width" or "height" or "depth" or "diameter" or "radius" or "thickness")
                    {
                        Messages.Add(ChatMessage.Error($"參數 {item.Key} 必須大於 0。"));
                        return;
                    }
                    updates[item.Key] = number;
                }
                else
                {
                    updates[item.Key] = item.Value;
                }
            }

            var command = new CadCommand
            {
                Action = "update_feature",
                TargetFeatureId = _selectedFeature.FeatureId,
                Parameters = updates,
            };
            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"參數更新失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            foreach (var item in dirtyItems)
                item.OriginalValue = item.Value;

            Messages.Add(ChatMessage.Assistant($"已更新 {dirtyItems.Count} 個參數，重建中…"));
            await RebuildAsync();
        }
        catch (Exception ex)
        {
            Log.Error(ex, "ApplyAllParametersAsync 失敗");
            Messages.Add(ChatMessage.Error($"參數批次更新失敗：{ex.Message}"));
        }
        finally { IsBusy = false; }
    }

    /// <summary>
    /// WP1-4: 隔離選取特徵（其他特徵隱藏）。
    /// </summary>
    private async Task IsolateFeatureAsync()
    {
        if (_selectedFeature == null) return;
        IsolatedFeatureId = _selectedFeature.FeatureId;
        await Task.CompletedTask;
    }

    /// <summary>
    /// WP1-4: 隱藏選取特徵。
    /// </summary>
    private async Task HideFeatureAsync()
    {
        if (_selectedFeature == null) return;
        ViewerScriptRequested?.Invoke($"hideFeature('{_selectedFeature.FeatureId}');");
        await Task.CompletedTask;
    }

    /// <summary>
    /// WP1-4: 顯示所有特徵（取消隔離與隱藏）。
    /// </summary>
    private async Task ShowAllFeaturesAsync()
    {
        IsolatedFeatureId = null;
        ViewerScriptRequested?.Invoke("showAllFeatures();");
        await Task.CompletedTask;
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

    /// <summary>
    /// 由 face picking 選中的 source_feature_id 反查特徵樹節點並選取。
    /// </summary>
    public void SelectFeatureById(string featureId)
    {
        var node = FeatureTree.FirstOrDefault(n => n.FeatureId == featureId);
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
        ((AsyncRelayCommand)SuppressFeatureCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)UnsuppressFeatureCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RollbackToHereCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)RollbackToEndCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)ExportChatCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)CreateDatumPlaneCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)ApplyAllParametersCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)IsolateFeatureCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)HideFeatureCommand).RaiseCanExecuteChanged();
        ((AsyncRelayCommand)ShowAllFeaturesCommand).RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(HasProject));
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    protected virtual void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}