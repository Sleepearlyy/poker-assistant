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
sys.path.insert(0, str(ROOT))
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
    shutil.copytree(ROOT / 'licenses', destination, dirs_exist_ok=True, copy_function=shutil.copy)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', type=Path, required=True)
    args = parser.parse_args()
    if not args.iscc.is_file() or not (ROOT/'solver/poker-engine.exe').is_file():
        parser.error('Build solver/poker-engine.exe and install Inno Setup 6 first.')
    conda_dlls = Path(sys.prefix)/'Library/bin'
    if conda_dlls.is_dir():
        os.environ['PATH'] = str(conda_dlls) + os.pathsep + os.environ.get('PATH', '')
    collect_licenses(ROOT/'build/licenses')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT/'德扑助手.spec')], cwd=ROOT, check=True)
    app = ROOT/'dist/德扑助手'
    for name in ['LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md']:
        shutil.copy(ROOT/name, app/name)
    shutil.copytree(ROOT/'build/licenses', app/'licenses', dirs_exist_ok=True)
    report = ROOT/'build/packaged-diagnostics.json'
    diagnostic_env = dict(os.environ, LOCALAPPDATA=str(ROOT/'build/diagnostic-user-data'), PATH=os.pathsep.join([os.path.join(os.environ['SystemRoot'], 'System32'), os.environ['SystemRoot']]))
    subprocess.run([str(app/'德扑助手.exe'), '--diagnostics', str(report)], check=True, timeout=120, env=diagnostic_env)
    if not json.loads(report.read_text(encoding='utf-8'))['ok']:
        raise RuntimeError('Packaged diagnostics failed')
    subprocess.run([str(args.iscc.resolve()), f'/DAppVersion={VERSION}', str(ROOT/'packaging/installer.iss')], cwd=ROOT, check=True)
    print(f'release/PokerAssistant-{VERSION}-windows-x64-setup.exe')


if __name__ == '__main__':
    main()
