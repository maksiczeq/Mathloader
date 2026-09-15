<#
    Mathloader - pelny build: exe + wersja portable (ZIP) + instalator (.exe)

    Uzycie:
        .\build.ps1                  # wszystko
        .\build.ps1 -SkipInstaller   # bez Inno Setup
        .\build.ps1 -Clean           # wyczysc artefakty i wyjdz

    UWAGA: ten plik MUSI byc zapisany jako UTF-8 z BOM.
    Windows PowerShell 5.1 czyta skrypty bez BOM jako ANSI (cp1250)
    i polskie znaki rozwalaja parser.
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Python  = Join-Path $Root ".venv\Scripts\python.exe"
$DistApp = Join-Path $Root "dist\Mathloader"
$OutDir  = Join-Path $Root "dist_installer"

# Wersja ma jedno zrodlo prawdy: version.py. Skrypt i instalator ja stamtad
# czytaja, zeby przy podbiciu nie zostac z rozjechanymi numerami w trzech
# miejscach naraz.
$VersionFile = Join-Path $Root "version.py"
if (-not (Test-Path $VersionFile)) { throw "Brak version.py" }
$match = [regex]::Match((Get-Content $VersionFile -Raw), 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $match.Success) { throw "Nie moge odczytac APP_VERSION z version.py" }
$Version = $match.Groups[1].Value

function Say($msg)  { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function SizeMB($path) {
    if (-not (Test-Path $path)) { return 0 }
    $s = (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
          Measure-Object Length -Sum).Sum
    return [math]::Round($s / 1MB, 1)
}

# ---- Sprzatanie -----------------------------------------------------------
if ($Clean) {
    Say "Czyszczenie"
    foreach ($d in @("build", "dist", "dist_installer")) {
        $p = Join-Path $Root $d
        if (Test-Path $p) { Remove-Item $p -Recurse -Force; Ok "usunieto $d" }
    }
    exit 0
}

# ---- 1. Srodowisko --------------------------------------------------------
Say "1/6  Sprawdzanie srodowiska"
Ok "wersja z version.py: $Version"
if (-not (Test-Path $Python)) {
    throw "Brak $Python - utworz venv:  python -m venv .venv"
}
& $Python --version
if ($LASTEXITCODE -ne 0) { throw "Nie moge uruchomic $Python" }

# Bez cudzyslowow w argumentach - PowerShell 5.1 gubi je przy wywolaniu
# natywnego .exe, wiec kazdy inline'owy kod Pythona z " dotarlby uszkodzony.
& $Python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw "Brak PyInstallera. Uruchom:  .\.venv\Scripts\pip install -r requirements-build.txt"
}
Ok "PyInstaller obecny"

