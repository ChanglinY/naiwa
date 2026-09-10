using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace NaiwaShell;

internal static class Native
{
    internal const uint CF_HDROP = 15;

    internal const uint MF_STRING = 0x0000;
    internal const uint MF_BYPOSITION = 0x0400;
    internal const uint CMF_DEFAULTONLY = 0x00000001;

    internal const uint GCS_VERBW = 0x00000004;
    internal const uint GCS_HELPTEXTW = 0x00000005;
    internal const uint GCS_VALIDATEW = 0x00000006;

    internal const int S_OK = 0;
    internal const int E_FAIL = unchecked((int)0x80004005);
    internal const int E_INVALIDARG = unchecked((int)0x80070057);
    internal const int E_NOTIMPL = unchecked((int)0x80004001);

    internal static readonly Guid FolderIdDesktop = new("B4BFCC3A-DB2C-424C-B029-7FE99A87C641");
    internal static readonly Guid FolderIdPublicDesktop = new("C4AA340D-F20F-4863-AFEF-F87EF2E6BA25");

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    internal static extern uint DragQueryFileW(IntPtr hDrop, uint iFile, StringBuilder? lpszFile, uint cch);

    [DllImport("ole32.dll")]
    internal static extern void ReleaseStgMedium(ref STGMEDIUM medium);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern bool InsertMenuW(IntPtr hMenu, uint uPosition, uint uFlags, UIntPtr uIDNewItem, string lpNewItem);

    [DllImport("shell32.dll")]
    internal static extern int SHGetKnownFolderPath(
        ref Guid rfid,
        uint dwFlags,
        IntPtr hToken,
        out IntPtr ppszPath);

    [DllImport("ole32.dll")]
    internal static extern void CoTaskMemFree(IntPtr pv);

    internal static string? GetKnownFolderPath(Guid folderId)
    {
        IntPtr ptr = IntPtr.Zero;
        try
        {
            Guid id = folderId;
            int hr = SHGetKnownFolderPath(ref id, 0, IntPtr.Zero, out ptr);
            if (hr != 0 || ptr == IntPtr.Zero)
            {
                return null;
            }

            return Marshal.PtrToStringUni(ptr);
        }
        catch
        {
            return null;
        }
        finally
        {
            if (ptr != IntPtr.Zero)
            {
                CoTaskMemFree(ptr);
            }
        }
    }

    internal static string? FirstHdropPath(IDataObject dataObject)
    {
        FORMATETC format = new()
        {
            cfFormat = (short)CF_HDROP,
            ptd = IntPtr.Zero,
            dwAspect = DVASPECT.DVASPECT_CONTENT,
            lindex = -1,
            tymed = TYMED.TYMED_HGLOBAL,
        };

        STGMEDIUM medium = default;
        bool gotMedium = false;
        try
        {
            dataObject.GetData(ref format, out medium);
            gotMedium = true;
            if (medium.unionmember == IntPtr.Zero)
            {
                return null;
            }

            uint count = DragQueryFileW(medium.unionmember, 0xFFFFFFFF, null, 0);
            if (count == 0)
            {
                return null;
            }

            var buffer = new StringBuilder(32768);
            uint copied = DragQueryFileW(medium.unionmember, 0, buffer, (uint)buffer.Capacity);
            if (copied == 0)
            {
                return null;
            }

            string path = buffer.ToString();
            return string.IsNullOrWhiteSpace(path) ? null : path;
        }
        catch
        {
            return null;
        }
        finally
        {
            if (gotMedium)
            {
                ReleaseStgMedium(ref medium);
            }
        }
    }
}

[ComVisible(true)]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("000214E8-0000-0000-C000-000000000046")]
public interface IShellExtInit
{
    [PreserveSig]
    int Initialize(
        IntPtr pidlFolder,
        [MarshalAs(UnmanagedType.Interface)] IDataObject? pdtobj,
        IntPtr hkeyProgID);
}

[ComVisible(true)]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("000214E4-0000-0000-C000-000000000046")]
public interface IContextMenu
{
    [PreserveSig]
    int QueryContextMenu(IntPtr hMenu, uint indexMenu, uint idCmdFirst, uint idCmdLast, uint uFlags);

    [PreserveSig]
    int InvokeCommand(IntPtr pici);

    [PreserveSig]
    int GetCommandString(UIntPtr idCmd, uint uType, IntPtr pReserved, IntPtr pszName, uint cchMax);
}

[StructLayout(LayoutKind.Sequential)]
internal struct CMINVOKECOMMANDINFO
{
    public uint cbSize;
    public uint fMask;
    public IntPtr hwnd;
    public IntPtr lpVerb;
    public IntPtr lpParameters;
    public IntPtr lpDirectory;
    public int nShow;
    public uint dwHotKey;
    public IntPtr hIcon;
}
