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
        // 使用 /api/chat 的 messages 陣列（取代把 system+history+user 串成單一字串），
        // 讓多輪對話有正確的角色邊界；format 傳入 JSON Schema 做受限解碼保證輸出合法 JSON。
        var messages = new List<object>
        {
            new { role = "system", content = _systemPrompt },
        };
        if (history != null)
        {
            foreach (var turn in history)
            {
                var role = turn.Role.Equals("assistant", StringComparison.OrdinalIgnoreCase) ? "assistant" : "user";
                messages.Add(new { role, content = turn.Content });
            }
        }
        messages.Add(new { role = "user", content = prompt });

        var requestBody = new
        {
            model = _modelName,
            messages = messages.ToArray(),
            format = JsonSerializer.Deserialize<JsonElement>(schema),
            stream = false,
            options = new { temperature = 0.1, top_p = 0.9 },
        };

        var json = JsonSerializer.Serialize(requestBody, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync("/api/chat", content);
        if (!response.IsSuccessStatusCode)
        {
            var errBody = await response.Content.ReadAsStringAsync();
            throw new HttpRequestException(
                $"Ollama 請求失敗（HTTP {(int)response.StatusCode} {response.StatusCode}）：{errBody}");
        }

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        return result.GetProperty("message").GetProperty("content").GetString()!;
    }
}
