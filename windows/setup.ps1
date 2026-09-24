# ============================================================================
# SHISHYA - prepare this Windows machine for the sandbox. Run once, as
# administrator:
#
#     powershell -ExecutionPolicy Bypass -File windows\setup.ps1
#
# Three things, each checked before it is changed, so running it twice is
# harmless:
#
#   1. WSL2 is installed. The sandbox is a WSL distribution of its own.
#   2. Ollama listens where the sandbox can reach it. By default it answers
#      on 127.0.0.1 only, and the sandbox is not 127.0.0.1 - it reaches
#      Windows at its NAT gateway, which is a different address.
#   3. The firewall lets the sandbox, and only the sandbox, reach port 11434.
#      Listening on every address would otherwise put the model on your
#      Wi-Fi as well.
#
# Nothing here creates the sandbox itself; that is host/vm.py's create(),
# which needs no administrator rights.
# ============================================================================
# ASCII only, on purpose: Windows PowerShell 5.1 reads a script without a
# byte-order mark as cp1252, and the last byte of a UTF-8 dash is a curly
# quote there - which it accepts as the end of a string.
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"

function Say($t)  { Write-Host $t -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Todo($t) { Write-Host "  [todo] $t" -ForegroundColor Yellow }

# Programs are run through this, never directly. Windows PowerShell 5.1,
# with ErrorActionPreference = Stop, turns anything a program writes to stderr
# into a terminating error once stderr is redirected - so `wsl --status` on a
# machine without WSL, which says so on stderr, killed this script on the very
# check meant to notice that and install it. Exit codes are what we test.
function Run-Native([scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $block } finally { $ErrorActionPreference = $saved }
}

# -- 1. WSL ------------------------------------------------------------------
Say "WSL"
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
$ready = $false
if ($wsl) {
    Run-Native { & wsl.exe --status *> $null }
    $ready = ($LASTEXITCODE -eq 0)
}
if ($ready) {
    Run-Native { & wsl.exe --update *> $null }
    Run-Native { & wsl.exe --set-default-version 2 *> $null }
    Ok "WSL2 is installed and up to date"
} else {
    # --no-distribution: the sandbox brings its own Ubuntu, and a second one
    # installed alongside it would only be confusing.
    Say "  installing WSL - this downloads and enables Windows features ..."
    Run-Native { & wsl.exe --install --no-distribution }
    if ($LASTEXITCODE -ne 0) {
        Todo "wsl --install failed (exit $LASTEXITCODE). Check that virtualisation is"
        Todo "enabled in the BIOS/UEFI, then run this again."
    } else {
        Todo "WSL was just installed. RESTART WINDOWS, then run install.ps1 again."
    }
    exit 0
}

# Mirrored networking would make the sandbox share Windows' own addresses,
# and the egress lock is written for NAT - the host as the gateway, loopback
# as the sandbox's own. Warn rather than rewrite somebody's global settings.
$wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
if ((Test-Path $wslconfig) -and
    (Select-String -Path $wslconfig -Pattern '^\s*networkingMode\s*=\s*mirrored' -Quiet)) {
    Todo "$wslconfig sets networkingMode=mirrored. Shishya's lock expects NAT:"
    Todo "remove that line (it affects every WSL distribution), then: wsl --shutdown"
} else {
    Ok "WSL networking is NAT"
}

# -- 2. Ollama ---------------------------------------------------------------
Say "Ollama"
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (Test-Path $ollama) {
    Ok "installed at $ollama"
} else {
    Todo "install Ollama for Windows from https://ollama.com/download, then run this again"
}

# For the user, not the machine: the Ollama tray app reads it at start.
$want = "0.0.0.0:11434"
if ([Environment]::GetEnvironmentVariable("OLLAMA_HOST", "User") -ne $want) {
    [Environment]::SetEnvironmentVariable("OLLAMA_HOST", $want, "User")
    Todo "OLLAMA_HOST set to $want - quit Ollama from the tray and start it again"
} else {
    Ok "OLLAMA_HOST is $want"
}

# -- 3. The firewall ---------------------------------------------------------
Say "Firewall"
# Scoped to WSL's virtual adapter: the sandbox can reach the model, the
# network the laptop is sitting on cannot. The adapter is created the first
# time any WSL 2 distribution boots, so boot one if it is not there yet.
$rule = "Shishya: model, from the sandbox only"
$alias = "vEthernet (WSL*)"
if (-not (Get-NetAdapter -Name $alias -ErrorAction SilentlyContinue)) {
    Todo "no WSL network adapter yet - create the sandbox, then run this again"
} else {
    $name = (Get-NetAdapter -Name $alias | Select-Object -First 1).Name
    Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort 11434 -InterfaceAlias $name -Profile Any | Out-Null
    Ok "inbound 11434 allowed on '$name' only"
}

# The Hyper-V firewall (Windows 11 22H2+) filters traffic between WSL and
# Windows as well; its default allows the guest to start connections, which
# is all the sandbox needs. Reported, not changed.
if (Get-Command Get-NetFirewallHyperVVMSetting -ErrorAction SilentlyContinue) {
    $hv = Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore `
        -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -ErrorAction SilentlyContinue
    if ($hv -and $hv.DefaultOutboundAction -eq "Block") {
        Todo "the Hyper-V firewall blocks WSL outbound by default; the sandbox"
        Todo "will not reach the model until that is allowed for port 11434"
    } else {
        Ok "Hyper-V firewall lets the sandbox start connections"
    }
}

Write-Host ""
Say "Next, in a new PowerShell window:"
Write-Host '    shishya create     # once - builds the sandbox'
Write-Host '    shishya run        # starts everything and opens the panel'
Write-Host '(shishya create re-runs this for the firewall rule once the sandbox'
Write-Host 'has booted and the WSL network adapter exists - one more UAC prompt.)'
