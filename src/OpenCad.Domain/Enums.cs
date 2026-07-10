using System.Text.Json.Serialization;

namespace OpenCad.Domain;

/// <summary>
/// 特徵類型列舉。對應 Feature Graph 中的 type 欄位。
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum FeatureType
{
    Sketch,
    Pad,
    Pocket,
    Revolve,
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
}

/// <summary>
/// 重建狀態。
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
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
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum FeatureSource
{
    Llm,
    User,
    Imported,
}