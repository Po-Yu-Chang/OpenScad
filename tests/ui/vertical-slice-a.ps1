<#
.SYNOPSIS
WP1-7: Vertical Slice A — 參數化支架 11 步基準測試腳本（Phase 1 Gate）

.DESCRIPTION
Phase 1 的完成定義＝本腳本 11 步全過。
腳本自管 CAD Worker server（含 token 自給與步驟 9 的真實重啟），透過 HTTP API 執行 11 步並驗證。

2026-07-12 重寫（WP1-7-UI）：
- 修正 $pid 唯讀自動變數賦值錯誤（原腳本一執行就會拋錯）→ $projectId
- 廢除「無 token 時 exit 0」的 no-op 綠燈——自管模式從 OPENCAD_TOKEN_FILE 自給 token；外部模式缺 token 一律 FAIL
- 補步驟 2（typed plan 走 apply_plan＋語意等價比對）
- 步驟 9 改為真實重啟 server 後讀回比對（原版是同一 live 專案連 GET 兩次，恆真）
- 步驟 4/7/8/10 斷言強化（孔數、solver_status.dof、named dimensions、undo 前後差 1、匯出檔存在）

用法：
  .\vertical-slice-a.ps1                          # 自管 server（build123d）
  .\vertical-slice-a.ps1 -Engine freecad          # 自管 server（FreeCAD 引擎）
  .\vertical-slice-a.ps1 -SkipServerStart -ServerUrl http://127.0.0.1:8765
      # 外部 server 模式：需 $env:OPENCAD_SESSION_TOKEN；步驟 9 無法驗證重啟，記 FAIL
#>

