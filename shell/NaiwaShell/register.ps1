[CmdletBinding()]
param([switch]$Machine)

$ErrorActionPreference = 'Stop'
$Clsid = '{8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E}'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Machine) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run PowerShell as administrator to register with -Machine.'
    }
}
if (-not [Environment]::Is64BitProcess) {
    throw 'Use 64-bit PowerShell for this x64 Explorer extension.'
}

$OutDir = $null
foreach ($candidate in @(
    (Join-Path $Root 'bin\Release\net8.0-windows'),
    (Join-Path $Root 'bin\Release\net8.0-windows\win-x64'),
    (Join-Path $Root 'bin\x64\Release\net8.0-windows')
)) {
    if (Test-Path -LiteralPath (Join-Path $candidate 'NaiwaShell.comhost.dll')) {
        $OutDir = $candidate
        break
    }
}
if (-not $OutDir) { throw 'Build NaiwaShell.csproj in Release first.' }
$Files = @('NaiwaShell.comhost.dll', 'NaiwaShell.dll', 'NaiwaShell.deps.json', 'NaiwaShell.runtimeconfig.json')
$Hashes = foreach ($name in $Files) {
    $source = Join-Path $OutDir $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing build file: $source" }
    (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
}

if ($Machine) {
    # A new build gets a new directory: Explorer may still have the old DLL loaded.
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($Hashes -join '')))
        $version = ([BitConverter]::ToString($digest)).Replace('-', '').Substring(0, 20).ToLowerInvariant()
    } finally { $sha.Dispose() }
    $Dest = Join-Path $env:ProgramFiles "Naiwa\shell\$version"
    $Hive = 'HKLM:'
} else {
    $Dest = Join-Path $env:LOCALAPPDATA 'Naiwa\shell'
    $Hive = 'HKCU:'
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
foreach ($name in $Files) {
    $source = Join-Path $OutDir $name
    $target = Join-Path $Dest $name
    if ((Test-Path -LiteralPath $target) -and
        ((Get-FileHash -LiteralPath $source).Hash -eq (Get-FileHash -LiteralPath $target).Hash)) { continue }
    Copy-Item -LiteralPath $source -Destination $target -Force
}

$DestComHost = Join-Path $Dest 'NaiwaShell.comhost.dll'
$inproc = "$Hive\Software\Classes\CLSID\$Clsid\InprocServer32"
New-Item -Path $inproc -Force | Out-Null
Set-Item -LiteralPath $inproc -Value $DestComHost
New-ItemProperty -LiteralPath $inproc -Name 'ThreadingModel' -Value 'Apartment' -PropertyType String -Force | Out-Null

# Only this user's files get the menu association, even with machine COM registration.
$handler = 'HKCU:\Software\Classes\AllFilesystemObjects\shellex\ContextMenuHandlers\NaiwaDestroy'
New-Item -Path $handler -Force | Out-Null
Set-Item -LiteralPath $handler -Value $Clsid

if (-not ('NaiwaShellNotify' -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class NaiwaShellNotify {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint eventId, uint flags, IntPtr item1, IntPtr item2);
}
"@
}
[NaiwaShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host "Registered NaiwaDestroy ($Hive) at $DestComHost"
