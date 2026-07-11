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

    /// <summary>
    /// WP-H1: 取得 Capability payload——引擎能力資訊供 LLM context。
    /// </summary>
    Task<CapabilityPayload> GetCapabilityPayloadAsync();
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
/// WP-H1 Capability payload——每次 LLM context 必帶的引擎能力資訊。
/// </summary>
public class CapabilityPayload
{
    public string SchemaVersion { get; set; } = "1.0";
    public string EngineVersion { get; set; } = "opencad-worker-1.0";
    public string FeatureCatalogJson { get; set; } = "[]";
    public List<string> UnsupportedFeatures { get; set; } = new();
    public List<string> Tools { get; set; } = new();
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

    /// <summary>
    /// Dry-run 重建（WP-H1 rebuild_staging）——只試跑不 commit。
    /// </summary>
    Task<RebuildResult> RebuildStagingAsync(string projectId);

    /// <summary>
    /// 取得 Capability payload（WP-H1）——引擎能力資訊供 LLM context。
    /// </summary>
    Task<string?> GetCapabilityAsync();

    /// <summary>驗證模型。</summary>
    Task<ValidationReport> ValidateAsync(string projectId);

    /// <summary>匯出模型。</summary>
    Task<string> ExportAsync(string projectId, string format);

    /// <summary>取得 GLB 預覽的 URL（WP-H2：內含短時效預簽 token，單次有效）。</summary>
    Task<string> GetPreviewUrlAsync(string projectId);

    /// <summary>取得 display_map 的 URL（面/邊拓撲對應表，供 viewer picking；預簽 token 單次有效）。</summary>
    Task<string> GetDisplayMapUrlAsync(string projectId);

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

    /// <summary>
    /// 交易式套用多個命令（staging + rollback）。
    /// 所有命令在 staging graph 上試跑，重建成功才 commit；
    /// 任一步驟失敗則回滾，原 graph 不受影響。
    /// </summary>
    Task<PlanResult> ApplyPlanAsync(string projectId, List<CadCommand> commands, string planLabel = "");

    /// <summary>
    /// 原子性清除所有特徵（Clear All）——單一交易，一個 undo 步驟。
    /// </summary>
    Task<bool> ResetProjectAsync(string projectId);

    /// <summary>
    /// 求解草圖約束（WP1-2，互動式，不進入歷史）。
    /// 回傳 {entities, solver_status} JSON 字串。
    /// </summary>
    Task<string?> SolveSketchAsync(string projectId, string featureId, List<Dictionary<string, object>> entities, List<Dictionary<string, object>> constraints);

    /// <summary>
    /// 建立基準幾何（WP1-3）。回傳更新後的 reference_geometry JSON 字串。
    /// </summary>
    Task<string?> CreateReferenceGeometryAsync(string projectId, string id, string name, string kind, Dictionary<string, object> definition);

    /// <summary>
    /// 刪除基準幾何（WP1-3）。
    /// </summary>
    Task<bool> DeleteReferenceGeometryAsync(string projectId, string rgId);

    /// <summary>
    /// 列出基準幾何（WP1-3）。回傳 reference_geometry JSON 陣列字串。
    /// </summary>
    Task<string?> ListReferenceGeometryAsync(string projectId);
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
    public int MeshRevision { get; set; }
    public string? ErrorCode { get; set; }
    public string? EngineMessage { get; set; }
    public MassProperties? MassProperties { get; set; }
}

/// <summary>
/// 交易式套用計畫的結果。所有命令在 staging graph 上試跑，
/// 重建成功才 commit；任一步驟失敗則回滾，原 graph 不受影響。
/// </summary>
public class PlanResult
{
    public string Status { get; set; } = string.Empty;
    public int AppliedCount { get; set; }
    public List<string> AppliedFeatures { get; set; } = new();
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