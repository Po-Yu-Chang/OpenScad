using System.Collections.ObjectModel;

namespace OpenCad.Desktop.ViewModels;

/// <summary>
/// 對話訊息模型。
/// </summary>
public class ChatMessage
{
    public string Text { get; set; } = string.Empty;
    public string BackgroundColor { get; set; } = "#313244";
    public bool IsUser { get; set; }

    public static ChatMessage User(string text) => new()
    {
        Text = text,
        BackgroundColor = "#45475a",
        IsUser = true,
    };

    public static ChatMessage Assistant(string text) => new()
    {
        Text = text,
        BackgroundColor = "#313244",
        IsUser = false,
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
    public ObservableCollection<FeatureNode> Children { get; set; } = new();
}