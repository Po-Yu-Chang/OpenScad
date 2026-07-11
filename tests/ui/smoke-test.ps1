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
    $freecadDir = Join-Path $repoRoot "FreeCAD" "FreeCAD_1.1.1-Windows-x86_64-py311"
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

    # 以「Name 包含 載入範例」比對，避免 header 空格/箭頭字元微調就失配
    $miType = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::MenuItem)
    $allMenus = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $miType)
    $menu = $null
    foreach ($m in $allMenus) { if ($m.Current.Name -like "*載入範例*") { $menu = $m; break } }
    if (-not $menu) {
        $names = ($allMenus | ForEach-Object { $_.Current.Name }) -join " | "
        throw "找不到載入範例選單。現有 MenuItem：$names"
    }
    $r = $menu.Current.BoundingRectangle
    [SmokeMouse]::Click([int]($r.X + $r.Width/2), [int]($r.Y + $r.Height/2))
    Start-Sleep -Seconds 2

    $itemCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty, "NEMA17 馬達座")
    $item = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $itemCond)
    if (-not $item) { throw "找不到 NEMA17 選單項" }
    $r2 = $item.Current.BoundingRectangle
    [SmokeMouse]::Click([int]($r2.X + $r2.Width/2), [int]($r2.Y + $r2.Height/2))
    Write-Host "3/5 已點擊載入範例，等待建模..." -ForegroundColor Cyan
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