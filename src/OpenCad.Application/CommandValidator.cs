using OpenCad.Domain;

namespace OpenCad.Application;

/// <summary>
/// 本地命令驗證器——在送出 Worker 前攔截格式錯誤的命令。
/// 驗證規則與 Python 端一致，但提前在 C# 端攔截可避免網路往返。
/// </summary>
public static class CommandValidator
{
    /// <summary>
    /// 驗證 CadCommand，回傳錯誤訊息列表。空列表表示通過。
    /// </summary>
    public static List<string> Validate(CadCommand command)
    {
        var errors = new List<string>();

        if (string.IsNullOrWhiteSpace(command.Action))
        {
            errors.Add("action 不得為空");
            return errors;
        }

        switch (command.Action)
        {
            case "create_feature":
                ValidateCreateFeature(command, errors);
                break;
            case "update_feature":
                ValidateUpdateFeature(command, errors);
                break;
            case "delete_feature":
            case "delete_feature_recursive":
                if (string.IsNullOrWhiteSpace(command.TargetFeatureId))
                    errors.Add($"{command.Action} 需要 target_feature_id");
                break;
            case "suppress_feature":
            case "unsuppress_feature":
                if (string.IsNullOrWhiteSpace(command.TargetFeatureId))
                    errors.Add($"{command.Action} 需要 target_feature_id");
                break;
            case "reorder_feature":
                if (string.IsNullOrWhiteSpace(command.TargetFeatureId))
                    errors.Add("reorder_feature 需要 target_feature_id");
                if (command.Parameters == null || !command.Parameters.ContainsKey("new_order"))
                    errors.Add("reorder_feature 需要 parameters.new_order");
                break;
            case "set_rollback":
                if (command.Parameters == null || !command.Parameters.ContainsKey("rollback_position"))
                    errors.Add("set_rollback 需要 parameters.rollback_position（null 或整數）");
                break;
            case "rebuild":
            case "validate":
            case "export":
            case "set_material":
                // 這些 action 不需要特徵驗證
                break;
            default:
                errors.Add($"未知的 action: {command.Action}");
                break;
        }

        return errors;
    }

