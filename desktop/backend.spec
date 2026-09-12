# Explicit inputs: never collect .env files, local databases, or the whole repo.
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

backend = Path(SPECPATH).parent / 'backend'
migrations = [(str(backend / 'alembic' / 'env.py'), 'alembic')]
migrations += [(str(file), 'alembic/versions') for file in sorted((backend / 'alembic' / 'versions').glob('*.py'))]
a = Analysis([str(backend / 'desktop_entry.py')], pathex=[str(backend)],
             binaries=[], datas=migrations + copy_metadata('email-validator'),
             hiddenimports=['sqlalchemy.dialects.sqlite', 'uvicorn.logging',
                            'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on'],
             excludes=['pytest', 'psycopg', 'uvloop', 'watchfiles'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pfos-api',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='pfos-api')
