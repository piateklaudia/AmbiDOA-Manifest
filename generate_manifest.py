#!/usr/bin/env python3
"""Create one AmbiDOA manifest from an equirectangular PNG and AprilTag descriptions."""
import argparse
import json
import re
from pathlib import Path

import cv2

DICTIONARIES = {
    '16h5': cv2.aruco.DICT_APRILTAG_16h5,
    '25h9': cv2.aruco.DICT_APRILTAG_25h9,
    '36h10': cv2.aruco.DICT_APRILTAG_36h10,
    '36h11': cv2.aruco.DICT_APRILTAG_36h11,
}
ALLOWED_TAG_IDS = set(range(5))

SOURCE_LINE = re.compile(r'^\s*(\d+)\s*[-–—:]\s*(.*?)\s*$')


def read_sources(path):
    sources = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = SOURCE_LINE.fullmatch(line)
        if not match:
            if re.match(r'^\d+', line):
                raise ValueError(f'Nieprawidłowa linia TXT {number}: {line}')
            continue
        tag_id, label = int(match.group(1)), match.group(2).strip()
        if not label or tag_id in sources:
            raise ValueError(f'Pusta lub powtórzona etykieta znacznika {tag_id}')
        sources[tag_id] = label
    if not sources:
        raise ValueError('Brak opisów źródeł w TXT')
    return sources


def _scan(detector, image, origin=(0, 0), scale=1):
    corners, ids, _ = detector.detectMarkers(image)
    found = {}
    if ids is None:
        return found
    for tag_id, quad in zip(ids.flatten(), corners):
        x, y = quad.reshape(4, 2).mean(axis=0)
        found[int(tag_id)] = (float(origin[0] + x / scale), float(origin[1] + y / scale))
    return found


def _tile_starts(length, tile, stride):
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, stride))
    if starts[-1] != length - tile:
        starts.append(length - tile)
    return starts


