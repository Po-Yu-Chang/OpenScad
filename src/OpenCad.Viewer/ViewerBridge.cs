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
        SketchCommitted,
        SketchCancelled,
        DatumPlaneClicked,
    }

    public record ViewerMessage(
        MessageType Type,
        string? ObjectId = null,
        string? ErrorMessage = null,
        string? FeatureId = null,
        string? EntitiesJson = null,
        string? DatumPlaneName = null);

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
                "sketch_committed" => MessageType.SketchCommitted,
                "sketch_cancelled" => MessageType.SketchCancelled,
                "datum_plane_clicked" => MessageType.DatumPlaneClicked,
                _ => (MessageType?)null,
            };

            if (type is null) return null;

            string? objectId = type == MessageType.Selection
                ? element.TryGetProperty("object", out var obj) ? obj.GetString() : null
                : null;

            string? errorMsg = type == MessageType.Error
                ? element.TryGetProperty("message", out var msg) ? msg.GetString() : null
                : null;

            string? featureId = type == MessageType.SketchCommitted
                ? element.TryGetProperty("feature_id", out var fid) ? fid.GetString() : null
                : null;

            string? entitiesJson = type == MessageType.SketchCommitted
                ? element.TryGetProperty("entities", out var ents) ? ents.GetRawText() : null
                : null;

            string? datumPlaneName = type == MessageType.DatumPlaneClicked
                ? element.TryGetProperty("name", out var dname) ? dname.GetString() : null
                : null;

            return new ViewerMessage(type.Value, objectId, errorMsg, featureId, entitiesJson, datumPlaneName);
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

    /// <summary>
    /// 建構進入草圖模式的 JavaScript 呼叫字串。
    /// </summary>
    public static string BuildEnterSketchScript(string featureId, string entitiesJson, string? planeJson = null) =>
        planeJson != null
            ? $"enterSketchMode('{featureId}', {entitiesJson}, {planeJson});"
            : $"enterSketchMode('{featureId}', {entitiesJson});";

    /// <summary>
    /// 建構離開草圖模式的 JavaScript 呼叫字串。
    /// </summary>
    public static string BuildExitSketchScript() =>
        "exitSketchMode();";
}