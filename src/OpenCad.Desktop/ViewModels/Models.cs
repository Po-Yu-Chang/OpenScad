using System.Collections.ObjectModel;
using System.Windows.Input;
using OpenCad.Domain;

namespace OpenCad.Desktop.ViewModels;

/// <summary>
/// 訊息種類——決定 UI 呈現樣式（顏色、對齊、邊框）。
/// </summary>
public enum MessageKind
{
    User,
    Assistant,
    Error,
    Plan,
    Diff,
}

/// <summary>
/// 對話訊息模型。
/// </summary>
public class ChatMessage
{
    public string Text { get; set; } = string.Empty;
    public MessageKind Kind { get; set; } = MessageKind.Assistant;
    public DesignPlan? Plan { get; set; }
    public ICommand? ApplyPlanCommand { get; set; }
    public ICommand? CancelPlanCommand { get; set; }
    public ModificationDiff? Diff { get; set; }
    public ICommand? ApplyDiffCommand { get; set; }
    public ICommand? CancelDiffCommand { get; set; }

    public static ChatMessage User(string text) => new()
    {
        Text = text,
        Kind = MessageKind.User,
    };

    public static ChatMessage Assistant(string text) => new()
    {
        Text = text,
        Kind = MessageKind.Assistant,
    };

    public static ChatMessage Error(string text) => new()
    {
        Text = text,
        Kind = MessageKind.Error,
    };

    public static ChatMessage FromPlan(DesignPlan plan, ICommand? applyCmd = null, ICommand? cancelCmd = null) => new()
    {
        Text = plan.Summary,
        Kind = MessageKind.Plan,
        Plan = plan,
        ApplyPlanCommand = applyCmd,
        CancelPlanCommand = cancelCmd,
    };

    public static ChatMessage FromDiff(ModificationDiff diff, ICommand? applyCmd = null, ICommand? cancelCmd = null) => new()
    {
        Text = diff.Description,
        Kind = MessageKind.Diff,
        Diff = diff,
        ApplyDiffCommand = applyCmd,
        CancelDiffCommand = cancelCmd,
    };
}

/// <summary>
/// 特徵樹節點模型。
/// </summary>
public class FeatureNode
{
    public string FeatureId { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string FeatureType { get; set; } = string.Empty;
    public List<ParameterItem> Parameters { get; set; } = new();
    public ObservableCollection<FeatureNode> Children { get; set; } = new();
}

/// <summary>
/// 特徵參數項——用於參數面板顯示與編輯。
/// 編輯後透過 ApplyCommand 走與 LLM 相同的 update_feature 命令路徑。
/// </summary>
public class ParameterItem : System.ComponentModel.INotifyPropertyChanged
{
    private string _value = string.Empty;

    public string Key { get; set; } = string.Empty;

    public string Value
    {
        get => _value;
        set
        {
            _value = value;
            OnPropertyChanged(nameof(Value));
            OnPropertyChanged(nameof(IsDirty));
        }
    }

    /// <summary>編輯前的原始值——用於判斷是否有未套用的變更。</summary>
    public string OriginalValue { get; set; } = string.Empty;

    public bool IsEditable { get; set; } = true;

    /// <summary>有未套用的編輯時為 true（顯示套用按鈕）。</summary>
    public bool IsDirty => IsEditable && Value != OriginalValue;

    /// <summary>套用此參數變更（發 update_feature 命令並重建）。</summary>
    public ICommand? ApplyCommand { get; set; }

    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(name));
}