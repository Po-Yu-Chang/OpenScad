using System.Text.Json;
using OpenCad.Domain;

namespace OpenCad.Tests;

/// <summary>
/// Feature Graph 拓撲排序與依賴追蹤測試。
/// </summary>
public class FeatureGraphTests
{
    private static Feature CreateFeature(string id, string name, FeatureType type, params string[] refs)
    {
        return new Feature
        {
            FeatureId = id,
            Name = name,
            Type = type,
            References = refs.ToList(),
            Parameters = new Dictionary<string, object>(),
            Constraints = new List<Dictionary<string, object>>()
        };
    }

    [Fact]
    public void TopologicalSort_EmptyGraph_ReturnsEmptyList()
    {
        var graph = new FeatureGraph();
        var result = graph.TopologicalSort();
        Assert.Empty(result);
    }

    [Fact]
    public void TopologicalSort_SingleFeature_ReturnsThatFeature()
    {
        var graph = new FeatureGraph();
        graph.Features["base"] = CreateFeature("base", "Base", FeatureType.Sketch);
        var result = graph.TopologicalSort();
        Assert.Single(result);
        Assert.Equal("base", result[0]);
    }

    [Fact]
    public void TopologicalSort_ChainedDependencies_ReturnsInOrder()
    {
        var graph = new FeatureGraph();
        graph.Features["base"] = CreateFeature("base", "Base", FeatureType.Sketch);
        graph.Features["pad"] = CreateFeature("pad", "Pad", FeatureType.Pad, "base");
        graph.Features["pocket"] = CreateFeature("pocket", "Pocket", FeatureType.Pocket, "pad");
        var result = graph.TopologicalSort();
        Assert.Equal(3, result.Count);
        Assert.Equal("base", result[0]);
        Assert.Equal("pad", result[1]);
        Assert.Equal("pocket", result[2]);
    }

    [Fact]
    public void TopologicalSort_CircularDependency_ThrowsException()
    {
        var graph = new FeatureGraph();
        graph.Features["a"] = CreateFeature("a", "A", FeatureType.Sketch, "b");
        graph.Features["b"] = CreateFeature("b", "B", FeatureType.Pad, "a");
        Assert.Throws<InvalidOperationException>(() => graph.TopologicalSort());
    }

    [Fact]
    public void GetDownstream_ReturnsAllDependents()
    {
        var graph = new FeatureGraph();
        graph.Features["base"] = CreateFeature("base", "Base", FeatureType.Sketch);
        graph.Features["pad"] = CreateFeature("pad", "Pad", FeatureType.Pad, "base");
        graph.Features["fillet"] = CreateFeature("fillet", "Fillet", FeatureType.Fillet, "pad");
        var downstream = graph.GetDownstream("base");
        Assert.Contains("pad", downstream);
        Assert.Contains("fillet", downstream);
    }

    [Fact]
    public void GetDownstream_NoDependents_ReturnsEmpty()
    {
        var graph = new FeatureGraph();
        graph.Features["base"] = CreateFeature("base", "Base", FeatureType.Sketch);
        graph.Features["other"] = CreateFeature("other", "Other", FeatureType.Sketch);
        var downstream = graph.GetDownstream("base");
        Assert.Empty(downstream);
    }

    [Fact]
    public void Feature_SerializeToJson_RoundTrips()
    {
        var feature = CreateFeature("box1", "Box 1", FeatureType.Sketch);
        feature.Parameters["width"] = 50.0;
        feature.Parameters["depth"] = 10.0;

        var json = JsonSerializer.Serialize(feature);
        var deserialized = JsonSerializer.Deserialize<Feature>(json);

        Assert.NotNull(deserialized);
        Assert.Equal("box1", deserialized!.FeatureId);
        Assert.Equal("Box 1", deserialized.Name);
        Assert.Equal(FeatureType.Sketch, deserialized.Type);
    }

    [Fact]
    public void FeatureGraph_SerializeToJson_RoundTrips()
    {
        var graph = new FeatureGraph();
        graph.Features["base"] = CreateFeature("base", "Base", FeatureType.Sketch);
        graph.Features["pad"] = CreateFeature("pad", "Pad", FeatureType.Pad, "base");

        var json = JsonSerializer.Serialize(graph);
        var deserialized = JsonSerializer.Deserialize<FeatureGraph>(json);

        Assert.NotNull(deserialized);
        Assert.Equal(2, deserialized!.Features.Count);
        Assert.True(deserialized.Features.ContainsKey("base"));
        Assert.True(deserialized.Features.ContainsKey("pad"));
    }

