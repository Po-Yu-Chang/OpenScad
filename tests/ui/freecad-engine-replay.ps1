<#
.SYNOPSIS
WP1-0R: FreeCAD 引擎 HTTP 重演驗收腳本

.DESCRIPTION
以 OPENCAD_ENGINE=freecad 啟動 Worker，透過 HTTP 重演：
建專案 → sketch(60×40 矩形) → pad 10 → hole Ø6 → fillet R2 → rebuild 200 次
→ display_map 面數>0 且含 surface_type=="cylinder"
→ preview.glb 200 次（走 presign）
→ STEP 匯出，用系統 Python（build123d 環境）讀回驗 bbox=60×40×10

用法：
  .\freecad-engine-replay.ps1

前置：
  tools\setup-freecad-python.ps1 已執行
  系統 Python 3.12 含 build123d
#>

param(
    [string]$FreeCadPython = ""
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

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

# # 摰? FreeCAD Python #
if (-not $FreeCadPython) {
    $FreeCadPython = Join-Path $repoRoot "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe"
}
if (-not (Test-Path $FreeCadPython)) {
    Write-Error "?曆???FreeCAD Python: $FreeCadPython"
    exit 1
}
Write-Host "FreeCAD Python: $FreeCadPython" -ForegroundColor Cyan

# # ?? Worker嚗reeCAD 撘?嚗???
Write-Host "`n=== WP1-0R: FreeCAD Engine Replay ===" -ForegroundColor Cyan
Write-Host "Starting CAD Worker with OPENCAD_ENGINE=freecad..."

$env:OPENCAD_ENGINE = "freecad"
$env:FREECAD_DIR = Join-Path $repoRoot "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311"
$env:PYTHONPATH = (Join-Path $repoRoot "cad-worker")
$env:OPENCAD_WORKER_PORT = "8791"
$env:OPENCAD_TOKEN_FILE = Join-Path $env:TEMP "opencad_replay_token.txt"
$env:OPENCAD_WORK_DIR = Join-Path $env:TEMP "opencad_replay_work"
$procId = $PID
$env:OPENCAD_PARENT_PID = $procId.ToString()

# 皜??? token 瑼?
if (Test-Path $env:OPENCAD_TOKEN_FILE) { Remove-Item $env:OPENCAD_TOKEN_FILE -Force }
# 蝣箔? work dir 摮
New-Item -ItemType Directory -Path $env:OPENCAD_WORK_DIR -Force | Out-Null

$serverProcess = Start-Process -FilePath $FreeCadPython `
    -ArgumentList "-m", "cad_worker.server" `
    -PassThru -NoNewWindow `
    -WorkingDirectory (Join-Path $repoRoot "cad-worker")

# 蝑? token 瑼??箇
# 首次載入 OCP/trimesh DLL 可能觸發 Defender 掃描（實測冷啟動 >200s），等待上限放寬至 300s
$tokenFound = $false
for ($i = 0; $i -lt 300; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $env:OPENCAD_TOKEN_FILE) {
        $token = (Get-Content $env:OPENCAD_TOKEN_FILE -Raw).Trim()
        if ($token) { $tokenFound = $true; break }
    }
    if ($serverProcess.HasExited) {
        Write-Host "Worker process exited prematurely (code: $($serverProcess.ExitCode))" -ForegroundColor Red
        exit 1
    }
}

if (-not $tokenFound) {
    Write-Host "Worker startup timeout ??no token file" -ForegroundColor Red
    Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

$ServerUrl = "http://127.0.0.1:8791"
$headers = @{ "X-Session-Token" = $token }

# 蝑? health check
$healthOk = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "$ServerUrl/api/health" -Method Get -Headers $headers -ErrorAction SilentlyContinue
        if ($health) {
            $healthOk = $true
            Write-Host "Health: engine=$($health.engine), engine_requested=$($health.engine_requested)"
            break
        }
    } catch { }
}

Step-Check "Worker startup + health" $healthOk "engine=$($health.engine)"

if (-not $healthOk) {
    Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "`nSummary: $($Result.Pass) passed, $($Result.Fail) failed" -ForegroundColor $(if ($Result.Fail -eq 0) { 'Green' } else { 'Red' })
    exit 1
}

