$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonBin = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonBin = "py"
} else {
    throw "Python 3 is required but was not found in PATH."
}

& $pythonBin (Join-Path $scriptDir "start.py")
