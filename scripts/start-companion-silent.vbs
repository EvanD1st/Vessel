' Silent background launcher for VESSEL Companion Daemon
' Runs pythonw.exe completely hidden with 0 console/terminal window.

Option Explicit
Dim WshShell, command, pythonwPath, statePath, fso

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count < 2 Then
    WScript.Quit 1
End If
pythonwPath = WScript.Arguments(0)
statePath = WScript.Arguments(1)
If Not fso.FileExists(pythonwPath) Or Not fso.FolderExists(statePath) Then WScript.Quit 1

command = """" & pythonwPath & """ -m vessel.desktop --state """ & statePath & """"
WshShell.Run command, 0, False
