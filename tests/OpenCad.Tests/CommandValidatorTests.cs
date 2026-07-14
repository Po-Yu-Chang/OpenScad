using OpenCad.Application;
using OpenCad.Domain;

namespace OpenCad.Tests;

/// <summary>
/// CommandValidator 本地驗證器測試——在送出 Worker 前攔截格式錯誤。
/// </summary>
public class CommandValidatorTests
{
    private static Feature MakeSketch(string id = "sk1") => new()
    {
        FeatureId = id,
        Type = FeatureType.Sketch,
        Name = "rect",
        SketchEntities = new() { new() { ["type"] = "rectangle", ["width"] = 10.0, ["height"] = 10.0 } },
        Plane = new() { ["base"] = "XY", ["offset"] = 0 },
    };

    private static Feature MakePad(string id = "pad1", string input = "sk1") => new()
    {
        FeatureId = id,
        Type = FeatureType.Pad,
        Name = "extrude",
        Input = input,
        References = new() { input },
        Parameters = new() { ["length"] = 5.0 },
    };

    [Fact]
    public void Validate_EmptyAction_ReturnsError()
    {
        var cmd = new CadCommand { Action = "" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Single(errors);
        Assert.Contains("action", errors[0]);
    }

    [Fact]
    public void Validate_CreateFeature_NullFeature_ReturnsError()
    {
        var cmd = new CadCommand { Action = "create_feature", Feature = null };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("feature 欄位"));
    }

