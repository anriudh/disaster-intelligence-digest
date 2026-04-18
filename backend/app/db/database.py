import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "../../data/disaster_intel.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_schema():
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))
    
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    
    conn = get_db()
    conn.executescript(schema)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    execute_schema()
    print("Database schema executed successfully.")