    private static void ValidateCreateFeature(CadCommand command, List<string> errors)
    {
        if (command.Feature == null)
        {
            errors.Add("create_feature 需要 feature 欄位");
            return;
        }

        var feat = command.Feature;

        if (string.IsNullOrWhiteSpace(feat.FeatureId))
            errors.Add("feature.feature_id 不得為空");

        if (string.IsNullOrWhiteSpace(feat.Name))
            errors.Add($"特徵 {feat.FeatureId} 缺少 name");

        // sketch 必須有 sketch_entities
        if (feat.Type == FeatureType.Sketch)
        {
            if (feat.SketchEntities == null || feat.SketchEntities.Count == 0)
                errors.Add($"特徵 {feat.FeatureId}（sketch）缺少 sketch_entities——空草圖會導致 pad 失敗");
        }

        // pad/revolve 必須有 input（指向 sketch）
        if (feat.Type is FeatureType.Pad or FeatureType.Revolve)
        {
            if (string.IsNullOrWhiteSpace(feat.Input))
                errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）缺少 input——必須指向上游 sketch");
        }

        // fillet/chamfer 必須有 input 和 radius
        if (feat.Type is FeatureType.Fillet or FeatureType.Chamfer)
        {
            if (string.IsNullOrWhiteSpace(feat.Input))
                errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）缺少 input——必須指向上游實體");
            if (!feat.Parameters.ContainsKey("radius") && !feat.Parameters.ContainsKey("radius_mm"))
                errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）缺少 radius 參數");
        }

        // hole 必須有 input 和 diameter
        if (feat.Type == FeatureType.Hole)
        {
            if (string.IsNullOrWhiteSpace(feat.Input))
                errors.Add($"特徵 {feat.FeatureId}（hole）缺少 input——必須指向上游實體");
            if (!feat.Parameters.ContainsKey("diameter") && !feat.Parameters.ContainsKey("diameter_mm")
                && feat.StandardParts.Count == 0)
                errors.Add($"特徵 {feat.FeatureId}（hole）缺少 diameter 或 standard_parts");
        }

        // pocket 必須有 input（指向實體）和 references（指向草圖）
        if (feat.Type == FeatureType.Pocket)
        {
            if (string.IsNullOrWhiteSpace(feat.Input))
                errors.Add($"特徵 {feat.FeatureId}（pocket）缺少 input——必須指向上游實體");
            if (feat.References.Count == 0)
                errors.Add($"特徵 {feat.FeatureId}（pocket）缺少 references——必須指向草圖輪廓");
        }

        // shell 必須有 input 和 thickness
        if (feat.Type == FeatureType.Shell)
        {
            if (string.IsNullOrWhiteSpace(feat.Input))
                errors.Add($"特徵 {feat.FeatureId}（shell）缺少 input——必須指向上游實體");
            if (!feat.Parameters.ContainsKey("thickness") && !feat.Parameters.ContainsKey("thickness_mm"))
                errors.Add($"特徵 {feat.FeatureId}（shell）缺少 thickness 參數");
        }

        // 驗證 radius/thickness 正值
        if (feat.Type is FeatureType.Fillet or FeatureType.Chamfer)
        {
            var radius = GetNumericParam(feat, "radius", "radius_mm");
            if (radius.HasValue && radius.Value <= 0)
                errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）radius 必須 > 0");
        }

        if (feat.Type == FeatureType.Shell)
        {
            var thickness = GetNumericParam(feat, "thickness", "thickness_mm");
            if (thickness.HasValue && thickness.Value <= 0)
                errors.Add($"特徵 {feat.FeatureId}（shell）thickness 必須 > 0");
        }

        // 驗證 hole diameter 正值
        if (feat.Type == FeatureType.Hole)
        {
            var diameter = GetNumericParam(feat, "diameter", "diameter_mm");
            if (diameter.HasValue && diameter.Value <= 0)
                errors.Add($"特徵 {feat.FeatureId}（hole）diameter 必須 > 0");
        }

        // 驗證 pad/revolve length 正值
        if (feat.Type is FeatureType.Pad or FeatureType.Revolve)
        {
            var length = GetNumericParam(feat, "length", "length_mm");
            if (length.HasValue && length.Value <= 0)
                errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）length 必須 > 0");
        }

        // 驗證 plane 格式
        if (feat.Type == FeatureType.Sketch)
        {
            if (feat.Plane != null && feat.Plane.ContainsKey("base"))
            {
                var baseVal = feat.Plane["base"]?.ToString()?.ToUpperInvariant();
                if (baseVal is not ("XY" or "XZ" or "YZ"))
                    errors.Add($"特徵 {feat.FeatureId} plane.base 必須為 XY、XZ 或 YZ，得到：{baseVal}");
            }
        }
    }

    private static void ValidateUpdateFeature(CadCommand command, List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(command.TargetFeatureId))
            errors.Add("update_feature 需要 target_feature_id");

        if (command.Parameters == null && command.StandardParts == null &&
            command.SketchEntities == null && command.Plane == null)
            errors.Add("update_feature 需要 parameters、standard_parts、sketch_entities 或 plane 至少一項");
    }

    /// <summary>
    /// 從參數取得數值，容忍 _mm 後綴。
    /// </summary>
    private static double? GetNumericParam(Feature feat, params string[] keys)
    {
        foreach (var key in keys)
        {
            if (feat.Parameters.TryGetValue(key, out var val))
            {
                if (val is double d) return d;
                if (val is int i) return i;
                if (val is System.Text.Json.JsonElement je)
                {
                    if (je.ValueKind == System.Text.Json.JsonValueKind.Number)
                        return je.GetDouble();
                }
            }
        }
        return null;
    }
}