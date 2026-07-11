using System.Text.Json;
using OpenCad.Infrastructure;
using Serilog;

namespace OpenCad.Tests;

/// <summary>
/// Tests for CadWorkerProcess to verify engine selection and error handling.
/// </summary>
public class CadWorkerProcessTests
{
    [Fact]
    public void CadWorkerProcess_With_Freecad_Engine_But_Missing_Python_Should_Log_Error()
    {
        // Arrange
        var workerPath = Path.GetTempPath();
        var pythonPath = Path.Combine(Path.GetTempPath(), "nonexistent_python.exe");
        var engine = "freecad";
        var freecadDir = Path.Combine(Path.GetTempPath(), "freecad");
        
        // Create a mock logger to capture log messages
        using var logCapture = new LogCapture();
        var logger = new LoggerConfiguration()
            .MinimumLevel.Information()
            .WriteTo.Sink(logCapture)
            .CreateLogger();

        // Act
        var workerProcess = new CadWorkerProcess(workerPath, pythonPath, engine, freecadDir, logger);
        
        // Assert
        // The constructor should log a warning about the Python path not containing "FreeCAD"
        Assert.Contains(logCapture.LogEvents, e => 
            e.Level == Serilog.Events.LogEventLevel.Warning && 
            e.MessageTemplate.Text.Contains("引擎設為 freecad 但 Python 路徑似乎不是 FreeCAD 的 Python"));
    }

    [Fact]
    public async Task CadWorkerProcess_StartAsync_With_Freecad_Engine_But_Missing_Python_Should_Return_False()
    {
        // Arrange
        var workerPath = Path.GetTempPath();
        var pythonPath = Path.Combine(Path.GetTempPath(), "nonexistent_python.exe");
        var engine = "freecad";
        var freecadDir = Path.Combine(Path.GetTempPath(), "freecad");
        
        // Create a mock logger to capture log messages
        using var logCapture = new LogCapture();
        var logger = new LoggerConfiguration()
            .MinimumLevel.Information()
            .WriteTo.Sink(logCapture)
            .CreateLogger();

        var workerProcess = new CadWorkerProcess(workerPath, pythonPath, engine, freecadDir, logger);
        
        // Act
        var result = await workerProcess.StartAsync();
        
        // Assert
        Assert.False(result);
        Assert.Contains(logCapture.LogEvents, e => 
            e.Level == Serilog.Events.LogEventLevel.Error && 
            e.MessageTemplate.Text.Contains("引擎設為 freecad 但找不到指定的 Python 可執行檔"));
    }
}

// Helper class to capture log events for testing
public class LogCapture : Serilog.Core.ILogEventSink, IDisposable
{
    private readonly List<Serilog.Events.LogEvent> _logEvents = new();
    private readonly object _lock = new();

    public IReadOnlyList<Serilog.Events.LogEvent> LogEvents
    {
        get
        {
            lock (_lock)
            {
                return _logEvents.ToList();
            }
        }
    }

    public void Emit(Serilog.Events.LogEvent logEvent)
    {
        lock (_lock)
        {
            _logEvents.Add(logEvent);
        }
    }

    public void Dispose()
    {
        // Nothing to dispose
    }
}