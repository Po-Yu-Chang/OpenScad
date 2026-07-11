using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace OpenCad.Desktop.Services;

/// <summary>
/// LLM 連線設定。
/// </summary>
public class LlmSettings
{
    /// <summary>提供者："auto"（預設）｜"openai"｜"ollama"｜"none"。
    /// auto：有設定 base_url 時用 OpenAI-compatible，否則自動偵測本機 Ollama。</summary>
    [JsonPropertyName("provider")]
    public string Provider { get; set; } = "auto";

    /// <summary>OpenAI-compatible API 基底位址，含 /v1（如 http://gateway.local:4000/v1）。</summary>
    [JsonPropertyName("base_url")]
    public string BaseUrl { get; set; } = "";

    /// <summary>API 金鑰——只存在本機設定檔，不隨專案散布。</summary>
    [JsonPropertyName("api_key")]
    public string ApiKey { get; set; } = "";

    /// <summary>模型名稱（如 coding-cloud、qwen2.5-coder:14b）。</summary>
    [JsonPropertyName("model")]
    public string Model { get; set; } = "";
}

/// <summary>
/// 應用程式設定——存於使用者家目錄 ~/.opencad/settings.json，
/// 不在 repo 內（機敏資訊如 API key 不得進版控）。
/// </summary>
public class AppSettings
{
    [JsonPropertyName("llm")]
    public LlmSettings Llm { get; set; } = new();

    /// <summary>幾何引擎："build123d"（預設）或 "freecad"。
    /// 僅開發機便利——正式打包另議。</summary>
    [JsonPropertyName("engine")]
    public string Engine { get; set; } = "build123d";

    /// <summary>FreeCAD 安裝目錄路徑。空字串＝使用 repo 根的
    /// FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\（僅開發機便利）。</summary>
    [JsonPropertyName("freecad_dir")]
    public string FreeCadDir { get; set; } = "";

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
    };

    public static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".opencad", "settings.json");

    public static AppSettings Load()
    {
        try
        {
            if (File.Exists(SettingsPath))
            {
                var json = File.ReadAllText(SettingsPath);
                return JsonSerializer.Deserialize<AppSettings>(json, JsonOpts) ?? new AppSettings();
            }
        }
        catch
        {
            // 設定檔損壞——使用預設值，不讓 App 崩潰
        }
        return new AppSettings();
    }

    public void Save()
    {
        var dir = Path.GetDirectoryName(SettingsPath)!;
        Directory.CreateDirectory(dir);
        File.WriteAllText(SettingsPath, JsonSerializer.Serialize(this, JsonOpts));
    }

    /// <summary>
    /// 確保設定檔存在（不存在時寫入含註解範本的預設檔），回傳檔案路徑。
    /// </summary>
    public static string EnsureSettingsFile()
    {
        if (!File.Exists(SettingsPath))
        {
            new AppSettings().Save();
        }
        return SettingsPath;
    }
}
