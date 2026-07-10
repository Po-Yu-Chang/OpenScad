using System.Net.Http;
using System.Text;
using System.Text.Json;
using OpenCad.Application;
using OpenCad.Domain;

namespace OpenCad.Llm;

/// <summary>
/// Ollama LLM 提供者——完全離線、OpenAI-compatible API。
/// 使用結構化輸出（format 參數傳入 JSON Schema）保證輸出合法 JSON。
/// </summary>
public class OllamaLlmProvider : ILlmProvider
{
    private readonly HttpClient _httpClient;
    private readonly string _modelName;
    private readonly string _systemPrompt;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    public OllamaLlmProvider(string baseUrl = "http://127.0.0.1:11434", string modelName = "qwen2.5-coder:14b")
    {
        _httpClient = new HttpClient { BaseAddress = new Uri(baseUrl), Timeout = TimeSpan.FromMinutes(2) };
        _modelName = modelName;
        _systemPrompt = BuildSystemPrompt();
    }

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

    private async Task<string> SendStructuredAsync(string prompt, string schema)
    {
        var requestBody = new
        {
            model = _modelName,
            prompt = $"{_systemPrompt}\n\n{prompt}",
            format = JsonSerializer.Deserialize<JsonElement>(schema),
            stream = false,
            options = new { temperature = 0.1, top_p = 0.9 },
        };

        var json = JsonSerializer.Serialize(requestBody, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync("/api/generate", content);
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        return result.GetProperty("response").GetString()!;
    }

    private static string BuildSystemPrompt() =>
        "你是 OpenCad 的 AI 建模助手。你的任務是：\n" +
        "1. 理解使用者的繁體中文工程設計需求。\n" +
        "2. 將需求轉換成受控的 CAD 命令（OpenCad Command JSON）。\n" +
        "3. 你只能透過受控命令操作模型，不能直接存取任意檔案或執行任意程式碼。\n" +
        "4. 標準件（如螺絲孔徑、NEMA 安裝尺寸）只選擇「標準與等級」，數值由引擎查表。\n" +
        "5. 如果需求中有缺少或矛盾的條件，必須提問，不得自行猜測。\n" +
        "6. 單位以 mm 為主。如果使用者混用單位，自動換算。\n\n" +
        "重要：你的輸出必須是合法 JSON，符合指定的 Schema。";
}