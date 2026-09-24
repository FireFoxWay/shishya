# ============================================================================
# SHISHYA - install on Windows, from one PowerShell line:
#
#     irm https://raw.githubusercontent.com/FireFoxWay/shishya/main/install.ps1 | iex
#
# or, from a checkout you already have (a private repository has no public
# raw URL, so this is the way in until it is published):
#
#     git clone https://github.com/FireFoxWay/shishya.git
#     powershell -ExecutionPolicy Bypass -File shishya\install.ps1
#
# Then, from any new PowerShell window:
#
#     shishya create     once - builds the sandbox (slow: downloads Ubuntu)
#     shishya run        every time after - starts it all, opens the panel
#
# What this does, each step checked before it acts so running it again is
# an update rather than a second install:
#
#   1. Git and Python 3.12, through winget, if they are missing
#   2. Ollama, through winget, if it is missing
#   3. clones the repository to %USERPROFILE%\shishya, or pulls if it is there
#   4. puts that folder on your PATH, so `shishya` works in any new window
#   5. a "Shishya" shortcut on the desktop that runs `shishya run`
#   6. windows\setup.ps1, elevated (one UAC prompt): WSL2, OLLAMA_HOST, the
#      firewall rule
#
# Options, as environment variables because `irm | iex` cannot pass
# parameters:  $env:SHISHYA_BRANCH = "some-branch"   (default: main)
#              $env:SHISHYA_DIR    = "D:\shishya"    (default: ~\shishya)
#              $env:SHISHYA_NO_SETUP = "1"           (skip step 6)
#
# ASCII only, on purpose: Windows PowerShell 5.1 reads a script without a
# byte-order mark as cp1252, and the last byte of a UTF-8 dash is a curly
# quote there - which it accepts as the end of a string.
# ============================================================================
$ErrorActionPreference = "Stop"

$Repo   = "https://github.com/FireFoxWay/shishya.git"
$Branch = if ($env:SHISHYA_BRANCH) { $env:SHISHYA_BRANCH } else { "main" }
$Dir    = if ($env:SHISHYA_DIR) { $env:SHISHYA_DIR } else { Join-Path $env:USERPROFILE "shishya" }

# Run from inside a checkout: install THAT one, whatever it is called.
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot ".git")) -and
    (Test-Path (Join-Path $PSScriptRoot "shishya.cmd"))) {
    $Dir = $PSScriptRoot
    $Here = $true
} else {
    $Here = $false
}

