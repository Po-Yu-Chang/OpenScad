using OpenCad.Application;
using Xunit;

namespace OpenCad.Tests;

/// <summary>
/// 本地意圖解析測試——單一 <see cref="IntentMatcher.Parse"/> 一次只回一個結果。
/// 重點回歸：關鍵字衝突（「取消還原」）與否定詞（「不要還原」）不得誤觸破壞性操作。
/// </summary>
public class IntentMatcherTests
{
    // ── Parse：正向 ──
    [Theory]
    [InlineData("幫我還原", LocalIntentKind.Undo)]
    [InlineData("回上一步", LocalIntentKind.Undo)]
    [InlineData("復原", LocalIntentKind.Undo)]
    [InlineData("撤銷", LocalIntentKind.Undo)]
    [InlineData("取消還原", LocalIntentKind.Redo)]
    [InlineData("取消復原", LocalIntentKind.Redo)]
    [InlineData("重做", LocalIntentKind.Redo)]
    [InlineData("全部都取消", LocalIntentKind.ClearAll)]
    [InlineData("清空整個模型", LocalIntentKind.ClearAll)]
    [InlineData("從頭開始", LocalIntentKind.ClearAll)]
    [InlineData("重新開始畫一個圓", LocalIntentKind.ClearAll)] // 「重新開始」屬 strong 清空片語，故命中 ClearAll
    [InlineData("縮放至適合", LocalIntentKind.ZoomFit)]
    [InlineData("基準面顯示", LocalIntentKind.ToggleDatumPlanes)]
    [InlineData("重建", LocalIntentKind.Rebuild)]
    public void Parse_Positive(string input, LocalIntentKind expected)
        => Assert.Equal(expected, IntentMatcher.Parse(input).Kind);

    // ── Parse：否定 / 誤判防止 → None ──
    [Theory]
    [InlineData("不要還原")]
    [InlineData("先不要清空")]
    [InlineData("我剛剛說的還原是什麼意思？")]
    [InlineData("清空孔位後重新排列")]   // 只有裸「清空」、無其他意圖 → None
    [InlineData("建立一個 60×60×5 底板")]
    public void Parse_NoneCases(string input)
        => Assert.Equal(LocalIntentKind.None, IntentMatcher.Parse(input).Kind);

    // ── 關鍵回歸：取消還原只命中 Redo（曾因 IsUndo 含「還原」被誤判為 Undo）──
    [Fact]
    public void Parse_CancelRestore_IsRedoNotUndo()
        => Assert.Equal(LocalIntentKind.Redo, IntentMatcher.Parse("取消還原").Kind);

    // ── 歧義：多意圖並存（Undo + 弱清空）──
    [Fact]
    public void Parse_RestoreThenClear_IsAmbiguous()
        => Assert.Equal(LocalIntentKind.Ambiguous, IntentMatcher.Parse("還原後清空").Kind);

    // ── SetView 帶視角字串 ──
    [Theory]
    [InlineData("等角", "iso")]
    [InlineData("前視", "front")]
    [InlineData("俯視", "top")]
    [InlineData("右視", "right")]
    public void Parse_SetView_CarriesView(string input, string view)
    {
        var it = IntentMatcher.Parse(input);
        Assert.Equal(LocalIntentKind.SetView, it.Kind);
        Assert.Equal(view, it.View);
    }

    // ── MatchView（仍為 public helper）──
    [Theory]
    [InlineData("側視", "right")]
    [InlineData("iso", "iso")]
    public void MatchView_Works(string input, string expected)
        => Assert.Equal(expected, IntentMatcher.MatchView(input));

    [Fact]
    public void MatchView_NullForNonView()
        => Assert.Null(IntentMatcher.MatchView("建立方塊"));

    // ── Classify shim：舊字串契約仍可用 ──
    [Theory]
    [InlineData("復原", "undo")]
    [InlineData("取消還原", "redo")]   // 回歸：不可為 undo
    [InlineData("重做", "redo")]
    [InlineData("等角", "view:iso")]
    [InlineData("縮放至適合", "zoom_fit")]
    [InlineData("基準面顯示", "datum_toggle")]
    [InlineData("重建", "rebuild")]
    [InlineData("全部都取消", "clear_all")]
    public void Classify_KnownIntents(string input, string expected)
        => Assert.Equal(expected, IntentMatcher.Classify(input));

    // ── Classify → null（交回 LLM）：否定、弱清空單獨、歧義、一般建模語句 ──
    [Theory]
    [InlineData("不要還原")]
    [InlineData("清空")]              // 弱清空單獨出現 → None → null
    [InlineData("還原後清空")]        // Ambiguous → null
    [InlineData("建立一個底板")]
    public void Classify_ReturnsNull(string input)
        => Assert.Null(IntentMatcher.Classify(input));
}
