import sqlite3

db_path = "agrivision.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

def add_column_if_missing(table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]

    if column not in cols:
        print(f"Adding {table}.{column}")
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    else:
        print(f"{table}.{column} already exists")

# users
add_column_if_missing("users", "phone", "VARCHAR")
add_column_if_missing("users", "location", "VARCHAR")
add_column_if_missing("users", "created_at", "DATETIME")

# farms
add_column_if_missing("farms", "created_at", "DATETIME")
add_column_if_missing("farms", "updated_at", "DATETIME")

# satellite reports
add_column_if_missing("satellite_reports", "farm_id", "INTEGER")
add_column_if_missing("satellite_reports", "change_json", "TEXT")

# disease reports
add_column_if_missing("disease_reports", "disease_key", "VARCHAR")
add_column_if_missing("disease_reports", "symptoms", "TEXT")
add_column_if_missing("disease_reports", "cause", "TEXT")
add_column_if_missing("disease_reports", "prevention", "TEXT")

cur.execute("""
UPDATE farms
SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
    updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
""")

cur.execute("""
UPDATE users
SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
""")

conn.commit()
conn.close()

print("DB column fix complete.")