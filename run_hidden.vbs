' Start WebPrint server silently (no console window).
' Uses pyw (windowed python) so nothing flashes on screen.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)

On Error Resume Next
sh.Run "pyw -3 """ & base & "\app.py""", 0, False
If Err.Number <> 0 Then
    Err.Clear
    sh.Run "pythonw """ & base & "\app.py""", 0, False
End If
On Error GoTo 0
