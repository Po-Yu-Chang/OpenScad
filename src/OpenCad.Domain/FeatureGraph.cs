using System.Text.Json.Serialization;

namespace OpenCad.Domain;

/// <summary>
/// Feature Graph 中的特徵節點。
/// 每個特徵至少需要：feature_id、type、name、input、parameters、references、
/// source、llm_description、validation、rebuild_status、error_message。
/// </summary>
public class Feature
{
    [JsonPropertyName("feature_id")]
    public string FeatureId { get; set; } = string.Empty;

    [JsonPropertyName("type")]
    [JsonConverter(typeof(SnakeCaseEnumConverter))]
    public FeatureType Type { get; set; }

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("input")]
    public string? Input { get; set; }

    [JsonPropertyName("references")]
    public List<string> References { get; set; } = new();

    [JsonPropertyName("sketch_entities")]
    public List<Dictionary<string, object>> SketchEntities { get; set; } = new();

    [JsonPropertyName("constraints")]
    public List<Dictionary<string, object>> Constraints { get; set; } = new();

    [JsonPropertyName("parameters")]
    public Dictionary<string, object> Parameters { get; set; } = new();

    [JsonPropertyName("standard_parts")]
    public Dictionary<string, object> StandardParts { get; set; } = new();

    [JsonPropertyName("plane")]
    public Dictionary<string, object> Plane { get; set; } = new() { ["base"] = "XY", ["offset"] = 0 };

    [JsonPropertyName("validation")]
    public ValidationSpec? Validation { get; set; }

    [JsonPropertyName("source")]
    [JsonConverter(typeof(SnakeCaseEnumConverter))]
    public FeatureSource Source { get; set; } = FeatureSource.Llm;

    [JsonPropertyName("llm_description")]
    public string LlmDescription { get; set; } = string.Empty;

    [JsonPropertyName("rebuild_status")]
    [JsonConverter(typeof(SnakeCaseEnumConverter))]
    public RebuildStatus RebuildStatus { get; set; } = RebuildStatus.Pending;

    [JsonPropertyName("error_message")]
    public string ErrorMessage { get; set; } = string.Empty;

    // v2 fields

    [JsonPropertyName("body")]
    public string Body { get; set; } = "body1";

    [JsonPropertyName("order")]
    public int? Order { get; set; }

    [JsonPropertyName("state")]
    [JsonConverter(typeof(SnakeCaseEnumConverter))]
    public FeatureState State { get; set; } = FeatureState.Active;
}

/// <summary>
/// Feature Graph——管理特徵依賴關係與拓撲排序。
/// 特徵只描述意圖與參數，由各 Adapter 負責轉譯（引擎中立）。
/// </summary>
public class FeatureGraph
{
    [JsonPropertyName("features")]
    public Dictionary<string, Feature> Features { get; set; } = new();

    // v2 document model fields

    [JsonPropertyName("bodies")]
    public List<BodyDefinition> Bodies { get; set; } = new() { new BodyDefinition { Id = "body1", Name = "主體" } };

    [JsonPropertyName("reference_geometry")]
    public List<ReferenceGeometryDefinition> ReferenceGeometry { get; set; } = new();

    [JsonPropertyName("rollback_position")]
    public int? RollbackPosition { get; set; }

    [JsonPropertyName("global_variables")]
    public List<GlobalVariable> GlobalVariables { get; set; } = new();

    [JsonPropertyName("configurations")]
    public List<ConfigurationDefinition> Configurations { get; set; } = new();

    [JsonPropertyName("custom_properties")]
    public Dictionary<string, object> CustomProperties { get; set; } = new();

    /// <summary>
    /// 拓撲排序，回傳特徵 ID 列表（上游在前）。
    /// </summary>
    public List<string> TopologicalSort()
    {
        var visited = new HashSet<string>();
        var tempMarked = new HashSet<string>();
        var result = new List<string>();

        void Visit(string fid)
        {
            if (visited.Contains(fid)) return;
            if (tempMarked.Contains(fid))
                throw new InvalidOperationException($"偵測到循環依賴：{fid}");

            tempMarked.Add(fid);

            if (Features.TryGetValue(fid, out var feature))
            {
                foreach (var ref_ in feature.References)
                {
                    if (Features.ContainsKey(ref_))
                        Visit(ref_);
                }
                if (feature.Input is { } input && Features.ContainsKey(input))
                    Visit(input);
            }

            tempMarked.Remove(fid);
            visited.Add(fid);
            result.Add(fid);
        }

        foreach (var fid in Features.Keys)
            Visit(fid);

        return result;
    }

    /// <summary>
    /// 取得目標特徵的所有下游依賴。
    /// </summary>
    public List<string> GetDownstream(string featureId)
    {
        var downstream = new List<string>();
        var seen = new HashSet<string>();

        void Collect(string fid)
        {
            foreach (var (id, feature) in Features)
            {
                if (id == fid) continue;
                if (feature.References.Contains(fid) || feature.Input == fid)
                {
                    if (seen.Add(id))
                    {
                        downstream.Add(id);
                        Collect(id);
                    }
                }
            }
        }

        Collect(featureId);
        return downstream;
    }
}

/// <summary>
/// 實體定義（v2）。
/// </summary>
public class BodyDefinition
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("material")]
    public string Material { get; set; } = string.Empty;

    [JsonPropertyName("appearance")]
    public string? Appearance { get; set; }
}

/// <summary>
/// 基準幾何定義（v2，WP1-3 填充）。
/// </summary>
public class ReferenceGeometryDefinition
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("type")]
    public string Type { get; set; } = "plane"; // plane|axis|point|csys

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("definition")]
    public Dictionary<string, object>? Definition { get; set; }
}

/// <summary>
/// 全域變數（v2，WP2-1 填充）。
/// </summary>
public class GlobalVariable
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("expression")]
    public string Expression { get; set; } = string.Empty;

    [JsonPropertyName("unit")]
    public string Unit { get; set; } = "mm";
}

/// <summary>
/// 組態定義（v2，WP2-2 填充）。
/// </summary>
public class ConfigurationDefinition
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("parent")]
    public string? Parent { get; set; }

    [JsonPropertyName("overrides")]
    public Dictionary<string, object> Overrides { get; set; } = new();
}