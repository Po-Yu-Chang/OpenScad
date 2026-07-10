using System.Net.Http;
using System.Text;
using System.Text.Json;
using OpenCad.Application;

namespace OpenCad.Llm;

/// <summary>
/// Ollama LLM 提供者——完全離線。
/// 使用 Ollama 原生 /api/generate 的 format 參數（傳入 JSON Schema）
/// 做受限解碼，保證輸出合法 JSON。
/// </summary>
public class OllamaLlmProvider : LlmProviderBase
{
    private readonly HttpClient _httpClient;
    private readonly string _modelName;
    private readonly string _systemPrompt;

    public OllamaLlmProvider(string baseUrl = "http://127.0.0.1:11434", string modelName = "qwen2.5-coder:14b")
    {
        _httpClient = new HttpClient { BaseAddress = new Uri(baseUrl), Timeout = TimeSpan.FromMinutes(2) };
        _modelName = modelName;
        _systemPrompt = BuildSystemPrompt();
    }

    protected override async Task<string> SendStructuredAsync(string prompt, string schema, List<ChatTurn>? history = null)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"System: {_systemPrompt}");
        if (history != null)
        {
            foreach (var turn in history)
            {
                // Role 通常為 user 或 assistant
                var role = turn.Role.Equals("assistant", StringComparison.OrdinalIgnoreCase) ? "Assistant" : "User";
                sb.AppendLine($"{role}: {turn.Content}");
            }
        }
        sb.AppendLine($"User: {prompt}");

        var requestBody = new
        {
            model = _modelName,
            prompt = sb.ToString(),
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
}
