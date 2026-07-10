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
/// 特徵參數項——用於參數面板顯示。
/// </summary>
public class ParameterItem
{
    public string Key { get; set; } = string.Empty;
    public string Value { get; set; } = string.Empty;
}