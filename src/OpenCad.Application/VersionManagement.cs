using OpenCad.Domain;

namespace OpenCad.Application;

/// <summary>
/// 版本管理服務——每次修改至少保存使用者原始要求、LLM 建模計畫、
/// 實際執行命令、修改前後參數、幾何檢查結果、執行時間、使用的模型與版本、是否由使用者接受。
/// </summary>
public class RevisionRecord
{
    public int RevisionNumber { get; set; }
    public string UserRequest { get; set; } = string.Empty;
    public DesignPlan? LlmPlan { get; set; }
    public CadCommand? ExecutedCommand { get; set; }
    public Dictionary<string, object>? ParametersBefore { get; set; }
    public Dictionary<string, object>? ParametersAfter { get; set; }
    public ValidationReport? ValidationReport { get; set; }
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public string? ModelName { get; set; }
    public string? ModelVersion { get; set; }
    public bool AcceptedByUser { get; set; }
}

public interface IVersionManager
{
    void SaveRevision(string projectId, RevisionRecord record);
    List<RevisionRecord> GetRevisions(string projectId);
    RevisionRecord? GetRevision(string projectId, int revisionNumber);
    bool Undo(string projectId);
    bool Redo(string projectId);
}

/// <summary>
/// 修改確認服務——執行前顯示修改計畫，執行後顯示修改前後差異。
/// 可接受、拒絕或回復修改。
/// </summary>
public class ModificationConfirmation
{
    public string Description { get; set; } = string.Empty;
    public List<ModificationDiff> Changes { get; set; } = new();
    public List<string> Preserved { get; set; } = new();
    public List<string> ValidationChecks { get; set; } = new();
}