using OpenCad.Domain;

namespace OpenCad.Application;

/// <summary>
/// LLM 提供者介面。不綁死單一模型，可支援 Ollama、llama.cpp、vLLM 等。
/// </summary>
public interface ILlmProvider
{
    /// <summary>
    /// 將設計需求轉成可審查的建模計畫。
    /// </summary>
    Task<DesignPlan> CreatePlanAsync(DesignContext context);

    /// <summary>
    /// 將建模計畫轉成受控 JSON Command。
    /// </summary>
    Task<CadCommand> CreateCommandAsync(DesignPlan plan);

    /// <summary>
    /// 根據使用者修改需求與目前特徵圖，產生 update_feature 命令。
    /// </summary>
    Task<CadCommand> CreateUpdateCommandAsync(string userRequest, string featureGraphJson, List<ChatTurn>? history = null);

    /// <summary>
    /// 讀取幾何檢查報告並提出修正建議。
    /// </summary>
    Task<ReviewResult> ReviewResultAsync(ValidationReport report);

    /// <summary>
    /// 根據重建錯誤碼與引擎訊息，產生修正命令（Repair Agent）。
    /// </summary>
    Task<CadCommand> RepairCommandAsync(string errorCode, string engineMessage, string featureGraphJson);
}

/// <summary>
/// 設計上下文——包含使用者需求與目前專案狀態。
/// </summary>
public class DesignContext
{
    public string UserRequest { get; set; } = string.Empty;
    public string? CurrentProjectId { get; set; }
    public FeatureGraph? CurrentGraph { get; set; }
    public List<string> AvailableStandards { get; set; } = new();
    public List<ChatTurn> History { get; set; } = new();
}

/// <summary>
/// LLM 對話紀錄的一個輪次。
/// </summary>
public class ChatTurn
{
    public string Role { get; set; } = string.Empty;
    public string Content { get; set; } = string.Empty;
}

/// <summary>
/// LLM 審查結果。
/// </summary>
public class ReviewResult
{
    public bool Passed { get; set; }
    public string Summary { get; set; } = string.Empty;
    public List<string> Issues { get; set; } = new();
    public CadCommand? SuggestedFix { get; set; }
}

/// <summary>
/// CAD Worker 介面——與 Python 幾何引擎的通訊合約。
/// </summary>
public interface ICadWorker
{
    /// <summary>建立專案。</summary>
    Task<string> CreateProjectAsync(string name, string description = "");

    /// <summary>套用受控命令。</summary>
    Task<CommandResult> ApplyCommandAsync(string projectId, CadCommand command);

    /// <summary>重建模型。</summary>
    Task<RebuildResult> RebuildAsync(string projectId);

    /// <summary>驗證模型。</summary>
    Task<ValidationReport> ValidateAsync(string projectId);

    /// <summary>匯出模型。</summary>
    Task<string> ExportAsync(string projectId, string format);

    /// <summary>取得 GLB 預覽的 URL。</summary>
    string GetPreviewUrl(string projectId);

    /// <summary>健康檢查。</summary>
    Task<bool> CheckHealthAsync();

    /// <summary>取得專案特徵圖（用於更新特徵樹）。</summary>
    Task<string> GetProjectAsync(string projectId);

    /// <summary>取得所有專案列表。</summary>
    Task<string> ListProjectsAsync();

    /// <summary>復原到上一版。</summary>
    Task<bool> UndoAsync(string projectId);

    /// <summary>重做到下一版。</summary>
    Task<bool> RedoAsync(string projectId);
}

public class CommandResult
{
    public string Status { get; set; } = string.Empty;
    public string? FeatureId { get; set; }
    public string? ErrorCode { get; set; }
    public string? EngineMessage { get; set; }
    public List<string>? AffectedFeatures { get; set; }
}

public class RebuildResult
{
    public string Status { get; set; } = string.Empty;
    public int FeatureCount { get; set; }
    public string? ErrorCode { get; set; }
    public string? EngineMessage { get; set; }
    public MassProperties? MassProperties { get; set; }
}

public class MassProperties
{
    public double VolumeMm3 { get; set; }
    public double SurfaceAreaMm2 { get; set; }
    public double MassG { get; set; }
    public string Material { get; set; } = string.Empty;
    public double DensityGcm3 { get; set; }
    public BoundingBoxMm? BoundingBoxMm { get; set; }
}

public class BoundingBoxMm
{
    public double MinX { get; set; }
    public double MinY { get; set; }
    public double MinZ { get; set; }
    public double MaxX { get; set; }
    public double MaxY { get; set; }
    public double MaxZ { get; set; }
    public double SizeX { get; set; }
    public double SizeY { get; set; }
    public double SizeZ { get; set; }
}