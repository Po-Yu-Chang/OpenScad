using System.Text.Json;
using System.Text.Json.Serialization;

namespace OpenCad.Domain;

/// <summary>
/// 帶單位的參數值。Feature Graph 內部一律以 mm 為正準單位保存。
/// </summary>
public class ParameterValue
{
    [JsonPropertyName("value")]
    public double Value { get; set; }

    [JsonPropertyName("unit")]
    public string Unit { get; set; } = "mm";

    public ParameterValue() { }

    public ParameterValue(double value, string unit = "mm")
    {
        Value = value;
        Unit = unit;
    }

    /// <summary>
    /// 將值轉換為 mm。
    /// </summary>
    public double ToMm() => Unit switch
    {
        "mm" => Value,
        "cm" => Value * 10.0,
        "m" => Value * 1000.0,
        "inch" => Value * 25.4,
        "deg" => Value,
        "rad" => Value,
        _ => Value,
    };

    public static ParameterValue Mm(double value) => new(value, "mm");

    public static ParameterValue Inch(double value) => new(value, "inch");

    public static ParameterValue Cm(double value) => new(value, "cm");
}

/// <summary>
/// 驗證條件規格。
/// </summary>
public class ValidationSpec
{
    [JsonPropertyName("min_thickness_mm")]
    public double? MinThicknessMm { get; set; }

    [JsonPropertyName("must_be_single_solid")]
    public bool? MustBeSingleSolid { get; set; }

    [JsonPropertyName("expected_hole_count")]
    public int? ExpectedHoleCount { get; set; }
}