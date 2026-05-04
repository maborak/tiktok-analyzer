# scripts/export_openapi.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api_main import app
import json

with open("docs/internal/openapi.json", "w") as f:
    json.dump(app.openapi(), f, indent=2)