using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

[assembly: ComVisible(false)]

namespace NaiwaShell;

[ComVisible(true)]
[Guid(NaiwaContextMenu.Clsid)]
[ClassInterface(ClassInterfaceType.None)]
[ProgId("Naiwa.DestroyContextMenu")]
public sealed class NaiwaContextMenu : IShellExtInit, IContextMenu
{
    public const string Clsid = "8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E";
    public const string MutexName = @"Local\NaiwaPet.Running";
    public const string PipeName = "NaiwaDestroy";
    public const string MenuText = "召唤奶蛙摧毁";
    public const string Verb = "NaiwaDestroy";
    public const int PipeTimeoutMs = 300;

    private string _path = "";

    [PreserveSig]
    public int Initialize(
        IntPtr pidlFolder,
        [MarshalAs(UnmanagedType.Interface)] IDataObject? pdtobj,
        IntPtr hkeyProgID)
    {
        _path = "";
        try
        {
            if (pdtobj is null)
            {
                return Native.S_OK;
            }

            string? first = Native.FirstHdropPath(pdtobj);
            if (!string.IsNullOrEmpty(first))
            {
                _path = first;
            }
        }
        catch
        {
            _path = "";
        }

        return Native.S_OK;
    }

    [PreserveSig]
    public int QueryContextMenu(IntPtr hMenu, uint indexMenu, uint idCmdFirst, uint idCmdLast, uint uFlags)
    {
        try
        {
            if (hMenu == IntPtr.Zero || idCmdLast < idCmdFirst)
            {
                return Native.S_OK;
            }

            if ((uFlags & Native.CMF_DEFAULTONLY) != 0)
            {
                return Native.S_OK;
            }

            if (!PetIsRunning())
            {
                return Native.S_OK;
            }

            if (!IsDesktopPath(_path))
            {
                return Native.S_OK;
            }

            bool inserted = Native.InsertMenuW(
                hMenu,
                indexMenu,
                Native.MF_STRING | Native.MF_BYPOSITION,
                new UIntPtr(idCmdFirst),
                MenuText);

            return inserted ? 1 : Native.S_OK;
        }
        catch
        {
            return Native.S_OK;
        }
    }

    [PreserveSig]
    public int InvokeCommand(IntPtr pici)
    {
        try
        {
            if (pici == IntPtr.Zero || !IsOurCommand(pici))
            {
                return Native.E_FAIL;
            }

            SendPathSilently(_path);
            return Native.S_OK;
        }
        catch
        {
            return Native.S_OK;
        }
    }

    [PreserveSig]
    public int GetCommandString(UIntPtr idCmd, uint uType, IntPtr pReserved, IntPtr pszName, uint cchMax)
    {
        try
        {
            if (idCmd != UIntPtr.Zero)
            {
                return Native.E_INVALIDARG;
            }

            if (uType == Native.GCS_VALIDATEW)
            {
                return Native.S_OK;
            }

            if (uType != Native.GCS_HELPTEXTW && uType != Native.GCS_VERBW)
            {
                return Native.E_NOTIMPL;
            }

            string text = uType == Native.GCS_HELPTEXTW ? MenuText : Verb;

            WriteUnicode(pszName, cchMax, text);
            return Native.S_OK;
        }
        catch
        {
            return Native.E_FAIL;
        }
    }

    internal static bool PetIsRunning()
    {
        try
        {
            if (!Mutex.TryOpenExisting(MutexName, out Mutex? existing))
            {
                return false;
            }

            existing.Dispose();
            return true;
        }
        catch
        {
            return false;
        }
    }

    internal static bool IsDesktopPath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        string target;
        try
        {
            target = NormalizePrefix(Path.GetFullPath(path));
        }
        catch
        {
            return false;
        }

        foreach (string? root in DesktopRoots())
        {
            if (string.IsNullOrWhiteSpace(root))
            {
                continue;
            }

            string prefix;
            try
            {
                prefix = NormalizePrefix(Path.GetFullPath(root));
            }
            catch
            {
                continue;
            }

            if (target.Equals(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (target.StartsWith(prefix + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    private static IEnumerable<string?> DesktopRoots()
    {
        yield return Native.GetKnownFolderPath(Native.FolderIdDesktop);
        yield return Native.GetKnownFolderPath(Native.FolderIdPublicDesktop);
        yield return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        yield return Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory);
    }

    private static string NormalizePrefix(string path)
    {
        return path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static bool IsOurCommand(IntPtr pici)
    {
        CMINVOKECOMMANDINFO info = Marshal.PtrToStructure<CMINVOKECOMMANDINFO>(pici);
        nint verb = info.lpVerb;
        if ((nuint)verb <= 0xFFFF)
        {
            return (ushort)(nuint)verb == 0;
        }

        try
        {
            string? name = Marshal.PtrToStringAnsi(verb);
            if (string.Equals(name, Verb, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            name = Marshal.PtrToStringUni(verb);
            return string.Equals(name, Verb, StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static void SendPathSilently(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return;
        }

        try
        {
            using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.Out);
            pipe.Connect(PipeTimeoutMs);
            byte[] payload = Encoding.UTF8.GetBytes(path + "\n");
            pipe.Write(payload, 0, payload.Length);
            pipe.Flush();
        }
        catch
        {
            // Spec: fail silently; never launch the pet.
        }
    }

    private static void WriteUnicode(IntPtr dest, uint cchMax, string text)
    {
        if (dest == IntPtr.Zero || cchMax == 0)
        {
            return;
        }

        char[] chars = text.ToCharArray();
        int maxChars = (int)cchMax;
        int copy = Math.Min(chars.Length, Math.Max(0, maxChars - 1));
        for (int i = 0; i < copy; i++)
        {
            Marshal.WriteInt16(dest, i * 2, chars[i]);
        }

        Marshal.WriteInt16(dest, copy * 2, 0);
    }
}
