# temp
import sys
import os

path = os.curdir
if path not in sys.path:
    sys.path.insert(0, path)

from app.main import app
from a2wsgi import ASGIMiddleware

application = ASGIMiddleware(app)