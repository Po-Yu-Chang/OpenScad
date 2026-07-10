using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using OpenCad.Application;
using OpenCad.Domain;

namespace OpenCad.Infrastructure;

/// <summary>
/// CAD Worker HTTP 客戶端——透過 localhost HTTP（FastAPI）與 Python Worker 通訊。
/// Worker 以獨立程序運行，只監聽 127.0.0.1，使用隨機工作階段 Token。
/// </summary>
public class CadWorkerClient : ICadWorker
{
    private readonly HttpClient _httpClient;
    private readonly string _sessionToken;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    };

    /// <param name="baseUrl">Worker 基地址，預設 http://127.0.0.1:8765</param>
    /// <param name="sessionToken">工作階段 Token</param>
    public CadWorkerClient(string baseUrl = "http://127.0.0.1:8765", string? sessionToken = null)
    {
        _httpClient = new HttpClient { BaseAddress = new Uri(baseUrl), Timeout = TimeSpan.FromMinutes(5) };
        _sessionToken = sessionToken ?? string.Empty;
        if (!string.IsNullOrEmpty(_sessionToken))
        {
            _httpClient.DefaultRequestHeaders.Add("X-Session-Token", _sessionToken);
        }
    }

    public async Task<string> CreateProjectAsync(string name, string description = "")
    {
        var req = new { name, description, units = "mm", engine = "build123d" };
        var json = JsonSerializer.Serialize(req, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync("/api/projects", content);
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        return result.GetProperty("project_id").GetString()!;
    }

    public async Task<CommandResult> ApplyCommandAsync(string projectId, CadCommand command)
    {
        var json = JsonSerializer.Serialize(command, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/commands", content);
        var body = await response.Content.ReadAsStringAsync();

        // 檢查 HTTP 狀態碼——傳輸層失敗時回傳結構化錯誤而非擲回 JsonException
        JsonElement? result = null;
        if (!response.IsSuccessStatusCode && !TryParseStructuredError(body, out result))
        {
            return new CommandResult
            {
                Status = "error",
                ErrorCode = "TRANSPORT_ERROR",
                EngineMessage = $"HTTP {response.StatusCode}: {body}",
            };
        }

        result ??= JsonSerializer.Deserialize<JsonElement>(body, JsonOpts);

        return new CommandResult
        {
            Status = result.Value.TryGetProperty("status", out var st) ? st.GetString() ?? "" : "",
            FeatureId = result.Value.TryGetProperty("feature_id", out var fi) ? fi.GetString() : null,
            ErrorCode = result.Value.TryGetProperty("error_code", out var ec) ? ec.GetString() : null,
            EngineMessage = result.Value.TryGetProperty("engine_message", out var em) ? em.GetString() : null,
            AffectedFeatures = result.Value.TryGetProperty("affected_features", out var af)
                ? af.EnumerateArray().Select(x => x.GetString()!).ToList()
                : null,
        };
    }

    public async Task<RebuildResult> RebuildAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/rebuild", null);
        var body = await response.Content.ReadAsStringAsync();

        // 檢查 HTTP 狀態碼
        JsonElement? result = null;
        if (!response.IsSuccessStatusCode && !TryParseStructuredError(body, out result))
        {
            return new RebuildResult
            {
                Status = "error",
                ErrorCode = "TRANSPORT_ERROR",
                EngineMessage = $"HTTP {response.StatusCode}: {body}",
            };
        }

        result ??= JsonSerializer.Deserialize<JsonElement>(body, JsonOpts);

        return new RebuildResult
        {
            Status = result.Value.TryGetProperty("status", out var st) ? st.GetString() ?? "" : "",
            FeatureCount = result.Value.TryGetProperty("feature_count", out var fc) ? fc.GetInt32() : 0,
            ErrorCode = result.Value.TryGetProperty("error_code", out var ec) ? ec.GetString() : null,
            EngineMessage = result.Value.TryGetProperty("engine_message", out var em) ? em.GetString() : null,
        };
    }

    /// <summary>
    /// 嘗試從回應主體解析結構化錯誤 JSON（Worker 失敗時仍回傳 JSON）。
    /// </summary>
    private static bool TryParseStructuredError(string body, out JsonElement? result)
    {
        result = null;
        if (string.IsNullOrWhiteSpace(body))
            return false;
        try
        {
            result = JsonSerializer.Deserialize<JsonElement>(body, JsonOpts);
            return result.Value.TryGetProperty("status", out _) || result.Value.TryGetProperty("error_code", out _);
        }
        catch
        {
            return false;
        }
    }

    public async Task<ValidationReport> ValidateAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/validate", null);
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body, JsonOpts);

        var report = result.GetProperty("report");
        return JsonSerializer.Deserialize<ValidationReport>(report.GetRawText(), JsonOpts)!;
    }

    public async Task<string> ExportAsync(string projectId, string format)
    {
        var req = new { format, filename = "model" };
        var json = JsonSerializer.Serialize(req, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/exports", content);
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        return result.GetProperty("path").GetString()!;
    }

    public string GetPreviewUrl(string projectId)
    {
        return $"{_httpClient.BaseAddress}api/projects/{projectId}/preview.glb";
    }

    /// <summary>
    /// 健康檢查。
    /// </summary>
    public async Task<bool> CheckHealthAsync()
    {
        try
        {
            var response = await _httpClient.GetAsync("/api/health");
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// 從 Token 檔案取得工作階段 Token。
    /// Worker 啟動時將 Token 寫入 OPENCAD_TOKEN_FILE 指定的檔案。
    /// </summary>
    public static async Task<string?> GetSessionTokenAsync(string tokenFilePath)
    {
        if (string.IsNullOrEmpty(tokenFilePath))
            return null;
        try
        {
            // 等待 Token 檔案出現（最多 10 秒）
            var deadline = DateTime.UtcNow.AddSeconds(10);
            while (DateTime.UtcNow < deadline)
            {
                if (File.Exists(tokenFilePath))
                {
                    var token = File.ReadAllText(tokenFilePath).Trim();
                    if (!string.IsNullOrEmpty(token))
                        return token;
                }
                await Task.Delay(200);
            }
            return null;
        }
        catch
        {
            return null;
        }
    }
}