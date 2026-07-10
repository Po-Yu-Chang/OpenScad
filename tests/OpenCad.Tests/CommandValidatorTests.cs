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
}