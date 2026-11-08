"""Build redistributable Windows packages with matching source and licenses."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_info import VERSION


def source_files():
    excluded = {'.git', '.venv', '__pycache__', 'build', 'dist', 'release', 'results', 'target'}
    for p in sorted(ROOT.rglob('*')):
        relative = p.relative_to(ROOT)
        if not p.is_file() or any(x in excluded for x in relative.parts):
            continue
        if p.suffix.lower() in {'.exe', '.dll', '.pyc', '.log', '.bak', '.key', '.pem'}:
            continue
        if p.name.startswith(('sample-', '.env')) or p.name == 'popup-settings.json':
            continue
        yield p, relative


def collect_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    packages = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get('Name', 'unknown')
        packages.append({'name': name, 'version': distribution.version, 'license': distribution.metadata.get('License', '')})
        folder = destination / name
        folder.mkdir(exist_ok=True)
        metadata = distribution.read_text('METADATA') or distribution.read_text('PKG-INFO') or json.dumps(dict(distribution.metadata))
        (folder / 'METADATA.txt').write_text(metadata, encoding='utf-8')
        for f in distribution.files or []:
            if any(s in f.name.lower() for s in ('license', 'copying', 'notice')):
                original = distribution.locate_file(f)
                if original.is_file():
                    # Flatten long wheel paths while preserving distinct files.
                    prefix = hashlib.sha256(str(f).encode()).hexdigest()[:10]
                    target = folder / (prefix + '-' + f.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
    (destination / 'packages.json').write_text(json.dumps(packages, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', type=Path, required=True)
    args = parser.parse_args()
    if not args.iscc.is_file():
        parser.error('Inno Setup compiler not found; install Inno Setup 6 or set --iscc.')
    if not (ROOT / 'solver' / 'poker-engine.exe').is_file():
        parser.error('Build solver/poker-engine.exe first (see README).')
    release = ROOT / 'release'
    release.mkdir(exist_ok=True)
    conda_dlls = Path(sys.prefix) / 'Library' / 'bin'
    if conda_dlls.is_dir():
        os.environ['PATH'] = str(conda_dlls) + os.pathsep + os.environ.get('PATH', '')
    source = release / f'PokerAssistant-{VERSION}-source.zip'
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, relative in source_files():
            archive.write(path, relative.as_posix())
    collect_licenses(ROOT / 'build' / 'licenses')
    shutil.copytree(ROOT / 'licenses', ROOT / 'build' / 'licenses', dirs_exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT / '德扑助手.spec')], cwd=ROOT, check=True)
    app = ROOT / 'dist' / '德扑助手'
    shutil.copy2(source, app / source.name)
    for name in ['LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md']:
        shutil.copy2(ROOT / name, app / name)
    shutil.copytree(ROOT / 'build' / 'licenses', app / 'licenses', dirs_exist_ok=True)
    if os.name == 'nt':
        report = ROOT / 'build' / 'packaged-diagnostics.json'
        diagnostic_env = dict(os.environ, LOCALAPPDATA=str(ROOT / 'build' / 'diagnostic-user-data'))
        subprocess.run([str(app / '德扑助手.exe'), '--diagnostics', str(report)], check=True, timeout=120, env=diagnostic_env)
        if not json.loads(report.read_text(encoding='utf-8'))['ok']:
            raise RuntimeError('Packaged diagnostics failed')
    shutil.make_archive(str(release / f'PokerAssistant-{VERSION}-windows-x64-portable'), 'zip', ROOT / 'dist', '德扑助手')
    subprocess.run([str(args.iscc.resolve()), f'/DAppVersion={VERSION}', str(ROOT / 'packaging' / 'installer.iss')], cwd=ROOT, check=True)
    artifacts = [source, release / f'PokerAssistant-{VERSION}-windows-x64-portable.zip', release / f'PokerAssistant-{VERSION}-windows-x64-setup.exe']
    sums = []
    for path in artifacts:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        sums.append(f'{digest.hexdigest()}  {path.name}\n')
    (release / 'SHA256SUMS.txt').write_text(''.join(sums), encoding='utf-8')
    print('Release artifacts:', ', '.join(p.name for p in artifacts))


if __name__ == '__main__':
    main()
