import os
import sys

# Add repository root directory to Python path for Vercel Serverless Function
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.app.main import app

# Export ASGI app for Vercel
# Vercel's @vercel/python runtime automatically binds to `app`
