SHISHYA FOR WINDOWS
===================

1. Keep this whole folder together. Shishya.exe needs the "payload" folder
   beside it. Put the folder anywhere - the Desktop is fine.

2. Double-click Shishya.exe.

   Your browser opens on the setup page. Press the button next to anything
   that says "not yet":

     01  Windows is ready     - one administrator prompt. If it says to
                                restart Windows, restart, then open
                                Shishya.exe again.
     02  The AI model         - installs Ollama (about 1 GB).
     03  The sandbox          - builds it, 20 to 30 minutes, once.
                                Leave the page open; it shows progress.
     04  Running              - starts it.

   When all four say "ready", press "Open Shishya".

3. After that, double-clicking Shishya.exe just opens Shishya.

Windows may show "Windows protected your PC" the first time, because this
program is not code-signed. Click "More info", then "Run anyway".

Where things live: the program copies itself to %LOCALAPPDATA%\shishya and
runs from there; your files are in %LOCALAPPDATA%\shishya\app\shared.
Updating = download a newer zip and run its Shishya.exe; your files are kept.

If virtualisation is off in the BIOS (setup step 01 will say so), on an ASUS
ROG laptop: F2 at power-on -> F7 (Advanced Mode) -> Advanced -> CPU
Configuration -> Intel (VMX) Virtualization Technology -> Enabled -> F10.
