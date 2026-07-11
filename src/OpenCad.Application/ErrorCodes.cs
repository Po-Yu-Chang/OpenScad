namespace OpenCad.Application;

/// <summary>
/// 結構化錯誤碼——Worker 失敗時回傳，Repair Agent 只消費此結構。
/// 錯誤代碼採固定枚舉並隨 Schema 版本控管。
/// </summary>
public static class ErrorCodes
{
    public const string FilletRadiusTooLarge = "FILLET_RADIUS_TOO_LARGE";
    public const string ShellFailed = "SHELL_FAILED";
    public const string BooleanOperationFailed = "BOOLEAN_OPERATION_FAILED";
    public const string FeatureReferenceNotFound = "FEATURE_REFERENCE_NOT_FOUND";
    public const string CircularDependency = "CIRCULAR_DEPENDENCY";
    public const string GeometryError = "GEOMETRY_ERROR";
    public const string ZeroVolume = "ZERO_VOLUME";
    public const string MultipleSolids = "MULTIPLE_SOLIDS";
    public const string InvalidBrep = "INVALID_BREP";
    public const string InvalidStandardPart = "INVALID_STANDARD_PART";
    public const string SketchNotClosed = "SKETCH_NOT_CLOSED";
    public const string ReferenceLost = "REFERENCE_LOST";
    public const string ReferenceAmbiguous = "REFERENCE_AMBIGUOUS";
    public const string ReorderDependencyViolation = "REORDER_DEPENDENCY_VIOLATION";
    public const string TransportError = "TRANSPORT_ERROR";
}

/// <summary>
/// 結構化錯誤——Worker 回傳格式。
/// </summary>
public class StructuredError
{
    public string ErrorCode { get; set; } = string.Empty;
    public string? FailedFeatureId { get; set; }
    public string Stage { get; set; } = string.Empty;
    public string EngineMessage { get; set; } = string.Empty;
    public string? SuggestionScope { get; set; }

    /// <summary>
    /// 依據錯誤碼取得修復建議範圍。
    /// </summary>
    public static string GetSuggestionScope(string errorCode) => errorCode switch
    {
        ErrorCodes.FilletRadiusTooLarge => "reduce_radius_or_split_edges",
        ErrorCodes.ShellFailed => "reduce_shell_thickness_or_change_open_face",
        ErrorCodes.BooleanOperationFailed => "check_overlap_or_reference_geometry",
        ErrorCodes.FeatureReferenceNotFound => "verify_feature_id_exists",
        ErrorCodes.CircularDependency => "break_dependency_cycle",
        ErrorCodes.ZeroVolume => "check_dimensions_are_positive",
        ErrorCodes.MultipleSolids => "check_boolean_operations",
        ErrorCodes.InvalidBrep => "check_geometry_integrity",
        ErrorCodes.InvalidStandardPart => "verify_standard_exists_in_lookup_table",
        ErrorCodes.SketchNotClosed => "ensure_profile_is_closed",
        ErrorCodes.ReferenceLost => "reference_disappeared_rerun_or_reselect",
        ErrorCodes.ReferenceAmbiguous => "disambiguate_reference_add_centroid_hint",
        ErrorCodes.ReorderDependencyViolation => "reorder_after_upstream_dependencies",
        ErrorCodes.TransportError => "check_worker_process_and_connection",
        _ => "review_error_details",
    };
}