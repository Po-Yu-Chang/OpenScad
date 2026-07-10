using System.Text.Json;
using OpenCad.Domain;

namespace OpenCad.Tests;

/// <summary>
/// 測試新增的 CAD action 類型（delete_feature, set_material, rebuild）
/// 與特徵類型（mirror, sweep, loft）的 JSON 序列化往返。
/// 這些是 LLM prompt 修復後 LLM 會產生的命令類型，必須能正確反序列化。
/// </summary>
public class NewActionTypesTests
{
    // ── delete_feature ──

    [Fact]
    public void CadCommand_DeleteFeature_SerializesCorrectly()
    {
        var cmd = new CadCommand
        {
            Action = "delete_feature",
            TargetFeatureId = "fillet_1",
            Reasoning = "使用者要求刪除最後的圓角"
        };

        var json = JsonSerializer.Serialize(cmd);
        Assert.Contains("\"action\":\"delete_feature\"", json);
        Assert.Contains("\"target_feature_id\":\"fillet_1\"", json);
    }

    [Fact]
    public void CadCommand_DeleteFeature_DeserializesFromLlmJson()
    {
        var json = """
        {
            "schema_version": "1.0",
            "action": "delete_feature",
            "target_feature_id": "pocket_1",
            "reasoning": "使用者要求刪除"
        }
        """;

        var cmd = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.NotNull(cmd);
        Assert.Equal("delete_feature", cmd!.Action);
        Assert.Equal("pocket_1", cmd.TargetFeatureId);
        Assert.Equal("使用者要求刪除", cmd.Reasoning);
    }

    // ── set_material ──

    [Fact]
    public void CadCommand_SetMaterial_SerializesCorrectly()
    {
        var cmd = new CadCommand
        {
            Action = "set_material",
            Parameters = new Dictionary<string, object>
            {
                ["material"] = "aluminum"
            },
            Reasoning = "使用者要求改為鋁合金"
        };

        var json = JsonSerializer.Serialize(cmd);
        Assert.Contains("\"action\":\"set_material\"", json);
        Assert.Contains("\"material\":\"aluminum\"", json);
    }

    [Fact]
    public void CadCommand_SetMaterial_DeserializesFromLlmJson()
    {
        var json = """
        {
            "schema_version": "1.0",
            "action": "set_material",
            "parameters": { "material": "steel" },
            "reasoning": "改為鋼材"
        }
        """;

        var cmd = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.NotNull(cmd);
        Assert.Equal("set_material", cmd!.Action);
        Assert.NotNull(cmd.Parameters);
        Assert.True(cmd.Parameters!.ContainsKey("material"));
        var mat = (JsonElement)cmd.Parameters["material"];
        Assert.Equal("steel", mat.GetString());
    }

    // ── rebuild (不支援功能的回應) ──

    [Fact]
    public void CadCommand_Rebuild_DeserializesFromLlmJson()
    {
        var json = """
        {
            "schema_version": "1.0",
            "action": "rebuild",
            "reasoning": "目前不支援 rib（加強肋）功能"
        }
        """;

        var cmd = JsonSerializer.Deserialize<CadCommand>(json);
        Assert.NotNull(cmd);
        Assert.Equal("rebuild", cmd!.Action);
        Assert.Contains("不支援", cmd.Reasoning);
    }

    // ── Feature Types: mirror, sweep, loft ──

    [Fact]
    public void Feature_MirrorType_SerializesAsSnakeCase()
    {
        var feat = new Feature
        {
            FeatureId = "mirror_1",
            Type = FeatureType.Mirror,
            Name = "鏡射",
            Input = "pad_1",
            Parameters = new Dictionary<string, object>(),
            References = new List<string>(),
            Constraints = new List<Dictionary<string, object>>()
        };

        var json = JsonSerializer.Serialize(feat);
        Assert.Contains("\"type\":\"mirror\"", json);
        Assert.Contains("\"feature_id\":\"mirror_1\"", json);
    }

    [Fact]
    public void Feature_SweepType_SerializesWithReferences()
    {
        var feat = new Feature
        {
            FeatureId = "sweep_1",
            Type = FeatureType.Sweep,
            Name = "掃掠彎管",
            Input = "profile_sketch",
            References = new List<string> { "path_sketch" },
            Parameters = new Dictionary<string, object>(),
            Constraints = new List<Dictionary<string, object>>()
        };

        var json = JsonSerializer.Serialize(feat);
        Assert.Contains("\"type\":\"sweep\"", json);
        Assert.Contains("\"references\":[\"path_sketch\"]", json);
    }

