"""Keep direct helper execution and application imports on one module namespace."""
from pathlib import Path
import sys

DIRECTORY=Path(__file__).resolve().parent
ROOT=DIRECTORY.parent
for directory in (ROOT,DIRECTORY):
    value=str(directory)
    if value not in sys.path:sys.path.insert(0,value)