# Wykrywanie przegladarki robimy w czystym PowerShellu - zadnego cytowania.
$pwBase = Join-Path $env:LOCALAPPDATA "ms-playwright"
$shellDirs = @()
if (Test-Path $pwBase) {
    $shellDirs = @(Get-ChildItem $pwBase -Directory `
                   -Filter "chromium_headless_shell-*" -ErrorAction SilentlyContinue)
}
if ($shellDirs.Count -eq 0) {
    Warn "Brak przegladarki - pobieram (jednorazowo, ~284 MB)"
    & $Python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "playwright install chromium nie powiodlo sie" }
} else {
    Ok "znaleziono: $($shellDirs[0].Name)"
}
Ok "Chromium headless shell dostepny"

# ---- 2. Ikona -------------------------------------------------------------
Say "2/6  Ikona"
& $Python (Join-Path $Root "tools\make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Generowanie ikony nie powiodlo sie" }
Ok "assets\mathloader.ico"

# ---- 3. Build PyInstaller -------------------------------------------------
Say "3/6  PyInstaller (to potrwa kilka minut)"
foreach ($d in @("build", "dist")) {
    $p = Join-Path $Root $d
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}
& $Python -m PyInstaller "Mathloader.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller zakonczyl sie bledem" }
if (-not (Test-Path (Join-Path $DistApp "Mathloader.exe"))) {
    throw "Brak dist\Mathloader\Mathloader.exe"
}
$appSize = SizeMB $DistApp
Ok "dist\Mathloader  ($appSize MB)"

# ---- 4. Weryfikacja paczki ------------------------------------------------
Say "4/6  Weryfikacja zawartosci"
$checks = [ordered]@{
    "Mathloader.exe"                   = "Mathloader.exe"
    "ikona"                            = "_internal\assets\mathloader.ico"
    "licencja"                         = "_internal\LICENSE"
    "sterownik Playwright"             = "_internal\playwright\driver\package"
    "przegladarka Chromium (headless)" = "_internal\ms-playwright"
}
$missing = @()
foreach ($k in $checks.Keys) {
    $p = Join-Path $DistApp $checks[$k]
    if (Test-Path $p) { Ok $k } else { Warn "BRAK: $k  ($($checks[$k]))"; $missing += $k }
}
if ($missing.Count -gt 0) { throw "Niekompletny build: $($missing -join ', ')" }

$shellExe = Get-ChildItem (Join-Path $DistApp "_internal\ms-playwright") -Recurse `
            -Filter "chrome-headless-shell.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
if (-not $shellExe) { throw "Brak chrome-headless-shell.exe w paczce" }
Ok "chrome-headless-shell.exe na miejscu"

# ---- 5. Wersja portable (ZIP) ---------------------------------------------
Say "5/6  Wersja portable"
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory $OutDir | Out-Null }

# Znacznik wlaczajacy tryb portable. Here-string SINGLE-quoted, bo tresc
# zawiera znaki, ktore w @"..."@ PowerShell potraktowalby jako escape.
$marker = @'
Ten plik wlacza tryb PORTABLE.

Ustawienia i historia lekcji zapisuja sie w podfolderze "data" obok
Mathloader.exe, a nie w %APPDATA%. Mozesz skopiowac caly folder np. na
pendrive i uruchamiac program na innym komputerze.

AKTUALIZACJA WERSJI PORTABLE:
Rozpakuj nowy ZIP do nowego folderu, a nastepnie PRZENIES do niego podfolder
"data" ze starej wersji. Inaczej zaczniesz z pusta historia i numeracja lekcji
od jedynki. (Wersja instalowana nie ma tego problemu - trzyma dane
w %APPDATA%\Mathloader, ktorego instalator nie rusza.)

Skasowanie tego pliku przelacza program w tryb zwykly (%APPDATA%\Mathloader).
'@

# Compress-Archive z PS 5.1 nie radzi sobie z paczka tej wielkosci
# (blokady plikow, dotkliwa powolnosc). Uzywamy .NET bezposrednio i
# pakujemy prosto z dist\ - bez kopiowania 500 MB na bok.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = Join-Path $OutDir "Mathloader-$Version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $DistApp, $zip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true)                      # $true = w archiwum jest folder "Mathloader"

# portable.txt oraz instrukcje dla testera dokladamy do gotowego archiwum.
$archive = [System.IO.Compression.ZipFile]::Open($zip, "Update")
try {
    $entry  = $archive.CreateEntry("Mathloader/portable.txt")
    $writer = New-Object System.IO.StreamWriter(
                  $entry.Open(), (New-Object System.Text.UTF8Encoding($false)))
    $writer.Write($marker)
    $writer.Dispose()

    # Instrukcja dotyczy trybu portable, wiec trafia TYLKO do ZIP-a
    # (wersja instalowana trzyma dane w %APPDATA%, nie w podfolderze data).
    $howto = Join-Path $Root "docs\INSTRUKCJA-TESTERA.txt"
    if (Test-Path $howto) {
        [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, $howto, "Mathloader/INSTRUKCJA-TESTERA.txt")
        Ok "dolaczono INSTRUKCJA-TESTERA.txt"
    } else {
        Warn "brak INSTRUKCJA-TESTERA.txt - pomijam"
    }
} finally {
    $archive.Dispose()
}

$zipSize = SizeMB $zip
if ($zipSize -lt 50) { throw "ZIP portable wyglada na pusty ($zipSize MB)" }
Ok "Mathloader-$Version-portable.zip  ($zipSize MB)"

# ---- 6. Instalator (Inno Setup) -------------------------------------------
Say "6/6  Instalator"
if ($SkipInstaller) {
    Warn "pominieto (-SkipInstaller)"
} else {
    $iscc = $null
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { $iscc = $c; break }
    }
    if (-not $iscc) {
        $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($cmd) { $iscc = $cmd.Source }
    }
    if (-not $iscc) {
        Warn "Nie znaleziono Inno Setup 6 - pomijam instalator."
        Warn "Pobierz: https://jrsoftware.org/isdl.php  (potem uruchom build.ps1 ponownie)"
    } else {
        & $iscc "/DAppVersion=$Version" "installer.iss"
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup zakonczyl sie bledem" }
        Ok "instalator zbudowany  (wersja $Version)"
    }
}

# ---- Podsumowanie ---------------------------------------------------------
Say "Gotowe"
Get-ChildItem $OutDir -File -ErrorAction SilentlyContinue | ForEach-Object {
    "  {0,-46} {1,8} MB" -f $_.Name, ([math]::Round($_.Length / 1MB, 1))
}
Write-Host "`n  Folder aplikacji : $DistApp" -ForegroundColor Gray
Write-Host "  Artefakty        : $OutDir`n" -ForegroundColor Gray
