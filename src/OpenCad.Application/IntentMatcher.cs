using System.Text;
using System.Text.RegularExpressions;

namespace OpenCad.Application;

/// <summary>本地意圖種類——使用者輸入對應的確定性 UI 操作。</summary>
public enum LocalIntentKind
{
    None,
    Undo,
    Redo,
    ClearAll,
    Rebuild,
    ZoomFit,
    SetView,
    ToggleDatumPlanes,
    Ambiguous
}

/// <summary>本地意圖結果；View 只在 SetView 時帶 "iso"/"front"/"top"/"right"。</summary>
public readonly record struct LocalIntent(LocalIntentKind Kind, string? View = null);

/// <summary>
/// 本地意圖匹配——在使用者輸入送達 LLM 之前，先攔截確定性的 UI 操作。
/// 這些操作（復原、重做、視角、縮放、基準面、重建）有明確的 UI 對應，送 LLM 只會增加延遲與誤判。
/// 單一 <see cref="Parse"/> 一次只回一個結果，避免關鍵字衝突（「取消還原」曾被誤判為 Undo）。
/// </summary>
public static class IntentMatcher
{
    // 否定詞——出現即不執行任何確定性操作（避免「不要還原」誤觸）。
    private static readonly string[] Negations = { "不要", "先不要", "別", "不用", "甭" };
    // 疑問語境——使用者只是在問，不是下令。
    private static readonly string[] Questions = { "什麼意思", "是什麼", "怎麼回事", "為什麼" };

    // Redo 先於 Undo 比對：「取消還原/取消復原」必須只命中 Redo。
    private static readonly string[] RedoKeywords = { "取消還原", "取消復原", "重做", "下一步", "redo" };
    private static readonly string[] UndoKeywords = { "復原", "撤銷", "還原", "上一步", "撤回", "undo" };

    // ClearAll：strong 片語命中即清空；weak 裸詞只在與其他意圖並存時造成歧義。
    private static readonly string[] StrongClear = { "全部都取消", "清空整個模型", "從頭開始", "全部清空", "重新開始" };
    private static readonly string[] WeakClear = { "清空", "清除", "清掉" };

    private static readonly string[] ZoomToFitKeywords = { "縮放至適合", "全視圖", "適應視窗", "fit" };
    private static readonly string[] RebuildKeywords = { "重建", "重新生成", "rebuild" };

    /// <summary>解析輸入，一次只回一個本地意圖；非本地意圖回 <see cref="LocalIntentKind.None"/>。</summary>
    public static LocalIntent Parse(string input)
    {
        var s = Normalize(input);
        if (s.Length == 0) return new LocalIntent(LocalIntentKind.None);

        // 否定詞 / 疑問語境優先：一律不執行。
        if (ContainsAny(s, Negations) || ContainsAny(s, Questions))
            return new LocalIntent(LocalIntentKind.None);

        var intents = new List<LocalIntentKind>();

        // Redo 先於 Undo。
        if (ContainsAny(s, RedoKeywords)) intents.Add(LocalIntentKind.Redo);
        else if (ContainsAny(s, UndoKeywords)) intents.Add(LocalIntentKind.Undo);

        bool strongClear = ContainsAny(s, StrongClear);
        if (strongClear) intents.Add(LocalIntentKind.ClearAll);

        string? view = MatchView(s);
        if (view != null) intents.Add(LocalIntentKind.SetView);

        if (ContainsAny(s, ZoomToFitKeywords)) intents.Add(LocalIntentKind.ZoomFit);
        if (IsDatumPlaneToggle(s)) intents.Add(LocalIntentKind.ToggleDatumPlanes);
        if (ContainsAny(s, RebuildKeywords)) intents.Add(LocalIntentKind.Rebuild);

        // 弱清空特例：無 strong 清空、但有裸「清空」且已存在其他意圖 → 歧義（如「還原後清空」）。
        if (!strongClear && ContainsAny(s, WeakClear) && intents.Count >= 1)
            return new LocalIntent(LocalIntentKind.Ambiguous);

        if (intents.Count > 1) return new LocalIntent(LocalIntentKind.Ambiguous);
        if (intents.Count == 1)
        {
            var kind = intents[0];
            return kind == LocalIntentKind.SetView
                ? new LocalIntent(kind, view)
                : new LocalIntent(kind);
        }
        return new LocalIntent(LocalIntentKind.None);
    }

    /// <summary>相容 shim：沿用舊字串契約，內部走 <see cref="Parse"/>。Ambiguous/None 皆回 null（交回 LLM）。</summary>
    public static string? Classify(string input)
    {
        var it = Parse(input);
        return it.Kind switch
        {
            LocalIntentKind.Undo => "undo",
            LocalIntentKind.Redo => "redo",
            LocalIntentKind.ClearAll => "clear_all",
            LocalIntentKind.SetView => $"view:{it.View}",
            LocalIntentKind.ZoomFit => "zoom_fit",
            LocalIntentKind.ToggleDatumPlanes => "datum_toggle",
            LocalIntentKind.Rebuild => "rebuild",
            _ => null
        };
    }

    /// <summary>匹配視角操作，回傳 "iso"/"front"/"top"/"right" 或 null。</summary>
    public static string? MatchView(string s)
    {
        s = Normalize(s);
        if (s.Contains("等角") || Has(s, "iso")) return "iso";
        if (s.Contains("正視") || s.Contains("前視")) return "front";
        if (s.Contains("俯視") || s.Contains("上視") || Has(s, "top")) return "top";
        if (s.Contains("右視") || s.Contains("側視") || Has(s, "right")) return "right";
        return null;
    }

    private static bool IsDatumPlaneToggle(string s) =>
        s.Contains("基準面") && (s.Contains("顯示") || s.Contains("隱藏") || s.Contains("切換") || s.Contains("開關"));

    private static string Normalize(string input)
    {
        if (string.IsNullOrEmpty(input)) return string.Empty;
        var n = input.Normalize(NormalizationForm.FormKC).Trim();
        return Regex.Replace(n, @"\s+", " ");
    }

    private static bool ContainsAny(string s, string[] keywords)
    {
        foreach (var k in keywords)
            if (Has(s, k)) return true;
        return false;
    }

    private static bool Has(string s, string keyword) =>
        s.Contains(keyword, StringComparison.OrdinalIgnoreCase);
}
