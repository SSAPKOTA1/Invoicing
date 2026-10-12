"""Entry point used by PyInstaller (and handy for ``python run_supplierapp.py``)."""

import sys

from supplier_app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
