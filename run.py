"""Launch the Campus Whispers server."""
import os
from app import create_app, init_db

if __name__ == "__main__":
    db_path = os.environ.get("DB_PATH", "campus_whispers.db")
    init_db(db_path)
    app = create_app({"DB_PATH": db_path})
    # Host 0.0.0.0 lets classmates reach it on your local network.
    # For wider access, deploy to Render/PythonAnywhere (see README).
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
