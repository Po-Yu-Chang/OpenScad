using System.Text.Json;
using OpenCad.Desktop.Services;

namespace OpenCad.Tests;

/// <summary>
/// WP1-0R: AppSettings engine parsing tests.
/// Verifies default values and JSON deserialization for the engine settings.
/// </summary>
public class AppSettingsEngineTests
{
    [Fact]
    public void Default_Engine_Is_Build123d()
    {
        var settings = new AppSettings();
        Assert.Equal("build123d", settings.Engine);
    }

    [Fact]
    public void Default_FreeCadDir_Is_Empty()
    {
        var settings = new AppSettings();
        Assert.Equal("", settings.FreeCadDir);
    }

    [Fact]
    public void Deserialize_Engine_Freecad()
    {
        var json = """{"engine":"freecad","freecad_dir":"C:\\FreeCAD"}""";
        var settings = JsonSerializer.Deserialize<AppSettings>(json);
        Assert.NotNull(settings);
        Assert.Equal("freecad", settings!.Engine);
        Assert.Equal("C:\\FreeCAD", settings.FreeCadDir);
    }

    [Fact]
    public void Deserialize_Missing_Engine_Defaults_To_Build123d()
    {
        // Settings JSON without engine field should default to build123d
        var json = """{"llm":{"provider":"none"}}""";
        var settings = JsonSerializer.Deserialize<AppSettings>(json);
        Assert.NotNull(settings);
        Assert.Equal("build123d", settings!.Engine);
        Assert.Equal("", settings.FreeCadDir);
    }

    [Fact]
    public void RoundTrip_Preserves_Engine()
    {
        var settings = new AppSettings { Engine = "freecad", FreeCadDir = "/path/to/freecad" };
        var json = JsonSerializer.Serialize(settings);
        var deserialized = JsonSerializer.Deserialize<AppSettings>(json);
        Assert.NotNull(deserialized);
        Assert.Equal("freecad", deserialized!.Engine);
        Assert.Equal("/path/to/freecad", deserialized.FreeCadDir);
    }
}