    [Fact]
    public void Feature_LoftType_SerializesWithMultipleReferences()
    {
        var feat = new Feature
        {
            FeatureId = "loft_1",
            Type = FeatureType.Loft,
            Name = "漸變段",
            Input = "profile_1",
            References = new List<string> { "profile_2", "profile_3" },
            Parameters = new Dictionary<string, object>(),
            Constraints = new List<Dictionary<string, object>>()
        };

        var json = JsonSerializer.Serialize(feat);
        Assert.Contains("\"type\":\"loft\"", json);
        Assert.Contains("\"profile_2\"", json);
        Assert.Contains("\"profile_3\"", json);
    }

    [Fact]
    public void Feature_SweepType_DeserializesFromLlmJson()
    {
        var json = """
        {
            "feature_id": "sweep_1",
            "type": "sweep",
            "name": "彎管",
            "input": "profile_sketch",
            "references": ["path_sketch"],
            "parameters": {},
            "constraints": []
        }
        """;

        var feat = JsonSerializer.Deserialize<Feature>(json);
        Assert.NotNull(feat);
        Assert.Equal(FeatureType.Sweep, feat!.Type);
        Assert.Equal("profile_sketch", feat.Input);
        Assert.Single(feat.References);
        Assert.Equal("path_sketch", feat.References[0]);
    }

    [Fact]
    public void Feature_LoftType_DeserializesFromLlmJson()
    {
        var json = """
        {
            "feature_id": "loft_1",
            "type": "loft",
            "name": "錐形",
            "input": "profile_1",
            "references": ["profile_2", "profile_3"],
            "parameters": {},
            "constraints": []
        }
        """;

        var feat = JsonSerializer.Deserialize<Feature>(json);
        Assert.NotNull(feat);
        Assert.Equal(FeatureType.Loft, feat!.Type);
        Assert.Equal(2, feat.References.Count);
        Assert.Equal("profile_2", feat.References[0]);
        Assert.Equal("profile_3", feat.References[1]);
    }

    [Fact]
    public void Feature_MirrorType_DeserializesFromLlmJson()
    {
        var json = """
        {
            "feature_id": "mirror_1",
            "type": "mirror",
            "name": "鏡射特徵",
            "input": "pad_1",
            "references": [],
            "parameters": {},
            "constraints": []
        }
        """;

        var feat = JsonSerializer.Deserialize<Feature>(json);
        Assert.NotNull(feat);
        Assert.Equal(FeatureType.Mirror, feat!.Type);
        Assert.Equal("pad_1", feat.Input);
    }

    // ── Hole with positions (陣列孔) ──

    [Fact]
    public void Feature_HoleWithPositions_DeserializesFromLlmJson()
    {
        var json = """
        {
            "feature_id": "mount_holes",
            "type": "hole",
            "name": "四個固定孔",
            "input": "pad_1",
            "references": [],
            "parameters": {
                "diameter": 3.5,
                "through_all": true,
                "positions": [[15.5, 15.5], [46.5, 15.5], [15.5, 46.5], [46.5, 46.5]]
            },
            "constraints": []
        }
        """;

        var feat = JsonSerializer.Deserialize<Feature>(json);
        Assert.NotNull(feat);
        Assert.Equal(FeatureType.Hole, feat!.Type);
        Assert.True(feat.Parameters.ContainsKey("positions"));
        Assert.True(feat.Parameters.ContainsKey("through_all"));
    }

    // ── All FeatureType enums serialize as snake_case ──

    [Theory]
    [InlineData(FeatureType.Sketch, "sketch")]
    [InlineData(FeatureType.Pad, "pad")]
    [InlineData(FeatureType.Pocket, "pocket")]
    [InlineData(FeatureType.Revolve, "revolve")]
    [InlineData(FeatureType.Sweep, "sweep")]
    [InlineData(FeatureType.Loft, "loft")]
    [InlineData(FeatureType.Hole, "hole")]
    [InlineData(FeatureType.LinearPattern, "linear_pattern")]
    [InlineData(FeatureType.CircularPattern, "circular_pattern")]
    [InlineData(FeatureType.Mirror, "mirror")]
    [InlineData(FeatureType.Fillet, "fillet")]
    [InlineData(FeatureType.Chamfer, "chamfer")]
    [InlineData(FeatureType.Shell, "shell")]
    [InlineData(FeatureType.BooleanUnion, "boolean_union")]
    [InlineData(FeatureType.BooleanDifference, "boolean_difference")]
    [InlineData(FeatureType.BooleanIntersection, "boolean_intersection")]
    public void FeatureType_SerializesAsSnakeCase(FeatureType type, string expected)
    {
        var feat = new Feature
        {
            FeatureId = "test",
            Type = type,
            Name = "test",
            Parameters = new Dictionary<string, object>(),
            References = new List<string>(),
            Constraints = new List<Dictionary<string, object>>()
        };

        var json = JsonSerializer.Serialize(feat);
        Assert.Contains($"\"type\":\"{expected}\"", json);
    }
}