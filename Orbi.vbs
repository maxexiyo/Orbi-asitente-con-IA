' Abre Orbi SIN ventana de consola (doble clic). Los errores quedan en orbi.log
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
py = dir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw"
sh.Run Chr(34) & py & Chr(34) & " " & Chr(34) & dir & "\live_orb.py" & Chr(34), 0, False
