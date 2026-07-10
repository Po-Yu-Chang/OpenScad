using System.Text.Json;
using OpenCad.Domain;

namespace OpenCad.Tests;

/// <summary>
/// CadCommand JSON 序列化與驗證測試。
/// </summary>
public class CommandSchemaTests
{
    [Fact]
    public void CadCommand_SerializeToJson_ValidStructure()
    {
        var cmd = new CadCommand
        {
            Action = "add_feature",
            Feature = new Feature
            {
                FeatureId = "test_box",
                Name = "Test Box",
                Type = FeatureType.Sketch,
                References = new List<string>(),
                Parameters = new Dictionary<string, object>
                {
                    ["width"] = 50.0,
                    ["depth"] = 10.0
                },
                Constraints = new List<Dictionary<string, object>>()
            },
            Reasoning = "使用者要求建立一個測試方塊"
        };

        var json = JsonSerializer.Serialize(cmd);
        Assert.Contains("add_feature", json);
        Assert.Contains("test_box", json);
        Assert.Contains("Test Box", json);
        Assert.Contains("sketch", json);
        Assert.Contains("50", json);
    }

    [Fact]
    public void CadCommand_DeserializeFromJson_RoundTrips()
    {
        var json = """
        {
            "schema_version": "1.0",
            "action": "add_feature",
            "feature": {
                "feature_id": "box1",
                "type": "sketch",
                "name": "Box 1",
                "references": [],
                "parameters": {
                    "width": 30.0
                },
                "constraints": []
            },
            "reasoning": "測試"
        }
        """;

        var cmd = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.NotNull(cmd);
        Assert.Equal("add_feature", cmd!.Action);
        Assert.NotNull(cmd.Feature);
        Assert.Equal("box1", cmd.Feature!.FeatureId);
        Assert.Equal("Box 1", cmd.Feature.Name);
        Assert.Equal(FeatureType.Sketch, cmd.Feature.Type);
        Assert.Empty(cmd.Feature.References);
        Assert.Single(cmd.Feature.Parameters);
        Assert.Equal("測試", cmd.Reasoning);
    }

    [Fact]
    public void CadCommand_DeleteFeature_HasTargetFeatureId()
    {
        var cmd = new CadCommand
        {
            Action = "delete_feature",
            TargetFeatureId = "unwanted_feature",
            Reasoning = "使用者要求刪除"
        };

        var json = JsonSerializer.Serialize(cmd);
        var deserialized = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.Equal("delete_feature", deserialized!.Action);
        Assert.Equal("unwanted_feature", deserialized.TargetFeatureId);
        Assert.Equal("使用者要求刪除", deserialized.Reasoning);
    }

    [Fact]
    public void CadCommand_UpdateParameter_HasParameters()
    {
        var cmd = new CadCommand
        {
            Action = "update_parameter",
            TargetFeatureId = "base_block",
            Parameters = new Dictionary<string, object>
            {
                ["width"] = 60.0
            },
            Reasoning = "使用者修改寬度"
        };

        var json = JsonSerializer.Serialize(cmd);
        var deserialized = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.Equal("update_parameter", deserialized!.Action);
        Assert.Equal("base_block", deserialized.TargetFeatureId);
        Assert.True(deserialized.Parameters!.ContainsKey("width"));
        var value = (System.Text.Json.JsonElement)deserialized.Parameters["width"];
        Assert.Equal(60.0, value.GetDouble());
    }

    [Fact]
    public void CadCommand_Export_HasExportFormat()
    {
        var cmd = new CadCommand
        {
            Action = "export",
            ExportFormat = "step",
            Reasoning = "使用者要求匯出 STEP"
        };

        var json = JsonSerializer.Serialize(cmd);
        var deserialized = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.Equal("export", deserialized!.Action);
        Assert.Equal("step", deserialized.ExportFormat);
    }

    [Fact]
    public void ParameterValue_DefaultUnit_IsMm()
    {
        var pv = new ParameterValue(50.0);
        Assert.Equal("mm", pv.Unit);
        Assert.Equal(50.0, pv.Value);
    }

    [Fact]
    public void ParameterValue_ToMm_ConvertsCorrectly()
    {
        var mm = new ParameterValue(50.0, "mm");
        var cm = new ParameterValue(5.0, "cm");
        var inch = new ParameterValue(1.0, "inch");

        Assert.Equal(50.0, mm.ToMm());
        Assert.Equal(50.0, cm.ToMm());
        Assert.Equal(25.4, inch.ToMm());
    }

    [Fact]
    public void ParameterValue_Mm_FactoryCreatesCorrectly()
    {
        var pv = ParameterValue.Mm(30.0);
        Assert.Equal(30.0, pv.Value);
        Assert.Equal("mm", pv.Unit);
    }

    [Fact]
    public void ValidationReport_Defaults_AreValid()
    {
        var report = new ValidationReport();
        Assert.True(report.IsValid);
        Assert.Empty(report.Errors);
        Assert.Empty(report.Warnings);
    }
}