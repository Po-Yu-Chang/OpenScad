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
    /// 送出提示詞並取得符合 schema 的 JSON 字串。由各提供者實作傳輸細節。
    /// </summary>
    protected abstract Task<string> SendStructuredAsync(string prompt, string schema);

    public async Task<DesignPlan> CreatePlanAsync(DesignContext context)
    {
        var userPrompt = $@"
使用者需求：{context.UserRequest}

請將此需求拆解成建模步驟。每個步驟描述要建立的特徵類型和參數。
如果需求中有缺少或矛盾的條件，請在 missing_info 中列出。
回傳 JSON 格式的設計計畫。";

        var planSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""steps"": { ""type"": ""array"", ""items"": { ""type"": ""object"",
      ""properties"": {
        ""description"": { ""type"": ""string"" },
        ""feature_type"": { ""type"": ""string"", ""enum"": [""sketch"",""pad"",""pocket"",""hole"",""linear_pattern"",""circular_pattern"",""mirror"",""fillet"",""chamfer"",""shell"",""revolve"",""boolean_union"",""boolean_difference"",""boolean_intersection""] },
        ""parameters"": { ""type"": ""object"" }
      }, ""required"": [""description"",""feature_type"",""parameters""] } },
    ""summary"": { ""type"": ""string"" },
    ""warnings"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } },
    ""missing_info"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } }
  },
  ""required"": [""steps"",""summary""]
}";

        var result = await SendStructuredAsync(userPrompt, planSchema);
        return JsonSerializer.Deserialize<DesignPlan>(result, JsonOpts) ?? new DesignPlan();
    }

    public async Task<CadCommand> CreateCommandAsync(DesignPlan plan)
    {
        var userPrompt = $@"
根據以下設計計畫，產生 OpenCad Command JSON。
設計計畫摘要：{plan.Summary}

步驟：
{string.Join("\n", plan.Steps.Select((s, i) => $"{i + 1}. {s.Description} ({s.FeatureType})"))}

請產生對應的 create_feature 或 update_feature 命令。";

        var commandSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""schema_version"": { ""type"": ""string"", ""const"": ""1.0"" },
    ""action"": { ""type"": ""string"", ""enum"": [""create_feature"",""update_feature"",""delete_feature"",""rebuild"",""export"",""validate""] },
    ""document_id"": { ""type"": ""string"" },
    ""target_feature_id"": { ""type"": ""string"" },
    ""feature"": { ""type"": ""object"" },
    ""parameters"": { ""type"": ""object"" },
    ""preserve"": { ""type"": ""array"", ""items"": { ""type"": ""string"" } },
    ""standard_parts"": { ""type"": ""object"" },
    ""reasoning"": { ""type"": ""string"" }
  },
  ""required"": [""schema_version"",""action""]
}";

        var result = await SendStructuredAsync(userPrompt, commandSchema);
        return JsonSerializer.Deserialize<CadCommand>(result, JsonOpts) ?? new CadCommand();
    }

    public async Task<CadCommand> CreateUpdateCommandAsync(string userRequest, string featureGraphJson)
    {
        var userPrompt = $@"
使用者的修改需求：{userRequest}

目前 Feature Graph（JSON）：
{featureGraphJson}

請根據使用者需求，找出要修改的目標特徵（target_feature_id），並產生 update_feature 命令。
規則：
1. 只修改使用者明確指定的特徵，其他特徵一律列入 preserve。
2. 標準件（如螺絲孔徑）只選擇標準與等級（如 M5＋normal_clearance），不要給數值。
3. 修改 parameters 或 standard_parts 來表達變更。
4. target_feature_id 必須是上述 Feature Graph 中已存在的 feature_id。";

        var commandSchema = @"
{
  ""type"": ""object"",
  ""properties"": {
    ""schema_version"": { ""type"": ""string"", ""const"": ""1.0"" },
    ""action"": { ""type"": ""string"", ""const"": ""update_feature"" },
    ""target_feature_id"": { ""type"": ""string"", ""description"": ""要修改的特徵 ID，必須存在於 Feature Graph"" },
    ""parameters"": { ""type"": ""object"", ""description"": ""要更新的參數鍵值"" },
    ""standard_parts"": { ""type"": ""object"", ""description"": ""要更新的標準件，如 {fastener: {standard: M5, fit: normal_clearance}}"" },
    ""preserve"": { ""type"": ""array"", ""items"": { ""type"": ""string"" }, ""description"": ""不得變動的特徵 ID 列表"" },
    ""reasoning"": { ""type"": ""string"" }
  },
  ""required"": [""schema_version"",""action"",""target_feature_id""]
}";

        var result = await SendStructuredAsync(userPrompt, commandSchema);
        return JsonSerializer.Deserialize<CadCommand>(result, JsonOpts) ?? new CadCommand();
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
        return JsonSerializer.Deserialize<ReviewResult>(result, JsonOpts) ?? new ReviewResult();
    }

    protected static string BuildSystemPrompt() =>
        "你是 OpenCad 的 AI 建模助手。你的任務是：\n" +
        "1. 理解使用者的繁體中文工程設計需求。\n" +
        "2. 將需求轉換成受控的 CAD 命令（OpenCad Command JSON）。\n" +
        "3. 你只能透過受控命令操作模型，不能直接存取任意檔案或執行任意程式碼。\n" +
        "4. 標準件（如螺絲孔徑、NEMA 安裝尺寸）只選擇「標準與等級」，數值由引擎查表。\n" +
        "5. 如果需求中有缺少或矛盾的條件，必須提問，不得自行猜測。\n" +
        "6. 單位以 mm 為主。如果使用者混用單位，自動換算。\n\n" +
        "重要：你的輸出必須是合法 JSON，符合指定的 Schema。";
}
