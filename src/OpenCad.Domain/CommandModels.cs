using System.Text.Json.Serialization;

namespace OpenCad.Domain;

/// <summary>
/// 受控命令。LLM 產生此 JSON，由確定性執行器處理。
/// LLM 不得直接產生 Python 或 OpenSCAD 程式碼。
/// </summary>
public class CadCommand
{
    [JsonPropertyName("schema_version")]
    public string SchemaVersion { get; set; } = "1.0";

    [JsonPropertyName("action")]
    public string Action { get; set; } = string.Empty;

    [JsonPropertyName("document_id")]
    public string? DocumentId { get; set; }

    [JsonPropertyName("target_feature_id")]
    public string? TargetFeatureId { get; set; }

    [JsonPropertyName("feature")]
    public Feature? Feature { get; set; }

    [JsonPropertyName("parameters")]
    public Dictionary<string, object>? Parameters { get; set; }

    [JsonPropertyName("preserve")]
    public List<string> Preserve { get; set; } = new();

    [JsonPropertyName("export_format")]
    public string? ExportFormat { get; set; }

    [JsonPropertyName("standard_parts")]
    public Dictionary<string, object>? StandardParts { get; set; }

    [JsonPropertyName("reasoning")]
    public string Reasoning { get; set; } = string.Empty;
}

/// <summary>
/// 設計計畫——LLM Planner 的輸出，供使用者審查後才執行。
/// </summary>
public class DesignPlan
{
    [JsonPropertyName("steps")]
    public List<DesignStep> Steps { get; set; } = new();

    [JsonPropertyName("summary")]
    public string Summary { get; set; } = string.Empty;

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = new();

    [JsonPropertyName("missing_info")]
    public List<string> MissingInfo { get; set; } = new();
}

public class DesignStep
{
    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;

    [JsonPropertyName("feature_type")]
    public string FeatureType { get; set; } = string.Empty;

    [JsonPropertyName("parameters")]
    public Dictionary<string, object> Parameters { get; set; } = new();
}

/// <summary>
/// 幾何驗證報告。
/// </summary>
public class ValidationReport
{
    [JsonPropertyName("is_valid")]
    public bool IsValid { get; set; } = true;

    [JsonPropertyName("solid_count")]
    public int SolidCount { get; set; }

    [JsonPropertyName("size_x")]
    public double SizeX { get; set; }

    [JsonPropertyName("size_y")]
    public double SizeY { get; set; }

    [JsonPropertyName("size_z")]
    public double SizeZ { get; set; }

    [JsonPropertyName("volume")]
    public double Volume { get; set; }

    [JsonPropertyName("surface_area")]
    public double SurfaceArea { get; set; }

    [JsonPropertyName("hole_count")]
    public int HoleCount { get; set; }

    [JsonPropertyName("minimum_wall_thickness")]
    public double MinimumWallThickness { get; set; }

    [JsonPropertyName("is_closed_solid")]
    public bool IsClosedSolid { get; set; }

    [JsonPropertyName("errors")]
    public List<string> Errors { get; set; } = new();

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = new();
}

/// <summary>
/// 修改前後差異。
/// </summary>
public class ModificationDiff
{
    [JsonPropertyName("feature_id")]
    public string FeatureId { get; set; } = string.Empty;

    [JsonPropertyName("before")]
    public Dictionary<string, object> Before { get; set; } = new();

    [JsonPropertyName("after")]
    public Dictionary<string, object> After { get; set; } = new();

    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;
}