try {
    # # ?? 1嚗遣撠? #
    $body = @{ name = "freecad-replay"; description = ""; units = "mm" } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    $projId = $resp.project_id
    Step-Check "Step 1: Create project" ($null -ne $projId)

    # # ?? 2:ketch 60?40 ?拙耦 #
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "sk1"
            type = "sketch"
            name = "Base Sketch"
            parameters = @{}
            sketch_entities = @(@{ type = "rectangle"; center = @(0,0); width = 60; height = 40 })
            plane = @{ base = "XY"; offset = 0 }
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    Step-Check "Step 2: Sketch 60x40" ($resp.status -eq "created")

    # # ?? 3嚗ad 10mm #
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "pad1"
            type = "pad"
            name = "Base Pad"
            parameters = @{ length = 10 }
            input = "sk1"
            references = @("sk1")
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    Step-Check "Step 3: Pad 10mm" ($resp.status -eq "created")

    # # ?? 4嚗ole ?6 through all #
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "hole1"
            type = "hole"
            name = "Center Hole"
            parameters = @{ diameter = 6; through_all = $true; positions = @(@(0, 0)) }
            input = "pad1"
            references = @("pad1")
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    Step-Check "Step 4: Hole ?6" ($resp.status -eq "created")

    # # ?? 5嚗illet R2 #
    $body = @{
        schema_version = "1.0"
        action = "create_feature"
        feature = @{
            feature_id = "fillet1"
            type = "fillet"
            name = "Edge Fillet"
            parameters = @{ radius = 2; edge_selector = "all" }
            input = "hole1"
            references = @("hole1")
        }
    } | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    Step-Check "Step 5: Fillet R2" ($resp.status -eq "created")

    # # ─── 步驟 6：Rebuild 200 次 ───
    $rebuildSuccess = $true
    $lastResp = $null
    for ($i = 1; $i -le 200; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/rebuild" -Method Post -Headers $headers
            $lastResp = $resp
            if ($resp.status -ne "success") {
                $rebuildSuccess = $false
                break
            }
        } catch {
            $rebuildSuccess = $false
            break
        }
    }
    Step-Check "Step 6: Rebuild 200 times" $rebuildSuccess "features=$($lastResp.feature_count)"

    # # ─── 步驟 7：display_map 面數>0 且含 cylinder ───
    $dm = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/display_map" -Method Get -Headers $headers
    $faceCount = $dm.faces.Count
    $hasCylinder = $false
    foreach ($f in $dm.faces) { if ($f.surface_type -eq "cylinder") { $hasCylinder = $true; break } }
    Step-Check "Step 7: display_map faces>0" ($faceCount -gt 0) "faces=$faceCount"
    Step-Check "Step 7: display_map has cylinder" $hasCylinder

    # # ?? 8嚗review.glb 200 甈?via presign #
    $glbSuccess = $true
    $lastGlbSize = 0
    for ($i = 1; $i -le 200; $i++) {
        try {
            $presignResp = Invoke-RestMethod -Uri "$ServerUrl/api/presign" -Method Post -Headers $headers
            $presignToken = $presignResp.presigned_token
            $glbUrl = "$ServerUrl/api/projects/$projId/preview.glb?token=$presignToken"
            $glbFile = Join-Path $env:TEMP "freecad_replay_test_$i.glb"
            Invoke-WebRequest -Uri $glbUrl -Method Get -OutFile $glbFile -ErrorAction Stop
            $glbSize = (Get-Item $glbFile).Length
            $lastGlbSize = $glbSize
            Remove-Item -Path $glbFile -Force -ErrorAction SilentlyContinue
            if ($glbSize -le 0) {
                $glbSuccess = $false
                break
            }
        } catch {
            $glbSuccess = $false
            break
        }
    }
    Step-Check "Step 8: preview.glb 200 times" $glbSuccess "size=$lastGlbSize bytes"

    # # ─── 步驟 9：STEP 匯出 ───
    $body = @{ format = "step"; filename = "replay_test" } | ConvertTo-Json
    $stepResp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projId/exports" -Method Post -Body $body -ContentType "application/json" -Headers $headers
    $stepPath = $stepResp.path
    Step-Check "Step 9: STEP export" (Test-Path $stepPath) "path=$stepPath"

    # # ?? 10嚗蝟餌絞 Python 霈??STEP 撽?bbox #
    $cadWorkerPath = Join-Path $repoRoot 'cad-worker'
    $verifyScript = @"
import sys
sys.path.insert(0, r'$cadWorkerPath')
from OCP.STEPControl import STEPControl_Reader
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
reader = STEPControl_Reader()
reader.ReadFile(r'$stepPath')
reader.TransferRoots()
shape = reader.OneShape()
bbox = Bnd_Box()
BRepBndLib.Add_s(shape, bbox)
xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
print(f'SIZE: X={xmax-xmin:.2f} Y={ymax-ymin:.2f} Z={zmax-zmin:.2f}')
"@
    $verifyFile = Join-Path $env:TEMP "verify_step.py"
    $verifyScript | Out-File -FilePath $verifyFile -Encoding utf8 -Force
    $verifyOutput = & python $verifyFile 2>&1
    Write-Host "  STEP verify output: $verifyOutput"
    $bboxOk = $verifyOutput -match "X=60\.0.*Y=40\.0.*Z=10\.0"
    Step-Check "Step 10: STEP bbox=60x40x10" $bboxOk $verifyOutput

} catch {
    Write-Host "  ERROR: $_" -ForegroundColor Red
    Step-Check "Exception" $false $_.Exception.Message
} finally {
    # # 皜? #
    try { Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -Path $env:OPENCAD_TOKEN_FILE -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -Path (Join-Path $env:TEMP "verify_step.py") -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -Path (Join-Path $env:TEMP "freecad_replay_test.step") -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -Path (Join-Path $env:TEMP "freecad_replay_test.glb") -Force -ErrorAction SilentlyContinue } catch {}
}

# # ?? #
Write-Host "`n=== Summary ===" -ForegroundColor Cyan
Write-Host "Passed: $($Result.Pass) / $($Result.Pass + $Result.Fail)" -ForegroundColor $(if ($Result.Fail -eq 0) { 'Green' } else { 'Red' })
Write-Host "Failed: $($Result.Fail)" -ForegroundColor $(if ($Result.Fail -eq 0) { 'Green' } else { 'Red' })

if ($Result.Fail -gt 0) {
    Write-Host "`nFailed steps:" -ForegroundColor Red
    foreach ($s in $Result.Step) {
        if ($s.Status -eq "FAIL") { Write-Host "  - $($s.Name): $($s.Detail)" -ForegroundColor Red }
    }
    exit 1
} else {
    Write-Host "`nAll steps PASSED!" -ForegroundColor Green
    exit 0
}
