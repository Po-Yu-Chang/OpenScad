namespace OpenCad.Application;

/// <summary>
/// 本地意圖匹配——在使用者輸入送達 LLM 之前，先攔截確定性的 UI 操作。
/// 這些操作（復原、重做、視角、縮放、基準面、重建）有明確的 UI 對應，
/// 送 LLM 只會增加延遲和誤判。
/// </summary>
public static class IntentMatcher
{
    /// <summary>判斷是否為復原意圖。</summary>
    public static bool IsUndo(string s) =>
        s.Contains("復原") || s.Contains("撤銷") || s.Equals("undo", StringComparison.OrdinalIgnoreCase);

    /// <summary>判斷是否為重做意圖。</summary>
    public static bool IsRedo(string s) =>
        s.Contains("重做") || s.Contains("取消復原") || s.Equals("redo", StringComparison.OrdinalIgnoreCase);

    /// <summary>匹配視角操作，回傳 "iso"/"front"/"top"/"right" 或 null。</summary>
    public static string? MatchView(string s)
    {
        if (s.Contains("等角") || s.Contains("iso")) return "iso";
        if (s.Contains("正視") || s.Contains("前視")) return "front";
        if (s.Contains("俯視") || s.Contains("上視") || s.Contains("top")) return "top";
        if (s.Contains("右視") || s.Contains("側視") || s.Contains("right")) return "right";
        return null;
    }

    /// <summary>判斷是否為縮放至適合意圖。</summary>
    public static bool IsZoomToFit(string s) =>
        s.Contains("縮放至適合") || s.Contains("全視圖") || s.Contains("適應視窗") || s.Contains("fit");

    /// <summary>判斷是否為基準面顯示/隱藏切換意圖。</summary>
    public static bool IsDatumPlaneToggle(string s) =>
        s.Contains("基準面") && (s.Contains("顯示") || s.Contains("隱藏") || s.Contains("切換") || s.Contains("開關"));

    /// <summary>判斷是否為重建意圖。</summary>
    public static bool IsRebuild(string s) =>
        s.Contains("重建") || s.Contains("重新生成") ||
        s.Equals("rebuild", StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// 綜合判斷：如果輸入匹配任何本地意圖，回傳意圖類型；否則回 null。
    /// </summary>
    public static string? Classify(string input)
    {
        var s = input.Trim();
        if (IsUndo(s)) return "undo";
        if (IsRedo(s)) return "redo";
        if (MatchView(s) is { } view) return $"view:{view}";
        if (IsZoomToFit(s)) return "zoom_fit";
        if (IsDatumPlaneToggle(s)) return "datum_toggle";
        if (IsRebuild(s)) return "rebuild";
        return null;
    }
}