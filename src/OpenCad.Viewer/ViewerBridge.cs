using System.Text.Json;

namespace OpenCad.Viewer;

/// <summary>
/// WebView 與 Three.js 之間的訊息橋接。
/// WebView 宿主依平台不同：WebView2（Windows）／WKWebView（macOS）／WebKitGTK（Linux）。
/// 前端 Three.js 程式碼三平台共用。
/// </summary>
public class ViewerBridge
{
    /// <summary>
    /// 訊息事件類型。
    /// </summary>
    public enum MessageType
    {
        Loaded,
        Selection,
        Error,
    }

    public record ViewerMessage(MessageType Type, string? ObjectId = null, string? ErrorMessage = null);

    /// <summary>
    /// 解析來自 WebView 的訊息。
    /// </summary>
    public static ViewerMessage? ParseMessage(string json)
    {
        try
        {
            var element = JsonSerializer.Deserialize<JsonElement>(json);
            var typeStr = element.GetProperty("type").GetString();

            var type = typeStr switch
            {
                "loaded" => MessageType.Loaded,
                "selection" => MessageType.Selection,
                "error" => MessageType.Error,
                _ => (MessageType?)null,
            };

            if (type is null) return null;

            string? objectId = type == MessageType.Selection
                ? element.TryGetProperty("object", out var obj) ? obj.GetString() : null
                : null;

            string? errorMsg = type == MessageType.Error
                ? element.TryGetProperty("message", out var msg) ? msg.GetString() : null
                : null;

            return new ViewerMessage(type.Value, objectId, errorMsg);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// 建構載入模型的 JavaScript 呼叫字串。
    /// </summary>
    public static string BuildLoadScript(string glbUrl) =>
        $"loadModel('{glbUrl}');";

    /// <summary>
    /// �構構切換視角的 JavaScript 呼叫字串。
    /// </summary>
    public static string BuildSetViewScript(string view) =>
        $"setView('{view}');";

    /// <summary>
    /// 建構清除高亮的 JavaScript 呼叫字串。
    /// </summary>
    public static string BuildClearHighlightScript() =>
        "clearHighlight();";
}