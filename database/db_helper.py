import sqlite3
import os
from config import DATABASE_PATH

def init_db():
    """Initializes the SQLite database tables."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Answer keys table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS answer_keys (
        exam_id TEXT PRIMARY KEY,
        keys TEXT,  -- Format: "1:A,2:B,3:C,4:D..."
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Results history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        exam_id TEXT,
        correct_count INTEGER,
        wrong_count INTEGER,
        skipped_count INTEGER,
        invalid_count INTEGER,
        total_score INTEGER,
        percentage REAL,
        answers_detected TEXT,  -- Format: "1:A,2:B,3:A,B..."
        scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (exam_id) REFERENCES answer_keys(exam_id)
    )
    """)
    
    conn.commit()
    conn.close()

def add_user(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
        (user_id, username, full_name)
    )
    conn.commit()
    conn.close()

def save_answer_key(exam_id: str, keys: str, admin_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO answer_keys (exam_id, keys, created_by) VALUES (?, ?, ?)",
        (exam_id, keys, admin_id)
    )
    conn.commit()
    conn.close()

def get_answer_key(exam_id: str):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT keys FROM answer_keys WHERE exam_id = ?", (exam_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def save_result(user_id: int, exam_id: str, correct: int, wrong: int, skipped: int, invalid: int, total_score: int, pct: float, detected: str):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO results (user_id, exam_id, correct_count, wrong_count, skipped_count, invalid_count, total_score, percentage, answers_detected)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, exam_id, correct, wrong, skipped, invalid, total_score, pct, detected))
    conn.commit()
    conn.close()

def get_user_history(user_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT exam_id, correct_count, total_score, percentage, scanned_at 
        FROM results 
        WHERE user_id = ? 
        ORDER BY scanned_at DESC 
        LIMIT 10
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_leaderboard(exam_id: str):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.full_name, r.total_score, r.percentage, r.scanned_at
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.exam_id = ?
        ORDER BY r.percentage DESC, r.total_score DESC, r.scanned_at ASC
        LIMIT 10
    """, (exam_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_exams():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT exam_id, created_at FROM answer_keys ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows
