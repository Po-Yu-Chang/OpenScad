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
        DeleteFeatureCommand = new AsyncRelayCommand(DeleteFeatureAsync, () => _selectedFeature != null && IsWorkerConnected);
        EditParametersCommand = new RelayCommand(EditParameters, () => _selectedFeature != null);

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

        // 輸入為專案 ID（GUID）時直接開啟該專案——配合「開啟專案」清單的操作方式
        if (Guid.TryParse(request.Trim(), out _))
        {
            await OpenProjectByIdAsync(request.Trim());
            return;
        }

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
            if (FeatureTree.Count > 0 && _worker != null && _projectId != null)
            {
                await SendUpdateAsync(request);
            }
            else
            {
                var context = new DesignContext
                {
                    UserRequest = request,
                    CurrentProjectId = _projectId,
                };

                var plan = await _llmProvider.CreatePlanAsync(context);

                // 顯示計畫卡片
                // 一次性卡片：套用/取消後停用按鈕，防止重複執行
                var planMsg = ChatMessage.FromPlan(plan);
                planMsg.ApplyPlanCommand = new RelayCommand(() =>
                {
                    if (!planMsg.IsActionable) return;
                    planMsg.IsActionable = false;
                    _ = ApplyPlanAsync(plan);
                });
                planMsg.CancelPlanCommand = new RelayCommand(() =>
                {
                    if (!planMsg.IsActionable) return;
                    planMsg.IsActionable = false;
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

    /// <summary>
    /// 語意修改流程（A1）：取得特徵圖 → LLM 產生 update 命令 → 顯示差異卡片（A2）→ 使用者確認後套用。
    /// </summary>
    private async Task SendUpdateAsync(string userRequest)
    {
        if (_worker == null || _projectId == null || _llmProvider == null) return;

        try
        {
            // 取得目前特徵圖 JSON
            var featureGraphJson = await _worker.GetProjectAsync(_projectId);

            // LLM 產生 update 命令
            var command = await _llmProvider.CreateUpdateCommandAsync(userRequest, featureGraphJson);

            if (string.IsNullOrEmpty(command.TargetFeatureId))
            {
                Messages.Add(ChatMessage.Assistant("無法判斷要修改的特徵，請更具體描述。"));
                return;
            }

            // 取得修改前的特徵資料（用於 diff）
            var beforeParams = ExtractFeatureParams(featureGraphJson, command.TargetFeatureId);

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

            var diff = new ModificationDiff
            {
                FeatureId = command.TargetFeatureId,
                Before = beforeParams,
                After = afterParams,
                Description = command.Reasoning,
            };

            // 顯示差異卡片（A2）
            // 一次性卡片：套用/取消後停用按鈕，防止重複執行
            var diffMsg = ChatMessage.FromDiff(diff);
            diffMsg.ApplyDiffCommand = new RelayCommand(() =>
            {
                if (!diffMsg.IsActionable) return;
                diffMsg.IsActionable = false;
                _ = ApplyDiffAsync(command);
            });
            diffMsg.CancelDiffCommand = new RelayCommand(() =>
            {
                if (!diffMsg.IsActionable) return;
                diffMsg.IsActionable = false;
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

            // 產生 sketch_N ID
            var sketchId = $"sketch_{FeatureTree.Count + 1}";
            var command = new CadCommand
            {
                Action = "create_feature",
                Feature = new Feature
                {
                    FeatureId = sketchId,
                    Type = FeatureType.Sketch,
                    Name = $"草圖 {FeatureTree.Count + 1}",
                    Parameters = new(),
                    SketchEntities = new(),
                },
            };

            var result = await _worker.ApplyCommandAsync(_projectId, command);
            if (result.Status == "error")
            {
                Messages.Add(ChatMessage.Error($"建立草圖失敗：{result.ErrorCode} — {result.EngineMessage}"));
                return;
            }

            await UpdateFeatureTreeAsync();
            Messages.Add(ChatMessage.Assistant($"已建立空草圖「{sketchId}」，進入編輯模式…"));

            // 進入草圖編輯模式
            EnterSketchEditor(sketchId, "[]");
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

            // 從 Worker 取得特徵圖，取出 sketch_entities
            var rawJson = await _worker.GetProjectAsync(_projectId);
            var projectInfo = JsonSerializer.Deserialize<JsonElement>(rawJson);
            string entitiesJson = "[]";

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

                if (targetFeat.HasValue &&
                    targetFeat.Value.TryGetProperty("sketch_entities", out var seEl))
                {
                    entitiesJson = seEl.GetRawText();
                }
            }

            EnterSketchEditor(_selectedFeature.FeatureId, entitiesJson);
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
    private void EnterSketchEditor(string featureId, string entitiesJson)
    {
        ViewerScriptRequested?.Invoke(ViewerBridge.BuildEnterSketchScript(featureId, entitiesJson));
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
        if (_selectedFeature == null || _worker == null || _projectId == null) return;

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

            var node = new FeatureNode
            {
                FeatureId = fid,
                DisplayName = $"{name} ({type})",
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
        if (_selectedFeature == null)
        {
            CanEditSketch = false;
            return;
        }

        var featureId = _selectedFeature.FeatureId;
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
        OnPropertyChanged(nameof(HasProject));
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    protected virtual void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}