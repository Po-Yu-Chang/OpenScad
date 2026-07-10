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
}