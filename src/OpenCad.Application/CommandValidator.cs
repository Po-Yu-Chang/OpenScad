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
            case "create_reference_geometry":
                // WP-S1：與 Python command_validator.py 的 create_reference_geometry 對稱
                if (command.ReferenceGeometry == null)
                    errors.Add("create_reference_geometry 需要 reference_geometry 欄位");
                else
                {
                    if (!command.ReferenceGeometry.ContainsKey("id") || IsEmptyValue(command.ReferenceGeometry["id"]))
                        errors.Add("reference_geometry 需要 id");
                    if (!command.ReferenceGeometry.ContainsKey("kind") || IsEmptyValue(command.ReferenceGeometry["kind"]))
                        errors.Add("reference_geometry 需要 kind");
                    if (!command.ReferenceGeometry.ContainsKey("definition") || command.ReferenceGeometry["definition"] == null)
                        errors.Add("reference_geometry 需要 definition");
                }
                break;
            case "update_reference_geometry":
            case "delete_reference_geometry":
                if (string.IsNullOrWhiteSpace(command.TargetFeatureId))
                    errors.Add($"{command.Action} 需要 target_feature_id");
                if (command.Action == "update_reference_geometry" && command.ReferenceGeometry == null)
                    errors.Add("update_reference_geometry 需要 reference_geometry 欄位");
                break;
            default:
                errors.Add($"未知的 action: {command.Action}");
                break;
        }

        return errors;
    }

    private static bool IsEmptyValue(object? val)
    {
        if (val == null) return true;
        if (val is string s) return string.IsNullOrWhiteSpace(s);
        if (val is System.Text.Json.JsonElement je)
        {
            return je.ValueKind == System.Text.Json.JsonValueKind.Null
                || (je.ValueKind == System.Text.Json.JsonValueKind.String && string.IsNullOrWhiteSpace(je.GetString()));
        }
        return false;
    }

    // WP-S1：與 Python command_validator.py 的 REQUIRES_INPUT 對稱（21 型，sketch 除外）。
    private static readonly HashSet<FeatureType> RequiresInput = new()
    {
        FeatureType.Pad, FeatureType.Revolve, FeatureType.Pocket, FeatureType.Hole,
        FeatureType.Fillet, FeatureType.Chamfer, FeatureType.Shell,
        FeatureType.Sweep, FeatureType.Loft, FeatureType.Mirror,
        FeatureType.LinearPattern, FeatureType.CircularPattern,
        FeatureType.BooleanUnion, FeatureType.BooleanDifference, FeatureType.BooleanIntersection,
        FeatureType.Draft, FeatureType.Rib, FeatureType.Thin, FeatureType.VariableFillet,
        FeatureType.Countersink, FeatureType.CosmeticThread,
    };

    // WP-S1：與 Python REQUIRED_PARAMS 對稱（key 或 key_mm 皆可）。
    private static readonly Dictionary<FeatureType, string[]> RequiredParams = new()
    {
        [FeatureType.Fillet] = new[] { "radius" },
        [FeatureType.Chamfer] = new[] { "radius" },
        [FeatureType.Shell] = new[] { "thickness" },
        [FeatureType.Rib] = new[] { "thickness" },
        [FeatureType.Thin] = new[] { "length", "thickness" },
        [FeatureType.Countersink] = new[] { "diameter" },
    };

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

        // WP-S1：與 Python REQUIRES_INPUT 對稱（21 型皆需要 input，取代原本只列
        // pad/revolve/fillet/chamfer/hole/pocket/shell 共 7 型的窄範圍）。
        if (RequiresInput.Contains(feat.Type))
        {
            if (string.IsNullOrWhiteSpace(feat.Input))
                errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）缺少 input——必須指向上游特徵");
        }

        // hole 必須有 diameter 或 standard_parts（Python 特例，非泛用 RequiredParams）
        if (feat.Type == FeatureType.Hole)
        {
            if (!feat.Parameters.ContainsKey("diameter") && !feat.Parameters.ContainsKey("diameter_mm")
                && feat.StandardParts.Count == 0)
                errors.Add($"特徵 {feat.FeatureId}（hole）缺少 diameter 或 standard_parts");
        }

        // pocket 必須有 references（指向草圖輪廓）
        if (feat.Type == FeatureType.Pocket)
        {
            if (feat.References.Count == 0)
                errors.Add($"特徵 {feat.FeatureId}（pocket）缺少 references——必須指向草圖輪廓");
        }

        // WP-S1：與 Python REQUIRED_PARAMS 對稱（fillet/chamfer/shell/rib/thin/countersink）
        if (RequiredParams.TryGetValue(feat.Type, out var requiredKeys))
        {
            foreach (var key in requiredKeys)
            {
                if (!feat.Parameters.ContainsKey(key) && !feat.Parameters.ContainsKey($"{key}_mm"))
                    errors.Add($"特徵 {feat.FeatureId}（{feat.Type}）缺少 {key} 參數");
            }
        }

        // WP-S1：與 Python 對稱——數值正負檢查不分特徵型別，凡有這些鍵就檢查
        // （取代原本只在特定型別才檢查 radius/thickness/diameter/length 的窄範圍）。
        foreach (var (key, mmKey) in new[]
        {
            ("radius", "radius_mm"), ("thickness", "thickness_mm"),
            ("diameter", "diameter_mm"), ("length", "length_mm"),
        })
        {
            var val = GetNumericParam(feat, key, mmKey);
            if (val.HasValue && val.Value <= 0)
                errors.Add($"特徵 {feat.FeatureId} {key} 必須 > 0，得到 {val.Value}");
        }

        // 驗證 plane 格式（含 datum:<id> 引用——WP-S1 對齊 Python，LLM prompt 已在教
        // 模型輸出 datum:<id> 形式，C# 原本只認 XY/XZ/YZ 會誤擋合法命令）
        if (feat.Type == FeatureType.Sketch)
        {
            if (feat.Plane != null && feat.Plane.ContainsKey("base"))
            {
                var baseVal = feat.Plane["base"]?.ToString()?.ToUpperInvariant() ?? "";
                var isDatumRef = baseVal.StartsWith("DATUM:") && baseVal.Length > 6;
                if (baseVal is not ("XY" or "XZ" or "YZ") && !isDatumRef)
                    errors.Add($"特徵 {feat.FeatureId} plane.base 必須為 XY、XZ、YZ 或 datum:id，得到：{baseVal}");
            }
        }
    }

    private static void ValidateUpdateFeature(CadCommand command, List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(command.TargetFeatureId))
            errors.Add("update_feature 需要 target_feature_id");

        // WP-S1 修復：Python 已放行只帶 constraints 的更新，C# 原本沒檢查
        // Constraints，會把「只改 constraints」的合法更新誤判為缺欄位。
        if (command.Parameters == null && command.StandardParts == null &&
            command.SketchEntities == null && command.Plane == null &&
            command.Constraints == null)
            errors.Add("update_feature 需要 parameters、standard_parts、sketch_entities、plane 或 constraints 至少一項");
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