# Videogen Studio installer for Windows 10/11.
# Run install.bat (double-click) or:  powershell -ExecutionPolicy Bypass -File install.ps1 [options]
#
#   -Gpu auto|nvidia|amd|cpu   which PyTorch build to install (default: detected)
#   -TorchIndex <url>          use a specific PyTorch wheel index instead
#   -Models video,image|none   which models to download now (default: ask; "none" = later, from the app)
#   -NoShortcut                don't create the desktop shortcut
#   -Yes                       no questions (models: none unless -Models is given)
#
# Everything goes into this folder (venv\, tools\, models\). Nothing is installed system-wide.
# Safe to run again: finished steps are skipped, interrupted model downloads resume.
param(
    [ValidateSet('auto', 'nvidia', 'amd', 'cpu')][string]$Gpu = 'auto',
    [string]$TorchIndex = '',
    [string[]]$Models = @(),
    [switch]$NoShortcut,
    [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is 10x slower with the progress bar
Set-Location $PSScriptRoot
$Root = $PSScriptRoot
$ElectronVersion = '33.4.11'
$ElectronSha = 'f64c8a5a81d9b420b636fdba13e180f49d69f2198e1d86a8b01f858b17a9483c'

function Step($n, $text) { Write-Host ""; Write-Host "[$n/6] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      $text" -ForegroundColor Green }
function Info($text) { Write-Host "      $text" -ForegroundColor Gray }
function Warn($text) { Write-Host "      $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host ""; Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Videogen Studio installer" -ForegroundColor White
Write-Host "  local image -> video (Wan 2.2) and text -> image (Chroma), no cloud" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. uv + Python
Step 1 "Python 3.12 (private copy in this folder)"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'tools\python'
$uv = Join-Path $Root 'tools\uv.exe'
if (-not (Test-Path $uv)) {
    $sys = Get-Command uv -ErrorAction SilentlyContinue
    if ($sys) { $uv = $sys.Source }
    else {
        Info "downloading uv (Python package manager)..."
        $env:UV_INSTALL_DIR = Join-Path $Root 'tools'
        $env:UV_NO_MODIFY_PATH = '1'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        if (-not (Test-Path $uv)) { Fail "uv could not be installed. Check your internet connection." }
    }
}
$py = Join-Path $Root 'venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    & $uv venv --python 3.12 venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create the Python environment." }
}
Ok "Python ready"

# ---------------------------------------------------------------- 2. GPU + PyTorch
Step 2 "PyTorch for your graphics card"
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
Info ("found: " + ($gpus -join ', '))
if ($Gpu -eq 'auto') {
    if ($gpus -match 'NVIDIA') { $Gpu = 'nvidia' }
    elseif ($gpus -match 'AMD|Radeon') { $Gpu = 'amd' }
    else { $Gpu = 'cpu' }
}
$envLines = @('# written by install.ps1 - GPU settings for Videogen Studio (KEY=VALUE, environment variables win)')
if (-not $TorchIndex) {
    switch ($Gpu) {
        'nvidia' {
            # CUDA 13 wheels need driver 580+, CUDA 12.8 needs 570+; older drivers get CUDA 12.6
            $drv = 0
            try { $drv = [double]((& nvidia-smi --query-gpu=driver_version --format=csv,noheader | Select-Object -First 1).Split('.')[0]) } catch {}
            if ($drv -ge 580 -or $drv -eq 0) { $TorchIndex = 'https://download.pytorch.org/whl/cu130' }
            elseif ($drv -ge 570) { $TorchIndex = 'https://download.pytorch.org/whl/cu128' }
            else { $TorchIndex = 'https://download.pytorch.org/whl/cu126'; Warn "NVIDIA driver $drv is old - consider updating to 580+ for the newest PyTorch." }
        }
        'amd' {
            # PyTorch for AMD on Windows comes from AMD's TheRock builds, one index per GPU family
            $all = $gpus -join ' '
            $gfx = $null
            if ($all -match '8060S|8050S|8040S|AI MAX') { $gfx = 'gfx1151' }
            elseif ($all -match '890M|880M|860M') { $gfx = 'gfx1150' }
            elseif ($all -match 'RX 90[0-9]0|R9700|AI PRO') { $gfx = 'gfx120X-all' }
            elseif ($all -match 'RX 7[0-9]00|W7[0-9]00|780M|760M|740M') { $gfx = 'gfx110X-all' }
            if (-not $gfx) {
                Warn ("no Windows PyTorch build is known for this AMD GPU - installing the CPU build so the app still opens. " +
                      "For GPU support use Linux (ROCm), or re-run with -TorchIndex <url> from https://github.com/ROCm/TheRock")
                $TorchIndex = 'https://download.pytorch.org/whl/cpu'
            } else {
                $TorchIndex = "https://rocm.nightlies.amd.com/v2/$gfx/"
                $envLines += 'TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1'
                Info "AMD family $gfx (TheRock nightly builds - AMD on Windows is still a preview)"
            }
        }
        default {
            Warn "no NVIDIA or AMD GPU found - installing the CPU build. The app opens, but generating needs a GPU."
            $TorchIndex = 'https://download.pytorch.org/whl/cpu'
        }
    }
}
$ErrorActionPreference = 'Continue'   # PowerShell 5.1 turns redirected stderr into terminating errors
& $py -c "import torch" 2>$null | Out-Null
$hasTorch = $LASTEXITCODE -eq 0
$ErrorActionPreference = 'Stop'
if ($hasTorch) {
    Ok "PyTorch already installed - keeping it"
} else {
    Info "installing PyTorch from $TorchIndex (about 2-4 GB)..."
    & $uv pip install --python $py --index-url $TorchIndex torch
    if ($LASTEXITCODE -ne 0) { Fail "PyTorch install failed. Try again, or pass -TorchIndex <url>." }
    Ok "PyTorch installed"
}
if (-not (Test-Path (Join-Path $Root 'local.env'))) { $envLines | Set-Content -Encoding ascii (Join-Path $Root 'local.env') }

# ---------------------------------------------------------------- 3. Python packages
Step 3 "Python packages (diffusers, transformers, ...)"
& $uv pip install --python $py -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "package install failed." }
Ok "packages installed"

# ---------------------------------------------------------------- 4. check the GPU
Step 4 "Checking the GPU"
# written to a file: PowerShell 5.1 mangles double quotes in arguments of native programs
$checkPy = Join-Path $env:TEMP 'videogen_gpu_check.py'
@'
import torch
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print('OK ' + p.name + ' ' + str(round(p.total_memory / 2**30)))
else:
    print('NOGPU')
'@ | Set-Content -Encoding ascii $checkPy
$ErrorActionPreference = 'Continue'
$res = (& $py $checkPy 2>$null | Select-Object -Last 1)
Remove-Item $checkPy -ErrorAction SilentlyContinue
$ErrorActionPreference = 'Stop'
if (-not $res) { $res = '' }
if ($res -like 'OK *') {
    $parts = $res.Split(' ')
    $mem = [int]$parts[-1]
    Ok ("GPU: " + ($parts[1..($parts.Count - 2)] -join ' ') + ", $mem GB")
    if ($mem -lt 22) { Warn "Image generation runs with CPU offload (slower). Video (Wan 2.2 A14B) needs ~64 GB of GPU memory." }
    elseif ($mem -lt 60) { Warn "Image generation: fine. Video (Wan 2.2 A14B) needs ~64 GB of GPU memory and will likely run out of memory." }
} else {
    Warn "PyTorch does not see a GPU. The app will start, but generation will fail. See README > Troubleshooting."
}

# ---------------------------------------------------------------- 5. desktop app (Electron, no Node.js needed)
Step 5 "Desktop app"
$exe = Join-Path $Root 'studio\node_modules\electron\dist\electron.exe'
if (Test-Path $exe) {
    Ok "already installed"
} else {
    $zip = Join-Path $env:TEMP "electron-v$ElectronVersion-win32-x64.zip"
    Info "downloading Electron $ElectronVersion (~110 MB)..."
    Invoke-WebRequest "https://github.com/electron/electron/releases/download/v$ElectronVersion/electron-v$ElectronVersion-win32-x64.zip" -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $ElectronSha) { Remove-Item $zip; Fail "Electron download is corrupted (checksum mismatch). Run the installer again." }
    $dist = Join-Path $Root 'studio\node_modules\electron\dist'
    $tmp = "$dist.tmp"   # extract next to it first, so an interrupted install never looks finished
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip -DestinationPath $tmp -Force
    if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
    New-Item -ItemType Directory -Force (Split-Path $dist) | Out-Null
    Move-Item $tmp $dist
    Remove-Item $zip
    Ok "installed"
}
if (-not $NoShortcut) {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Videogen Studio.lnk'
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = $exe
    $sh.Arguments = 'studio'
    $sh.WorkingDirectory = $Root
    $sh.IconLocation = Join-Path $Root 'studio\icon.ico'
    $sh.Description = 'Videogen Studio'
    $sh.Save()
    Ok "desktop shortcut created"
}

