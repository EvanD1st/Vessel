' Silent background launcher for VESSEL Companion Daemon
' Runs pythonw.exe completely hidden with 0 console/terminal window.

Option Explicit
Dim WshShell, command, pythonwPath, statePath, fso

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

pythonwPath = "C:\Users\USER\AppData\Local\Programs\Python\Python314\pythonw.exe"
statePath = "C:\Users\USER\AppData\Local\VESSEL\projects\6d192de427b15783"

If Not fso.FileExists(pythonwPath) Then
    pythonwPath = "pythonw.exe"
End If

command = """" & pythonwPath & """ -m vessel.desktop --state """ & statePath & """"
WshShell.Run command, 0, False
