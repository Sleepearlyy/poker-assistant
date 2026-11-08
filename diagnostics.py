"""Offline installation check. Does not capture the screen or start a UI."""
from app_info import VERSION
from paths import ROOT, DATA


def run():
    checks = {}
    try:
        from reader import Reader, load_layout
        import numpy as np
        _, layout = load_layout(ROOT / 'layouts.json', np.zeros((1010, 1920, 3), dtype=np.uint8), 'auto')
        reader = Reader(layout)
        checks['ocr_models'] = reader is not None
        checks['layout'] = len(layout['seats']) == 6
        checks['dealer_template'] = (ROOT / 'assets' / 'dealer.png').is_file()
        from advisor import call_engine
        result = call_engine(dict(mode='equity', hero=['2c','3d'], board=['Ah','Kh','Qh','Jh','Th'], ranges=['random','random'], samples=100))
        checks['native_equity'] = abs(result['equity'] - 1/3) < 1e-6
        probe = DATA / '.write-check'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        checks['writable_data'] = True
    except Exception as exc:
        checks['error'] = str(exc)
    return {'version': VERSION, 'ok': bool(checks) and all(v is True for v in checks.values()), 'checks': checks}
