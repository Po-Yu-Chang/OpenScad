using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace OpenCad.Llm;

/// <summary>
/// OpenAI-compatible LLM 提供者——支援 LiteLLM Gateway、vLLM、
/// LM Studio 等任何實作 /v1/chat/completions 的服務。
/// 以 response_format json_object＋提示詞內嵌 Schema 取得結構化輸出
/// （json_object 是各家後端的最大公約數）。
/// </summary>
public class OpenAiCompatibleLlmProvider : LlmProviderBase
{
    private readonly HttpClient _httpClient;
    private readonly string _modelName;
    private readonly string _systemPrompt;

    /// <param name="baseUrl">API 基底位址，含 /v1（如 http://gateway.local:4000/v1）</param>
    /// <param name="apiKey">API 金鑰（可為空）</param>
    /// <param name="modelName">模型名稱</param>
    public OpenAiCompatibleLlmProvider(string baseUrl, string? apiKey, string modelName)
    {
        // BaseAddress 需以 / 結尾，相對路徑才會接在 /v1 之後
        var normalized = baseUrl.TrimEnd('/') + "/";
        _httpClient = new HttpClient { BaseAddress = new Uri(normalized), Timeout = TimeSpan.FromMinutes(2) };
        if (!string.IsNullOrEmpty(apiKey))
            _httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
        _modelName = modelName;
        _systemPrompt = BuildSystemPrompt();
    }

    /// <summary>
    /// 連線測試——GET /models，2 秒逾時內回 200 即視為可用。
    /// </summary>
    public async Task<bool> CheckConnectivityAsync()
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            var resp = await _httpClient.GetAsync("models", cts.Token);
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    protected override async Task<string> SendStructuredAsync(string prompt, string schema)
    {
        var requestBody = new
        {
            model = _modelName,
            messages = new object[]
            {
                new { role = "system", content = $"{_systemPrompt}\n\n你的回覆必須是符合以下 JSON Schema 的單一 JSON 物件（不要加任何說明文字或 markdown 圍欄）：\n{schema}" },
                new { role = "user", content = prompt },
            },
            response_format = new { type = "json_object" },
            temperature = 0.1,
        };

        var json = JsonSerializer.Serialize(requestBody, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync("chat/completions", content);
        if (!response.IsSuccessStatusCode)
        {
            // 部分後端不支援 response_format——退回純提示詞模式
            var fallbackBody = new
            {
                model = _modelName,
                messages = new object[]
                {
                    new { role = "system", content = $"{_systemPrompt}\n\n你的回覆必須是符合以下 JSON Schema 的單一 JSON 物件（不要加任何說明文字或 markdown 圍欄）：\n{schema}" },
                    new { role = "user", content = prompt },
                },
                temperature = 0.1,
            };
            content = new StringContent(JsonSerializer.Serialize(fallbackBody, JsonOpts), Encoding.UTF8, "application/json");
            response = await _httpClient.PostAsync("chat/completions", content);
            response.EnsureSuccessStatusCode();
        }

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        var text = result.GetProperty("choices")[0].GetProperty("message").GetProperty("content").GetString() ?? "";
        return ExtractJson(text);
    }

    /// <summary>
    /// 從回覆中抽出 JSON——容忍 markdown 圍欄與前後說明文字。
    /// </summary>
    private static string ExtractJson(string text)
    {
        text = text.Trim();
        // 去除 ```json ... ``` 圍欄
        if (text.StartsWith("```"))
        {
            var firstNewline = text.IndexOf('\n');
            var lastFence = text.LastIndexOf("```", StringComparison.Ordinal);
            if (firstNewline >= 0 && lastFence > firstNewline)
                text = text[(firstNewline + 1)..lastFence].Trim();
        }
        // 取第一個 { 到最後一個 } 的區段
        var start = text.IndexOf('{');
        var end = text.LastIndexOf('}');
        if (start >= 0 && end > start)
            return text[start..(end + 1)];
        return text;
    }
}