function Say($t)  { Write-Host $t -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Todo($t) { Write-Host "  [todo] $t" -ForegroundColor Yellow }
# throw, never exit: under `irm | iex` this runs in the person's own window,
# and `exit` would close it along with the message saying what went wrong.
function Fail($t) { Write-Host "  [FAIL] $t" -ForegroundColor Red; throw "Shishya install stopped: $t" }

# winget installs change PATH in the registry, not in this window.
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Have-Winget { [bool](Get-Command winget.exe -ErrorAction SilentlyContinue) }

function Winget-Install($id, $what) {
    if (-not (Have-Winget)) {
        Fail "$what is missing and winget is not available - install $what by hand, then run this again"
    }
    # Not piped anywhere: winget draws its progress bar only when it owns the
    # console, and Ollama is a download of a gigabyte or more. Piped, the
    # window sat on "Downloading ..." with no movement for minutes and looked
    # hung.
    Say "  installing $what - this can take several minutes, watch the progress bar ..."
    & winget.exe install --id $id -e --source winget --silent `
        --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

# A real Python, not the Microsoft Store stub that opens the Store when run.
# Returns the command name that works: "py" (the launcher) or "python".
function Find-Python {
    foreach ($name in "py", "python") {
        $exe = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $exe -or $exe.Source -like "*WindowsApps*") { continue }
        $pre = if ($name -eq "py") { @("-3") } else { @() }
        try {
            $out = & $name @pre -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
        } catch { continue }
        if ("$out".Trim() -eq "True") { return $name }
    }
    return $null
}

Write-Host ""
if ($Here) {
    $current = (& git -C $Dir rev-parse --abbrev-ref HEAD 2>$null)
    if ($current) { $Branch = $current }
}
Say "Shishya - installing into $Dir (branch $Branch)"

# -- 1. Git and Python -------------------------------------------------------
Say "Tools"
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    Winget-Install "Git.Git" "Git"
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { Fail "Git did not install" }
}
Ok "Git"

if (-not (Find-Python)) {
    Winget-Install "Python.Python.3.12" "Python 3.12"
    if (-not (Find-Python)) { Fail "Python did not install - open a new window and run this again" }
}
Ok ("Python (" + (Find-Python) + ")")

# -- 2. Ollama ---------------------------------------------------------------
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollama) -and -not (Get-Command ollama.exe -ErrorAction SilentlyContinue)) {
    Winget-Install "Ollama.Ollama" "Ollama"
}
if ((Test-Path $ollama) -or (Get-Command ollama.exe -ErrorAction SilentlyContinue)) {
    Ok "Ollama"
} else {
    Todo "Ollama is not installed - get it from https://ollama.com/download"
}

# -- 3. The repository -------------------------------------------------------
Say "Repository"
if ($Here) {
    Ok "using this checkout: $Dir"
} elseif (Test-Path (Join-Path $Dir ".git")) {
    & git -C $Dir fetch --quiet origin $Branch
    & git -C $Dir checkout --quiet $Branch
    & git -C $Dir pull --quiet --ff-only origin $Branch
    if ($LASTEXITCODE -ne 0) { Fail "could not update $Dir - local changes? Try: git -C `"$Dir`" status" }
    Ok "updated $Dir"
} elseif (Test-Path $Dir) {
    Fail "$Dir exists and is not a git checkout - move it, or set `$env:SHISHYA_DIR"
} else {
    & git clone --branch $Branch $Repo $Dir
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed - is the repository private? Sign in when Git asks." }
    Ok "cloned to $Dir"
}

# -- 4. PATH -----------------------------------------------------------------
# The user PATH only, and read from the registry rather than $env:Path, which
# also holds the machine PATH - writing that back into the user's is the
# `setx PATH %PATH%` mistake.
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = @($userPath -split ";" | Where-Object { $_ })
if ($parts -notcontains $Dir) {
    [Environment]::SetEnvironmentVariable("Path", (($parts + $Dir) -join ";"), "User")
    Ok "added $Dir to your PATH"
} else {
    Ok "$Dir is on your PATH"
}
if (($env:Path -split ";") -notcontains $Dir) { $env:Path = "$env:Path;$Dir" }

# -- 5. Desktop shortcut -----------------------------------------------------
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $desktop "Shishya.lnk"))
    $link.TargetPath = Join-Path $Dir "shishya.cmd"
    $link.Arguments = "run"
    $link.WorkingDirectory = $Dir
    $link.WindowStyle = 7          # minimised: the page is what you look at
    $link.Description = "Start Shishya and open the control panel"
    $link.Save()
    Ok "Shishya shortcut on the desktop"
} catch {
    Todo "could not create the desktop shortcut: $($_.Exception.Message)"
}

# -- 6. WSL, Ollama's address, the firewall (needs administrator) ------------
Say "Windows setup"
if ($env:SHISHYA_NO_SETUP -eq "1") {
    Todo "skipped - run windows\setup.ps1 as administrator yourself"
} else {
    $setup = Join-Path $Dir "windows\setup.ps1"
    $admin = ([Security.Principal.WindowsPrincipal] `
              [Security.Principal.WindowsIdentity]::GetCurrent()
             ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    try {
        if ($admin) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup
        } else {
            Say "  asking for administrator rights (WSL and the firewall need them) ..."
            Say "  read what it says, then close that window to finish here."
            Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
                "-File", "`"$setup`"")
        }
    } catch {
        Todo "setup did not run: $($_.Exception.Message)"
        Todo "run it yourself, as administrator: $setup"
    }
}

Write-Host ""
Say "Done. Open a NEW PowerShell window (so PATH is picked up), then:"
Write-Host "    shishya create     # once: builds the sandbox - 15 to 30 minutes"
Write-Host "    shishya run        # every time after: starts everything, opens http://localhost:8200"
Write-Host ""
Write-Host "If windows\setup.ps1 said to restart Windows, do that first."
