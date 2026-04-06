$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Green
}

# Check if uv is installed
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Info "uv is not installed. Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    
    # Refresh PATH from registry to see the new installation in the current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" + [System.Environment]::GetEnvironmentVariable("Path","Machine")
    
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        # Fallback check in default location if PATH update failed for some reason
        $uvPath = "$env:LOCALAPPDATA\programs\uv\uv.exe"
        if (Test-Path $uvPath) {
             # Add to current session path temporarily
             $env:Path = "$(Split-Path $uvPath);$env:Path"
        } else {
            Write-Error "Failed to install uv or find it in PATH. Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
            exit 1
        }
    }
    Write-Success "uv installed successfully"
} else {
    Write-Info "uv is already installed"
}

# Run create-pywire-app
Write-Info "Running create-pywire-app..."
uvx create-pywire-app @args
