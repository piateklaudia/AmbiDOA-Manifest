# Instalacja — AmbiDOA-Manifest

## Wymagania

- Python 3 (zalecana wersja: 3.12 lub 3.13 lub 3.15, ja mam 3.15)
- pip
- System macOS, Linux lub Windows
- Pliki wejściowe: panorama PNG w projekcji equirectangularnej oraz TXT z numerami AprilTagów i opisami źródeł

## 1. Pobranie projektu

Pobierz repozytorium z GitHuba i otwórz jego folder w terminalu.

## 2. Utworzenie środowiska wirtualnego

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 3. Instalacja zależności

```bash
python -m pip install -r requirements.txt
```

## 4. Sprawdzenie instalacji

```bash
python generate_manifest.py --help
```

## 5. Generowanie manifestu

Przykład dla danych umieszczonych w folderze `KP`:

```bash
python generate_manifest.py \
  --png KP/20261026_2_Zdj_at_kp-studioD1-kalibracja.png \
  --txt KP/20261026_2_NK_at_kp-studioD1-kalibracja.txt \
  --wav 20261026_2_AK_at_kp-studioD1-kalibracja.wav \
  --output KP/manifest_kalibracja.json
```

Powyższy przykład dotyczy macOS/Linux. W Windows należy wpisać polecenie w jednej linii.

Skrypt odczytuje PNG i TXT, wykrywa znaczniki AprilTag, oblicza azymuty i elewacje oraz zapisuje manifest JSON.

Plik WAV nie musi znajdować się w folderze podczas generowania manifestu. Wartość `--wav` określa ścieżkę, którą będzie później odczytywał dataloader sieci neuronowej.

## 6. Zakończenie pracy

Aby wyłączyć środowisko wirtualne:

```bash
deactivate
```

Przy następnym uruchomieniu projektu wystarczy ponownie aktywować `.venv`. Nie trzeba za każdym razem instalować bibliotek.

## Uwagi

- Nie kopiuj folderu `.venv` pomiędzy komputerami.
- Folder `.venv` jest wykluczony z repozytorium przez `.gitignore`.
- Generator zakłada panoramę equirectangularną o proporcjach 2:1.
- Domyślna rodzina znaczników to AprilTag 16h5.
- Domyślna liczba slotów w manifeście wynosi 10.
- Kierunek azymutu 0° odpowiada środkowi panoramy.
