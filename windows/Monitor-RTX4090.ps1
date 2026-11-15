param(
  [int]$GpuIndex = 0,
  [int]$DurationMinutes = 90,
  [int]$StopCoreC = 88
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$out = Join-Path $root "results\windows_$stamp"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$exe = (Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue)
if ($exe) { $smi = $exe.Source }
else {
  $smi = 'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe'
  if (-not (Test-Path $smi)) { throw 'nvidia-smi.exe not found. Install or repair NVIDIA driver.' }
}
$id = @(& $smi -i $GpuIndex --query-gpu=name,memory.total --format=csv,noheader,nounits 2>&1)
if ($LASTEXITCODE -ne 0 -or ($id -join ' ') -notmatch 'RTX\s+4090') { throw "Selected GPU is not an RTX 4090: $($id -join ' ')" }
$idLine = ($id -join ' ')
if ($idLine -notmatch '(?i)RTX\s+4090\s*,\s*(\d+)') { throw "Cannot parse 4090 VRAM capacity: $idLine" }
if ([int]$Matches[1] -lt 23000) { throw "Not enough VRAM for RTX 4090: $idLine" }
& $smi -i $GpuIndex -q > (Join-Path $out 'preflight.txt')
$fields = 'timestamp,index,name,memory.total,memory.used,temperature.gpu,utilization.gpu,power.draw,clocks.sm,clocks.mem,pstate'
$csvPath = Join-Path $out 'telemetry.csv'
'"timestamp","index","name","memory_total_MiB","memory_used_MiB","temp_core_C","gpu_util_pct","power_W","sm_clock_MHz","mem_clock_MHz","pstate"' | Set-Content $csvPath
Write-Host "Logging GPU $GpuIndex to $out"
Write-Host 'Run OCCT/3DMark/memtest_vulkan now. STOP GUI STRESS TESTS if a high-temp warning appears.'
$end = (Get-Date).AddMinutes($DurationMinutes)
$high = $false
while ((Get-Date) -lt $end) {
  try {
    $lines = @(& $smi -i $GpuIndex --query-gpu=$fields --format=csv,noheader,nounits 2>&1)
    if ($LASTEXITCODE -ne 0) { Add-Content (Join-Path $out 'telemetry_notes.txt') "$(Get-Date): nvidia-smi failed: $($lines -join ' ')"; Start-Sleep -Seconds 2; continue }
    foreach ($line in $lines) {
      Add-Content $csvPath $line
      $parts = $line -split ','
      if ($parts.Count -ge 6) {
        $v = 0.0
        if ([double]::TryParse($parts[5].Trim(), [ref]$v) -and $v -ge $StopCoreC -and -not $high) {
          Write-Warning "GPU core temperature is $v C. STOP your stress test and investigate cooling."
          Add-Content (Join-Path $out 'telemetry_notes.txt') "TEMPERATURE THRESHOLD at $(Get-Date): $v C"
          $high = $true
        }
      }
    }
  } catch { Add-Content (Join-Path $out 'telemetry_notes.txt') "$(Get-Date): Exception: $_" }
  Start-Sleep -Seconds 2
}
Write-Host "Finished. Results: $out"
if ($high) { Write-Warning 'High core temperature observed.' }
