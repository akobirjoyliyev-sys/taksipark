"""Lokal sinov uchun embedded PostgreSQL (Docker'siz). Faqat development!

Ishga tushirish (Python 3.12 venv, `pip install pgserver`):
    python scripts/local_pg.py .local/pgdata
"""

import sys
import time

import pgserver

srv = pgserver.get_server(sys.argv[1] if len(sys.argv) > 1 else ".local/pgdata", cleanup_mode=None)
print("URI", srv.get_uri(), flush=True)
srv.psql("SELECT 1;")
while True:
    time.sleep(3600)
