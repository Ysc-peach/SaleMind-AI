"""One-time, pinned font asset preparation. Never called by export requests."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

REVISION = 'a85815a42757630ce188fdad368c2dfc444d4773'
INPUT_HASH = 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da'
BASE = f'https://raw.githubusercontent.com/google/fonts/{REVISION}/ofl/notosanssc/'


def main():
    from io import BytesIO
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    import fontTools
    target = Path(__file__).resolve().parents[1] / 'apps/sales/assets/fonts'
    if any((target / name).exists() for name in ('NotoSansSC-Regular.ttf','manifest.json','OFL.txt')):
        raise SystemExit('Existing font assets retained. Verify or remove only explicitly owned assets before rebuilding.')
    with urlopen(BASE + 'NotoSansSC%5Bwght%5D.ttf',timeout=60) as response:
        raw = response.read(17772301)
    if len(raw) != 17772300 or hashlib.sha256(raw).hexdigest() != INPUT_HASH:
        raise SystemExit('Upstream font checksum mismatch.')
    with urlopen(BASE + 'OFL.txt',timeout=30) as response:
        license_bytes = response.read(16384)
    if b'SIL OPEN FONT LICENSE' not in license_bytes:
        raise SystemExit('Upstream font license missing.')
    font = instantiateVariableFont(TTFont(BytesIO(raw)),{'wght':400},inplace=True)
    assert 'glyf' in font and 'fvar' not in font
    names = {1:'Noto Sans SC',2:'Regular',4:'Noto Sans SC Regular',6:'NotoSansSC-Regular'}
    for record in font['name'].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    buffer = BytesIO()
    font.save(buffer)
    result = buffer.getvalue()
    target.mkdir(parents=True,exist_ok=True)
    (target/'NotoSansSC-Regular.ttf').write_bytes(result)
    (target/'OFL.txt').write_bytes(license_bytes)
    (target/'manifest.json').write_text(json.dumps({
        'revision':REVISION,'input_sha256':INPUT_HASH,'weight':400,
        'fonttools':fontTools.__version__,'static_sha256':hashlib.sha256(result).hexdigest(),
        'license_sha256':hashlib.sha256(license_bytes).hexdigest(),
    },indent=2)+'\n',encoding='utf-8')
    print('Prepared static font and license; no runtime downloads.')


if __name__ == '__main__':
    main()
