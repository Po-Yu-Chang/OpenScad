using OpenCad.Application;

namespace OpenCad.Tests;

/// <summary>
/// 意圖攔截測試——驗證使用者的繁體中文輸入能正確匹配到對應的 UI 操作，
/// 不被送到 LLM。涵蓋 SolidWorks 常見操作的繁體中文情境。
/// </summary>
public class IntentMatcherTests
{
    // ── Undo ──

    [Theory]
    [InlineData("復原")]
    [InlineData("撤銷")]
    [InlineData("undo")]
    [InlineData("UNDO")]
    [InlineData("Undo")]
    [InlineData("復原上一步")]
    [InlineData("把上次的圓角取消，復原")]
    public void IsUndo_MatchesUndoKeywords(string input)
    {
        Assert.True(IntentMatcher.IsUndo(input));
    }

    [Theory]
    [InlineData("建立一個方塊")]
    [InlineData("加圓角")]
    [InlineData("redo")]
    [InlineData("重做")]
    [InlineData("")]
    public void IsUndo_DoesNotMatchNonUndoInput(string input)
    {
        Assert.False(IntentMatcher.IsUndo(input));
    }

    // ── Redo ──

    [Theory]
    [InlineData("重做")]
    [InlineData("取消復原")]
    [InlineData("redo")]
    [InlineData("REDO")]
    [InlineData("重做上一步")]
    public void IsRedo_MatchesRedoKeywords(string input)
    {
        Assert.True(IntentMatcher.IsRedo(input));
    }

    [Theory]
    [InlineData("復原")]
    [InlineData("undo")]
    [InlineData("建立方塊")]
    public void IsRedo_DoesNotMatchNonRedoInput(string input)
    {
        Assert.False(IntentMatcher.IsRedo(input));
    }

    // ── View ──

    [Theory]
    [InlineData("等角", "iso")]
    [InlineData("iso", "iso")]
    [InlineData("正視", "front")]
    [InlineData("前視", "front")]
    [InlineData("俯視", "top")]
    [InlineData("上視", "top")]
    [InlineData("top", "top")]
    [InlineData("右視", "right")]
    [InlineData("側視", "right")]
    [InlineData("right", "right")]
    public void MatchView_ReturnsCorrectView(string input, string expected)
    {
        Assert.Equal(expected, IntentMatcher.MatchView(input));
    }

    [Theory]
    [InlineData("建立方塊")]
    [InlineData("加圓角 R3")]
    [InlineData("復原")]
    public void MatchView_ReturnsNullForNonViewInput(string input)
    {
        Assert.Null(IntentMatcher.MatchView(input));
    }

    // ── Zoom to Fit ──

    [Theory]
    [InlineData("縮放至適合")]
    [InlineData("全視圖")]
    [InlineData("適應視窗")]
    [InlineData("fit")]
    public void IsZoomToFit_MatchesZoomKeywords(string input)
    {
        Assert.True(IntentMatcher.IsZoomToFit(input));
    }

    [Theory]
    [InlineData("放大")]
    [InlineData("縮小")]
    [InlineData("正視")]
    public void IsZoomToFit_DoesNotMatchNonZoomInput(string input)
    {
        Assert.False(IntentMatcher.IsZoomToFit(input));
    }

    // ── Datum Plane Toggle ──

    [Theory]
    [InlineData("基準面顯示")]
    [InlineData("基準面隱藏")]
    [InlineData("切換基準面")]
    [InlineData("基準面開關")]
    public void IsDatumPlaneToggle_MatchesDatumKeywords(string input)
    {
        Assert.True(IntentMatcher.IsDatumPlaneToggle(input));
    }

    [Theory]
    [InlineData("基準面")]
    [InlineData("顯示邊線")]
    [InlineData("建立基準面 XY 上的草圖")]
    public void IsDatumPlaneToggle_DoesNotMatchNonToggleInput(string input)
    {
        Assert.False(IntentMatcher.IsDatumPlaneToggle(input));
    }

    // ── Rebuild ──

    [Theory]
    [InlineData("重建")]
    [InlineData("重新生成")]
    [InlineData("rebuild")]
    [InlineData("Rebuild")]
    public void IsRebuild_MatchesRebuildKeywords(string input)
    {
        Assert.True(IntentMatcher.IsRebuild(input));
    }

    [Theory]
    [InlineData("建立")]
    [InlineData("重做")]
    [InlineData("重新描述")]
    public void IsRebuild_DoesNotMatchNonRebuildInput(string input)
    {
        Assert.False(IntentMatcher.IsRebuild(input));
    }

    // ── Classify (綜合) ──

    [Theory]
    [InlineData("復原", "undo")]
    [InlineData("撤銷", "undo")]
    [InlineData("重做", "redo")]
    [InlineData("等角", "view:iso")]
    [InlineData("正視", "view:front")]
    [InlineData("俯視", "view:top")]
    [InlineData("右視", "view:right")]
    [InlineData("縮放至適合", "zoom_fit")]
    [InlineData("基準面顯示", "datum_toggle")]
    [InlineData("重建", "rebuild")]
    public void Classify_ReturnsCorrectIntent(string input, string expected)
    {
        Assert.Equal(expected, IntentMatcher.Classify(input));
    }

    [Theory]
    [InlineData("建立一個 60×60×5 底板")]
    [InlineData("所有邊加 R3 圓角")]
    [InlineData("加四個 M3 固定孔")]
    [InlineData("把厚度改成 10mm")]
    [InlineData("做 2mm 薄殼")]
    [InlineData("刪除最後的圓角")]
    [InlineData("改成鋁合金")]
    public void Classify_ReturnsNullForLLMBoundInput(string input)
    {
        // 這些建模操作應該送 LLM，不應被本地攔截
        Assert.Null(IntentMatcher.Classify(input));
    }

    [Theory]
    [InlineData("  復原  ", "undo")]
    [InlineData(" 重做 ", "redo")]
    public void Classify_HandlesWhitespace(string input, string expected)
    {
        Assert.Equal(expected, IntentMatcher.Classify(input));
    }
}