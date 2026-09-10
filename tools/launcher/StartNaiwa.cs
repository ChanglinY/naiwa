using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    static int Main()
    {
        var dir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
            Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var runPy = Path.Combine(dir, "run.py");
        var req = Path.Combine(dir, "requirements.txt");
        var venvPy = Path.Combine(dir, ".venv", "Scripts", "python.exe");
        var venvPyw = Path.Combine(dir, ".venv", "Scripts", "pythonw.exe");

        if (!File.Exists(runPy))
        {
            Fail("找不到 run.py。请把本程序放在奶蛙项目根目录（和 run.py 同一层）。");
            return 1;
        }

        try
        {
            if (!File.Exists(venvPyw))
            {
                var bootstrap = FindPython();
                if (bootstrap == null)
                {
                    Fail(
                        "未检测到 Python 3。\n\n" +
                        "这个启动器只会替你运行 run.py，并不能代替 Python。\n" +
                        "请先安装 Python 3，安装时勾选 Add python.exe to PATH，然后再双击本程序。\n\n" +
                        "https://www.python.org/downloads/windows/");
                    return 1;
                }

                MessageBox.Show(
                    "第一次运行会创建虚拟环境并安装依赖，可能需要一两分钟。",
                    "奶蛙",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);

                var venvArgs = bootstrap.Item2 + "-m venv .venv";
                if (Run(bootstrap.Item1, venvArgs, dir) != 0 || !File.Exists(venvPy))
                {
                    Fail("创建虚拟环境失败。请确认已安装 Python 3，并勾选 Add python.exe to PATH。");
                    return 1;
                }

                if (File.Exists(req))
                {
                    if (Run(venvPy, "-m pip install -r requirements.txt", dir) != 0)
                    {
                        Fail("安装依赖失败。请检查网络后重试。");
                        return 1;
                    }
                }
            }

            var psi = new ProcessStartInfo
            {
                FileName = File.Exists(venvPyw) ? venvPyw : venvPy,
                Arguments = Quote(runPy),
                WorkingDirectory = dir,
                UseShellExecute = false,
            };
            Process.Start(psi);
            return 0;
        }
        catch (Exception ex)
        {
            Fail(ex.Message);
            return 1;
        }
    }

    static Tuple<string, string> FindPython()
    {
        var py = ResolveOnPath("py.exe");
        if (py != null)
            return Tuple.Create(py, "-3 ");

        var python = ResolveOnPath("python.exe") ?? ResolveOnPath("python3.exe");
        if (python != null)
            return Tuple.Create(python, "");

        return null;
    }

    static string ResolveOnPath(string name)
    {
        var path = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrEmpty(path))
            return null;

        foreach (var dir in path.Split(Path.PathSeparator))
        {
            if (string.IsNullOrWhiteSpace(dir))
                continue;
            var candidate = Path.Combine(dir.Trim('"'), name);
            if (File.Exists(candidate))
                return candidate;
        }
        return null;
    }

    static int Run(string fileName, string arguments, string workingDirectory)
    {
        var psi = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
        };
        using (var proc = Process.Start(psi))
        {
            if (proc == null)
                return 1;
            proc.WaitForExit();
            return proc.ExitCode;
        }
    }

    static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    static void Fail(string message)
    {
        MessageBox.Show(message, "奶蛙", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}