# ---------------------------------------------------------------- 6. models
Step 6 "Models"
$Models = @($Models | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if (-not $Models) {
    if ($Yes) { $Models = @('none') }
    else {
        Write-Host "      What should be downloaded now? (you can also do it later inside the app)"
        Write-Host "        1  Image model  Chroma1-HD       27.5 GB   needs ~24 GB GPU memory (less with offload)"
        Write-Host "        2  Video model  Wan 2.2 A14B     71 GB     needs ~64 GB GPU memory"
        Write-Host "        3  Both                          99 GB"
        Write-Host "        4  Later, from the app"
        $c = Read-Host "      Choice [4]"
        $pick = @{ '1' = @('image'); '2' = @('video'); '3' = @('image', 'video') }[$c]
        $Models = if ($pick) { $pick } else { @('none') }
    }
}
$list = @($Models | Where-Object { $_ -ne 'none' })
if ($list.Count -gt 0) {
    & $py download_models.py @list
    if ($LASTEXITCODE -ne 0) { Warn "Download did not finish. Run install.bat again or use the Download button in the app - it resumes." }
} else {
    Info "skipped - the app offers the download when you open Create image / Create video"
}

Write-Host ""
Write-Host "  Done. Start Videogen Studio from the desktop shortcut or with studio.bat" -ForegroundColor Green
Write-Host ""
