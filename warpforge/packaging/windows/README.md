# Windows

GIMP 3 for Windows bundles its own Python (an MSYS2/UCRT build without NumPy).
WarpForge needs nothing else.

Install from the release ZIP (no Python needed): unpack it and run

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

(`-Uninstall` removes it, `-GimpVersion 3.0` picks a profile). From a source
checkout: `python tools\install.py`.

Debugging: GIMP runs plug-ins with `pythonw.exe`, so there is no console.
Set a log file before starting GIMP:

```powershell
$env:WARPFORGE_LOG_FILE = "$env:TEMP\warpforge.log"; & "$env:LOCALAPPDATA\Programs\GIMP 3\bin\gimp-3.exe"
```

The native library (`warpforge_native.dll`) is a plain C ABI DLL
loaded with `ctypes`; an MSVC build loads fine in GIMP's Python (verified).
