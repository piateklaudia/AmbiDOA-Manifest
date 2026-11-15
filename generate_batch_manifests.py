#!/usr/bin/env python3
"""Generate individual and combined AmbiDOA manifests from a dataset directory.

Pairs files by date and recording number: YYYYMMDD_N or YYYYMMDD_N-M.
Requires one PNG, one TXT and one WAV per recording key.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from generate_manifest import generate

KEY = re.compile(r"^(\d{8})_(\d+(?:-\d+)?)(?=_|\.|$)")
KINDS = {".png": "png", ".txt": "txt", ".wav": "wav"}


def collect(folder: Path, recursive: bool):
    groups = defaultdict(lambda: defaultdict(list))
    paths = folder.rglob('*') if recursive else folder.iterdir()
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in KINDS:
            continue
        match = KEY.match(path.name)
        if match is None:
            continue
        key = f"{match.group(1)}_{match.group(2)}"
        # Include the relative parent to prevent collisions between subfolders.
        rel_parent = path.parent.relative_to(folder)
        groups[(rel_parent, key)][KINDS[path.suffix.lower()]].append(path)
    return groups



class NeedsReview(Exception):
    """User cannot determine whether a detected marker is an active source."""


def load_decisions(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('manual_decisions.json musi zawierać obiekt JSON')
    return data


def save_decisions(path, decisions):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')
    temp.replace(path)


def ask_extra(tag_id, record_key, decisions, decisions_path):
    decision_key = f'{record_key}|{tag_id}'
    previous = decisions.get(decision_key)
    if previous is not None:
        if previous.get('status') == 'yes':
            print(f'ID {tag_id}: przywracam opis: {previous["label"]}')
            return previous['label']
        if previous.get('status') == 'no':
            print(f'ID {tag_id}: wcześniej potwierdzono brak źródła')
            return None
        if previous.get('status') == 'review':
            print(f'ID {tag_id}: wcześniejsza odpowiedź „nie wiem” — pytam ponownie')
        raise ValueError(f'Nieznana decyzja w {decisions_path}: {decision_key}')
    print(f'\nWykryto AprilTag ID {tag_id}, którego nie opisano w TXT.')
    print('[1] Tak — było aktywne źródło (podam nazwę)')
    print('[2] Nie — pomiń znacznik')
    print('[3] Nie wiem — oznacz nagranie do weryfikacji')
    while True:
        answer = input('Wybierz 1, 2 lub 3: ').strip()
        if answer in ('1', '2', '3'):
            break
        print('Wpisz 1, 2 lub 3.')
    if answer == '1':
        while True:
            label = input(f'Nazwa dźwięku przy ID {tag_id}: ').strip()
            if label:
                break
            print('Nazwa nie może być pusta.')
        decision = {'status': 'yes', 'label': label}
    elif answer == '2':
        decision = {'status': 'no'}
    else:
        decision = {'status': 'review'}
    decisions[decision_key] = decision
    save_decisions(decisions_path, decisions)
    if answer == '3':
        raise NeedsReview(f'ID {tag_id}: nie potwierdzono, czy było źródło')
    return decision.get('label')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', type=Path, help='Folder zawierający PNG, TXT i WAV')
    parser.add_argument('--recursive', action='store_true', help='Szukaj również w podfolderach')
    parser.add_argument('--output', type=Path, help='Nazwa lub ścieżka zbiorczego manifestu JSON')
    parser.add_argument('--family', default='16h5', choices=('16h5', '25h9', '36h10', '36h11'))
    parser.add_argument('--slots', type=int, default=10)
    parser.add_argument('--max-scale', type=int, choices=(1, 2, 4, 8), default=8)
    parser.add_argument('--manual', action='store_true', help='Wskaz myszą brakujące znaczniki')
    args = parser.parse_args()
    try:
        folder = (args.folder or Path(input('Podaj ścieżkę do folderu z danymi: ').strip().strip('"\''))).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f'Nie znaleziono folderu: {folder}')
        if args.slots < 1:
            raise ValueError('--slots musi być dodatnie')
        groups = collect(folder, args.recursive)
        if not groups:
            raise ValueError('Nie znaleziono plików YYYYMMDD_N[_...] lub YYYYMMDD_N-M[_...] z rozszerzeniami PNG/TXT/WAV')
        errors = []
        for (rel, key), kinds in sorted(groups.items(), key=lambda t: (str(t[0][0]), t[0][1])):
            for kind in ('png', 'txt', 'wav'):
                if len(kinds[kind]) != 1:
                    errors.append(f'{rel / key}: {kind.upper()} — znaleziono {len(kinds[kind])}, wymagany dokładnie 1')
        if errors:
            raise ValueError('Niejednoznaczne lub niekompletne zestawy:\n' + '\n'.join(errors))

        default_name = f'manifest_{folder.name}.json'
        if args.output:
            combined_path = args.output.expanduser()
            if not combined_path.is_absolute():
                combined_path = folder / combined_path
        else:
            answer = input(f'Nazwa manifestu zbiorczego [Enter = {default_name}]: ').strip()
            combined_path = folder / (answer or default_name)
        if combined_path.suffix.lower() != '.json':
            combined_path = combined_path.with_suffix('.json')
        combined_path = combined_path.resolve()
        combined_path.parent.mkdir(parents=True, exist_ok=True)

        decisions_path = folder / 'manual_decisions.json'
        decisions = load_decisions(decisions_path)
        planned = []
        all_entries = []
        review = []
        for (rel, key), kinds in sorted(groups.items(), key=lambda t: (str(t[0][0]), t[0][1])):
            png, txt, wav = (kinds[k][0] for k in ('png', 'txt', 'wav'))
            # Relative to the directory containing the combined manifest.
            # os.path.relpath handles datasets stored in subdirectories.
            wav_ref = Path(os.path.relpath(wav, combined_path.parent)).as_posix()
            print(f'\nPrzetwarzanie {rel / key}:')
            record_key = f'{rel.as_posix()}/{key}'
            try:
                result = generate(
                    png, txt, wav_ref, args.slots, args.family, 0,
                    max_scale=args.max_scale, manual=args.manual,
                    resolve_extra=lambda tag_id: ask_extra(
                        tag_id, record_key, decisions, decisions_path))
            except (NeedsReview, ValueError) as exc:
                review.append(f'{record_key}: {exc}')
                print(f'Wymaga weryfikacji: {exc}')
                continue
            entry = result[0]
            # Force integer JSON values: round(float, 0) otherwise returns float.
            entry['azimuths'] = [int(x) if x is not None else None for x in entry['azimuths']]
            entry['elevations'] = [int(x) if x is not None else None for x in entry['elevations']]
            individual = folder / rel / f'manifest_{key}.json'
            individual_entry = dict(entry)
            individual_entry['audio_filepath'] = Path(os.path.relpath(wav, individual.parent)).as_posix()
            planned.append((individual.resolve(), [individual_entry]))
            all_entries.append(entry)

        targets = [p for p, _ in planned] + [combined_path]
        report_path = folder / 'manifest_review_report.txt'
        targets.append(report_path)
        if len(set(targets)) != len(targets):
            raise ValueError('Konflikt nazw: manifest zbiorczy ma tę samą ścieżkę co pojedynczy')
        existing = [p for p in targets if p.exists()]
        if existing:
            answer = input(f'Istnieje już {len(existing)} plik(ów) wynikowych. Nadpisać? [t/N]: ').strip().lower()
            if answer not in ('t', 'tak'):
                print('Anulowano. Nic nie zapisano.')
                return

        for path, data in planned:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'Zapisano: {path}')
        combined_path.write_text(json.dumps(all_entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report_path.write_text('Nagrania wymagające weryfikacji:\n' +
                               ('\n'.join(review) if review else '(brak)') + '\n', encoding='utf-8')
        if review:
            print(f'Wymagają weryfikacji: {len(review)}; raport: {report_path}')
            print('UWAGA: stare pojedyncze manifesty pominiętych nagrań, jeśli istnieją, nie są usuwane.')
        print(f'\nGotowe: {len(all_entries)} wpisów. Manifest zbiorczy: {combined_path}')
    except (ValueError, OSError, EOFError, KeyboardInterrupt) as exc:
        parser.exit(1, f'Błąd: {exc}\n')


if __name__ == '__main__':
    main()
