Option Explicit

Dim shell, files, baseDir, pythonPath, appPath
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
baseDir = files.GetParentFolderName(WScript.ScriptFullName)
pythonPath = files.BuildPath(baseDir, ".venv\Scripts\pythonw.exe")
appPath = files.BuildPath(baseDir, "launch_app.pyw")

If Not files.FileExists(pythonPath) Then
    MsgBox "Python environment not found. Please follow the installation steps in README.md.", vbCritical, "Docspace"
    WScript.Quit 1
End If
If Not files.FileExists(appPath) Then
    MsgBox "launch_app.pyw not found. Keep this launcher in the Docspace folder.", vbCritical, "Docspace"
    WScript.Quit 1
End If

shell.CurrentDirectory = baseDir
shell.Run Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & appPath & Chr(34), 0, False
