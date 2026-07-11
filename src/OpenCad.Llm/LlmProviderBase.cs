using System.Text.Json;
using OpenCad.Application;
using OpenCad.Domain;

namespace OpenCad.Llm;

/// <summary>
/// LLM 提供者共用基底——提示詞與 Schema 集中於此，
/// 各提供者（Ollama／OpenAI-compatible）只實作傳輸層 SendStructuredAsync。
/// </summary>
public abstract class LlmProviderBase : ILlmProvider
{
    protected static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>
    /// 引擎支援的 create_feature 型別——唯一真相。
    /// 須與 schemas/feature.schema.json 的 type enum、Domain.FeatureType、
    /// build123d 適配器的 _build_* 方法一致。datum 為 reference geometry，不屬 create_feature 型別，故不列於此。
    /// </summary>
    public static readonly string[] EngineSupportedFeatureTypes =
    {
        "sketch", "pad", "pocket", "revolve", "sweep", "loft", "hole",
        "linear_pattern", "circular_pattern", "mirror", "fillet", "chamfer", "shell",
        "boolean_union", "boolean_difference", "boolean_intersection",
        "draft", "rib", "thin", "variable_fillet", "countersink", "cosmetic_thread",
    };

    /// <summary>
    /// 引擎不支援的功能（拒絕規則）——唯一真相。
    /// 須與 cad-worker server.py /api/capability 的 unsupported_features 一致。
    /// </summary>
    public static readonly string[] EngineUnsupportedFeatures =
    {
        "thread", "knit", "trim_surface", "thicken", "delete_face", "helical_gear",
    };

    /// <summary>JSON schema enum 內容片段——"a","b",...（不含中括號），供提示詞內嵌 schema 使用。</summary>
    private static readonly string SupportedFeatureTypesJson =
        string.Join(",", EngineSupportedFeatureTypes.Select(t => $"\"{t}\""));

    /// <summary>不支援清單的可讀文字，供提示詞內嵌。</summary>
    private static readonly string UnsupportedFeaturesText = string.Join("、", EngineUnsupportedFeatures);

    /// <summary>
    /// LLM 可輸出的命令 action——唯一真相，供修改流程與修復流程 schema 共用（避免三份 schema 漂移）。
    /// </summary>
    public static readonly string[] EngineCommandActions =
    {
        "create_feature", "update_feature", "delete_feature", "set_material", "rebuild",
    };

    private static readonly string CommandActionsJson =
        string.Join(",", EngineCommandActions.Select(a => $"\"{a}\""));

    private static string Snippet(string s) => s.Length > 300 ? s[..300] + "…" : s;

    /// <summary>
    /// 反序列化 LLM 回傳的 JSON；失敗時拋出含原始片段的可讀錯誤（取代靜默 null 造成的難解例外）。
    /// </summary>
    protected static T DeserializeOrThrow<T>(string json) where T : new()
    {
        try
        {
            return JsonSerializer.Deserialize<T>(json, JsonOpts) ?? new T();
        }
        catch (JsonException ex)
        {
            throw new InvalidOperationException(
                $"LLM 回傳的 JSON 無法解析（{ex.Message}）。原始內容：{Snippet(json)}");
        }
    }

    /// <summary>
    /// 送出提示詞並取得符合 schema 的 JSON 字串。由各提供者實作傳輸細節。
    /// </summary>
    protected abstract Task<string> SendStructuredAsync(string prompt, string schema, List<ChatTurn>? history = null);

