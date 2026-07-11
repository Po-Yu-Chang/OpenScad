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
public class ChatMessage : System.ComponentModel.INotifyPropertyChanged
{
    public string Text { get; set; } = string.Empty;
    public MessageKind Kind { get; set; } = MessageKind.Assistant;
    public DesignPlan? Plan { get; set; }
    public ICommand? ApplyPlanCommand { get; set; }
    public ICommand? CancelPlanCommand { get; set; }
    public ModificationDiff? Diff { get; set; }
    public ICommand? ApplyDiffCommand { get; set; }
    public ICommand? CancelDiffCommand { get; set; }

    private bool _isActionable = true;

    /// <summary>
    /// 卡片按鈕是否可操作——套用或取消後設為 false（一次性），
    /// 防止重複點擊造成命令被執行多次。
    /// </summary>
    public bool IsActionable
    {
        get => _isActionable;
        set
        {
            _isActionable = value;
            PropertyChanged?.Invoke(this,
                new System.ComponentModel.PropertyChangedEventArgs(nameof(IsActionable)));
        }
    }

    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;

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
    public bool IsDatumPlane { get; set; } = false;
    public string? PlaneBase { get; set; } = null;
    /// <summary>WP1-3: 基準幾何節點的原始 id——非 null 即為 reference geometry 節點（取代 __rg_ 前綴字串解析）。</summary>
    public string? ReferenceGeometryId { get; set; } = null;
    public int Order { get; set; } = 0;
    public string State { get; set; } = "active";  // active / suppressed / failed / orphan
    public bool IsSuppressed => State == "suppressed";
    public bool IsFailed => State == "failed";
    public bool IsOrphan => State == "orphan";
    public string TypeIcon => FeatureType switch
    {
        "sketch" => "▭",
        "pad" => "⬒",
        "pocket" => "⬓",
        "hole" => "○",
        "fillet" => "◠",
        "chamfer" => "◢",
        "linear_pattern" => "⊞",
        "circular_pattern" => "⊛",
        "datum_plane" => "▱",
        "datum_axis" => "─",
        "datum_point" => "•",
        "folder" => "📁",
        "origin" => "✛",
        _ => "▸",
    };
    public string StateIcon => State switch
    {
        "suppressed" => "⊘",  // suppressed — gray
        "failed" => "✗",      // failed — red
        "orphan" => "⚠",      // orphan — orange
        _ => "",              // active — no icon
    };
    public string StateColor => State switch
    {
        "suppressed" => "Gray",
        "failed" => "Red",
        "orphan" => "Orange",
        _ => "Transparent",
    };
    public List<ParameterItem> Parameters { get; set; } = new();
    public ObservableCollection<FeatureNode> Children { get; set; } = new();
}

/// <summary>
/// 特徵參數項——用於參數面板顯示與編輯（WP1-4 型別化控件）。
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

    /// <summary>WP1-4: 參數型別——決定控件類型。</summary>
    public ParameterType ParamType { get; set; } = ParameterType.Number;

    /// <summary>WP1-4: 單位（mm, deg, 等）。</summary>
    public string? Unit { get; set; }

    /// <summary>WP1-4: 下拉選項（ParamType == Dropdown 時使用）。</summary>
    public List<string>? DropdownOptions { get; set; }

    /// <summary>WP1-4: 參照選取器提示文字（ParamType == Reference 時使用）。</summary>
    public string? ReferenceHint { get; set; }

    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(name));
}

/// <summary>
/// WP1-4: 參數型別——決定 Property Manager 中的控件類型。
/// </summary>
public enum ParameterType
{
    /// <summary>數值＋單位（如 10mm, 30deg）</summary>
    Number,
    /// <summary>下拉選單（如 edges: all/top/bottom）</summary>
    Dropdown,
    /// <summary>布林勾選（如 through_all）</summary>
    Checkbox,
    /// <summary>參照選取器（如 input 指向特徵 ID）</summary>
    Reference,
    /// <summary>唯讀文字（如 feature_id）</summary>
    ReadOnly,
}

/// <summary>
/// WP1-4: 選取過濾器——控制 raycast 僅命中指定類型。
/// </summary>
public enum SelectionFilter
{
    All,
    Face,
    Edge,
    Vertex,
}

/// <summary>
/// WP1-4: 顯示模式。
/// </summary>
public enum DisplayMode
{
    Shaded,
    ShadedWithEdges,
    Wireframe,
    Transparent,
}

/// <summary>
/// WP1-4: 量測結果。
/// </summary>
public class MeasurementResult
{
    public string Type { get; set; } = "";  // distance, angle, radius
    public double Value { get; set; }
    public string Unit { get; set; } = "mm";
    public string Description { get; set; } = "";
}