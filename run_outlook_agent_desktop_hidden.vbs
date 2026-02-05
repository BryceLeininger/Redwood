Dim shell
Set shell = CreateObject("WScript.Shell")

Dim scriptDir
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

shell.CurrentDirectory = scriptDir
shell.Run "pythonw -m agent_factory.desktop_agent_app", 0, False