def detect_tags(image, family='16h5', expected=None, max_scale=8):
    """Return tag centers in ORIGINAL image pixels. Upscale only small tiles."""
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARIES[family])
    detector = cv2.aruco.ArucoDetector(dictionary)
    found = _scan(detector, image)
    expected = set(expected) if expected is not None else None
    if expected is not None and expected <= found.keys():
        return found

    height, width = image.shape[:2]
    tile_size = min(640, width, height)
    stride = max(1, tile_size // 2)
    xs = _tile_starts(width, tile_size, stride)
    ys = _tile_starts(height, tile_size, stride)
    # Start with inexpensive original-resolution tiles; 8x is last resort.
    for scale in (1, 2, 4, 8):
        if scale > max_scale:
            break
        for contrast in (False, True):
            for y in ys:
                for x in xs:
                    tile = image[y:y + tile_size, x:x + tile_size]
                    if contrast:
                        gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
                        tile = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
                    if scale != 1:
                        tile = cv2.resize(tile, None, fx=scale, fy=scale,
                                          interpolation=cv2.INTER_CUBIC)
                    detected = _scan(detector, tile, (x, y), scale)
                    for tag_id, point in detected.items():
                        if tag_id not in found:
                            found[tag_id] = point
                    if expected is not None and expected <= found.keys():
                        return found
    return found


def manual_centers(image, missing):
    """Click center of each missing tag, using a desktop OpenCV window."""
    print('\nTryb ręczny: kliknij ŚRODEK znacznika wskazanego w oknie. ESC = przerwij.')
    height, width = image.shape[:2]
    display_scale = min(1.0, 1400 / width, 850 / height)
    shown = cv2.resize(image, None, fx=display_scale, fy=display_scale)
    result = {}
    window = 'Wskaz srodek AprilTag (ESC = anuluj)'
    try:
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        for tag_id in missing:
            selected = []
            canvas = shown.copy()
            cv2.putText(canvas, f'Kliknij srodek znacznika ID {tag_id}', (15, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 255), 2)
            def on_click(event, x, y, flags, userdata):
                if event == cv2.EVENT_LBUTTONDOWN:
                    selected.append((x / display_scale, y / display_scale))
            cv2.setMouseCallback(window, on_click)
            while not selected:
                cv2.imshow(window, canvas)
                key = cv2.waitKey(50) & 0xFF
                if key == 27:
                    raise ValueError('Anulowano ręczne wskazywanie znaczników')
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    raise ValueError('Zamknięto okno wskazywania znaczników')
            result[tag_id] = selected[0]
            print(f'ID {tag_id}: x={selected[0][0]:.1f}, y={selected[0][1]:.1f} (ręcznie)')
    finally:
        cv2.destroyWindow(window)
    return result


def generate(png, txt, wav, slots=10, family='16h5', decimals=0,
             max_scale=8, manual=False, resolve_extra=None):
    if not wav.lower().endswith('.wav'):
        raise ValueError('--wav musi kończyć się na .wav')
    image = cv2.imread(str(png))
    if image is None:
        raise ValueError(f'Nie można otworzyć PNG: {png}')
    height, width = image.shape[:2]
    if width != 2 * height:
        raise ValueError(f'PNG ma wymiary {width}x{height}; wymagane 2:1')
    sources = read_sources(txt)
    invalid_txt = sorted(set(sources) - ALLOWED_TAG_IDS)
    if invalid_txt:
        raise ValueError(f'TXT zawiera ID spoza dozwolonego zakresu 0-4: {invalid_txt}')
    detected = detect_tags(image, family, expected=None, max_scale=max_scale)
    invalid_detected = sorted(set(detected) - ALLOWED_TAG_IDS)
    if invalid_detected:
        print(f'Ostrzeżenie: pomijam wykryte ID spoza 0-4: {invalid_detected}')
    detected = {tag_id: xy for tag_id, xy in detected.items()
                if tag_id in ALLOWED_TAG_IDS}

    print('\n--- Kontrola znaczników ---')
    print('Źródła opisane w TXT:')
    for tag_id, label in sorted(sources.items()):
        print(f'  ID {tag_id}: {label}')
    print('Detekcje ID 0–4 (współrzędne oryginalnego PNG):')
    for tag_id, (x, y) in sorted(detected.items()):
        status = 'opisany w TXT' if tag_id in sources else 'BRAK OPISU w TXT'
        print(f'  ID {tag_id}: x={x:.1f}, y={y:.1f} — {status}')
    if not detected:
        print('  Brak automatycznych detekcji ID 0–4')

    # Najpierw uzupełniamy wszystkie brakujące znaczniki z TXT.
    missing = sorted(set(sources) - set(detected))
    if missing:
        print(f'Brak automatycznej detekcji ID z TXT: {missing}')
        if manual:
            detected.update(manual_centers(image, missing))
        missing = sorted(set(sources) - set(detected))
        if missing:
            raise ValueError(f'Nie wykryto znaczników z TXT: {missing}. '
                             'Uruchom z --manual, aby wskazać je myszą.')

    # Odpowiedź „nie wiem” nie przerywa weryfikacji kolejnych znaczników.
    # Wyjątek jest zgłaszany dopiero po zakończeniu całej kontroli.
    unresolved = []
    extras = sorted(set(detected) - set(sources))
    for tag_id in extras:
        if resolve_extra is None:
            unresolved.append(f'ID {tag_id}: brak opisu w TXT')
            continue
        try:
            label = resolve_extra(tag_id)
        except Exception as exc:
            # NeedsReview pochodzi z generatora zbiorczego; nie importujemy
            # go tutaj, żeby uniknąć zależności cyklicznej.
            if exc.__class__.__name__ != 'NeedsReview':
                raise
            unresolved.append(str(exc))
            continue
        if label is None:
            print(f'ID {tag_id}: potwierdzono brak aktywnego źródła')
        else:
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f'Nieprawidłowy opis źródła ID {tag_id}')
            sources[tag_id] = label.strip()

    if len(sources) > slots:
        raise ValueError(f'Źródeł {len(sources)}, ale slotów tylko {slots}')

    print('\n--- Podsumowanie nagrania ---')
    for tag_id in sorted(sources):
        x, y = detected[tag_id]
        az = round(180 - 360 * x / width)
        el = round(90 - 180 * y / height)
        print(f'  ID {tag_id}: {sources[tag_id]} | x={x:.1f}, y={y:.1f} | '
              f'azymut={az}°, elewacja={el}°')
    if unresolved:
        print('Nierozstrzygnięte kwestie:')
        for problem in unresolved:
            print(f'  - {problem}')
        raise ValueError('Nagranie wymaga weryfikacji: ' + '; '.join(unresolved))
    if resolve_extra is not None:
        while True:
            answer = input('Czy wszystkie źródła i pozycje są poprawne? [t/n/?]: ').strip().lower()
            if answer in ('t', 'tak'):
                break
            if answer in ('n', 'nie', '?'):
                raise ValueError('Nagranie wymaga weryfikacji: nie potwierdzono podsumowania')
            print('Wpisz t (tak), n (nie) lub ? (nie wiem).')

    regions, azimuths, elevations = [], [], []
    for tag_id in sorted(sources):
        x, y = detected[tag_id]
        azimuth = 180 - 360 * x / width
        elevation = 90 - 180 * y / height
        regions.append(sources[tag_id])
        azimuths.append(round(azimuth))
        elevations.append(round(elevation))
        print(f'AprilTag {tag_id}: {sources[tag_id]} | x={x:.1f}, y={y:.1f} | '
              f'azymut={azimuths[-1]}°, elewacja={elevations[-1]}°')
    n = len(sources)
    return [{
        'audio_filepath': wav,
        'n_sources': n,
        'regions': regions + [''] * (slots - n),
        'azimuths': azimuths + [None] * (slots - n),
        'elevations': elevations + [None] * (slots - n),
        'mask': [1] * n + [0] * (slots - n),
    }]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--png', required=True, type=Path)
    parser.add_argument('--txt', required=True, type=Path)
    parser.add_argument('--wav', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--family', choices=DICTIONARIES, default='16h5')
    parser.add_argument('--slots', type=int, default=10)
    parser.add_argument('--max-scale', type=int, choices=(1, 2, 4, 8), default=8)
    parser.add_argument('--manual', action='store_true', help='Kliknij brakujące znaczniki w oknie')
    args = parser.parse_args()
    try:
        data = generate(args.png, args.txt, args.wav, args.slots, args.family,
                        max_scale=args.max_scale, manual=args.manual)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Zapisano: {args.output}')
    except (ValueError, OSError, cv2.error) as exc:
        parser.exit(1, f'Błąd: {exc}\n')

if __name__ == '__main__':
    main()
