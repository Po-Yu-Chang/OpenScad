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
        var req = new { name, description, units = "mm", engine = "build123d", material = "pla" };
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
            MeshRevision = result.Value.TryGetProperty("mesh_revision", out var mr) ? mr.GetInt32() : 0,
            ErrorCode = result.Value.TryGetProperty("error_code", out var ec) ? ec.GetString() : null,
            EngineMessage = result.Value.TryGetProperty("engine_message", out var em) ? em.GetString() : null,
            MassProperties = result.Value.TryGetProperty("mass_properties", out var mp) ? ParseMassProperties(mp) : null,
        };
    }

    public async Task<RebuildResult> RebuildStagingAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/rebuild?dry_run=true", null);
        var body = await response.Content.ReadAsStringAsync();

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
            MassProperties = result.Value.TryGetProperty("mass_properties", out var mp) ? ParseMassProperties(mp) : null,
        };
    }

    public async Task<string?> GetCapabilityAsync()
    {
        var response = await _httpClient.GetAsync("/api/capability");
        if (!response.IsSuccessStatusCode)
            return null;
        return await response.Content.ReadAsStringAsync();
    }

    /// <summary>
    /// 解析質量屬性 JSON。
    /// </summary>
    private static MassProperties? ParseMassProperties(JsonElement mp)
    {
        if (mp.ValueKind != JsonValueKind.Object)
            return null;

        var props = new MassProperties
        {
            VolumeMm3 = mp.TryGetProperty("volume_mm3", out var v) ? v.GetDouble() : 0,
            SurfaceAreaMm2 = mp.TryGetProperty("surface_area_mm2", out var sa) ? sa.GetDouble() : 0,
            MassG = mp.TryGetProperty("mass_g", out var mg) ? mg.GetDouble() : 0,
            Material = mp.TryGetProperty("material", out var mat) ? mat.GetString() ?? "" : "",
            DensityGcm3 = mp.TryGetProperty("density_g_cm3", out var den) ? den.GetDouble() : 0,
        };

        if (mp.TryGetProperty("bounding_box_mm", out var bb) && bb.ValueKind == JsonValueKind.Object)
        {
            props.BoundingBoxMm = new BoundingBoxMm
            {
                MinX = bb.TryGetProperty("min_x", out var mn) ? mn.GetDouble() : 0,
                MinY = bb.TryGetProperty("min_y", out var my) ? my.GetDouble() : 0,
                MinZ = bb.TryGetProperty("min_z", out var mz) ? mz.GetDouble() : 0,
                MaxX = bb.TryGetProperty("max_x", out var mx) ? mx.GetDouble() : 0,
                MaxY = bb.TryGetProperty("max_y", out var my2) ? my2.GetDouble() : 0,
                MaxZ = bb.TryGetProperty("max_z", out var mz2) ? mz2.GetDouble() : 0,
                SizeX = bb.TryGetProperty("size_x", out var sx) ? sx.GetDouble() : 0,
                SizeY = bb.TryGetProperty("size_y", out var sy) ? sy.GetDouble() : 0,
                SizeZ = bb.TryGetProperty("size_z", out var sz) ? sz.GetDouble() : 0,
            };
        }

        return props;
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

    public async Task<string> GetPreviewUrlAsync(string projectId)
    {
        // WP-H2：URL 只放短時效預簽 token（單次有效），靜態 SESSION_TOKEN 不進 URL/log
        var token = await GetPresignedTokenAsync();
        return $"{_httpClient.BaseAddress}api/projects/{projectId}/preview.glb?token={token}&t={_rebuildCount}";
    }

    public async Task<string> GetDisplayMapUrlAsync(string projectId)
    {
        var token = await GetPresignedTokenAsync();
        return $"{_httpClient.BaseAddress}api/projects/{projectId}/display_map?token={token}&t={_rebuildCount}";
    }

    private async Task<string> GetPresignedTokenAsync()
    {
        var response = await _httpClient.PostAsync("/api/presign", null);
        response.EnsureSuccessStatusCode();
        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        return result.GetProperty("presigned_token").GetString()!;
    }

    private int _rebuildCount;

    /// <summary>
    /// 重建計數——用於 preview URL 的 cache-busting 參數。
    /// </summary>
    public int RebuildCount
    {
        get => _rebuildCount;
        set => _rebuildCount = value;
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
    /// 取得專案資訊與特徵圖（用於更新特徵樹）。
    /// </summary>
    public async Task<string> GetProjectAsync(string projectId)
    {
        var response = await _httpClient.GetAsync($"/api/projects/{projectId}");
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync();
    }

    /// <summary>
    /// 取得所有專案列表。
    /// </summary>
    public async Task<string> ListProjectsAsync()
    {
        var response = await _httpClient.GetAsync("/api/projects");
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync();
    }

    /// <summary>
    /// 將專案改名。
    /// </summary>
    public async Task<bool> RenameProjectAsync(string projectId, string name)
    {
        var json = JsonSerializer.Serialize(new { name }, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");
        var response = await _httpClient.PatchAsync($"/api/projects/{projectId}", content);
        return response.IsSuccessStatusCode;
    }

    /// <summary>
    /// 刪除專案（記憶體＋磁碟）。
    /// </summary>
    public async Task<bool> DeleteProjectAsync(string projectId)
    {
        var response = await _httpClient.DeleteAsync($"/api/projects/{projectId}");
        return response.IsSuccessStatusCode;
    }

    /// <summary>
    /// 複製專案，回傳新專案 ID（失敗回 null）。
    /// </summary>
    public async Task<string?> DuplicateProjectAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/duplicate", null);
        if (!response.IsSuccessStatusCode) return null;
        var body = await response.Content.ReadAsStringAsync();
        var result = JsonSerializer.Deserialize<JsonElement>(body);
        return result.GetProperty("project_id").GetString();
    }

    /// <summary>
    /// 上傳 3D 縮圖（PNG bytes，由 viewer 擷取）。
    /// </summary>
    public async Task<bool> UploadThumbnailAsync(string projectId, byte[] pngBytes)
    {
        var content = new ByteArrayContent(pngBytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("image/png");
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/thumbnail", content);
        return response.IsSuccessStatusCode;
    }

    /// <summary>
    /// 取得縮圖 URL（內含短時效預簽 token，比照 preview.glb）。
    /// </summary>
    public async Task<string> GetThumbnailUrlAsync(string projectId)
    {
        var token = await GetPresignedTokenAsync();
        return $"{_httpClient.BaseAddress}api/projects/{projectId}/thumbnail.png?token={token}&t={_rebuildCount}";
    }

    /// <summary>
    /// 復原到上一版。
    /// </summary>
    public async Task<bool> UndoAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/undo", null);
        return response.IsSuccessStatusCode;
    }

    /// <summary>
    /// 重做到下一版。
    /// </summary>
    public async Task<bool> RedoAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/redo", null);
        return response.IsSuccessStatusCode;
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

    /// <summary>
    /// 交易式套用多個命令（staging + rollback）。
    /// 所有命令在 staging graph 上試跑，重建成功才 commit；
    /// 任一步驟失敗則回滾，原 graph 不受影響。
    /// </summary>
    public async Task<PlanResult> ApplyPlanAsync(string projectId, List<CadCommand> commands, string planLabel = "")
    {
        var req = new { commands, plan_label = planLabel };
        var json = JsonSerializer.Serialize(req, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/apply_plan", content);
        var body = await response.Content.ReadAsStringAsync();

        JsonElement? result = null;
        if (!response.IsSuccessStatusCode && !TryParseStructuredError(body, out result))
        {
            return new PlanResult
            {
                Status = "error",
                ErrorCode = "TRANSPORT_ERROR",
                EngineMessage = $"HTTP {response.StatusCode}: {body}",
            };
        }

        result ??= JsonSerializer.Deserialize<JsonElement>(body, JsonOpts);

        var status = result.Value.TryGetProperty("status", out var st) ? st.GetString() ?? "" : "";

        var appliedFeatures = new List<string>();
        if (result.Value.TryGetProperty("applied_features", out var af) && af.ValueKind == JsonValueKind.Array)
        {
            appliedFeatures = af.EnumerateArray().Select(x => x.GetString()!).ToList();
        }

        return new PlanResult
        {
            Status = status,
            AppliedCount = result.Value.TryGetProperty("applied_count", out var ac) ? ac.GetInt32() : 0,
            AppliedFeatures = appliedFeatures,
            ErrorCode = result.Value.TryGetProperty("error_code", out var ec) ? ec.GetString() : null,
            EngineMessage = result.Value.TryGetProperty("engine_message", out var em) ? em.GetString() : null,
            MassProperties = result.Value.TryGetProperty("mass_properties", out var mp) ? ParseMassProperties(mp) : null,
        };
    }

    /// <summary>
    /// 原子性清除所有特徵（Clear All）——單一交易，一個 undo 步驟。
    /// </summary>
    public async Task<bool> ResetProjectAsync(string projectId)
    {
        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/reset", null);
        return response.IsSuccessStatusCode;
    }

    /// <summary>
    /// 求解草圖約束（WP1-2，互動式，不進入歷史）。
    /// 回傳 {entities, solver_status} JSON 字串。
    /// </summary>
    public async Task<string?> SolveSketchAsync(string projectId, string featureId, List<Dictionary<string, object>> entities, List<Dictionary<string, object>> constraints)
    {
        var req = new { entities, constraints };
        var json = JsonSerializer.Serialize(req, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/sketch/{featureId}/solve", content);
        if (!response.IsSuccessStatusCode) return null;
        return await response.Content.ReadAsStringAsync();
    }

    public async Task<string?> CreateReferenceGeometryAsync(string projectId, string id, string name, string kind, Dictionary<string, object> definition)
    {
        var req = new { id, name, kind, definition };
        var json = JsonSerializer.Serialize(req, JsonOpts);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _httpClient.PostAsync($"/api/projects/{projectId}/reference_geometry", content);
        if (!response.IsSuccessStatusCode) return null;
        return await response.Content.ReadAsStringAsync();
    }

    public async Task<bool> DeleteReferenceGeometryAsync(string projectId, string rgId)
    {
        var response = await _httpClient.DeleteAsync($"/api/projects/{projectId}/reference_geometry/{rgId}");
        return response.IsSuccessStatusCode;
    }

    public async Task<string?> ListReferenceGeometryAsync(string projectId)
    {
        var response = await _httpClient.GetAsync($"/api/projects/{projectId}/reference_geometry");
        if (!response.IsSuccessStatusCode) return null;
        return await response.Content.ReadAsStringAsync();
    }
}