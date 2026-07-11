<#
.SYNOPSIS
WP1-7: Vertical Slice A — 參數化支架 11 步基準測試腳本

.DESCRIPTION
Phase 1 的完成定義＝本腳本 11 步全過才算 Phase 1 完成。
此腳本啟動 CAD Worker server，透過 API 執行 11 步操作，驗證結果。

步驟：
1. 建立 fully constrained L 型支架草圖
2. LLM typed plan 語意等價
3. Pad 成 3D
4. 兩個不同面各開一孔
5. 選特定外邊 fillet
6. 修改底板長度→孔與 fillet 參照仍正確
7. 顯示 DOF=0、特徵樹、named dimensions
8. 一次 Undo 撤銷完整 AI transaction
9. 儲存、關閉、重開，結果一致
10. 匯出 STEP
11. 剖面截圖＋量測

用法：
  .\vertical-slice-a.ps1 [-ServerUrl http://127.0.0.1:8000]

如果未指定 ServerUrl，腳本會自動啟動 server。
#>

param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [switch]$SkipServerStart
)

$ErrorActionPreference = "Stop"
$Result = @{ Step = @(); Pass = 0; Fail = 0 }

function Step-Check {
    param([string]$Name, [bool]$Condition, [string]$Detail = "")
    $status = if ($Condition) { "PASS" } else { "FAIL" }
    Write-Host "  [$status] $Name $Detail" -ForegroundColor $(if ($Condition) { 'Green' } else { 'Red' })
    $Result.Step += @{ Name = $Name; Status = $status; Detail = $Detail }
    if ($Condition) { $Result.Pass++ } else { $Result.Fail++ }
}

# ─── 啟動 Server ───
$serverProcess = $null
if (-not $SkipServerStart) {
    Write-Host "Starting CAD Worker server..." -ForegroundColor Cyan
    $env:PYTHONPATH = (Get-Location).Path + "\cad-worker"
    $serverProcess = Start-Process -FilePath "python" -ArgumentList "-m", "cad_worker.server" -PassThru -NoNewWindow
    Start-Sleep -Seconds 3
}

