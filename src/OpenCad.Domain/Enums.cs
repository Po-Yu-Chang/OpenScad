using System.Text.Json;
using System.Text.Json.Serialization;

namespace OpenCad.Domain;

/// <summary>
/// snake_case 列舉轉換器——Python Worker 的 enum 值為 snake_case
/// （如 "linear_pattern"），C# 序列化必須一致，否則 Worker 端 ValueError。
/// </summary>
public class SnakeCaseEnumConverter : JsonStringEnumConverter
{
    public SnakeCaseEnumConverter() : base(JsonNamingPolicy.SnakeCaseLower) { }
}

/// <summary>
/// 特徵類型列舉。對應 Feature Graph 中的 type 欄位。
/// </summary>
[JsonConverter(typeof(SnakeCaseEnumConverter))]
public enum FeatureType
{
    Sketch,
    Pad,
    Pocket,
    Revolve,
    Sweep,
    Loft,
    Hole,
    LinearPattern,
    CircularPattern,
    Mirror,
    Fillet,
    Chamfer,
    Shell,
    BooleanUnion,
    BooleanDifference,
    BooleanIntersection,
    Draft,
    Rib,
    Thin,
    VariableFillet,
    Countersink,
    CosmeticThread,
}

/// <summary>
/// 重建狀態。
/// </summary>
[JsonConverter(typeof(SnakeCaseEnumConverter))]
public enum RebuildStatus
{
    Pending,
    Building,
    Success,
    Failed,
}

/// <summary>
/// 特徵建立來源。
/// </summary>
[JsonConverter(typeof(SnakeCaseEnumConverter))]
public enum FeatureSource
{
    Llm,
    User,
    Imported,
}

/// <summary>
/// 特徵狀態機（v2）。
/// </summary>
[JsonConverter(typeof(SnakeCaseEnumConverter))]
public enum FeatureState
{
    Active,
    Suppressed,
    Failed,
    Orphan,
}