param(
    [string]$ServerUrl = "",
    [switch]$SkipServerStart,
    [string]$Engine = "build123d",
    [int]$Port = 8830
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Result = @{ Step = @(); Pass = 0; Fail = 0; Skip = 0; Failures = @() }

function Step-Check {
    param([string]$Name, [bool]$Condition, [string]$Detail = "")
    $status = if ($Condition) { "PASS" } else { "FAIL" }
    Write-Host "  [$status] $Name $Detail" -ForegroundColor $(if ($Condition) { 'Green' } else { 'Red' })
    $Result.Step += @{ Name = $Name; Status = $status; Detail = $Detail }
    if ($Condition) {
        $Result.Pass++
    } else {
        $Result.Fail++
        $Result.Failures += $Name
    }
}

function Step-Skip {
    <# WP-H1：明確標 SKIP（不算 PASS 也不算 FAIL）——真 gateway 未設定時的
       誠實狀態，不得偷偷算成 PASS 湊數。#>
    param([string]$Name, [string]$Reason = "")
    Write-Host "  [SKIP] $Name $Reason" -ForegroundColor Yellow
    $Result.Step += @{ Name = $Name; Status = "SKIP"; Detail = $Reason }
    $Result.Skip++
}

function Get-GatewayConfig {
    <# WP-H1：讀 ~/.opencad/settings.json 的 llm 設定。provider 不是
       openai/auto，或沒有 base_url，一律回傳 $null（代表沒有可用的真
       gateway）。與 tests/prompts/gateway_client.py 的 load_gateway_config
       走同一套判斷規則，兩邊都要能正確辨識「有沒有真 gateway 可用」。 #>
    $settingsPath = Join-Path $env:USERPROFILE ".opencad\settings.json"
    if (-not (Test-Path $settingsPath)) { return $null }
    try {
        $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
    $llm = $settings.llm
    if (-not $llm) { return $null }
    $provider = if ($llm.provider) { $llm.provider } else { "none" }
    if ($provider -ne "openai" -and $provider -ne "auto") { return $null }
    if (-not $llm.base_url) { return $null }
    return @{
        BaseUrl = $llm.base_url.TrimEnd("/")
        ApiKey  = $llm.api_key
        Model   = $llm.model
    }
}

function Invoke-Gateway {
    <# WP-H1：呼叫真 LiteLLM/OpenAI-compatible gateway，回傳解析後的 JSON
       物件。契約與 src/OpenCad.Llm/OpenAiCompatibleLlmProvider.cs 對齊：
       POST {base_url}/chat/completions，response_format=json_object，
       400/422 時退回不帶此欄位重試一次；回應在
       choices[0].message.content，需要剝除 ```json 圍欄。 #>
    param(
        [Parameter(Mandatory)] $Config,
        [Parameter(Mandatory)][string]$SystemPrompt,
        [Parameter(Mandatory)][string]$UserPrompt,
        [array]$History = @()
    )
    $gwHeaders = @{ "Content-Type" = "application/json" }
    if ($Config.ApiKey) { $gwHeaders["Authorization"] = "Bearer $($Config.ApiKey)" }

    $messages = @(@{ role = "system"; content = $SystemPrompt })
    $messages += $History
    $messages += @{ role = "user"; content = $UserPrompt }

    $body = @{
        model = $Config.Model
        messages = $messages
        response_format = @{ type = "json_object" }
        temperature = 0.1
    }
    $url = "$($Config.BaseUrl)/chat/completions"
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Post -Body ($body | ConvertTo-Json -Depth 10) -ContentType "application/json" -Headers $gwHeaders -TimeoutSec 120
    } catch {
        # 400/422（gateway 不支援 response_format）退回不帶此欄位重試一次
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 400 -or $statusCode -eq 422) {
            $body.Remove("response_format")
            $resp = Invoke-RestMethod -Uri $url -Method Post -Body ($body | ConvertTo-Json -Depth 10) -ContentType "application/json" -Headers $gwHeaders -TimeoutSec 120
        } else {
            throw
        }
    }
    $content = $resp.choices[0].message.content
    # 剝除 markdown code fence（三個反引號），取第一個 { 到最後一個 }
    $fence = [string][char]96 + [char]96 + [char]96
    $text = $content.Trim()
    if ($text.StartsWith($fence)) {
        $lines = $text -split "`n", 2
        $text = if ($lines.Count -gt 1) { $lines[1] } else { $text }
        if ($text.TrimEnd().EndsWith($fence)) {
            $text = $text.Substring(0, $text.LastIndexOf($fence))
        }
    }
    $start = $text.IndexOf("{")
    $end = $text.LastIndexOf("}")
    if ($start -eq -1 -or $end -eq -1 -or $end -lt $start) {
        throw "回應中找不到 JSON 物件：$($text.Substring(0, [Math]::Min(300, $text.Length)))"
    }
    return ($text.Substring($start, $end - $start + 1) | ConvertFrom-Json)
}

function Get-WorkerPython {
    param([string]$EngineName)
    if ($EngineName -eq "freecad") {
        $fcPython = Join-Path $RepoRoot "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe"
        if (-not (Test-Path $fcPython)) {
            Write-Host "FreeCAD python not found: $fcPython" -ForegroundColor Red
            exit 1
        }
        return $fcPython
    }
    return "python"
}

function Start-WorkerServer {
    <# 啟動 server，輪詢 health＋token 檔（0.5s x 60），回傳 @{Process; Token}；失敗回 $null #>
    param([string]$TokenFile)
    $env:OPENCAD_TOKEN_FILE = $TokenFile
    $pythonPath = Get-WorkerPython $Engine
    $proc = Start-Process -FilePath $pythonPath -ArgumentList "-m", "cad_worker.server" -PassThru -NoNewWindow -WorkingDirectory $RepoRoot
    $tok = $null
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $health = Invoke-RestMethod -Uri "$script:ServerUrl/api/health" -Method Get
            if ($health -and (Test-Path $TokenFile)) {
                $tok = (Get-Content $TokenFile -Raw).Trim()
                if ($tok) { break }
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $tok) {
        if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
        return $null
    }
    return @{ Process = $proc; Token = $tok }
}

# ─── 啟動 Server／取得 token ───
$serverProcess = $null
$tokenFiles = @()
$workDir = $null

try {
    if (-not $SkipServerStart) {
        if (-not $ServerUrl) { $ServerUrl = "http://127.0.0.1:$Port" }
        Write-Host "Starting CAD Worker server (engine=$Engine, port=$Port)..." -ForegroundColor Cyan
        $workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vsa-" + [System.IO.Path]::GetRandomFileName())
        $null = New-Item -ItemType Directory -Path $workDir -Force
        $tokenFile1 = [System.IO.Path]::GetTempFileName()
        $tokenFiles += $tokenFile1

        $env:OPENCAD_WORKER_PORT = "$Port"
        $env:OPENCAD_WORK_DIR = $workDir
        $env:OPENCAD_ENGINE = $Engine
        $env:PYTHONPATH = Join-Path $RepoRoot "cad-worker"

        $started = Start-WorkerServer -TokenFile $tokenFile1
        if (-not $started) {
            Write-Host "Server failed to start or token unavailable — FAIL" -ForegroundColor Red
            exit 1
        }
        $serverProcess = $started.Process
        $token = $started.Token
    } else {
        # 外部 server 模式：token 必須由環境提供；缺少＝FAIL（禁止 no-op 綠燈）
        if (-not $ServerUrl) { $ServerUrl = "http://127.0.0.1:8765" }
        $token = $env:OPENCAD_SESSION_TOKEN
        if (-not $token) {
            Write-Host "External server mode requires OPENCAD_SESSION_TOKEN — FAIL" -ForegroundColor Red
            exit 1
        }
    }

    $headers = @{ "X-Session-Token" = $token }

    Write-Host "`n=== WP1-7: Vertical Slice A — 11 Steps (engine=$Engine) ===" -ForegroundColor Cyan

    # ─── 建立專案 ───
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects" -Method Post -Body (@{name="L-bracket"; description="VSA"; units="mm"} | ConvertTo-Json) -ContentType "application/json" -Headers $headers
    $projectId = $resp.project_id
    if (-not $projectId) {
        Write-Host "Project creation failed" -ForegroundColor Red
        exit 1
    }

    $sketchFeature = @{
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

    # ─── 步驟 1：L 型支架草圖（含 named constraints）───
    try {
        $body = @{ schema_version = "1.0"; action = "create_feature"; feature = $sketchFeature } | ConvertTo-Json -Depth 10
        $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
        $graph = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers
        $sk = $graph.features.features | Where-Object { $_.feature_id -eq "sk1" }
        Step-Check "Step 1: L-bracket sketch (constrained)" (($resp.status -eq "created") -and ($sk.type -eq "sketch") -and ($sk.constraints.Count -ge 2))
    } catch {
        Step-Check "Step 1: L-bracket sketch (constrained)" $false $_.Exception.Message
    }

    # ─── 步驟 2：真 LLM 生成 plan，語意欄位跟 typed plan 比對 ───
    # WP-H1 修復：原本沒有 LLM 參與——把同一個寫死的 $sketchFeature 送
    # apply_plan 再跟自己的常數比對，只證明 apply_plan 端點能跑，不是「LLM
    # plan 語意等價」。改為：有設定真 gateway 就真的送一句自然語言需求給
    # LLM，比對它生出的 typed plan 語意欄位（width/height/plane.base）跟
    # 期望值是否一致；沒設定 gateway 就明確 SKIP（不得 PASS）。
    $gwConfig = Get-GatewayConfig
    if (-not $gwConfig) {
        Step-Skip "Step 2: LLM plan semantic equivalence" "沒有設定真 gateway（~/.opencad/settings.json 的 llm.provider 須為 openai/auto 且有 base_url）——Master Plan §3.5 允許無 LLM 環境 skip，不得 PASS"
    } else {
        try {
            $systemPrompt = @"
你是 OpenCad 的 AI 建模助手。將使用者需求轉換成 CAD 命令 JSON。
sketch 特徵必須指定 plane.base：XY/XZ/YZ。sketch_entities 用 rectangle 時填 width/height（mm）。
輸出必須是合法 JSON，符合 schema：
{"type":"object","properties":{"steps":{"type":"array","items":{"type":"object","properties":{"description":{"type":"string"},"feature_type":{"type":"string"},"parameters":{"type":"object"},"sketch_entities":{"type":"array"},"plane":{"type":"object"}}}},"summary":{"type":"string"}},"required":["steps","summary"]}
"@
            $userPrompt = "在 XY 基準面上畫一個 60mm x 40mm 的矩形草圖。"
            $plan = Invoke-Gateway -Config $gwConfig -SystemPrompt $systemPrompt -UserPrompt $userPrompt
            $sketchStep = $plan.steps | Where-Object { $_.feature_type -eq "sketch" } | Select-Object -First 1
            if (-not $sketchStep) {
                Step-Check "Step 2: LLM plan semantic equivalence" $false "回應沒有 sketch 步驟：$($plan | ConvertTo-Json -Depth 5 -Compress)"
            } else {
                $rectEnt = $sketchStep.sketch_entities | Where-Object { $_.type -eq "rectangle" -or $_.entity_type -eq "rectangle" } | Select-Object -First 1
                $planeBase = if ($sketchStep.plane.base) { $sketchStep.plane.base } else { "XY" }
                $w = if ($rectEnt.width) { $rectEnt.width } else { $rectEnt.parameters.width }
                $h = if ($rectEnt.height) { $rectEnt.height } else { $rectEnt.parameters.height }
                $equiv = ($w -eq 60) -and ($h -eq 40) -and ($planeBase -eq "XY")
                Step-Check "Step 2: LLM plan semantic equivalence" $equiv "width=$w height=$h plane=$planeBase"
            }
        } catch {
            Step-Check "Step 2: LLM plan semantic equivalence" $false $_.Exception.Message
        }
    }

    # ─── 步驟 3：Pad 成 3D ───
    try {
        $body = @{
            schema_version = "1.0"; action = "create_feature"
            feature = @{ feature_id = "pad1"; type = "pad"; name = "Base Pad"; parameters = @{length=10}; input = "sk1"; references = @("sk1") }
        } | ConvertTo-Json -Depth 10
        $created = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
        $rebuilt = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/rebuild" -Method Post -Headers $headers
        Step-Check "Step 3: Pad to 3D + rebuild" (($created.status -eq "created") -and ($rebuilt.status -eq "success"))
    } catch {
        Step-Check "Step 3: Pad to 3D + rebuild" $false $_.Exception.Message
    }

    # ─── 步驟 4：兩個不同面各開一孔 ───
    try {
        foreach ($hole in @(
            @{id="hole1"; pos=@(15,10,10); dia=5},
            @{id="hole2"; pos=@(30,20,5); dia=3}
        )) {
            $body = @{
                schema_version = "1.0"; action = "create_feature"
                feature = @{
                    feature_id = $hole.id; type = "hole"; name = "Hole-$($hole.id)"
                    parameters = @{diameter=$hole.dia; depth=10}
                    input = "pad1"; references = @("pad1"); position = @{point=$hole.pos}
                }
            } | ConvertTo-Json -Depth 10
            $null = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
        }
        $rebuilt = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/rebuild" -Method Post -Headers $headers
        $graph = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers
        $holes = @($graph.features.features | Where-Object { $_.type -eq "hole" })
        Step-Check "Step 4: Two holes on different faces" (($rebuilt.status -eq "success") -and ($holes.Count -eq 2)) "holes=$($holes.Count)"
    } catch {
        Step-Check "Step 4: Two holes on different faces" $false $_.Exception.Message
    }

    # ─── 步驟 5：外邊 fillet ───
    try {
        $body = @{
            schema_version = "1.0"; action = "create_feature"
            feature = @{ feature_id = "fillet1"; type = "fillet"; name = "Edge Fillet"; parameters = @{radius=2}; input = "pad1"; references = @("pad1") }
        } | ConvertTo-Json -Depth 10
        $null = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
        $rebuilt = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/rebuild" -Method Post -Headers $headers
        Step-Check "Step 5: Fillet outer edge" ($rebuilt.status -eq "success")
    } catch {
        Step-Check "Step 5: Fillet outer edge" $false $_.Exception.Message
    }

    # ─── 步驟 6：修改底板長度 → 參照仍正確 ───
    try {
        $body = @{
            schema_version = "1.0"; action = "update_feature"; target_feature_id = "sk1"
            sketch_entities = @(@{type="rectangle"; center=@(0,0); width=80; height=40})
        } | ConvertTo-Json -Depth 10
        $updated = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/commands" -Method Post -Body $body -ContentType "application/json" -Headers $headers
        $rebuilt = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/rebuild" -Method Post -Headers $headers
        $graph = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers
        $feats = $graph.features.features
        $holeRef = ($feats | Where-Object { $_.feature_id -eq "hole1" }).input
        $filletRef = ($feats | Where-Object { $_.feature_id -eq "fillet1" }).input
        Step-Check "Step 6: Modify dims, refs intact" (($updated.status -eq "updated") -and ($rebuilt.status -eq "success") -and ($holeRef -eq "pad1") -and ($filletRef -eq "pad1"))
    } catch {
        Step-Check "Step 6: Modify dims, refs intact" $false $_.Exception.Message
    }

    # ─── 步驟 7：DOF＋named dimensions ───
    try {
        $solved = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/sketch/sk1/solve" -Method Post -Body "{}" -ContentType "application/json" -Headers $headers
        $graph = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers
        $sk = $graph.features.features | Where-Object { $_.feature_id -eq "sk1" }
        $names = @($sk.constraints | ForEach-Object { $_.name })
        $ok = ($null -ne $solved.solver_status.dof) -and ($names -contains "width") -and ($names -contains "height")
        Step-Check "Step 7: DOF + named dimensions" $ok "dof=$($solved.solver_status.dof) state=$($solved.solver_status.state)"
    } catch {
        Step-Check "Step 7: DOF + named dimensions" $false $_.Exception.Message
    }

    # ─── 步驟 8：Undo（撤銷完整一筆交易＝步驟 6 的尺寸修改，寬度 80 → 還原 60）───
    try {
        $skBefore = (Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers).features.features | Where-Object { $_.feature_id -eq "sk1" }
        $widthBefore = $skBefore.sketch_entities[0].width
        $undone = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/undo" -Method Post -Headers $headers
        $skAfter = (Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers).features.features | Where-Object { $_.feature_id -eq "sk1" }
        $widthAfter = $skAfter.sketch_entities[0].width
        $null = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/rebuild" -Method Post -Headers $headers
        Step-Check "Step 8: Undo AI transaction" (($undone.status -eq "ok") -and ($widthBefore -eq 80) -and ($widthAfter -eq 60)) "width $widthBefore -> $widthAfter"
    } catch {
        Step-Check "Step 8: Undo AI transaction" $false $_.Exception.Message
    }

    # ─── 步驟 9：真實重啟 server → 讀回一致 ───
    try {
        if (-not $SkipServerStart) {
            # WP-H1 修復：原本快照只比 feature_id/type/name/input，掉尺寸
            # （如 parameters.length 被存檔/重啟過程弄壞）也會被判 PASS。
            # 加入 parameters 之後，任何參數在存檔/重啟循環中遺失都能被抓到。
            $snapBefore = (Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers).features.features |
                Sort-Object feature_id | Select-Object feature_id, type, name, input, parameters | ConvertTo-Json -Depth 6

            if ($serverProcess -and -not $serverProcess.HasExited) {
                Stop-Process -Id $serverProcess.Id -Force
                $serverProcess.WaitForExit()
            }
            $serverProcess = $null

            $tokenFile2 = [System.IO.Path]::GetTempFileName()
            $tokenFiles += $tokenFile2
            $restarted = Start-WorkerServer -TokenFile $tokenFile2   # 同一 OPENCAD_WORK_DIR
            if (-not $restarted) {
                Step-Check "Step 9: Save/close/reload consistency" $false "restart failed"
            } else {
                $serverProcess = $restarted.Process
                $headers = @{ "X-Session-Token" = $restarted.Token }
                $snapAfter = (Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId" -Method Get -Headers $headers).features.features |
                    Sort-Object feature_id | Select-Object feature_id, type, name, input, parameters | ConvertTo-Json -Depth 6
                # 重開後重建一次（正常使用流程）——後續 export 需要記憶體中的已建模型
                $rebuilt = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/rebuild" -Method Post -Headers $headers
                Step-Check "Step 9: Save/close/reload consistency" (($snapBefore -eq $snapAfter) -and ($rebuilt.status -eq "success"))
            }
        } else {
            Step-Check "Step 9: Save/close/reload consistency" $false "external server mode cannot verify restart — run in self-managed mode"
        }
    } catch {
        Step-Check "Step 9: Save/close/reload consistency" $false $_.Exception.Message
    }

    # ─── 步驟 10：STEP 匯出（檔案實際存在）───
    try {
        $resp = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/exports" -Method Post -Body (@{format="step"; filename="l_bracket"} | ConvertTo-Json) -ContentType "application/json" -Headers $headers
        Step-Check "Step 10: STEP export" (($resp.status -eq "exported") -and (Test-Path $resp.path)) $resp.path
    } catch {
        Step-Check "Step 10: STEP export" $false $_.Exception.Message
    }

    # ─── 步驟 11：剖面基礎（display_map/GLB）＋量測（validate report）───
    try {
        $sectionOk = $false
        try {
            $dm = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/display_map" -Method Get -Headers $headers
            $sectionOk = ($null -ne $dm.faces) -and ($null -ne $dm.edges)
        } catch {
            $glb = Invoke-WebRequest -Uri "$ServerUrl/api/projects/$projectId/preview.glb" -Headers $headers -UseBasicParsing
            $sectionOk = ($glb.StatusCode -eq 200)
        }
        $val = Invoke-RestMethod -Uri "$ServerUrl/api/projects/$projectId/validate" -Method Post -Headers $headers
        Step-Check "Step 11: Section + measurement" ($sectionOk -and ($null -ne $val.report))
    } catch {
        Step-Check "Step 11: Section + measurement" $false $_.Exception.Message
    }

    # ─── 結果摘要 ───
    $totalSteps = $Result.Pass + $Result.Fail + $Result.Skip
    Write-Host "`n=== Results (engine=$Engine) ===" -ForegroundColor Cyan
    Write-Host "  Pass: $($Result.Pass) / $totalSteps" -ForegroundColor Green
    Write-Host "  Fail: $($Result.Fail) / $totalSteps" -ForegroundColor $(if ($Result.Fail -eq 0) { 'Gray' } else { 'Red' })
    if ($Result.Skip -gt 0) {
        Write-Host "  Skip: $($Result.Skip) / $totalSteps（見下方 SKIP 明細——不算 PASS，也不算 FAIL）" -ForegroundColor Yellow
        $Result.Step | Where-Object { $_.Status -eq "SKIP" } | ForEach-Object { Write-Host "    - $($_.Name): $($_.Detail)" -ForegroundColor Yellow }
    }
    if ($Result.Failures.Count -gt 0) {
        Write-Host "`n  Failed Steps:" -ForegroundColor Red
        $Result.Failures | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    }
    if ($Result.Fail -eq 0 -and $Result.Skip -eq 0) {
        Write-Host "`n  [OK] Phase 1 Gate PASSED — all steps green." -ForegroundColor Green
    } elseif ($Result.Fail -eq 0) {
        Write-Host "`n  [OK*] Phase 1 Gate PASSED with $($Result.Skip) SKIP — 沒有 FAIL，但不是全綠，見上方 SKIP 明細。" -ForegroundColor Yellow
    } else {
        Write-Host "`n  [X] Phase 1 Gate FAILED — $($Result.Fail) step(s) failed." -ForegroundColor Red
    }

} finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    foreach ($tf in $tokenFiles) {
        if ($tf -and (Test-Path $tf)) { Remove-Item -Path $tf -Force -ErrorAction SilentlyContinue }
    }
    if ($workDir -and (Test-Path $workDir)) {
        Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit $(if ($Result.Fail -eq 0) { 0 } else { 1 })