    public async Task<DesignPlan> CreatePlanAsync(DesignContext context)
    {
        // WP-H1: Capability payload — 從 schema 程式生成 feature catalog
        var capability = await GetCapabilityPayloadAsync();
        var userPrompt = $@"
=== CAPABILITY PAYLOAD (WP-H1) ===
schema_version: {capability.SchemaVersion}
engine_version: {capability.EngineVersion}
支援 feature catalog: {capability.FeatureCatalogJson}
不支援功能（拒絕規則）: {string.Join(", ", capability.UnsupportedFeatures)}

=== 使用者需求 ===
{context.UserRequest}

請將此需求拆解成建模步驟。每個步驟描述要建立的特徵類型和參數。
拆解規則：
- 每個 pad/revolve 之前必須有一個 sketch 步驟提供輪廓（sketch_entities 放在 sketch 步驟，不要放在 pad 上）。
- 平面尺寸（長×寬）由 sketch 的 rectangle width/height 表達；pad.parameters 只放拉伸距離，參數名固定為 length（mm）。
  例如 10×8×5 長方體 = sketch(rectangle width 10, height 8) + pad(length 5)。
- 草圖座標以基準面原點為中心：rectangle 以 center_x/center_y 定位（置中於原點時可省略），circle 用 center_x/center_y。
  例如 10×8 置中底板＋中心貫穿孔：rectangle 不需座標、circle 的 center_x/center_y 都是 0。
- 挖除（pocket）同樣需要前置 sketch 步驟提供輪廓；pocket.parameters 用 through_all: true（貫穿）或 depth（盲孔深度 mm），兩者擇一必填。
- hole 特徵不需要 sketch 步驟，直接在 parameters 中指定 diameter、through_all、positions。
- sketch 步驟的 sketch_entities 必須填入實際的草圖幾何，不能留空。
  例如「10mm x 5mm 矩形草圖」的 sketch_entities 必須是：
  [{{""type"":""rectangle"",""width"":10,""height"":5,""center_x"":0,""center_y"":0}}]
  例如「半徑 3mm 圓」的 sketch_entities 必須是：
  [{{""type"":""circle"",""radius"":3,""center_x"":0,""center_y"":0}}]
- WP1-3 基準幾何：需要 datum plane 時，使用 feature_type=""datum_plane""，parameters 含 method（offset/angle_between/mid_plane）、source_ref（如 ""face:f1.top""）、offset_mm 或 angle_deg。
  datum_plane 可作為後續 sketch 的草圖平面——plane.base 設為 ""datum:<datum_id>""（如 ""datum:datum_plane_1""）。
  datum_axis 用 feature_type=""datum_axis""，parameters 含 method（intersection/cylinder_axis）、source_ref、source_ref_2。
  datum_point 用 feature_type=""datum_point""，parameters 含 method（vertex/center）、source_ref。
如果需求中有缺少或矛盾的條件，請在 missing_info 中列出。
回傳 JSON 格式的設計計畫。";

        var planSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""steps"": { ""type"": ""array"", ""items"": { ""type"": ""object"",
      ""properties"": {
        ""description"": { ""type"": ""string"" },
        ""feature_type"": { ""type"": ""string"", ""enum"": [""sketch"",""pad"",""pocket"",""hole"",""linear_pattern"",""circular_pattern"",""mirror"",""fillet"",""chamfer"",""shell"",""revolve"",""sweep"",""loft"",""boolean_union"",""boolean_difference"",""boolean_intersection"",""draft"",""rib"",""thin"",""variable_fillet"",""countersink"",""cosmetic_thread"",""datum_plane"",""datum_axis"",""datum_point""] },
        ""parameters"": { ""type"": ""object"" },
        ""sketch_entities"": { ""type"": ""array"", ""items"": { ""type"": ""object"" } },
        ""constraints"": { ""type"": ""array"", ""items"": { ""type"": ""object"" }, ""description"": ""草圖約束（WP1-2）。每個約束含 id, type, targets, value_mm/value_deg, name"" },
        ""standard_parts"": { ""type"": ""object"" },
        ""plane"": { ""type"": ""object"", ""properties"": { ""base"": { ""type"": ""string"", ""enum"": [""XY"",""XZ"",""YZ""] }, ""offset"": { ""type"": ""number"" } }, ""required"": [""base""] }
      }, ""required"": [""description"",""feature_type"",""parameters""] } },
    ""summary"": { ""type"": ""string"" },
    ""warnings"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } },
    ""missing_info"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } }
  },
  ""required"": [""steps"",""summary""]
}";

        var result = await SendStructuredAsync(userPrompt, planSchema, context.History);
        return DeserializeOrThrow<DesignPlan>(result);
    }

    public async Task<UpdateCommandBatch> CreateUpdateCommandAsync(string userRequest, string featureGraphJson, List<ChatTurn>? history = null)
    {
        // WP-H1: Capability payload
        var capability = await GetCapabilityPayloadAsync();
        var userPrompt = $@"
=== CAPABILITY PAYLOAD (WP-H1) ===
schema_version: {capability.SchemaVersion}
engine_version: {capability.EngineVersion}
支援 feature catalog: {capability.FeatureCatalogJson}
不支援功能（拒絕規則）: {string.Join(", ", capability.UnsupportedFeatures)}
可用工具: {string.Join(", ", capability.Tools)}

=== 使用者修改需求 ===
{userRequest}

=== 目前 Feature Graph（JSON） ===
{featureGraphJson}

請根據使用者需求，產生一個或多個命令，放入 commands 陣列（依執行順序）。
一句話含多個動作時（如「挖四個孔並倒角」＝先 hole 再 fillet），要拆成多個命令依序放入 commands，不可只做其中一個。
每個命令的類型判斷如下：
- 修改既有特徵的參數 → action=update_feature，指定 target_feature_id。
- 新增特徵（圓角 fillet、倒角 chamfer、挖孔 hole/pocket、薄殼 shell、鏡射 mirror、迴轉 revolve、掃掠 sweep、放樣 loft、
  拔模 draft、補強肋 rib、薄件 thin、變半徑圓角 variable_fillet、沉頭孔 countersink、裝飾螺紋 cosmetic_thread、
  陣列 linear_pattern/circular_pattern、布林 boolean_union/boolean_difference/boolean_intersection 等）→ action=create_feature，
  在 feature 中給定：feature_id（新的唯一 ID，如 fillet_1）、type、input（要加工的實體特徵 ID，如最後一個 pad）、parameters。
- 刪除既有特徵 → action=delete_feature，指定 target_feature_id。
  如果使用者說「刪掉最後的圓角」「取消倒角」「把 pocket_1 刪掉」等，用 delete_feature 而非 update_feature。
- 變更材質 → action=set_material，parameters 中指定 material（如 pla/abs/aluminum/steel/stainless_steel/brass/copper）。
- 重建模型 → action=rebuild。

各特徵參數說明：
- fillet：radius(mm)、edges(預設 all；可選 all_vertical/all_horizontal/top/bottom)。
  重要：使用者說「通孔不要動」「孔不要動」「不要影響孔」時，必須在 parameters 中加入 exclude_holes: true，
  這樣圓角只作用於外邊緣，不會影響內部孔的邊緣。
- chamfer：length(mm)、edges(同上)；同樣支援 exclude_holes: true。
- hole：diameter(mm，直徑) 或 standard_parts.fastener.standard(如 M3/M5)+fit(normal_clearance 等)；
  through_all(true/false)、depth(mm，盲孔用)；hole_type(""simple""或""counterbore"")；
  positions 為 [[x,y],...] 座標列表，用於多孔排列（如四個固定孔），中心單孔用 [[0,0]]。
  重要：使用者說 radius(半徑) 時，diameter = radius × 2（如 radius 3mm → diameter 6mm）。
  重要：孔的陣列/排列一律使用 hole 的 positions 參數列表，不要使用 linear_pattern 或 circular_pattern（Pattern 僅支援實體特徵，不支援切除）。
- pocket：through_all(true) 或 depth(mm)；需要前置 sketch 或直接用 positions+diameter。
  重要：在修改流程中（create_feature 單一特徵），挖圓孔一律用 hole（diameter + positions），不要用 pocket。
  pocket 僅適用於非圓形切除（如矩形槽、不規則槽），且必須在 feature.references 中指向一個已有的 sketch 特徵 ID 作為輪廓。
- shell：thickness(mm)。
- mirror：input=要鏡射的實體特徵 ID；目前固定對 XZ 平面鏡射。
- revolve：angle(度，預設 360)；需要前置 sketch 步驟。
- sweep：input=輪廓草圖，references=[路徑草圖]。
- loft：input=第一個輪廓，references=[第二個、第三個…]。
- linear_pattern：input=要陣列的實體特徵，parameters 含 count（總數含原件）、spacing_mm（間距）、direction（如 ""x""/""y""）。
- circular_pattern：input=要陣列的實體特徵，parameters 含 count（總數）、angle_deg（總角度，預設 360）。
- draft：input=實體，parameters 含 angle_deg（拔模角）、face_selector、direction。
- rib：input=實體，parameters 含 thickness（肋厚 mm）、direction、sketch_id（肋輪廓草圖 ID）。
- thin：input=實體，parameters 含 length、thickness。
- variable_fillet：input=實體，parameters 含 radii（各邊半徑）或 radius、edge_selector。
- countersink：input=實體，parameters 含 diameter、countersink_diameter、countersink_angle_deg、positions=[[x,y],…]。
- cosmetic_thread：input=實體，parameters 含 diameter、pitch、depth、positions=[[x,y],…]。
- boolean_union／boolean_difference／boolean_intersection：input=第一個實體，references=[其他實體特徵 ID]（對兩個以上實體做布林）。

規則：
1. 只修改使用者明確指定的特徵，其他特徵一律列入 preserve。
2. 標準件（如螺絲孔徑）只選擇標準與等級（如 M5＋normal_clearance），不要給數值。
3. update_feature 只能修改該特徵型別本身既有的參數——嚴禁發明不存在的參數
   （例如在 pad 上加 fillet_radius 無效；圓角必須用 create_feature 新增 fillet 特徵）。
4. target_feature_id／input 必須是上述 Feature Graph 中已存在的 feature_id。
5. 如果使用者需求涉及引擎不支援的功能（{UnsupportedFeaturesText}），在 reasoning 中說明不支援，action 設為 rebuild（不變更模型）。
   注意：draft 拔模、rib 補強肋、countersink 沉頭孔、linear_pattern/circular_pattern 陣列、boolean 布林等皆為支援特徵，請正常用 create_feature 建立，不可誤判為不支援。
6. 若需求缺少必要資訊（如尺寸未給、要挖孔但沒說位置或大小、指代不清無法判斷是哪個特徵），不要亂猜也不要硬產生命令：
   把 commands 留空陣列，並在 clarification 欄位用繁體中文寫出要向使用者反問的一句話。
7. 每個 create_feature 的 feature_id 必須是全新且唯一的（不可與 Feature Graph 既有 ID 相同）。多個命令間有依賴時，後面的命令可引用前面命令新建的 feature_id。";

        var commandSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""commands"": { ""type"": ""array"", ""description"": ""依序執行的命令列表；一句多動作要拆成多個命令依序放入"", ""items"": {
      ""type"": ""object"",
      ""properties"": {
        ""schema_version"": { ""type"": ""string"", ""const"": ""1.0"" },
        ""action"": { ""type"": ""string"", ""enum"": [__ACTIONS__], ""description"": ""修改既有特徵用 update_feature；新增特徵用 create_feature；刪除特徵用 delete_feature；變更材質用 set_material；重建用 rebuild"" },
        ""target_feature_id"": { ""type"": ""string"", ""description"": ""update_feature/delete_feature 必填：要修改或刪除的特徵 ID，必須存在於 Feature Graph"" },
        ""feature"": { ""type"": ""object"", ""description"": ""create_feature 必填：新特徵定義"",
          ""properties"": {
            ""feature_id"": { ""type"": ""string"", ""description"": ""新的唯一 ID，如 fillet_1"" },
            ""type"": { ""type"": ""string"", ""enum"": [__FEATURE_TYPES__] },
            ""name"": { ""type"": ""string"" },
            ""input"": { ""type"": ""string"", ""description"": ""要加工的實體特徵 ID（fillet/chamfer/hole/pocket/shell/pattern/draft/rib 等必填；sketch/pad 免）"" },
            ""references"": { ""type"": ""array"", ""items"": { ""type"": ""string"" }, ""description"": ""sweep/loft/pocket/boolean 的參考草圖或實體 ID 列表"" },
            ""parameters"": { ""type"": ""object"" }
          },
          ""required"": [""feature_id"",""type"",""parameters""] },
        ""parameters"": { ""type"": ""object"", ""description"": ""update_feature/set_material 用：要更新的參數鍵值"" },
        ""standard_parts"": { ""type"": ""object"", ""description"": ""要更新的標準件，如 {fastener: {standard: M5, fit: normal_clearance}}"" },
        ""preserve"": { ""type"": ""array"", ""items"": { ""type"": ""string"" }, ""description"": ""不得變動的特徵 ID 列表"" },
        ""reasoning"": { ""type"": ""string"" }
      },
      ""required"": [""schema_version"",""action""] } },
    ""clarification"": { ""type"": ""string"", ""description"": ""需求不明確時向使用者反問的一句話（繁中）；填此欄時 commands 應為空陣列"" }
  },
  ""required"": [""commands""]
}".Replace("__FEATURE_TYPES__", SupportedFeatureTypesJson).Replace("__ACTIONS__", CommandActionsJson);

        var result = await SendStructuredAsync(userPrompt, commandSchema, history);
        return ParseUpdateBatch(result);
    }

    /// <summary>
    /// 解析修改流程回傳：優先 {commands:[...], clarification}；
    /// 回退容忍模型直接回單一命令物件。兩者皆失敗則拋出可讀錯誤。
    /// </summary>
    private static UpdateCommandBatch ParseUpdateBatch(string json)
    {
        try
        {
            var batch = JsonSerializer.Deserialize<UpdateCommandBatch>(json, JsonOpts);
            if (batch != null && (batch.Commands.Count > 0 || !string.IsNullOrWhiteSpace(batch.Clarification)))
                return batch;
        }
        catch (JsonException) { /* 回退到單一命令解析 */ }

        try
        {
            var single = JsonSerializer.Deserialize<CadCommand>(json, JsonOpts);
            if (single != null && !string.IsNullOrWhiteSpace(single.Action))
                return new UpdateCommandBatch { Commands = { single } };
        }
        catch (JsonException) { /* 落到最終錯誤 */ }

        throw new InvalidOperationException($"LLM 回傳的修改命令無法解析。原始內容：{Snippet(json)}");
    }

    public async Task<ReviewResult> ReviewResultAsync(ValidationReport report)
    {
        var userPrompt = $@"
幾何驗證報告：
有效：{report.IsValid}
實體數量：{report.SolidCount}
尺寸：{report.SizeX} × {report.SizeY} × {report.SizeZ} mm
體積：{report.Volume} mm³
孔數：{report.HoleCount}
最小壁厚：{report.MinimumWallThickness} mm
錯誤：{string.Join(", ", report.Errors)}
警告：{string.Join(", ", report.Warnings)}

請分析此報告，指出問題並提出修正建議。";

        var reviewSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""passed"": { ""type"": ""boolean"" },
    ""summary"": { ""type"": ""string"" },
    ""issues"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } }
  },
  ""required"": [""passed"",""summary""]
}";

        var result = await SendStructuredAsync(userPrompt, reviewSchema);
        return DeserializeOrThrow<ReviewResult>(result);
    }

    public async Task<CadCommand> RepairCommandAsync(string errorCode, string engineMessage, string featureGraphJson)
    {
        var errorDescriptions = new Dictionary<string, string>
        {
            ["SKETCH_NOT_CLOSED"] = "草圖未閉合——pad/pocket 需要至少一個閉合輪廓（rectangle/circle/polygon/slot/closed polyline）。請改為閉合草圖或加入閉合輪廓。",
            ["INVALID_STANDARD_PART"] = "標準件查表失敗——請確認 standard_parts 中的 standard 欄位為有效值（如 M3/M4/M5）。",
            ["CIRCULAR_DEPENDENCY"] = "特徵圖存在循環依賴——請移除相互引用的 input/references。",
            ["GEOMETRY_ERROR"] = "幾何建立失敗——請檢查參數是否合理（如尺寸為正數、位置在實體範圍內）。",
            ["FILLET_RADIUS_TOO_LARGE"] = "圓角半徑過大——圓角半徑超過了可用的邊緣長度或與孔/特徵碰撞。請嘗試減小半徑（例如減半）或確認該邊緣是否有足夠空間。",
            ["CHAMFER_DISTANCE_TOO_LARGE"] = "倒角距離過大——倒角尺寸超過了可用的邊緣長度。請嘗試減小距離。",
            ["REFERENCE_NOT_FOUND"] = "參考特徵不存在——請確認 input/references 指向已存在的特徵 ID。",
        };

        var desc = errorDescriptions.TryGetValue(errorCode, out var d) ? d : "未知錯誤類型，請根據引擎訊息修正。";

        var userPrompt = $@"
重建失敗，請修正。

錯誤碼：{errorCode}
引擎訊息：{engineMessage}
說明：{desc}

目前特徵圖（JSON）：
{featureGraphJson}

請產生一個 update_feature 或 delete_feature 命令來修正問題。";

        var result = await SendStructuredAsync(userPrompt, LlmCommandSchema);
        var cmd = DeserializeOrThrow<CadCommand>(result);
        if (string.IsNullOrEmpty(cmd.Action)) cmd.Action = "rebuild";
        return cmd;
    }

    /// <summary>
    /// WP-H1: 取得 Capability payload。子類可覆寫以從引擎動態取得。
    /// 預設從硬編碼 catalog 生成（與 server /api/capability 一致）。
    /// </summary>
    public virtual Task<CapabilityPayload> GetCapabilityPayloadAsync()
    {
        var payload = new CapabilityPayload
        {
            SchemaVersion = "1.0",
            EngineVersion = "opencad-worker-1.0",
            UnsupportedFeatures = EngineUnsupportedFeatures.ToList(),
            Tools = new List<string> { "inspect_document", "query_feature_catalog", "propose_transaction", "validate_transaction", "rebuild_staging", "request_user_confirmation" },
        };
        // Feature catalog——與 schemas/feature.schema.json 的 type enum、
        // cad-worker server.py 的 _FEATURE_PARAM_HINTS 對齊（唯一真相）。
        // datum 為 reference geometry，非 create_feature 型別，故不列於此。
        var catalog = new List<object>
        {
            new { type = "sketch", parameters = new[] { "sketch_entities", "plane", "constraints" } },
            new { type = "pad", parameters = new[] { "length", "taper_deg" } },
            new { type = "pocket", parameters = new[] { "depth", "through_all" } },
            new { type = "revolve", parameters = new[] { "angle" } },
            new { type = "sweep", parameters = Array.Empty<string>() },
            new { type = "loft", parameters = Array.Empty<string>() },
            new { type = "hole", parameters = new[] { "diameter", "depth", "through_all", "positions", "hole_type" } },
            new { type = "linear_pattern", parameters = new[] { "count", "spacing_mm", "direction" } },
            new { type = "circular_pattern", parameters = new[] { "count", "angle_deg" } },
            new { type = "mirror", parameters = Array.Empty<string>() },
            new { type = "fillet", parameters = new[] { "radius", "edges", "exclude_holes" } },
            new { type = "chamfer", parameters = new[] { "length", "edges", "exclude_holes" } },
            new { type = "shell", parameters = new[] { "thickness" } },
            new { type = "boolean_union", parameters = Array.Empty<string>() },
            new { type = "boolean_difference", parameters = Array.Empty<string>() },
            new { type = "boolean_intersection", parameters = Array.Empty<string>() },
            new { type = "draft", parameters = new[] { "angle_deg", "face_selector", "direction" } },
            new { type = "rib", parameters = new[] { "thickness", "direction", "sketch_id" } },
            new { type = "thin", parameters = new[] { "length", "thickness" } },
            new { type = "variable_fillet", parameters = new[] { "radii", "edge_selector", "radius" } },
            new { type = "countersink", parameters = new[] { "diameter", "countersink_diameter", "countersink_angle_deg", "positions" } },
            new { type = "cosmetic_thread", parameters = new[] { "diameter", "pitch", "depth", "positions" } },
        };
        payload.FeatureCatalogJson = JsonSerializer.Serialize(catalog, JsonOpts);
        return Task.FromResult(payload);
    }

    /// <summary>
    /// WP-H1: 程式硬檢查——拒絕不支援的功能，防止 LLM 偷換近似幾何。
    /// 回傳 true 表示通過檢查；false 表示命令被拒絕，reasoning 含拒絕原因。
    /// </summary>
    public static bool ValidateAgainstCatalog(CadCommand command, CapabilityPayload capability, out string rejectReason)
    {
        rejectReason = "";
        var unsupportedSet = new HashSet<string>(capability.UnsupportedFeatures, StringComparer.OrdinalIgnoreCase);

        // Check create_feature with unsupported type
        if (command.Action == "create_feature" && command.Feature != null)
        {
            var featType = command.Feature.Type.ToString().ToLowerInvariant();
            if (unsupportedSet.Contains(featType))
            {
                rejectReason = $"不支援的功能：{featType}。引擎不支援此特徵類型，不得以近似幾何替代。";
                return false;
            }
        }

        // Check reasoning mentions unsupported but action is not rebuild (偷換)
        if (command.Reasoning != null && command.Action != "rebuild")
        {
            foreach (var unsupported in unsupportedSet)
            {
                if (command.Reasoning.Contains(unsupported, StringComparison.OrdinalIgnoreCase))
                {
                    rejectReason = $"需求涉及不支援的功能：{unsupported}。應設 action=rebuild 並在 reasoning 中說明。不得以近似幾何替代。";
                    return false;
                }
            }
        }

        return true;
    }

    private static readonly string LlmCommandSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""schema_version"": { ""type"": ""string"", ""const"": ""1.0"" },
    ""action"": { ""type"": ""string"", ""enum"": [__ACTIONS__] },
    ""document_id"": { ""type"": ""string"" },
    ""target_feature_id"": { ""type"": ""string"" },
    ""feature"": { ""type"": ""object"" },
    ""parameters"": { ""type"": ""object"" },
    ""preserve"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } },
    ""standard_parts"": { ""type"": ""object"" },
    ""reasoning"": { ""type"": ""string"" }
  },
  ""required"": [""schema_version"",""action""]
}".Replace("__ACTIONS__", CommandActionsJson);

    protected static string BuildSystemPrompt() =>
        "你是 OpenCad 的 AI 建模助手。你的任務是：\n" +
        "1. 理解使用者的繁體中文工程設計需求。\n" +
        "2. 將需求轉換成受控的 CAD 命令（OpenCad Command JSON）。\n" +
        "3. 你只能透過受控命令操作模型，不能直接存取任意檔案或執行任意程式碼。\n" +
        "4. 標準件（如螺絲孔徑、NEMA 安裝尺寸）只選擇「標準與等級」，數值由引擎查表。\n" +
        "5. 如果需求中有缺少或矛盾的條件，必須提問，不得自行猜測。\n" +
        "6. 單位以 mm 為主。如果使用者混用單位，自動換算。\n" +
        "7. sketch 特徵必須指定 plane.base：XY=上基準面（俯視）、XZ=前基準面（正視）、YZ=右基準面（側視）。offset 為沿法線偏移量(mm)，預設 0。\n" +
        "   依零件方位選擇：水平平板上的草圖用 XY；垂直面板上的孔/槽用 XZ 或 YZ。\n" +
        "8. sketch_entities 支援以下類型：rectangle(矩形)、circle(圓)、polygon(多邊形)、slot(長圓孔)、line(線段)、polyline(多段線)、arc(圓弧)、construction_line(建構線)。\n" +
        "   pad/pocket 的輸入草圖必須包含至少一個閉合輪廓（rectangle/circle/polygon/slot/closed polyline）。線段、弧、建構線僅為輔助。\n" +
        "9. hole 特徵支援 hole_type: \"simple\"(簡單孔) 或 \"counterbore\"(沉頭孔)。沉頭孔需指定 standard_parts.fastener.standard（如 M3/M4/M5），由引擎查表取得沉頭直徑與深度。\n" +
        "10. sweep 特徵：input=輪廓草圖，references=[路徑草圖]。輪廓沿路徑掃描成實體（如管件、彎管）。路徑草圖用 line/polyline/arc 定義路徑線段。\n" +
        "11. loft 特徵：input=第一個輪廓草圖，references=[第二個、第三個…]。在多個輪廓之間建立漸變實體（如錐形、過渡段）。至少需要兩個輪廓。\n" +
        "12. 質量屬性：重建後回傳體積、表面積、質量、邊界框。可用 action=\"set_material\" + parameters.material 變更材質（如 pla/abs/aluminum/steel）。\n" +
        "13. 計畫步驟中，sketch 特徵必須在 step.sketch_entities 中提供草圖實體（如 rectangle/circle/slot 等），不能只放在 parameters。\n" +
        "   hole 特徵如果需要查表，必須在 step.standard_parts 中指定 fastener.standard 和 fastener.fit。\n" +
        "   sketch 的 plane 請放在 step.plane，鍵名是 base（如 {\"base\":\"XY\",\"offset\":0}）。\n" +
        "14. 修改流程（已有特徵時）：action 可以是 update_feature（改參數）、create_feature（加新特徵）、\n" +
        "    delete_feature（刪特徵，如「刪掉圓角」「取消倒角」）、set_material（改材質）、rebuild（重建/不支援功能時）。\n" +
        "    使用者說「刪除」「取消」「刪掉」某特徵時，用 delete_feature + target_feature_id，不要用 update_feature。\n" +
        "15. 孔的陣列/排列：hole 特徵的 positions 參數為 [[x,y],...] 座標列表，可直接建立多孔排列（如四個固定孔）。\n" +
        "    重要：孔的排列一律使用 positions，不要使用 linear_pattern 或 circular_pattern（Pattern 僅支援實體特徵，不支援切除）。\n" +
        "16. 進階特徵皆可用 create_feature 建立（勿誤判為不支援）：draft（拔模角）、rib（補強肋）、thin（薄件）、\n" +
        "    variable_fillet（變半徑圓角）、countersink（沉頭孔）、cosmetic_thread（裝飾螺紋）、\n" +
        "    linear_pattern/circular_pattern（陣列）、boolean_union/boolean_difference/boolean_intersection（布林）。\n" +
        "17. 修改流程中挖圓孔/貫穿孔：一律使用 hole 特徵（diameter + positions），不要用 pocket。\n" +
        "    pocket 需要 references 指向已有的 sketch 特徵作為輪廓，修改流程中無法同時建立 sketch + pocket 兩個特徵。\n" +
        "    hole 的 positions 用 [[x,y],...] 格式，中心孔用 [[0,0]]。diameter 是直徑(mm)，radius 是半徑——注意換算（radius 3mm = diameter 6mm）。\n" +
        "18. fillet/chamfer 的 exclude_holes 參數：當使用者說「通孔不要動」「孔不要影響」「不要動到中間的孔」時，\n" +
        "    必須在 fillet/chamfer 的 parameters 中加入 exclude_holes: true。這會讓圓角/倒角只作用於外邊緣，跳過孔的邊緣。\n" +
        "    若使用者沒有特別說要保護孔，則不需要加 exclude_holes（預設 false）。\n" +
        "19. 草圖約束（WP1-2）：sketch 步驟可包含 constraints 陣列，用來定義 fully-constrained 草圖。\n" +
        "    約束格式：{\"id\":\"c1\",\"type\":\"horizontal|vertical|coincident|distance|radius|diameter|equal|parallel|perpendicular|concentric|midpoint|symmetric|angle|tangent\",\"targets\":[\"e1.start\",\"e2.end\"],\"value_mm\":60,\"name\":\"d1\"}\n" +
        "    targets 使用「實體ID.點位」格式，如 e1.start（線段起點）、e1.end（線段終點）、e1.center（圓心）。\n" +
        "    範例：矩形 60×40 fully-constrained = rectangle(width:60,height:40) + horizontal(底邊) + vertical(左邊) + distance(60) + distance(40)。\n" +
        "    輸出 fully-constrained 草圖——所有尺寸由約束驅動，不要在 sketch_entities 參數中硬編碼多餘尺寸。\n" +
        "重要：你的輸出必須是合法 JSON，符合指定的 Schema。\n" +
        "20. WP-H1 拒絕規則（系統提示＋程式硬檢查雙層）：\n" +
        "    a. 缺尺寸→必須提問，不得自行猜測數值（如「做一個盒子」無尺寸→提問，不可用任意值）。\n" +
        "    b. selector 歧義→要求使用者點選（如「挖一個孔」未指定位置→提問，回傳 missing_info）。\n" +
        "    c. 不支援的功能→明確說明不支援，**不得偷換近似幾何**（如「螺旋齒輪」→拒絕，不可改為圓柱）。\n" +
        $"       目前不支援清單（唯一真相）：{UnsupportedFeaturesText}。\n" +
        "    d. 不得靜默改尺寸/刪特徵——所有變更必須在 reasoning 中說明。\n" +
        "    e. 破壞性命令（delete_feature）必須在 reasoning 中明確說明刪除目標與影響範圍。\n" +
        "21. WP-H1 Capability payload：每次呼叫必帶 schema_version=1.0、engine_version、feature_catalog。\n" +
        "    模型不得憑 prompt 記憶猜功能——只能使用 feature_catalog 中列出的型別與參數。\n" +
        "22. WP-H1 修復迴圈限制：低風險修復最多 2 次（非 3 次），只修白名單類型：\n" +
        "    SKETCH_NOT_CLOSED、INVALID_STANDARD_PART、REFERENCE_NOT_FOUND、FILLET_RADIUS_TOO_LARGE、CHAMFER_DISTANCE_TOO_LARGE。\n" +
        "    其餘錯誤類型一律出卡片讓使用者手動處理。";
}