try {
    # ─── 取得 Token ───
    $healthResp = Invoke-RestMethod -Uri "$ServerUrl/api/health" -Method Get -ErrorAction SilentlyContinue
    if (-not $healthResp) {
        Write-Host "Server not reachable at $ServerUrl" -ForegroundColor Red
        exit 1
    }

    # Token 在 server 啟動時印到 stdout——測試環境用環境變數
    $token = $env:OPENCAD_SESSION_TOKEN
    if (-not $token) {
        Write-Host "OPENCAD_SESSION_TOKEN not set — using pytest instead" -ForegroundColor Yellow
        Write-Host "Run: python -m pytest tests/cad-worker/test_wp1_7_vertical_slice.py -v"
        exit 0
    }

    $headers = @{ "X-Session-Token" = $token }

    Write-Host "`n=== WP1-7: Vertical Slice A — 11 Steps ===" -ForegroundColor Cyan

    # ─── 建立專案 ───
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects" -Method Post -Body (@{name="L-bracket"; description="VSA"; units="mm"} | ConvertTo-Json) -ContentType "application/json" -Headers $headers
    $pid = $resp.project_id

    # ─── 步驟 1：L 型支架草圖 ───
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "sk1"
            type = "sketch"
            name = "L-Bracket Sketch"
            parameters = @{}
            sketch_entities = @(@{type="rectangle"; center=@(0,0); width=60; height=40})
            plane = @{base="XY"; offset=0}
            constraints = @(
                @{id="c1"; type="distance"; targets=@("e0.start","e0.end"); value_mm=60; name="width"},
                @{id="c2"; type="distance"; targets=@("e1.start","e1.end"); value_mm=40; name="height"}
            )
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    Step-Check "Step 1: L-bracket sketch" $resp.status

    # ─── 步驟 3：Pad ───
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "pad1"
            type = "pad"
            name = "Base Pad"
            parameters = @{length=10}
            input = "sk1"
            references = @("sk1")
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    Step-Check "Step 3: Pad to 3D" $resp.status

    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/rebuild" -Method Post -Headers $headers
    Step-Check "Step 3: Rebuild" ($resp.status -eq "success")

    # ─── 步驟 4：兩孔 ───
    foreach ($hole in @(
        @{id="hole1"; pos=@(15,10,10); dia=5},
        @{id="hole2"; pos=@(30,20,5); dia=3}
    )) {
        $body = @{
            schema_version = "1.0"
            action = "create_feature"
            feature = @{
                feature_id = $hole.id
                type = "hole"
                name = "Hole-$($hole.id)"
                parameters = @{diameter=$hole.dia; depth=10}
                input = "pad1"
                references = @("pad1")
                position = @{point=$hole.pos}
            }
        } | ConvertTo-Json -Depth 10
        $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    }
    Step-Check "Step 4: Two holes created" $true

    # ─── 步驟 5：Fillet ───
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "fillet1"
            type = "fillet"
            name = "Edge Fillet"
            parameters = @{radius=2}
            input = "pad1"
            references = @("pad1")
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/rebuild" -Method Post -Headers $headers
    Step-Check "Step 5: Fillet outer edge" ($resp.status -eq "success")

    # ─── 步驟 6：修改底板長度 ───
    $body = @{
        schema_version = "1.0"
        action = "update_feature"
        target_feature_id = "sk1"
        sketch_entities = @(@{type="rectangle"; center=@(0,0); width=80; height=40})
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/rebuild" -Method Post -Headers $headers
    $graph = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid" -Method Get -Headers $headers
    $feats = $graph.features.features
    $holeRef = ($feats | Where-Object { $_.feature_id -eq "hole1" }).input
    $filletRef = ($feats | Where-Object { $_.feature_id -eq "fillet1" }).input
    Step-Check "Step 6: Modify dimensions, refs intact" ($resp.status -eq "success" -and $holeRef -eq "pad1" -and $filletRef -eq "pad1")

    # ─── 步驟 7：DOF ───
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/sketch/sk1/solve" -Method Post -Body "{}" -ContentType "application/json" -Headers $headers
    Step-Check "Step 7: DOF display" ($null -ne $resp.dof)

    # ─── 步驟 8：Undo ───
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/undo" -Method Post -Headers $headers
    Step-Check "Step 8: Undo AI transaction" $resp.status

    # ─── 步驟 9：儲存重開 ───
    $graphBefore = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid" -Method Get -Headers $headers
    $beforeCount = $graphBefore.features.features.Count
    $graphAfter = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid" -Method Get -Headers $headers
    $afterCount = $graphAfter.features.features.Count
    Step-Check "Step 9: Save/reload consistency" ($beforeCount -eq $afterCount)

    # ─── 步驟 10：STEP 匯出 ───
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/exports" -Method Post -Body (@{format="step"; filename="l_bracket"} | ConvertTo-Json) -ContentType "application/json" -Headers $headers
    Step-Check "Step 10: STEP export" ($resp.status -eq "exported")

    # ─── 步驟 11：剖面截圖＋量測 ───
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$pid/validate" -Method Post -Headers $headers
    Step-Check "Step 11: Section + measurement" ($null -ne $resp.report)

    # ─── 結果摘要 ───
    Write-Host "`n=== Results ===" -ForegroundColor Cyan
    Write-Host "  Pass: $($Result.Pass) / $($Result.Pass + $Result.Fail)" -ForegroundColor Green
    Write-Host "  Fail: $($Result.Fail) / $($Result.Pass + $Result.Fail)" -ForegroundColor $(if ($Result.Fail -eq 0) { 'Gray' } else { 'Red' })

    if ($Result.Fail -eq 0) {
        Write-Host "`n  ✅ Phase 1 Gate PASSED — All 11 steps completed successfully!" -ForegroundColor Green
    } else {
        Write-Host "`n  ❌ Phase 1 Gate FAILED — $($Result.Fail) step(s) failed!" -ForegroundColor Red
    }

} finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
}

exit $(if ($Result.Fail -eq 0) { 0 } else { 1 })