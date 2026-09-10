[CmdletBinding()]
param([switch]$Machine)

$ErrorActionPreference = 'Stop'
$Clsid = '{8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E}'
if ($Machine) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run PowerShell as administrator to unregister with -Machine.'
    }
}
if (-not [Environment]::Is64BitProcess) { throw 'Use 64-bit PowerShell.' }

$keys = @(
    'HKCU:\Software\Classes\AllFilesystemObjects\shellex\ContextMenuHandlers\NaiwaDestroy',
    "HKCU:\Software\Classes\CLSID\$Clsid"
)
if ($Machine) { $keys += "HKLM:\Software\Classes\CLSID\$Clsid" }
# These are the exact Naiwa-owned registry keys; installed DLLs are retained.
foreach ($key in $keys) {
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
}
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
Write-Host 'Unregistered NaiwaDestroy. Installed DLL files were left in place.'
if (-not $Machine) {
    Write-Host 'If installed with -Machine, also run this script with -Machine as administrator.'
}
