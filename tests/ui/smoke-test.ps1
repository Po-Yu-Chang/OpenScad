# OpenCad UI 冒煙測試——以 UIAutomation 驅動真實視窗驗證垂直切片。
# 用法：powershell -ExecutionPolicy Bypass -File tests\ui\smoke-test.ps1 [-Engine build123d|freecad]
# 前置：已 dotnet build、Python 環境含 build123d（build123d 引擎）或 FreeCAD（freecad 引擎）。
# 通過標準：載入範例後 log 出現 rebuild 200 與 preview.glb 200，關閉後無殘留 worker。

param(
    [Parameter()]
    [ValidateSet("build123d", "freecad")]
    [string]$Engine = "build123d"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SmokeMouse {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    public static void Click(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(150);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
    }
}
"@

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$exeDir = Join-Path $repoRoot "src\OpenCad.Desktop\bin\Debug\net8.0"
$exe = Join-Path $exeDir "OpenCad.Desktop.exe"
if (-not (Test-Path $exe)) { Write-Error "找不到 $exe——請先 dotnet build"; exit 1 }

# 設定引擎配置
$settingsDir = Join-Path $env:USERPROFILE ".opencad"
$settingsFile = Join-Path $settingsDir "settings.json"
if (-not (Test-Path $settingsDir)) {
    New-Item -ItemType Directory -Path $settingsDir | Out-Null
}

# 建立引擎設定
$settings = @{
    engine = $Engine
    llm = @{
        provider = "none"
    }
}

if ($Engine -eq "freecad") {
    # 檢查 FreeCAD 目錄是否存在
    # PS 5.1 的 Join-Path 不支援多個子路徑（PS7 才有）——必須巢狀呼叫
    $freecadDir = Join-Path (Join-Path $repoRoot "FreeCAD") "FreeCAD_1.1.1-Windows-x86_64-py311"
    if (Test-Path $freecadDir) {
        $settings.freecad_dir = $freecadDir
    }
}

# 寫入設定檔
$settings | ConvertTo-Json -Depth 3 | Set-Content -Path $settingsFile -Encoding UTF8

Set-Location $exeDir
Remove-Item opencad*.log -ErrorAction SilentlyContinue

Write-Host "1/5 啟動應用程式 (引擎: $Engine)..." -ForegroundColor Cyan
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 24

$fail = $false
try {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $winCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        "OpenCad — 全本地 LLM 原生參數化機械 CAD")
    $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $winCond)
    if (-not $win) { throw "找不到主視窗——視窗未顯示" }
    Write-Host "2/5 視窗已顯示 ✓" -ForegroundColor Green

    [SmokeMouse]::SetForegroundWindow((New-Object IntPtr($win.Current.NativeWindowHandle))) | Out-Null
    Start-Sleep -Milliseconds 500

    # 開始頁的 Menu 用 FindAll(Descendants) 會漏撈（Avalonia/UIA 對 Menu/Popup 的怪癖）；
    # 改用 TreeWalker 遞迴 + Name 包含比對，對 header 空格/箭頭微調也有韌性。
    # 必須限定 ControlType=MenuItem/Button——純名稱比對會誤中聊天歡迎訊息的 TextBlock
    # （文案含「載入範例」），Expand/Invoke 打在 Text 元素上靜默無效。
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    function Find-ByName($el, $needle, $maxDepth = 14) {
        if ($maxDepth -lt 0) { return $null }
        $cur = $el.Current
        if (($cur.Name -like "*$needle*") -and
            ($cur.ControlType.ProgrammaticName -in @("ControlType.MenuItem", "ControlType.Button"))) { return $el }
        $c = $walker.GetFirstChild($el)
        while ($c) {
            $f = Find-ByName $c $needle ($maxDepth - 1)
            if ($f) { return $f }
            $c = $walker.GetNextSibling($c)
        }
        return $null
    }

    # 開始頁：開啟「載入範例」子選單並選第一項（NEMA17）。
    # Avalonia 的 MenuItem 在 UIA 只暴露 ScrollItemPattern（無 ExpandCollapse/Invoke），
    # 實體滑鼠座標點擊又受 DPI 虛擬化影響——鍵盤路徑（SetFocus→Enter→Down→Enter）
    # 是實測唯一穩定的驅動方式（2026-07-12 驗證）。
    $menu = Find-ByName $win "載入範例"
    if (-not $menu) { throw "找不到載入範例選單（開始頁）" }
    $menu.SetFocus()
    Start-Sleep -Milliseconds 600
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Start-Sleep -Milliseconds 1200

    # 子選單展開後 NEMA17 MenuItem 才會出現在 UIA 樹——以此確認選單真的開了
    $item = Find-ByName $win "NEMA17"
    if (-not $item) {
        # 少數情況 Enter 只取得焦點未展開——補一次 DOWN 再確認
        [System.Windows.Forms.SendKeys]::SendWait("{DOWN}")
        Start-Sleep -Milliseconds 800
        $item = Find-ByName $win "NEMA17"
    }
    if (-not $item) { throw "找不到 NEMA17 選單項（子選單未展開）" }
    [System.Windows.Forms.SendKeys]::SendWait("{DOWN}")
    Start-Sleep -Milliseconds 400
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Write-Host "3/5 已觸發載入範例，等待建模..." -ForegroundColor Cyan
    Start-Sleep -Seconds 40

    $log = Get-Content opencad*.log -Raw
    if ($log -notmatch 'rebuild HTTP/1.1" 200') { throw "log 中沒有 rebuild 200" }
    if ($log -notmatch 'preview\.glb\?token=[^"]*" (200|304)') { throw "log 中沒有 preview.glb 抓取成功" }
    Write-Host "4/5 重建 200 ✓  GLB 抓取 ✓" -ForegroundColor Green
}
catch {
    Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
    $fail = $true
}
finally {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 6
    # 檢查殘留的 worker 程序（python 或 python.exe）
    $stray = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -eq "127.0.0.1" } |
        ForEach-Object { Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } |
        Where-Object { ($_.ProcessName -eq "python" -or $_.ProcessName -eq "python.exe") -and $_.StartTime -gt (Get-Date).AddMinutes(-3) }
    if ($stray) {
        Write-Host "FAIL: 關閉後仍有殘留 worker（$($stray.Count) 個）" -ForegroundColor Red
        $stray | Stop-Process -Force
        $fail = $true
    } else {
        Write-Host "5/5 無殘留 worker ✓" -ForegroundColor Green
    }
}

if ($fail) { Write-Host "`n冒煙測試 FAIL" -ForegroundColor Red; exit 1 }
Write-Host "`n冒煙測試 PASS" -ForegroundColor Green
exit 0