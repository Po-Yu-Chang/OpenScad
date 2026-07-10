using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using OpenCad.MVVM;
using OpenCad.Viewer;

namespace OpenCad.Desktop.ViewModels;

/// <summary>
/// 主 ViewModel——連接 UI 與 LLM／CAD Worker。
/// </summary>
public class MainViewModel : INotifyPropertyChanged
{
    private string _inputText = string.Empty;
    private string _llmStatus = "LLM 狀態：未連線";
    private string _modelInfoText = string.Empty;
    private string _validationText = "驗證報告：尚未執行";
    private bool _hasModel;

    public ObservableCollection<ChatMessage> Messages { get; } = new();
    public ObservableCollection<FeatureNode> FeatureTree { get; } = new();

    public string InputText
    {
        get => _inputText;
        set { _inputText = value; OnPropertyChanged(); }
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

    public bool HasModel
    {
        get => _hasModel;
        set { _hasModel = value; OnPropertyChanged(); }
    }

    public ICommand SendCommand { get; }
    public ICommand NewProjectCommand { get; }
    public ICommand OpenProjectCommand { get; }
    public ICommand SaveProjectCommand { get; }
    public ICommand SetViewCommand { get; }
    public ICommand ExportCommand { get; }
    public ICommand RebuildCommand { get; }

    /// <summary>
    /// 當 ViewModel 需要在 3D 視窗中執行 JavaScript 時觸發。
    /// MainWindow 訂閱此事件並透過 WebView.ExecuteScriptAsync 執行。
    /// </summary>
    public event Action<string>? ViewerScriptRequested;

    public MainViewModel()
    {
        SendCommand = new RelayCommand(Send);
        NewProjectCommand = new RelayCommand(NewProject);
        OpenProjectCommand = new RelayCommand(OpenProject);
        SaveProjectCommand = new RelayCommand(SaveProject);
        SetViewCommand = new RelayCommand<string>(SetView);
        ExportCommand = new RelayCommand<string>(Export);
        RebuildCommand = new RelayCommand(Rebuild);

        // 歡迎訊息
        Messages.Add(ChatMessage.Assistant(
            "您好！我是 OpenCad AI 建模助手。\n" +
            "請用繁體中文描述您要設計的零件，例如：\n" +
            "「建立一個 NEMA17 馬達座，底板 60 × 60 × 5 mm，" +
            "中心孔直徑 24 mm，使用四個 M3 一般間隙孔，" +
            "固定孔距依 NEMA17 標準，外圍加 R3 圓角。」"));
    }

    private void Send()
    {
        if (string.IsNullOrWhiteSpace(InputText)) return;

        Messages.Add(ChatMessage.User(InputText));
        var request = InputText;
        InputText = string.Empty;

        // TODO: Phase 1 — 透過 LLM 產生設計計畫，再轉成受控命令
        Messages.Add(ChatMessage.Assistant(
            $"已收到您的需求：\n{request}\n\n" +
            "（Phase 0 階段：LLM 整合將在後續實作）\n" +
            "目前請透過 CAD Worker API 手動操作。"));
    }

    private void NewProject()
    {
        FeatureTree.Clear();
        Messages.Add(ChatMessage.Assistant("已建立新專案。"));
    }

    private void OpenProject()
    {
        // TODO: Phase 1 — 開啟 .opencad 專案檔
        Messages.Add(ChatMessage.Assistant("（開啟專案功能將在 Phase 1 實作）"));
    }

    private void SaveProject()
    {
        // TODO: Phase 1 — 儲存 .opencad 專案檔
        Messages.Add(ChatMessage.Assistant("（儲存專案功能將在 Phase 1 實作）"));
    }

    private void SetView(string? view)
    {
        if (view is { } v)
        {
            // 透過 WebView 執行 setView(view) JavaScript
            ViewerScriptRequested?.Invoke(ViewerBridge.BuildSetViewScript(v));
            Messages.Add(ChatMessage.Assistant($"切換視角至 {v}"));
        }
    }

    private void Export(string? format)
    {
        if (format is { } f)
            Messages.Add(ChatMessage.Assistant($"匯出 {f.ToUpper()} 格式...（Phase 1 實作）"));
    }

    private void Rebuild()
    {
        Messages.Add(ChatMessage.Assistant("重建模型...（Phase 1 實作）"));
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    protected virtual void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}