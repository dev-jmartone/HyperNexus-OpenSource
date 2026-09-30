Set objShell = CreateObject("WScript.Shell") 
objShell.CurrentDirectory = "C:\" 
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "".\EstadoUsuario_temp.ps1""", 1, False 