    [Fact]
    public void Validate_Sketch_NoSketchEntities_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "sk1",
            Type = FeatureType.Sketch,
            Name = "empty sketch",
            SketchEntities = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("sketch_entities"));
    }

    [Fact]
    public void Validate_Pad_NoInput_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "pad1",
            Type = FeatureType.Pad,
            Name = "pad",
            Parameters = new() { ["length"] = 5.0 },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("input"));
    }

    [Fact]
    public void Validate_Fillet_NoRadius_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "f1",
            Type = FeatureType.Fillet,
            Name = "fillet",
            Input = "pad1",
            References = new() { "pad1" },
            Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("radius"));
    }

    [Fact]
    public void Validate_Fillet_NegativeRadius_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "f1",
            Type = FeatureType.Fillet,
            Name = "fillet",
            Input = "pad1",
            References = new() { "pad1" },
            Parameters = new() { ["radius"] = -2.0 },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("radius 必須 > 0"));
    }

    [Fact]
    public void Validate_Hole_NoDiameter_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "h1",
            Type = FeatureType.Hole,
            Name = "hole",
            Input = "pad1",
            Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("diameter"));
    }

    [Fact]
    public void Validate_Pocket_NoReferences_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "p1",
            Type = FeatureType.Pocket,
            Name = "pocket",
            Input = "pad1",
            References = new(),
            Parameters = new() { ["depth"] = 3.0 },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("references"));
    }

    [Fact]
    public void Validate_Shell_NoThickness_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "s1",
            Type = FeatureType.Shell,
            Name = "shell",
            Input = "pad1",
            Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("thickness"));
    }

    [Fact]
    public void Validate_ValidSketch_Passes()
    {
        var cmd = new CadCommand { Action = "create_feature", Feature = MakeSketch() };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_ValidPad_Passes()
    {
        var cmd = new CadCommand { Action = "create_feature", Feature = MakePad() };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_ValidFillet_Passes()
    {
        var feat = new Feature
        {
            FeatureId = "f1",
            Type = FeatureType.Fillet,
            Name = "fillet",
            Input = "pad1",
            References = new() { "pad1" },
            Parameters = new() { ["radius"] = 2.0, ["edge_selector"] = "all" },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_DeleteFeature_NoTarget_ReturnsError()
    {
        var cmd = new CadCommand { Action = "delete_feature" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("target_feature_id"));
    }

    [Fact]
    public void Validate_UpdateFeature_NoTarget_ReturnsError()
    {
        var cmd = new CadCommand { Action = "update_feature", Parameters = new() { ["x"] = 1.0 } };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("target_feature_id"));
    }

    [Fact]
    public void Validate_UnknownAction_ReturnsError()
    {
        var cmd = new CadCommand { Action = "do_something_weird" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("未知的 action"));
    }

    [Fact]
    public void Validate_Sketch_BadPlaneBase_ReturnsError()
    {
        var feat = MakeSketch();
        feat.Plane = new() { ["base"] = "DIAGONAL", ["offset"] = 0 };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("plane.base"));
    }

    [Fact]
    public void Validate_Fillet_RadiusMmSuffix_Passes()
    {
        var feat = new Feature
        {
            FeatureId = "f1",
            Type = FeatureType.Fillet,
            Name = "fillet",
            Input = "pad1",
            References = new() { "pad1" },
            Parameters = new() { ["radius_mm"] = 2.0 },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    // ── v2 command tests ──

    [Fact]
    public void Validate_SuppressFeature_NoTarget_ReturnsError()
    {
        var cmd = new CadCommand { Action = "suppress_feature" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("target_feature_id"));
    }

    [Fact]
    public void Validate_SuppressFeature_WithTarget_Passes()
    {
        var cmd = new CadCommand { Action = "suppress_feature", TargetFeatureId = "pad1" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_UnsuppressFeature_NoTarget_ReturnsError()
    {
        var cmd = new CadCommand { Action = "unsuppress_feature" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("target_feature_id"));
    }

    [Fact]
    public void Validate_ReorderFeature_NoNewOrder_ReturnsError()
    {
        var cmd = new CadCommand { Action = "reorder_feature", TargetFeatureId = "pad1" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("new_order"));
    }

    [Fact]
    public void Validate_ReorderFeature_WithNewOrder_Passes()
    {
        var cmd = new CadCommand
        {
            Action = "reorder_feature",
            TargetFeatureId = "pad1",
            Parameters = new() { ["new_order"] = 2 },
        };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_SetRollback_NoPosition_ReturnsError()
    {
        var cmd = new CadCommand { Action = "set_rollback" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("rollback_position"));
    }

    [Fact]
    public void Validate_SetRollback_WithNullPosition_Passes()
    {
        var cmd = new CadCommand
        {
            Action = "set_rollback",
            Parameters = new() { ["rollback_position"] = null! },
        };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    // ── WP-S1：C#↔Python validator 對稱測試——14 個原本 C# 沒檢查 input 的型別 ──
    // 與 cad-worker/cad_worker/validators/command_validator.py 的 REQUIRES_INPUT 對稱。

    [Theory]
    [InlineData(FeatureType.Sweep)]
    [InlineData(FeatureType.Loft)]
    [InlineData(FeatureType.Mirror)]
    [InlineData(FeatureType.LinearPattern)]
    [InlineData(FeatureType.CircularPattern)]
    [InlineData(FeatureType.BooleanUnion)]
    [InlineData(FeatureType.BooleanDifference)]
    [InlineData(FeatureType.BooleanIntersection)]
    [InlineData(FeatureType.Draft)]
    [InlineData(FeatureType.Rib)]
    [InlineData(FeatureType.Thin)]
    [InlineData(FeatureType.VariableFillet)]
    [InlineData(FeatureType.Countersink)]
    [InlineData(FeatureType.CosmeticThread)]
    public void Validate_NewFeatureType_NoInput_ReturnsError(FeatureType type)
    {
        var feat = new Feature
        {
            FeatureId = "f1",
            Type = type,
            Name = "test",
            Parameters = new() { ["thickness"] = 2.0, ["length"] = 5.0, ["diameter"] = 3.0 },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("input"));
    }

    [Fact]
    public void Validate_Rib_NoThickness_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "r1", Type = FeatureType.Rib, Name = "rib",
            Input = "pad1", Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("thickness"));
    }

    [Fact]
    public void Validate_Thin_MissingLengthAndThickness_ReturnsBothErrors()
    {
        var feat = new Feature
        {
            FeatureId = "t1", Type = FeatureType.Thin, Name = "thin",
            Input = "sk1", Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("length"));
        Assert.Contains(errors, e => e.Contains("thickness"));
    }

    [Fact]
    public void Validate_Countersink_NoDiameter_ReturnsError()
    {
        var feat = new Feature
        {
            FeatureId = "cs1", Type = FeatureType.Countersink, Name = "countersink",
            Input = "pad1", Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("diameter"));
    }

    [Fact]
    public void Validate_CosmeticThread_WithInput_Passes()
    {
        // cosmetic_thread 只需要 input，沒有額外必填參數（與 Python 對稱）
        var feat = new Feature
        {
            FeatureId = "ct1", Type = FeatureType.CosmeticThread, Name = "thread",
            Input = "pad1", Parameters = new() { ["diameter"] = 6.0 },
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_BooleanUnion_WithInput_Passes()
    {
        var feat = new Feature
        {
            FeatureId = "u1", Type = FeatureType.BooleanUnion, Name = "union",
            Input = "p1", References = new() { "p1", "p2" }, Parameters = new(),
        };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    // ── update_feature 只帶 constraints ──

    [Fact]
    public void Validate_UpdateFeature_OnlyConstraints_Passes()
    {
        var cmd = new CadCommand
        {
            Action = "update_feature",
            TargetFeatureId = "sk1",
            Constraints = new() { new() { ["id"] = "c1", ["type"] = "horizontal", ["targets"] = new List<object> { "e1" } } },
        };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_UpdateFeature_NoFieldsAtAll_ReturnsError()
    {
        var cmd = new CadCommand { Action = "update_feature", TargetFeatureId = "sk1" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("constraints"));
    }

    // ── plane.base datum:<id> ──

    [Fact]
    public void Validate_Sketch_DatumPlaneBase_Passes()
    {
        var feat = MakeSketch();
        feat.Plane = new() { ["base"] = "datum:dp1", ["offset"] = 0 };
        var cmd = new CadCommand { Action = "create_feature", Feature = feat };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    // ── reference_geometry 三個 action ──

    [Fact]
    public void Validate_CreateReferenceGeometry_MissingFields_ReturnsErrors()
    {
        var cmd = new CadCommand { Action = "create_reference_geometry" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("reference_geometry 欄位"));
    }

    [Fact]
    public void Validate_CreateReferenceGeometry_Valid_Passes()
    {
        var cmd = new CadCommand
        {
            Action = "create_reference_geometry",
            ReferenceGeometry = new()
            {
                ["id"] = "dp1",
                ["kind"] = "plane",
                ["definition"] = new Dictionary<string, object> { ["method"] = "offset" },
            },
        };
        var errors = CommandValidator.Validate(cmd);
        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_DeleteReferenceGeometry_NoTarget_ReturnsError()
    {
        var cmd = new CadCommand { Action = "delete_reference_geometry" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("target_feature_id"));
    }

    [Fact]
    public void Validate_UpdateReferenceGeometry_NoPayload_ReturnsError()
    {
        var cmd = new CadCommand { Action = "update_reference_geometry", TargetFeatureId = "dp1" };
        var errors = CommandValidator.Validate(cmd);
        Assert.Contains(errors, e => e.Contains("reference_geometry 欄位"));
    }
}