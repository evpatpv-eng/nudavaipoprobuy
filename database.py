"""SQLite база данных для бота."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "bot_data.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Настройки мастера (портфолио)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Примеры работ (фото)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT UNIQUE
        )
    """)

    # Услуги и цены
    cur.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        )
    """)

    # Дни, когда запись невозможна (0=Пн, 6=Вс)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocked_weekdays (
            day INTEGER PRIMARY KEY
        )
    """)

    # Свободные слоты: дата_время, сеанс 2 часа
    cur.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_time TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'free'
        )
    """)

    # Записи клиентов
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            client_name TEXT,
            client_phone TEXT,
            client_username TEXT,
            client_user_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            FOREIGN KEY (slot_id) REFERENCES slots(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        )
    """)

    conn.commit()
    conn.close()


# === Settings (портфолио) ===
def get_setting(key):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_setting(key, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


# === Works (примеры работ) ===
def add_work(file_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO works (file_id) VALUES (?)", (file_id,))
    conn.commit()
    conn.close()


def get_works():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT file_id FROM works ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def clear_works():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM works")
    conn.commit()
    conn.close()


# === Services ===
def add_service(name, price):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO services (name, price) VALUES (?, ?)", (name, int(price)))
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def get_services():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price FROM services ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_service(sid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM services WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


# === Blocked weekdays ===
def set_blocked_weekdays(days):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM blocked_weekdays")
    for d in days:
        cur.execute("INSERT INTO blocked_weekdays (day) VALUES (?)", (d,))
    conn.commit()
    conn.close()


def get_blocked_weekdays():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT day FROM blocked_weekdays")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


# === Slots ===
def add_slot(dt_str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO slots (slot_time, status) VALUES (?, 'free')", (dt_str,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_free_slots():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, slot_time FROM slots WHERE status = 'free' AND slot_time >= datetime('now', 'localtime') ORDER BY slot_time"
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_slot(slot_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, slot_time, status FROM slots WHERE id = ?", (slot_id,))
    row = cur.fetchone()
    conn.close()
    return row


def book_slot(slot_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE slots SET status = 'booked' WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()


def get_slots_admin():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, slot_time, status FROM slots ORDER BY slot_time")
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_slot(slot_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
    cur.execute("DELETE FROM bookings WHERE slot_id = ? AND status = 'pending'", (slot_id,))
    conn.commit()
    conn.close()


# === Bookings ===
def create_booking(slot_id, service_id, name, phone, username, user_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (slot_id, service_id, client_name, client_phone, client_username, client_user_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (slot_id, service_id, name, phone, username or "", user_id, datetime.now().isoformat()),
    )
    bid = cur.lastrowid
    conn.commit()
    conn.close()
    return bid


def get_booking(bid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT b.id, b.slot_id, b.service_id, b.client_name, b.client_phone, b.client_username, b.client_user_id, b.status,
                  s.name as service_name, s.price, sl.slot_time
           FROM bookings b
           JOIN services s ON b.service_id = s.id
           JOIN slots sl ON b.slot_id = sl.id
           WHERE b.id = ?""",
        (bid,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def confirm_booking(bid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE bookings SET status = 'confirmed' WHERE id = ?", (bid,))
    conn.commit()
    conn.close()


def reject_booking(bid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT slot_id FROM bookings WHERE id = ?", (bid,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE slots SET status = 'free' WHERE id = ?", (row[0],))
    cur.execute("UPDATE bookings SET status = 'rejected' WHERE id = ?", (bid,))
    conn.commit()
    conn.close()


def get_pending_bookings():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT b.id, b.client_name, b.client_phone, b.client_username,
                  s.name, s.price, sl.slot_time
           FROM bookings b
           JOIN services s ON b.service_id = s.id
           JOIN slots sl ON b.slot_id = sl.id
           WHERE b.status = 'pending'
           ORDER BY sl.slot_time"""
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_bookings_history():
    """Возвращает все подтверждённые и отклонённые записи, отсортированные по дате слота (новые сверху)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT b.id,
                  b.status,
                  b.client_name,
                  b.client_username,
                  s.name as service_name,
                  s.price,
                  sl.slot_time
           FROM bookings b
           JOIN services s ON b.service_id = s.id
           JOIN slots sl ON b.slot_id = sl.id
           WHERE b.status IN ('confirmed', 'rejected')
           ORDER BY sl.slot_time DESC"""
    )
    rows = cur.fetchall()
    conn.close()
    return rows
