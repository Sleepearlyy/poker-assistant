"""Build a Windows installer; source is published in the matching Git tag."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'app'
sys.path.insert(0, str(APP))
from app_info import VERSION


def collect_licenses(destination):
    if destination.exists():
        if destination.resolve() != ROOT/'build/licenses':
            raise RuntimeError('Unexpected license output directory')
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for package in importlib.metadata.distributions():
        folder = destination / package.metadata.get('Name', 'unknown')
        folder.mkdir(exist_ok=True)
        for file in package.files or []:
            if any(word in file.name.lower() for word in ('license', 'copying', 'notice')):
                original = package.locate_file(file)
                if original.is_file():
                    prefix = hashlib.sha256(str(file).encode()).hexdigest()[:10]
                    shutil.copy(original, folder / (prefix + '-' + file.name))
    metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--format-version', '1', '--locked'], cwd=APP/'solver'))
    notices = []
    for package in metadata['packages']:
        if package['name'] == 'poker-engine':
            continue
        notices.append(f"\n{package['name']} {package['version']} | {package.get('license')} | {package.get('repository')}\n")
        for file in Path(package['manifest_path']).parent.iterdir():
            if file.is_file() and (any(word in file.name.lower() for word in ('license', 'copying', 'notice', 'copyright')) or file.name == 'AUTHORS'):
                notices.append(file.read_text(encoding='utf-8', errors='replace'))
    (destination/'RUST-NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', type=Path, required=True)
    args = parser.parse_args()
    if not args.iscc.is_file() or not (APP/'solver/poker-engine.exe').is_file():
        parser.error('Build app/solver/poker-engine.exe and install Inno Setup 6 first.')
    conda_dlls = Path(sys.prefix)/'Library/bin'
    if conda_dlls.is_dir():
        os.environ['PATH'] = str(conda_dlls) + os.pathsep + os.environ.get('PATH', '')
    collect_licenses(ROOT/'build/licenses')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT/'packaging/app.spec')], cwd=ROOT, check=True)
    app = ROOT/'dist/德扑助手'
    for name in ['LICENSE', 'README.md']:
        shutil.copy(ROOT/name, app/name)
    for relative in ['assets/deck-theme.png', 'THIRD_PARTY_NOTICES.md']:
        target = app/'app'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(APP/relative, target)
    shutil.copytree(ROOT/'build/licenses', app/'licenses', dirs_exist_ok=True)
    subprocess.run([str(args.iscc.resolve()), f'/DAppVersion={VERSION}', str(ROOT/'packaging/installer.iss')], cwd=ROOT, check=True)
    print(f'release/PokerAssistant-{VERSION}-windows-x64-setup.exe')


if __name__ == '__main__':
    main()
