import os
import sys

# Ensure root directory is in the python path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from api.index import app

if __name__ == "__main__":
    # Create static directory if not exists
    os.makedirs('static', exist_ok=True)
    
    # Run server on port 5000 to allow local network (intranet) access
    app.run(host='0.0.0.0', port=5000, debug=True)
