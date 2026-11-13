' Arranca el receptor RIV-Alert sin abrir ninguna ventana.
' Si ya está funcionando, el propio receptor se cierra al momento (solo puede haber uno).
Set sh = CreateObject("WScript.Shell")
dir = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\AlertasRivas"
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & dir & "\receptor.ps1""", 0, False