    // ── v2 tests ──

    [Fact]
    public void Feature_V2_DefaultBodyIsBody1()
    {
        var feature = CreateFeature("x", "X", FeatureType.Sketch);
        Assert.Equal("body1", feature.Body);
    }

    [Fact]
    public void Feature_V2_DefaultStateIsActive()
    {
        var feature = CreateFeature("x", "X", FeatureType.Sketch);
        Assert.Equal(FeatureState.Active, feature.State);
    }

    [Fact]
    public void Feature_V2_BodyOrderState_SerializeRoundTrip()
    {
        var feature = new Feature
        {
            FeatureId = "pad1",
            Name = "Pad 1",
            Type = FeatureType.Pad,
            Body = "body2",
            Order = 3,
            State = FeatureState.Suppressed,
        };

        var json = JsonSerializer.Serialize(feature);
        var deserialized = JsonSerializer.Deserialize<Feature>(json);

        Assert.NotNull(deserialized);
        Assert.Equal("body2", deserialized!.Body);
        Assert.Equal(3, deserialized.Order);
        Assert.Equal(FeatureState.Suppressed, deserialized.State);
    }

    [Fact]
    public void FeatureGraph_V2_DefaultBodiesHasBody1()
    {
        var graph = new FeatureGraph();
        Assert.Single(graph.Bodies);
        Assert.Equal("body1", graph.Bodies[0].Id);
    }

    [Fact]
    public void FeatureGraph_V2_RollbackPositionDefaultNull()
    {
        var graph = new FeatureGraph();
        Assert.Null(graph.RollbackPosition);
    }

    [Fact]
    public void FeatureGraph_V2_GlobalVariablesDefaultEmpty()
    {
        var graph = new FeatureGraph();
        Assert.Empty(graph.GlobalVariables);
    }

    [Fact]
    public void FeatureGraph_V2_ConfigurationsDefaultEmpty()
    {
        var graph = new FeatureGraph();
        Assert.Empty(graph.Configurations);
    }

    [Fact]
    public void FeatureGraph_V2_CustomPropertiesDefaultEmpty()
    {
        var graph = new FeatureGraph();
        Assert.Empty(graph.CustomProperties);
    }

    [Fact]
    public void FeatureGraph_V2_ReferenceGeometryDefaultEmpty()
    {
        var graph = new FeatureGraph();
        Assert.Empty(graph.ReferenceGeometry);
    }

    [Fact]
    public void FeatureGraph_V2_BodiesSerializeRoundTrip()
    {
        var graph = new FeatureGraph();
        graph.Bodies.Add(new BodyDefinition { Id = "body2", Name = "Second", Material = "AL6061" });

        var json = JsonSerializer.Serialize(graph);
        var deserialized = JsonSerializer.Deserialize<FeatureGraph>(json);

        Assert.NotNull(deserialized);
        Assert.Equal(2, deserialized!.Bodies.Count);
        Assert.Equal("body2", deserialized.Bodies[1].Id);
        Assert.Equal("AL6061", deserialized.Bodies[1].Material);
    }

    [Fact]
    public void Feature_V2_FailedStateSerializeRoundTrip()
    {
        var feature = new Feature
        {
            FeatureId = "bad1",
            Name = "Bad",
            Type = FeatureType.Fillet,
            State = FeatureState.Failed,
            ErrorMessage = "radius too large",
        };

        var json = JsonSerializer.Serialize(feature);
        var deserialized = JsonSerializer.Deserialize<Feature>(json);

        Assert.NotNull(deserialized);
        Assert.Equal(FeatureState.Failed, deserialized!.State);
        Assert.Equal("radius too large", deserialized.ErrorMessage);
    }

    [Fact]
    public void Feature_V2_OrphanStateSerializeRoundTrip()
    {
        var feature = new Feature
        {
            FeatureId = "orphan1",
            Name = "Orphaned",
            Type = FeatureType.Hole,
            State = FeatureState.Orphan,
        };

        var json = JsonSerializer.Serialize(feature);
        var deserialized = JsonSerializer.Deserialize<Feature>(json);

        Assert.NotNull(deserialized);
        Assert.Equal(FeatureState.Orphan, deserialized!.State);
    }
}