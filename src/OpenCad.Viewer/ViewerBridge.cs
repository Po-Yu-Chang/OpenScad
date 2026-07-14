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
        SketchSolve,
        DatumPlaneClicked,
        FaceSelected,
        MeasurementResult,
    }

    public record ViewerMessage(
        MessageType Type,
        string? ObjectId = null,
        string? ErrorMessage = null,
        string? FeatureId = null,
        string? EntitiesJson = null,
        string? ConstraintsJson = null,
        string? DatumPlaneName = null,
        string? BrepFaceRef = null,
        string? SourceFeatureId = null,
        double[]? Centroid = null,
        int MeshRevision = 0,
        string? MeasurementType = null,
        double MeasurementValue = 0,
        string? MeasurementUnit = null,
        string? MeasurementDescription = null);

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
                "sketch_solve" => MessageType.SketchSolve,
                "datum_plane_clicked" => MessageType.DatumPlaneClicked,
                "face_selected" => MessageType.FaceSelected,
                "measurement_result" => MessageType.MeasurementResult,
                _ => (MessageType?)null,
            };

            if (type is null) return null;

            string? objectId = type == MessageType.Selection
                ? element.TryGetProperty("object", out var obj) ? obj.GetString() : null
                : null;

            string? errorMsg = type == MessageType.Error
                ? element.TryGetProperty("message", out var msg) ? msg.GetString() : null
                : null;

            string? featureId = (type == MessageType.SketchCommitted || type == MessageType.SketchSolve)
                ? element.TryGetProperty("feature_id", out var fid) ? fid.GetString() : null
                : null;

            string? entitiesJson = (type == MessageType.SketchCommitted || type == MessageType.SketchSolve)
                ? element.TryGetProperty("entities", out var ents) ? ents.GetRawText() : null
                : null;

            string? constraintsJson = (type == MessageType.SketchCommitted || type == MessageType.SketchSolve)
                ? element.TryGetProperty("constraints", out var cons) ? cons.GetRawText() : null
                : null;

            string? datumPlaneName = type == MessageType.DatumPlaneClicked
                ? element.TryGetProperty("name", out var dname) ? dname.GetString() : null
                : null;

            string? brepFaceRef = type == MessageType.FaceSelected
                ? element.TryGetProperty("brep_face_ref", out var bfr) ? bfr.GetString() : null
                : null;

            string? sourceFeatureId = type == MessageType.FaceSelected
                ? element.TryGetProperty("source_feature_id", out var sfi) ? sfi.GetString() : null
                : null;

            int meshRevision = type == MessageType.FaceSelected
                ? element.TryGetProperty("mesh_revision", out var mrev) ? mrev.GetInt32() : 0
                : 0;

            // WP-S1：datum 平面「真選面」需要點選面的質心座標
            double[]? centroid = null;
            if (type == MessageType.FaceSelected &&
                element.TryGetProperty("centroid", out var centroidEl) &&
                centroidEl.ValueKind == JsonValueKind.Array)
            {
                var vals = new List<double>();
                foreach (var item in centroidEl.EnumerateArray())
                    vals.Add(item.GetDouble());
                if (vals.Count == 3) centroid = vals.ToArray();
            }

            string? measurementType = null;
            double measurementValue = 0;
            string? measurementUnit = null;
            string? measurementDescription = null;
            if (type == MessageType.MeasurementResult)
            {
                measurementType = element.TryGetProperty("measurement_type", out var mt) ? mt.GetString() : null;
                // value 由 JS 以字串（toFixed）或數值送出——兩種都接受
                if (element.TryGetProperty("value", out var mv))
                {
                    if (mv.ValueKind == JsonValueKind.Number) measurementValue = mv.GetDouble();
                    else if (mv.ValueKind == JsonValueKind.String && double.TryParse(mv.GetString(), out var parsed)) measurementValue = parsed;
                }
                measurementUnit = element.TryGetProperty("unit", out var mu) ? mu.GetString() : null;
                measurementDescription = element.TryGetProperty("description", out var md) ? md.GetString() : null;
            }

            return new ViewerMessage(type.Value, objectId, errorMsg, featureId, entitiesJson, constraintsJson, datumPlaneName, brepFaceRef, sourceFeatureId, centroid, meshRevision,
                measurementType, measurementValue, measurementUnit, measurementDescription);
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
    /// 建構載入模型 + display_map 的 JavaScript 呼叫字串。
    /// display_map 提供面/邊拓撲對應表，供 viewer 精確 picking。
    /// </summary>
    public static string BuildLoadScript(string glbUrl, string displayMapUrl) =>
        $"loadModelWithMap('{glbUrl}', '{displayMapUrl}');";

    /// <summary>
    /// 建構切換視角的 JavaScript 呼叫字串。
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

    /// <summary>
    /// 建構將求解器結果送回 viewer 的 JavaScript 呼叫字串（WP1-2）。
    /// </summary>
    public static string BuildSolverResultScript(string resultJson) =>
        $"opencadSolverResult({resultJson});";
}