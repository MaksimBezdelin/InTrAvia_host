# ============================================================
# InTrAvia Dispatch — Сервер (Flask)
# ============================================================
#
# Файл собран командой InTrAvia вместе с нейросетью-ассистентом.
#
# Что сгенерировано нейросетью:
#   - базовый каркас Flask-приложения (импорты, роуты, JSON-ответы);
#   - типовые CRUD-эндпоинты для users / engineers / pilots / transport;
#   - схема БД и SQL-запросы;
#   - заготовки функций диспетчеризации, Whisper-транскрипции,
#     стриминга аудио.
#
# Что доработано вручную:
#   - логика приоритетов инженеров по специализации (жёсткая привязка);
#   - механика отказа / отмены с причиной и переназначением клона;
#   - задержки рейсов, отмена рейса с удалением заявки;
#   - флаг all_rejected (когда отказались все специалисты);
#   - повторная проверка очереди через 10 секунд;
#   - миграции колонок, нумерация инженеров, устойчивость к WAL.
#
# Каждый блок помечен по происхождению:
#   [AI]  — сгенерировано нейросетью;
#   [MAN] — доработано вручную;
#   [MIX] — смешанная работа.
# ============================================================

# ============================================================
# [AI] Базовые импорты — стандартный набор для Flask-приложения
# ============================================================
import os
import re
import math
import time
import json
import base64
import sqlite3
import tempfile
import subprocess
import shutil
import threading
from flask import (
    Flask, request, jsonify, session,
    render_template, redirect, url_for,
    Response, abort
)

# ------------------------------------------------------------
# [MIX] Конфигурация
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

REGULATION_MINUTES = 15
WALK_SPEED_KMH = 5.0
RECHECK_DELAY_SEC = 10   # [MAN] повторная проверка очереди

FFMPEG_PATH = r'C:\Users\deela\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe'

# [MAN] проверка ffmpeg и подмешивание его в PATH
if os.path.exists(FFMPEG_PATH):
    ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
    current_path = os.environ.get('PATH', '')
    if ffmpeg_dir not in current_path.split(os.pathsep):
        os.environ['PATH'] = ffmpeg_dir + os.pathsep + current_path
        print(f'[FFMPEG] Добавлено в PATH: {ffmpeg_dir}')
    else:
        print(f'[FFMPEG] Уже в PATH: {ffmpeg_dir}')
else:
    print(f'[FFMPEG] ВНИМАНИЕ: {FFMPEG_PATH} не найден!')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = 'intravia-secret-key-change-in-production'
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024


# ------------------------------------------------------------
# [MAN] Координаты стоянок
# ------------------------------------------------------------
PARKING_COORDS = {
    '101': (55.9807, 37.4171), '102': (55.9806, 37.4171),
    '103': (55.9801, 37.4173), '104': (55.9800, 37.4174),
    '105': (55.9808, 37.4163), '106': (55.9807, 37.4164),
    '107': (55.9804, 37.4172), '108': (55.9803, 37.4173),
    '109': (55.9801, 37.4166), '110': (55.9800, 37.4167),
    '111': (55.9797, 37.4175), '112': (55.9796, 37.4176),
    '113': (55.9794, 37.4170), '114': (55.9793, 37.4170),
    '115': (55.9790, 37.4179), '116': (55.9789, 37.4179),
    '117': (55.9785, 37.4183), '118': (55.9782, 37.4176),
    '119': (55.9783, 37.4172), '120': (55.9784, 37.4172),
    '121': (55.9785, 37.4171), '122': (55.9783, 37.4181),
    '124': (55.9799, 37.4095), '125': (55.9797, 37.4097),
    '126': (55.9796, 37.4113), '127': (55.9796, 37.4115),
    '128': (55.9792, 37.4100), '129': (55.9790, 37.4102),
    '130': (55.9796, 37.4111), '131': (55.9791, 37.4111),
    '132': (55.9790, 37.4112), '134': (55.9789, 37.4115),
    '135': (55.9788, 37.4116), '136': (55.9784, 37.4105),
    '137': (55.9782, 37.4106), '138': (55.9781, 37.4118),
    '139': (55.9780, 37.4120), '140': (55.9775, 37.4125),
    '141': (55.9771, 37.4119), '142': (55.9771, 37.4110),
    '143': (55.9772, 37.4104), '144': (55.9774, 37.4103),
    '145': (55.9774, 37.4121), '146': (55.9772, 37.4121),
    '11': (55.9624, 37.4013), '12': (55.9624, 37.4004),
    '13': (55.9625, 37.4017), '14': (55.9627, 37.4027),
    '15': (55.9627, 37.4030), '16': (55.9630, 37.4043),
    '17': (55.9632, 37.4047), '19': (55.9643, 37.4047),
    '20': (55.9645, 37.4046), '21': (55.9650, 37.4043),
    '22': (55.9652, 37.4042), '23': (55.9655, 37.4043),
    '24': (55.9656, 37.4046), '25': (55.9656, 37.4050),
    '26': (55.9650, 37.4055), '27': (55.9648, 37.4056),
    '28': (55.9642, 37.4058), '29': (55.9640, 37.4060),
    '30': (55.9635, 37.4074), '31': (55.9636, 37.4087),
    '32': (55.9636, 37.4092), '33': (55.9637, 37.4107),
    '34': (55.9638, 37.4108), '35': (55.9639, 37.4118),
    '36': (55.9644, 37.4128), '37': (55.9644, 37.4128),
    '38': (55.9648, 37.4130), '39': (55.9652, 37.4132),
    '40': (55.9656, 37.4134), '41': (55.9659, 37.4135),
    '46': (55.9664, 37.4134), '47': (55.9667, 37.4135),
    '48': (55.9669, 37.4137), '49': (55.9669, 37.4138),
    '50': (55.9670, 37.4146), '51': (55.9671, 37.4155),
    '52': (55.9672, 37.4163), '53': (55.9674, 37.4171),
    '54': (55.9674, 37.4172), '55': (55.9671, 37.4180),
    '57': (55.9669, 37.4181), '58': (55.9668, 37.4181),
    '59': (55.9664, 37.4179), '60': (55.9661, 37.4175),
}


# ============================================================
# [AI] Дистанция между координатами (haversine)
# ============================================================
def distance_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ============================================================
# [MIX] Соединение с БД
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError as e:
        print(f'[DB] PRAGMA warning: {e}')
    return conn


# ============================================================
# [MIX] Схема БД
# ============================================================
def ensure_schema(conn):
    cur = conn.cursor()

    # [AI] Таблица users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        TEXT PRIMARY KEY,
            email     TEXT UNIQUE NOT NULL,
            password  TEXT NOT NULL,
            name      TEXT NOT NULL,
            role      TEXT NOT NULL,
            avatar    TEXT,
            phone     TEXT,
            shift     TEXT,
            status    TEXT DEFAULT 'offline'
        )
    """)

    # [AI] Таблица engineers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS engineers (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            device_id       TEXT,
            specialization  TEXT DEFAULT 'general',
            coords_lat      REAL DEFAULT 55.975,
            coords_lng      REAL DEFAULT 37.410,
            status          TEXT DEFAULT 'free',
            task            TEXT,
            phone           TEXT
        )
    """)

    # [AI] Таблица pilots
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pilots (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT UNIQUE,
            phone       TEXT,
            aircraft    TEXT,
            rank        TEXT DEFAULT 'pilot',
            status      TEXT DEFAULT 'active'
        )
    """)

    # [AI] Таблица transport
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transport (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id    TEXT UNIQUE NOT NULL,
            lat          REAL NOT NULL,
            lng          REAL NOT NULL,
            speed        INTEGER DEFAULT 50,
            assigned_to  TEXT
        )
    """)

    # [MIX] Таблица requests — каркас от нейросети,
    # вручную добавлены блоки под отказ/отмену/задержки.
    # ВАЖНО: комментарии внутри SQL-строки удалены — SQLite
    # не понимает символ '#' и падает с unrecognized token.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id                    TEXT PRIMARY KEY,
            aircraft              TEXT,
            fault_type            TEXT,
            severity              TEXT DEFAULT 'medium',
            terminal              TEXT,
            parking_id            TEXT,
            description           TEXT,
            source                TEXT DEFAULT 'dispatcher',
            engineer_id           TEXT,
            engineer_name         TEXT,
            travel_time           REAL DEFAULT 0,
            using_car             INTEGER DEFAULT 0,
            walk_to_car           REAL DEFAULT 0,
            car_time              REAL DEFAULT 0,
            best_car              TEXT,
            status                TEXT DEFAULT 'assigned',
            criticality           TEXT DEFAULT 'medium',
            engineer_comment      TEXT,
            pilot_name            TEXT,
            pilot_rank            TEXT,
            pilot_audio           TEXT,
            pilot_audio_mime      TEXT,
            pilot_audio_duration  REAL DEFAULT 0,
            pilot_audio_text      TEXT,
            rejected_by           TEXT DEFAULT '',
            cancel_reason         TEXT DEFAULT '',
            cancelled_by_name     TEXT DEFAULT '',
            cancelled_at          TIMESTAMP,
            replaces_request_id   TEXT DEFAULT '',
            delay_minutes         INTEGER DEFAULT 0,
            delay_reason          TEXT DEFAULT '',
            delay_started_at      TIMESTAMP,
            delay_approved_by     TEXT DEFAULT '',
            flight_cancelled      INTEGER DEFAULT 0,
            flight_cancel_reason  TEXT DEFAULT '',
            flight_cancelled_at   TIMESTAMP,
            all_rejected          INTEGER DEFAULT 0,
            created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # [MAN] Автомиграция — докатка колонок на старых БД
    cur.execute("PRAGMA table_info(requests)")
    existing_cols = {row['name'] for row in cur.fetchall()}
    needed_cols = {
        'pilot_name':           "TEXT",
        'pilot_rank':           "TEXT",
        'pilot_audio':          "TEXT",
        'pilot_audio_mime':     "TEXT",
        'pilot_audio_duration': "REAL DEFAULT 0",
        'pilot_audio_text':     "TEXT",
        'rejected_by':          "TEXT DEFAULT ''",
        'cancel_reason':        "TEXT DEFAULT ''",
        'cancelled_by_name':    "TEXT DEFAULT ''",
        'cancelled_at':         "TIMESTAMP",
        'replaces_request_id':  "TEXT DEFAULT ''",
        'delay_minutes':        "INTEGER DEFAULT 0",
        'delay_reason':         "TEXT DEFAULT ''",
        'delay_started_at':     "TIMESTAMP",
        'delay_approved_by':    "TEXT DEFAULT ''",
        'flight_cancelled':     "INTEGER DEFAULT 0",
        'flight_cancel_reason': "TEXT DEFAULT ''",
        'flight_cancelled_at':  "TIMESTAMP",
        'all_rejected':         "INTEGER DEFAULT 0",
    }
    for col, col_type in needed_cols.items():
        if col not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE requests ADD COLUMN {col} {col_type}")
                print(f"[MIGRATION] Добавлена колонка requests.{col}")
            except sqlite3.OperationalError as e:
                print(f"[MIGRATION] Не удалось добавить {col}: {e}")
    conn.commit()


# ============================================================
# [MIX] Начальные данные
# ============================================================
def seed_initial_data(conn):
    cur = conn.cursor()

    # [AI] Админ по умолчанию
    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO users (id, email, password, name, role, avatar, status)
            VALUES (?, ?, ?, ?, 'admin', '👨‍💼', 'online')
        """, ('admin_1', 'admin@aeroflot.ru', 'admin123', 'Администратор'))

    # [AI] Диспетчеры по умолчанию
    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'dispatcher'")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO users (id, email, password, name, role, avatar, phone, shift, status)
            VALUES (?, ?, ?, ?, 'dispatcher', '👨‍✈️', ?, ?, 'online')
        """, [
            ('disp_1', 'dispatcher@aeroflot.ru',  'disp123', 'Петров П.П.',  '+7 (999) 200-10-01', 'day'),
            ('disp_2', 'dispatcher2@aeroflot.ru', 'disp123', 'Козлов К.К.',  '+7 (999) 200-10-02', 'night'),
        ])

    # [MIX] Инженеры
    cur.execute("SELECT COUNT(*) FROM engineers")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO engineers (id, name, device_id, specialization, coords_lat, coords_lng, status, phone)
            VALUES (?, ?, ?, ?, ?, ?, 'free', ?)
        """, [
            ('eng_1',  'Иванов И.И.',    'EN-001', 'engine',     55.975, 37.410, '+7 (999) 300-10-01'),
            ('eng_5',  'Морозов М.М.',   'EN-005', 'engine',     55.974, 37.412, '+7 (999) 300-10-05'),
            ('eng_7',  'Волков В.В.',    'EN-007', 'engine',     55.973, 37.408, '+7 (999) 300-10-07'),
            ('eng_2',  'Сидоров С.С.',   'EN-002', 'avionics',   55.977, 37.412, '+7 (999) 300-10-02'),
            ('eng_8',  'Зайцев З.З.',    'EN-008', 'avionics',   55.978, 37.410, '+7 (999) 300-10-08'),
            ('eng_13', 'Гусев Г.Г.',     'EN-013', 'avionics',   55.976, 37.418, '+7 (999) 300-10-13'),
            ('eng_3',  'Кузнецов К.К.',  'EN-003', 'hydraulics', 55.973, 37.415, '+7 (999) 300-10-03'),
            ('eng_10', 'Орлов О.О.',     'EN-010', 'hydraulics', 55.977, 37.416, '+7 (999) 300-10-10'),
            ('eng_4',  'Смирнов С.С.',   'EN-004', 'electrical', 55.976, 37.408, '+7 (999) 300-10-04'),
            ('eng_9',  'Лебедев Л.Л.',   'EN-009', 'electrical', 55.974, 37.418, '+7 (999) 300-10-09'),
            ('eng_14', 'Соколов С.С.',   'EN-014', 'electrical', 55.972, 37.410, '+7 (999) 300-10-14'),
            ('eng_6',  'Новиков Н.Н.',   'EN-006', 'mechanical', 55.976, 37.415, '+7 (999) 300-10-06'),
            ('eng_11', 'Титов Т.Т.',     'EN-011', 'mechanical', 55.972, 37.413, '+7 (999) 300-10-11'),
            ('eng_15', 'Фомин Ф.Ф.',     'EN-015', 'mechanical', 55.979, 37.412, '+7 (999) 300-10-15'),
            ('eng_12', 'Белов Б.Б.',     'EN-012', 'general',    55.979, 37.414, '+7 (999) 300-10-12'),
            ('eng_16', 'Егоров Е.Е.',    'EN-016', 'general',    55.971, 37.415, '+7 (999) 300-10-16'),
        ])

        # [AI] Привязка учёток инженеров
        cur.executemany("""
            INSERT OR IGNORE INTO users (id, email, password, name, role, avatar, status)
            VALUES (?, ?, 'eng123', ?, 'engineer', '🔧', 'offline')
        """, [
            ('eng_1',  'ivanov@aeroflot.ru',    'Иванов И.И.'),
            ('eng_2',  'sidorov@aeroflot.ru',   'Сидоров С.С.'),
            ('eng_3',  'kuznetsov@aeroflot.ru', 'Кузнецов К.К.'),
            ('eng_4',  'smirnov@aeroflot.ru',   'Смирнов С.С.'),
            ('eng_5',  'morozov@aeroflot.ru',   'Морозов М.М.'),
            ('eng_6',  'novikov@aeroflot.ru',   'Новиков Н.Н.'),
            ('eng_7',  'volkov@aeroflot.ru',    'Волков В.В.'),
            ('eng_8',  'zaytsev@aeroflot.ru',   'Зайцев З.З.'),
            ('eng_9',  'lebedev@aeroflot.ru',   'Лебедев Л.Л.'),
            ('eng_10', 'orlov@aeroflot.ru',     'Орлов О.О.'),
            ('eng_11', 'titov@aeroflot.ru',     'Титов Т.Т.'),
            ('eng_12', 'belov@aeroflot.ru',     'Белов Б.Б.'),
            ('eng_13', 'gusev@aeroflot.ru',     'Гусев Г.Г.'),
            ('eng_14', 'sokolov@aeroflot.ru',   'Соколов С.С.'),
            ('eng_15', 'fomin@aeroflot.ru',     'Фомин Ф.Ф.'),
            ('eng_16', 'egorov@aeroflot.ru',    'Егоров Е.Е.'),
        ])

    # [AI] Пилоты по умолчанию
    cur.execute("SELECT COUNT(*) FROM pilots")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO pilots (id, name, email, phone, aircraft, rank, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, [
            ('pilot_1', 'Иванов И.И.',   'ivanov@aeroflot.ru',    '+7 (999) 100-10-01', 'SU-1234', 'captain'),
            ('pilot_2', 'Петров П.П.',   'petrov@aeroflot.ru',    '+7 (999) 100-10-02', 'SU-1235', 'pilot'),
            ('pilot_3', 'Сидоров С.С.',  'sidorov@aeroflot.ru',   '+7 (999) 100-10-03', 'SU-1236', 'co-pilot'),
            ('pilot_4', 'Кузнецов К.К.', 'kuznetsov@aeroflot.ru', '+7 (999) 100-10-04', 'SU-1237', 'captain'),
            ('pilot_5', 'Смирнов С.С.',  'smirnov@aeroflot.ru',   '+7 (999) 100-10-05', 'SU-1238', 'pilot'),
        ])
        cur.executemany("""
            INSERT OR IGNORE INTO users (id, email, password, name, role, avatar, status)
            VALUES (?, ?, 'pilot123', ?, 'pilot', '👨‍✈️', 'offline')
        """, [
            ('pilot_1', 'pilot1@aeroflot.ru', 'Иванов И.И.'),
            ('pilot_2', 'pilot2@aeroflot.ru', 'Петров П.П.'),
            ('pilot_3', 'pilot3@aeroflot.ru', 'Сидоров С.С.'),
            ('pilot_4', 'pilot4@aeroflot.ru', 'Кузнецов К.К.'),
            ('pilot_5', 'pilot5@aeroflot.ru', 'Смирнов С.С.'),
        ])

    # [AI] Спецтранспорт по умолчанию
    cur.execute("SELECT COUNT(*) FROM transport")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO transport (device_id, lat, lng, speed)
            VALUES (?, ?, ?, ?)
        """, [
            ('CAR-001', 55.9780, 37.4150, 40),
            ('CAR-002', 55.9790, 37.4130, 60),
            ('CAR-003', 55.9760, 37.4090, 50),
            ('CAR-004', 55.9740, 37.4160, 30),
            ('CAR-005', 55.9770, 37.4180, 70),
        ])

    conn.commit()


# ============================================================
# [MAN] Номера инженеров (EN-XXX)
# ============================================================
DEVICE_ID_RE = re.compile(r'^EN-(\d{3})$')


def get_engineer_number_from_device(device_id):
    if not device_id:
        return 0
    m = DEVICE_ID_RE.match(str(device_id))
    if m:
        return int(m.group(1))
    return 0


def get_used_numbers(conn):
    cur = conn.cursor()
    cur.execute("SELECT device_id FROM engineers")
    used = set()
    for row in cur.fetchall():
        n = get_engineer_number_from_device(row['device_id'])
        if n > 0:
            used.add(n)
    return used


def next_engineer_number(conn):
    used = get_used_numbers(conn)
    return (max(used) + 1) if used else 1


def normalize_device_id(device_id, number):
    if number > 0:
        return f'EN-{number:03d}'
    return device_id or 'EN-000'


# ============================================================
# [MAN] Миграция нумерации инженеров
# ============================================================
def migrate_engineer_numbers():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, device_id, name FROM engineers")
    rows = cur.fetchall()
    if not rows:
        conn.close()
        return

    def sort_key(r):
        m = re.search(r'(\d+)\s*$', str(r['id'] or ''))
        num = int(m.group(1)) if m else 10**9
        return (num, str(r['name'] or ''))

    ordered = sorted(rows, key=sort_key)

    needs = False
    for idx, r in enumerate(ordered, start=1):
        if get_engineer_number_from_device(r['device_id']) != idx:
            needs = True
            break

    if not needs:
        conn.close()
        return

    print(f'[MIGRATION] Перенумерация {len(ordered)} инженеров')

    mapping = []
    for idx, r in enumerate(ordered, start=1):
        old_id = r['id']
        tmp_id = f'__tmp_{int(time.time() * 1000000)}_{idx}'
        tmp_dev = f'__TMP_{idx}'
        new_id = f'eng_{idx}'
        new_dev = f'EN-{idx:03d}'
        mapping.append((tmp_id, new_id, new_dev, r['name'], old_id))

        try:
            cur.execute("UPDATE engineers SET id = ?, device_id = ? WHERE id = ?",
                        (tmp_id, tmp_dev, old_id))
            cur.execute("UPDATE users SET id = ? WHERE id = ?", (tmp_id, old_id))
            cur.execute("UPDATE requests SET engineer_id = ? WHERE engineer_id = ?",
                        (tmp_id, old_id))
        except sqlite3.IntegrityError as e:
            print(f'[MIGRATION] Не удалось сдвинуть {old_id}: {e}')

    conn.commit()

    for tmp_id, new_id, new_dev, name, old_id in mapping:
        try:
            cur.execute("UPDATE engineers SET id = ?, device_id = ? WHERE id = ?",
                        (new_id, new_dev, tmp_id))
            cur.execute("UPDATE users SET id = ? WHERE id = ?", (new_id, tmp_id))
            cur.execute("UPDATE requests SET engineer_id = ? WHERE engineer_id = ?",
                        (new_id, tmp_id))
            print(f'[MIGRATION] {name}: {old_id} → {new_id} ({new_dev})')
        except sqlite3.IntegrityError as e:
            print(f'[MIGRATION] Не удалось установить {new_id}: {e}')

    conn.commit()
    conn.close()
    print('[MIGRATION] Готово')


def init_db():
    print(f'[DB] Используется база: {DB_PATH}')
    conn = get_db()
    ensure_schema(conn)
    seed_initial_data(conn)
    conn.close()
    migrate_engineer_numbers()
    print('[DB] Инициализация завершена')


# ============================================================
# [MIX] Утилиты инженеров
# ============================================================
def set_engineer_busy(conn, engineer_id, task_text):
    if not engineer_id:
        return False
    cur = conn.cursor()
    cur.execute("SELECT id FROM engineers WHERE id = ?", (engineer_id,))
    if not cur.fetchone():
        return False
    cur.execute("UPDATE engineers SET status = 'busy', task = ? WHERE id = ?",
                (task_text, engineer_id))
    print(f'[ENGINEER] {engineer_id} → busy ({task_text})')
    return cur.rowcount > 0


def set_engineer_free(conn, engineer_id):
    if not engineer_id:
        return False
    cur = conn.cursor()
    cur.execute("SELECT id FROM engineers WHERE id = ?", (engineer_id,))
    if not cur.fetchone():
        return False
    cur.execute("UPDATE engineers SET status = 'free', task = NULL WHERE id = ?",
                (engineer_id,))
    print(f'[ENGINEER] {engineer_id} → free')
    return cur.rowcount > 0


# [MAN] Сколько активных заявок у инженера (кроме указанной)
def engineer_has_active_requests(conn, engineer_id, exclude_request_id=None):
    cur = conn.cursor()
    if exclude_request_id:
        cur.execute("""
            SELECT COUNT(*) FROM requests
            WHERE engineer_id = ?
              AND status NOT IN ('completed', 'cancelled', 'flight_cancelled')
              AND id != ?
        """, (engineer_id, exclude_request_id))
    else:
        cur.execute("""
            SELECT COUNT(*) FROM requests
            WHERE engineer_id = ?
              AND status NOT IN ('completed', 'cancelled', 'flight_cancelled')
        """, (engineer_id,))
    return cur.fetchone()[0]


# ============================================================
# [MAN] Поиск инженера — строго по специализации
# ============================================================
def get_free_engineer_for(conn, fault_type, required_skill_map,
                          target_lat=None, target_lng=None,
                          exclude_ids=None):
    if exclude_ids is None:
        exclude_ids = set()
    exclude_ids = {str(x) for x in exclude_ids}

    required_skill = required_skill_map.get(fault_type, 'general')

    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, device_id, specialization, coords_lat, coords_lng
        FROM engineers WHERE status = 'free'
    """)
    all_free = [dict(r) for r in cur.fetchall()]

    # [MAN] Исключаем занятых по активным заявкам — защита от рассинхрона
    cur.execute("""
        SELECT DISTINCT engineer_id FROM requests
        WHERE status NOT IN ('completed', 'cancelled', 'flight_cancelled')
          AND engineer_id IS NOT NULL
    """)
    busy_with_requests = {row['engineer_id'] for row in cur.fetchall()}

    all_free = [e for e in all_free
                if str(e['id']) not in exclude_ids
                and str(e['id']) not in busy_with_requests]

    # [MAN] Строго по специализации
    pool = [e for e in all_free if e['specialization'] == required_skill]

    print(f'[DISPATCH] fault={fault_type} skill="{required_skill}" '
          f'| свободных={len(all_free)} подходящих={len(pool)} '
          f'| exclude={exclude_ids}')

    if not pool:
        return None, None

    if target_lat is None or target_lng is None:
        return pool[0], {
            'travel_time': 0, 'walk_time': 0, 'using_car': False,
            'best_car': None, 'best_car_time': 0, 'walk_to_car': 0
        }

    # [AI] Расчёт маршрута: пешком + вариант с машиной
    cur.execute("""
        SELECT id, device_id, lat, lng, speed
        FROM transport WHERE assigned_to IS NULL
    """)
    cars = [dict(r) for r in cur.fetchall()]

    feasible = []
    for e in pool:
        e_lat = e['coords_lat'] or 55.975
        e_lng = e['coords_lng'] or 37.410
        walk_dist = distance_km(e_lat, e_lng, target_lat, target_lng)
        walk_time = walk_dist / WALK_SPEED_KMH * 60

        best_car = None
        best_time = walk_time
        best_car_time = 0
        best_walk_to_car = 0

        for car in cars:
            wtc = distance_km(e_lat, e_lng, car['lat'], car['lng']) / WALK_SPEED_KMH * 60
            sp = car['speed'] or 30
            dt = distance_km(car['lat'], car['lng'], target_lat, target_lng) / sp * 60
            t = wtc + dt
            if t < best_time:
                best_time = t
                best_car = car
                best_car_time = dt
                best_walk_to_car = wtc

        if best_time > REGULATION_MINUTES:
            continue

        feasible.append({
            'engineer': e,
            'travel_time': round(best_time, 1),
            'walk_time': round(walk_time, 1),
            'using_car': best_car is not None,
            'best_car': best_car,
            'best_car_time': round(best_car_time, 1),
            'walk_to_car': round(best_walk_to_car, 1)
        })

    if not feasible:
        return None, None

    feasible.sort(key=lambda x: x['travel_time'])
    return feasible[0]['engineer'], feasible[0]


# ============================================================
# [MAN] Разбор очереди
# ============================================================
def try_reassign_queued():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT engineer_id FROM requests
        WHERE status NOT IN ('completed', 'cancelled', 'flight_cancelled')
          AND engineer_id IS NOT NULL
    """)
    busy_engineers = {row['engineer_id'] for row in cur.fetchall()}

    cur.execute("""
        SELECT id, aircraft, fault_type, parking_id, rejected_by
        FROM requests WHERE status = 'queued'
        ORDER BY created_at ASC
    """)
    queued = [dict(r) for r in cur.fetchall()]

    if not queued:
        conn.close()
        return

    for q in queued:
        rejected = set()
        if q['rejected_by']:
            for x in str(q['rejected_by']).split(','):
                if x.strip():
                    rejected.add(x.strip())

        exclude = set(rejected) | busy_engineers

        parking_id = str(q['parking_id'] or '')
        target = PARKING_COORDS.get(parking_id, (55.975, 37.410))

        engineer, route = get_free_engineer_for(
            conn,
            q['fault_type'] or 'engine_failure',
            FAULT_SKILL,
            target[0], target[1],
            exclude_ids=exclude
        )
        if not engineer:
            continue

        # [MAN] Сбрасываем delay_* и all_rejected при назначении
        cur.execute("""
            UPDATE requests
            SET engineer_id = ?, engineer_name = ?,
                travel_time = ?, using_car = ?, walk_to_car = ?,
                car_time = ?, best_car = ?, status = 'assigned',
                delay_minutes = 0,
                delay_reason = '',
                delay_started_at = NULL,
                delay_approved_by = '',
                all_rejected = 0
            WHERE id = ?
        """, (
            engineer['id'], engineer['name'],
            route['travel_time'],
            1 if route['using_car'] else 0,
            route['walk_to_car'],
            route['best_car_time'],
            route['best_car']['device_id'] if route['best_car'] else None,
            q['id']
        ))
        if route['using_car'] and route['best_car']:
            cur.execute("UPDATE transport SET assigned_to = ? WHERE id = ?",
                        (q['id'], route['best_car']['id']))

        cur.execute("UPDATE engineers SET status = 'busy', task = ? WHERE id = ?",
                    ('ВС ' + (q['aircraft'] or ''), engineer['id']))
        busy_engineers.add(engineer['id'])
        print(f'[QUEUE] {q["id"]} назначена на {engineer["id"]}')

    conn.commit()
    conn.close()


# ============================================================
# [AI] Страницы
# ============================================================
@app.route('/')
def index():
    return redirect(url_for('login_page'))


@app.route('/login.html')
def login_page():
    return render_template('login.html')


@app.route('/admin/dashboard.html')
def admin_dashboard():
    return render_template('admin/dashboard.html')


@app.route('/dispatcher/dashboard.html')
def dispatcher_dashboard():
    return render_template('dispatcher/dashboard.html')


@app.route('/engineer/dashboard.html')
def engineer_dashboard():
    return render_template('engineer/dashboard.html')


@app.route('/pilot/dashboard.html')
def pilot_dashboard():
    return render_template('pilot/dashboard.html')


# ============================================================
# [AI] Авторизация
# ============================================================
@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()

    if not email or not password:
        return jsonify({'error': 'Заполните все поля'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, name, role, avatar
        FROM users WHERE email = ? AND password = ?
    """, (email, password))
    user = cur.fetchone()

    if not user:
        conn.close()
        return jsonify({'error': 'Неверный email или пароль'}), 401

    cur.execute("UPDATE users SET status = 'online' WHERE id = ?", (user['id'],))
    conn.commit()
    conn.close()

    extra = {}
    if user['role'] == 'pilot':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT aircraft, rank FROM pilots WHERE id = ?", (user['id'],))
        row = cur.fetchone()
        conn.close()
        if row:
            extra['aircraft'] = row['aircraft'] or ''
            extra['rank'] = row['rank'] or 'pilot'

    result = {
        'id': user['id'],
        'email': user['email'],
        'name': user['name'],
        'role': user['role'],
        'avatar': user['avatar'] or '👤'
    }
    result.update(extra)

    return jsonify({'success': True, 'user': result})


# ============================================================
# [MIX] Инженеры — CRUD
# ============================================================
@app.route('/api/engineers', methods=['GET'])
def get_engineers():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, device_id, specialization,
               coords_lat, coords_lng, status, task, phone
        FROM engineers
    """)
    rows = cur.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        num = get_engineer_number_from_device(d.get('device_id'))
        d['number'] = num
        d['device_id'] = normalize_device_id(d.get('device_id'), num)
        result.append(d)

    result.sort(key=lambda x: x.get('number') or 0)
    return jsonify(result)


@app.route('/api/engineers/me', methods=['GET'])
def get_my_engineer():
    engineer_id = request.args.get('id')
    if not engineer_id:
        return jsonify({'error': 'Не указан id инженера'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, device_id, specialization,
               coords_lat, coords_lng, status, task, phone
        FROM engineers WHERE id = ?
    """, (engineer_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({'error': 'Инженер не найден'}), 404

    d = dict(row)
    num = get_engineer_number_from_device(d.get('device_id'))
    d['number'] = num
    d['device_id'] = normalize_device_id(d.get('device_id'), num)
    return jsonify(d)


@app.route('/api/engineers/<eng_id>', methods=['GET'])
def get_engineer(eng_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, device_id, specialization,
               coords_lat, coords_lng, status, task, phone
        FROM engineers WHERE id = ?
    """, (eng_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Инженер не найден'}), 404
    d = dict(row)
    num = get_engineer_number_from_device(d.get('device_id'))
    d['number'] = num
    d['device_id'] = normalize_device_id(d.get('device_id'), num)
    return jsonify(d)


@app.route('/api/engineers', methods=['POST'])
def create_engineer():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()

    if not name or not email:
        return jsonify({'error': 'Имя и email обязательны'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cur.fetchone():
        conn.close()
        return jsonify({'error': 'Инженер с таким email уже существует'}), 400

    # [MAN] Автонумерация eng_N / EN-00N
    number = next_engineer_number(conn)
    eng_id = f'eng_{number}'
    device_id = f'EN-{number:03d}'

    cur.execute("SELECT COUNT(*) FROM engineers")
    total = cur.fetchone()[0]
    base_lat = 55.975 + (total % 6) * 0.0008
    base_lng = 37.410 + (total % 6) * 0.0008

    cur.execute("""
        INSERT INTO engineers (id, name, device_id, specialization,
                               coords_lat, coords_lng, status, phone)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        eng_id, name, device_id,
        data.get('specialization', 'general'),
        base_lat, base_lng,
        data.get('status', 'free'),
        data.get('phone', '')
    ))

    cur.execute("""
        INSERT INTO users (id, email, password, name, role, avatar, status)
        VALUES (?, ?, 'eng123', ?, 'engineer', '🔧', 'offline')
    """, (eng_id, email, name))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': eng_id,
                    'device_id': device_id, 'number': number})


@app.route('/api/engineers/<eng_id>', methods=['PUT'])
def update_engineer(eng_id):
    data = request.get_json() or {}
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM engineers WHERE id = ?", (eng_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Инженер не найден'}), 404

    cur.execute("""
        UPDATE engineers
        SET name = ?, specialization = ?, status = ?, task = ?, phone = ?
        WHERE id = ?
    """, (
        data.get('name'),
        data.get('specialization', 'general'),
        data.get('status', 'free'),
        data.get('task'),
        data.get('phone', ''),
        eng_id
    ))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/engineers/<eng_id>', methods=['DELETE'])
def delete_engineer(eng_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM engineers WHERE id = ?", (eng_id,))
    cur.execute("DELETE FROM users WHERE id = ?", (eng_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/engineers/<eng_id>/coords', methods=['PUT'])
def update_engineer_coords(eng_id):
    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')
    if lat is None or lng is None:
        return jsonify({'error': 'lat/lng обязательны'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE engineers SET coords_lat = ?, coords_lng = ? WHERE id = ?",
                (lat, lng, eng_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# [AI] Пилоты — стандартный CRUD
# ============================================================
@app.route('/api/pilots', methods=['GET'])
def get_pilots():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, email, phone, aircraft, rank, status
        FROM pilots ORDER BY name
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/pilots', methods=['POST'])
def create_pilot():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    if not name or not email:
        return jsonify({'error': 'Имя и email обязательны'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM pilots WHERE email = ?", (email,))
    if cur.fetchone():
        conn.close()
        return jsonify({'error': 'Пилот с таким email уже существует'}), 400

    pilot_id = 'pilot_' + str(int(time.time() * 1000))
    cur.execute("""
        INSERT INTO pilots (id, name, email, phone, aircraft, rank, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (pilot_id, name, email, data.get('phone', ''),
          data.get('aircraft', ''), data.get('rank', 'pilot'),
          data.get('status', 'active')))

    cur.execute("""
        INSERT INTO users (id, email, password, name, role, avatar, status)
        VALUES (?, ?, 'pilot123', ?, 'pilot', '👨‍✈️', 'offline')
    """, (pilot_id, email, name))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': pilot_id})


@app.route('/api/pilots/<pilot_id>', methods=['PUT'])
def update_pilot(pilot_id):
    data = request.get_json() or {}
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM pilots WHERE id = ?", (pilot_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Пилот не найден'}), 404
    cur.execute("""
        UPDATE pilots SET name = ?, phone = ?, aircraft = ?, rank = ?, status = ?
        WHERE id = ?
    """, (data.get('name'), data.get('phone', ''), data.get('aircraft', ''),
          data.get('rank', 'pilot'), data.get('status', 'active'), pilot_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/pilots/<pilot_id>', methods=['DELETE'])
def delete_pilot(pilot_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pilots WHERE id = ?", (pilot_id,))
    cur.execute("DELETE FROM users WHERE id = ?", (pilot_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# [AI] Пользователи — CRUD
# ============================================================
@app.route('/api/users', methods=['GET'])
def get_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, name, role, avatar, phone, shift, status
        FROM users ORDER BY role, name
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/users', methods=['POST'])
def create_user():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    role = data.get('role', 'dispatcher')
    if not name or not email:
        return jsonify({'error': 'Имя и email обязательны'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cur.fetchone():
        conn.close()
        return jsonify({'error': 'Пользователь с таким email уже существует'}), 400
    user_id = role + '_' + str(int(time.time() * 1000))
    avatar = '👨‍✈️' if role == 'dispatcher' else '👤'
    password = 'disp123' if role == 'dispatcher' else 'user123'
    cur.execute("""
        INSERT INTO users (id, email, password, name, role, avatar, phone, shift, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'offline')
    """, (user_id, email, password, name, role, avatar,
          data.get('phone', ''), data.get('shift', 'day')))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': user_id})


@app.route('/api/users/<user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json() or {}
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Пользователь не найден'}), 404
    cur.execute("""
        UPDATE users SET name = ?, phone = ?, shift = ?, status = ?
        WHERE id = ?
    """, (data.get('name'), data.get('phone', ''), data.get('shift', 'day'),
          data.get('status', 'offline'), user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/users/<user_id>', methods=['DELETE'])
def delete_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# [AI] Транспорт — CRUD
# ============================================================
@app.route('/api/transport', methods=['GET'])
def get_transport():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, device_id, lat, lng, speed, assigned_to
        FROM transport ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/transport', methods=['POST'])
def create_transport():
    data = request.get_json() or {}
    device_id = (data.get('device_id') or '').strip()
    lat = data.get('lat')
    lng = data.get('lng')
    if not device_id or lat is None or lng is None:
        return jsonify({'error': 'device_id, lat, lng обязательны'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM transport WHERE device_id = ?", (device_id,))
    if cur.fetchone():
        conn.close()
        return jsonify({'error': 'Транспорт с таким device_id уже существует'}), 400
    cur.execute("""
        INSERT INTO transport (device_id, lat, lng, speed, assigned_to)
        VALUES (?, ?, ?, ?, ?)
    """, (device_id, lat, lng, data.get('speed', 50), data.get('assigned_to')))
    conn.commit()
    transport_id = cur.lastrowid
    conn.close()
    return jsonify({'success': True, 'id': transport_id})


@app.route('/api/transport/<int:transport_id>', methods=['PUT'])
def update_transport(transport_id):
    data = request.get_json() or {}
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM transport WHERE id = ?", (transport_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Транспорт не найден'}), 404
    cur.execute("""
        UPDATE transport SET device_id = ?, lat = ?, lng = ?, speed = ?, assigned_to = ?
        WHERE id = ?
    """, (data.get('device_id'), data.get('lat'), data.get('lng'),
          data.get('speed', 50), data.get('assigned_to'), transport_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/transport/<int:transport_id>', methods=['DELETE'])
def delete_transport(transport_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM transport WHERE id = ?", (transport_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/transport/<int:transport_id>/coords', methods=['PUT'])
def update_transport_coords(transport_id):
    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')
    if lat is None or lng is None:
        return jsonify({'error': 'lat/lng обязательны'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE transport SET lat = ?, lng = ?, speed = COALESCE(?, speed)
        WHERE id = ?
    """, (lat, lng, data.get('speed'), transport_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# [MIX] Заявки — GET / PUT / DELETE
# ============================================================
@app.route('/api/requests', methods=['GET'])
def get_requests():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, aircraft, fault_type, severity, terminal, parking_id,
               description, source, engineer_id, engineer_name,
               travel_time, using_car, walk_to_car, car_time, best_car,
               status, criticality, engineer_comment, created_at,
               pilot_name, pilot_rank, pilot_audio, pilot_audio_mime,
               pilot_audio_duration, pilot_audio_text, rejected_by,
               cancel_reason, cancelled_by_name, cancelled_at,
               replaces_request_id,
               delay_minutes, delay_reason, delay_started_at,
               delay_approved_by, flight_cancelled, flight_cancel_reason,
               flight_cancelled_at, all_rejected
        FROM requests ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/requests/<request_id>', methods=['PUT'])
def update_request(request_id):
    data = request.get_json() or {}
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM requests WHERE id = ?", (request_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Заявка не найдена'}), 404

    cur.execute("""
        UPDATE requests
        SET status = COALESCE(?, status),
            criticality = COALESCE(?, criticality),
            engineer_comment = COALESCE(?, engineer_comment),
            aircraft = COALESCE(?, aircraft),
            fault_type = COALESCE(?, fault_type),
            terminal = COALESCE(?, terminal),
            parking_id = COALESCE(?, parking_id)
        WHERE id = ?
    """, (
        data.get('status'),
        data.get('criticality'),
        data.get('engineer_comment'),
        data.get('aircraft'),
        data.get('fault_type'),
        data.get('terminal'),
        data.get('parking_id'),
        request_id
    ))

    new_status = data.get('status')

    # [MAN] Освобождаем инженера при cancelled
    if new_status == 'cancelled':
        cur.execute("SELECT engineer_id FROM requests WHERE id = ?", (request_id,))
        r = cur.fetchone()
        if r and r['engineer_id']:
            other = engineer_has_active_requests(conn, r['engineer_id'], request_id)
            if other == 0:
                cur.execute("UPDATE engineers SET status = 'free', task = NULL WHERE id = ?",
                            (r['engineer_id'],))
        cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to = ?",
                    (request_id,))

    # [MAN] То же для completed
    if new_status == 'completed':
        cur.execute("SELECT engineer_id FROM requests WHERE id = ?", (request_id,))
        r = cur.fetchone()
        if r and r['engineer_id']:
            other = engineer_has_active_requests(conn, r['engineer_id'], request_id)
            if other == 0:
                cur.execute("UPDATE engineers SET status = 'free', task = NULL WHERE id = ?",
                            (r['engineer_id'],))
        cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to = ?",
                    (request_id,))

    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/requests/<request_id>', methods=['DELETE'])
def delete_request(request_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, engineer_id, status FROM requests WHERE id = ?", (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Заявка не найдена'}), 404

    engineer_id = row['engineer_id']
    old_status = row['status']

    cur.execute("DELETE FROM requests WHERE id = ?", (request_id,))
    cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to = ?", (request_id,))

    if engineer_id and old_status not in ('completed', 'cancelled', 'flight_cancelled'):
        other = engineer_has_active_requests(conn, engineer_id, request_id)
        if other == 0:
            set_engineer_free(conn, engineer_id)

    conn.commit()
    conn.close()

    try_reassign_queued()
    return jsonify({'success': True})


@app.route('/api/requests/<request_id>/pilot_audio_text', methods=['PUT'])
def save_pilot_audio_text(request_id):
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, source FROM requests WHERE id = ?", (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Заявка не найдена'}), 404
    if row['source'] != 'pilot':
        conn.close()
        return jsonify({'error': 'Это не заявка КВС'}), 400
    cur.execute("UPDATE requests SET pilot_audio_text = ? WHERE id = ?", (text, request_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# [MAN] Таблица «поломка → специализация»
# ============================================================
FAULT_SKILL = {
    'engine_failure':        'engine',
    'engine_oil':            'engine',
    'engine_overheat':       'engine',
    'engine_vibration':      'engine',
    'engine_start':          'engine',
    'fuel_leak':             'engine',
    'fuel_system':           'engine',
    'avionics_nav':          'avionics',
    'avionics_radio':        'avionics',
    'avionics_autopilot':    'avionics',
    'avionics_transponder':  'avionics',
    'avionics_display':      'avionics',
    'avionics_gps':          'avionics',
    'hydraulic':             'hydraulics',
    'hydraulic_leak':        'hydraulics',
    'hydraulic_pressure':    'hydraulics',
    'electrical':            'electrical',
    'electrical_generator':  'electrical',
    'electrical_battery':    'electrical',
    'electrical_short':      'electrical',
    'electrical_lighting':   'electrical',
    'landing_gear':          'mechanical',
    'pneumatic':             'mechanical',
    'brake_system':          'mechanical',
    'flap_issue':            'mechanical',
    'aileron_issue':         'mechanical',
    'rudder_issue':          'mechanical',
    'wing_damage':           'mechanical',
    'fuselage_damage':       'mechanical',
    'door_issue':            'mechanical',
    'air_condition':         'general',
    'pressurization':        'general',
    'oxygen_system':         'general',
    'fire_system':           'general',
    'deicing_system':        'general',
    'pilot_voice':           'general',
}


# ============================================================
# [MIX] Диспетчеризация — POST /api/dispatch
# ============================================================
@app.route('/api/dispatch', methods=['POST'])
def dispatch():
    data = request.get_json() or {}
    source = data.get('source', 'dispatcher')
    conn = get_db()
    cur = conn.cursor()

    # === Ветка «голосовая заявка от КВС» ===
    if source == 'pilot':
        pilot_name = (data.get('pilot_name') or '').strip() or 'Пилот'
        pilot_rank = (data.get('pilot_rank') or '').strip() or 'КВС'
        aircraft = (data.get('aircraft') or '').strip() or None
        engineer_id = data.get('engineer_id')
        pilot_audio = data.get('pilot_audio') or ''
        pilot_audio_mime = data.get('pilot_audio_mime') or 'audio/webm'
        pilot_audio_duration = data.get('pilot_audio_duration') or 0

        if not pilot_audio:
            conn.close()
            return jsonify({'success': False, 'error': 'Аудиозапись не передана'}), 400

        if engineer_id:
            cur.execute("SELECT name, rank, aircraft FROM pilots WHERE id = ?", (engineer_id,))
            p = cur.fetchone()
            if p:
                pilot_name = p['name'] or pilot_name
                pilot_rank = p['rank'] or pilot_rank
                aircraft = aircraft or p['aircraft']

        request_id = 'req_' + str(int(time.time() * 1000))
        cur.execute("""
            INSERT INTO requests (
                id, aircraft, fault_type, severity, terminal, parking_id,
                description, source, engineer_id, engineer_name,
                travel_time, status, criticality,
                pilot_name, pilot_rank, pilot_audio, pilot_audio_mime,
                pilot_audio_duration
            )
            VALUES (?, ?, ?, 'medium', NULL, NULL,
                    ?, 'pilot', NULL, NULL,
                    0, 'new', 'medium',
                    ?, ?, ?, ?, ?)
        """, (request_id, aircraft, 'pilot_voice',
              'Голосовая заявка от командира ВС',
              pilot_name, pilot_rank, pilot_audio, pilot_audio_mime,
              pilot_audio_duration))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'request_id': request_id,
                        'requestId': request_id, 'id': request_id})

    # === Ветка «заявка от диспетчера» ===
    aircraft = (data.get('aircraft') or '').strip()
    fault_type = data.get('fault_type', 'engine_failure')
    severity = data.get('severity', 'medium')
    terminal = data.get('terminal', 'D')
    parking_id = str(data.get('parking_id') or '')
    description = data.get('description', '')

    if not aircraft or not parking_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Не указан рейс или стоянка'}), 400

    target = PARKING_COORDS.get(parking_id)
    if target:
        target_lat, target_lng = target
    else:
        target_lat, target_lng = 55.975, 37.410

    engineer, route = get_free_engineer_for(
        conn, fault_type, FAULT_SKILL, target_lat, target_lng
    )

    request_id = 'req_' + str(int(time.time() * 1000))

    # [MAN] Нет инженера — очередь + старт задержки + all_rejected
    if not engineer:
        cur.execute("""
            INSERT INTO requests (
                id, aircraft, fault_type, severity, terminal, parking_id,
                description, source, status, criticality, rejected_by,
                delay_started_at, delay_reason, all_rejected
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'dispatcher', 'queued', ?, '',
                    CURRENT_TIMESTAMP, 'Ожидание инженера', 1)
        """, (request_id, aircraft, fault_type, severity, terminal, parking_id,
              description, severity))
        conn.commit()
        conn.close()
        print(f'[DISPATCH] {request_id} → очередь (нет специалистов)')
        return jsonify({'success': True, 'request_id': request_id,
                        'queued': True, 'delay_started': True,
                        'message': 'Нет свободных инженеров. Заявка в очереди.'})

    travel_time = route['travel_time']
    using_car = route['using_car']
    best_car = route['best_car']

    cur.execute("""
        INSERT INTO requests (
            id, aircraft, fault_type, severity, terminal, parking_id,
            description, source, engineer_id, engineer_name,
            travel_time, using_car, walk_to_car, car_time, best_car,
            status, criticality, rejected_by, all_rejected
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'dispatcher', ?, ?, ?, ?, ?, ?, ?, 'assigned', ?, '', 0)
    """, (request_id, aircraft, fault_type, severity, terminal, parking_id,
          description, engineer['id'], engineer['name'],
          travel_time, 1 if using_car else 0,
          route['walk_to_car'], route['best_car_time'],
          best_car['device_id'] if best_car else None, severity))

    if using_car and best_car:
        cur.execute("UPDATE transport SET assigned_to = ? WHERE id = ?",
                    (request_id, best_car['id']))

    set_engineer_busy(conn, engineer['id'], 'ВС ' + aircraft)
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'request_id': request_id,
        'selected': {
            'engineer': {
                'id': engineer['id'],
                'name': engineer['name'],
                'device_id': normalize_device_id(
                    engineer['device_id'],
                    get_engineer_number_from_device(engineer['device_id'])
                ),
                'specialization': engineer['specialization'],
                'coords_lat': engineer['coords_lat'],
                'coords_lng': engineer['coords_lng']
            },
            'travel_time': travel_time,
            'using_car': using_car,
            'walk_time': route['walk_time'],
            'walk_to_car': route['walk_to_car'],
            'car_time': route['best_car_time'],
            'best_car': best_car['device_id'] if using_car else None,
            'best_car_obj': {
                'id': best_car['id'],
                'deviceId': best_car['device_id'],
                'lat': best_car['lat'],
                'lng': best_car['lng'],
                'speed': best_car['speed']
            } if using_car else None
        }
    })


# ============================================================
# [MAN] Отложенная перепроверка очереди
# ============================================================
def _schedule_recheck(request_id):
    def worker():
        time.sleep(RECHECK_DELAY_SEC)
        try:
            conn2 = get_db()
            cur2 = conn2.cursor()
            cur2.execute("SELECT status, flight_cancelled FROM requests WHERE id = ?",
                         (request_id,))
            r = cur2.fetchone()
            conn2.close()
            if r and r['status'] == 'queued' and not r['flight_cancelled']:
                print(f'[RECHECK] {request_id} — проверка через {RECHECK_DELAY_SEC} сек')
                try_reassign_queued()
        except Exception as e:
            print(f'[RECHECK] ошибка: {e}')

    threading.Thread(target=worker, daemon=True).start()


# ============================================================
# [MIX] Отмена заявки инженером — POST /cancel
# ============================================================
@app.route('/api/requests/<request_id>/cancel', methods=['POST'])
def cancel_request(request_id):
    data = request.get_json() or {}
    engineer_id = str(data.get('engineer_id') or '').strip()
    reason = (data.get('reason') or '').strip()

    if not reason:
        return jsonify({'success': False, 'error': 'Укажите причину отмены'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, aircraft, fault_type, severity, terminal, parking_id,
               description, engineer_id, engineer_name, status, rejected_by,
               created_at
        FROM requests WHERE id = ?
    """, (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
    if row['status'] == 'completed':
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка уже выполнена'}), 400
    if row['status'] == 'cancelled':
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка уже отменена'}), 400

    who_id = engineer_id or row['engineer_id']
    who_name = row['engineer_name'] or ''
    if who_id:
        cur.execute("SELECT name FROM engineers WHERE id = ?", (who_id,))
        e = cur.fetchone()
        if e and e['name']:
            who_name = e['name']

    old_engineer_id = row['engineer_id']

    if old_engineer_id:
        cur.execute("UPDATE engineers SET status = 'free', task = NULL WHERE id = ?",
                    (old_engineer_id,))
    cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to = ?",
                (request_id,))

    rejected_prev = set()
    if row['rejected_by']:
        for x in str(row['rejected_by']).split(','):
            if x.strip():
                rejected_prev.add(x.strip())
    if who_id:
        rejected_prev.add(str(who_id))
    rejected_str = ','.join(sorted(rejected_prev))

    fault_type = row['fault_type'] or 'engine_failure'
    parking_id = str(row['parking_id'] or '')
    aircraft = row['aircraft'] or 'ВС'
    target = PARKING_COORDS.get(parking_id, (55.975, 37.410))
    target_lat, target_lng = target

    cur.execute("""
        SELECT DISTINCT engineer_id FROM requests
        WHERE status NOT IN ('completed', 'cancelled', 'flight_cancelled')
          AND engineer_id IS NOT NULL AND id != ?
    """, (request_id,))
    busy_engineers = {r['engineer_id'] for r in cur.fetchall()}
    exclude_all = rejected_prev | busy_engineers

    new_engineer, route = get_free_engineer_for(
        conn, fault_type, FAULT_SKILL,
        target_lat, target_lng, exclude_ids=exclude_all
    )

    cur.execute("""
        UPDATE requests
        SET status = 'cancelled',
            cancel_reason = ?,
            cancelled_by_name = ?,
            cancelled_at = CURRENT_TIMESTAMP,
            rejected_by = ?
        WHERE id = ?
    """, (reason, who_name, rejected_str, request_id))

    # [MAN] Если нашли нового — создаём клон
    if new_engineer:
        new_request_id = 'req_' + str(int(time.time() * 1000)) + '_r'
        travel_time = route['travel_time']
        using_car = route['using_car']
        best_car = route['best_car']

        cur.execute("""
            INSERT INTO requests (
                id, aircraft, fault_type, severity, terminal, parking_id,
                description, source, engineer_id, engineer_name,
                travel_time, using_car, walk_to_car, car_time, best_car,
                status, criticality, rejected_by, replaces_request_id,
                all_rejected
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'dispatcher', ?, ?, ?, ?, ?, ?, ?, 'assigned', ?, ?, ?, 0)
        """, (new_request_id, aircraft, fault_type, row['severity'] or 'medium',
              row['terminal'], parking_id, row['description'],
              new_engineer['id'], new_engineer['name'],
              travel_time, 1 if using_car else 0,
              route['walk_to_car'], route['best_car_time'],
              best_car['device_id'] if best_car else None,
              row['severity'] or 'medium',
              rejected_str, request_id))

        if using_car and best_car:
            cur.execute("UPDATE transport SET assigned_to = ? WHERE id = ?",
                        (new_request_id, best_car['id']))

        cur.execute("UPDATE engineers SET status = 'busy', task = ? WHERE id = ?",
                    ('ВС ' + aircraft, new_engineer['id']))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'request_id': request_id,
            'cancelled_by_name': who_name,
            'reason': reason,
            'reassigned': True,
            'new_request_id': new_request_id,
            'selected': {
                'request_id': new_request_id,
                'engineer': {
                    'id': new_engineer['id'],
                    'name': new_engineer['name'],
                    'device_id': normalize_device_id(
                        new_engineer['device_id'],
                        get_engineer_number_from_device(new_engineer['device_id'])
                    ),
                    'specialization': new_engineer['specialization'],
                    'coords_lat': new_engineer['coords_lat'],
                    'coords_lng': new_engineer['coords_lng']
                },
                'travel_time': travel_time,
                'using_car': using_car,
                'walk_to_car': route['walk_to_car'],
                'car_time': route['best_car_time'],
                'best_car': best_car['device_id'] if using_car else None,
                'best_car_obj': {
                    'id': best_car['id'],
                    'deviceId': best_car['device_id'],
                    'lat': best_car['lat'],
                    'lng': best_car['lng'],
                    'speed': best_car['speed']
                } if using_car else None
            }
        })

    # [MAN] Никого не нашли — очередь + all_rejected + отложенная проверка
    required_skill = FAULT_SKILL.get(fault_type, 'general')
    cur.execute("SELECT id, status FROM engineers WHERE specialization = ?",
                (required_skill,))
    all_spec = [dict(r) for r in cur.fetchall()]
    busy_spec = [e for e in all_spec if e['status'] == 'busy']
    free_spec = [e for e in all_spec if e['status'] == 'free']
    can_assign = [e for e in free_spec if str(e['id']) not in rejected_prev]
    all_rejected = 1 if len(can_assign) == 0 else 0

    cur.execute("""
        UPDATE requests
        SET status = 'queued',
            all_rejected = ?,
            delay_started_at = COALESCE(delay_started_at, CURRENT_TIMESTAMP),
            delay_reason = CASE
                WHEN delay_reason = '' OR delay_reason IS NULL
                THEN 'Ожидание инженера'
                ELSE delay_reason
            END
        WHERE id = ?
    """, (all_rejected, request_id))
    conn.commit()
    conn.close()

    if busy_spec:
        _schedule_recheck(request_id)
        return jsonify({
            'success': True,
            'request_id': request_id,
            'cancelled_by_name': who_name,
            'reason': reason,
            'reassigned': False,
            'queued': True,
            'delay_started': True,
            'all_rejected': bool(all_rejected),
            'recheck_in': RECHECK_DELAY_SEC,
            'message': f'Все специалисты заняты. Проверка через {RECHECK_DELAY_SEC} сек.'
        })

    return jsonify({
        'success': True,
        'request_id': request_id,
        'cancelled_by_name': who_name,
        'reason': reason,
        'reassigned': False,
        'queued': True,
        'delay_started': True,
        'all_rejected': bool(all_rejected),
        'message': 'Нет инженеров с нужной специализацией. Заявка в очереди.'
    })


# ============================================================
# [MIX] Отказ инженера от заявки — POST /reject
# ============================================================
@app.route('/api/requests/<request_id>/reject', methods=['POST'])
def reject_request(request_id):
    data = request.get_json() or {}
    rejected_by = str(data.get('engineer_id') or '')
    reason = (data.get('reason') or '').strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, aircraft, fault_type, severity, terminal, parking_id,
               description, engineer_id, rejected_by, status
        FROM requests WHERE id = ?
    """, (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
    if row['status'] == 'completed':
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка уже выполнена'}), 400

    if not rejected_by:
        rejected_by = str(row['engineer_id'] or '')

    fault_type = row['fault_type'] or 'engine_failure'
    parking_id = str(row['parking_id'] or '')
    aircraft = row['aircraft'] or 'ВС'
    target = PARKING_COORDS.get(parking_id, (55.975, 37.410))
    target_lat, target_lng = target

    old_engineer_id = row['engineer_id']
    rejected_prev = set()
    if row['rejected_by']:
        for x in str(row['rejected_by']).split(','):
            if x.strip():
                rejected_prev.add(x.strip())
    if rejected_by:
        rejected_prev.add(rejected_by)
    rejected_str = ','.join(sorted(rejected_prev))

    if old_engineer_id:
        set_engineer_free(conn, old_engineer_id)
    cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to = ?",
                (request_id,))

    cur.execute("""
        SELECT DISTINCT engineer_id FROM requests
        WHERE status NOT IN ('completed', 'cancelled', 'flight_cancelled')
          AND engineer_id IS NOT NULL AND id != ?
    """, (request_id,))
    busy_engineers = {r['engineer_id'] for r in cur.fetchall()}
    exclude_all = rejected_prev | busy_engineers

    new_engineer, route = get_free_engineer_for(
        conn, fault_type, FAULT_SKILL,
        target_lat, target_lng, exclude_ids=exclude_all
    )

    if new_engineer:
        travel_time = route['travel_time']
        using_car = route['using_car']
        best_car = route['best_car']

        cur.execute("""
            UPDATE requests
            SET engineer_id = ?, engineer_name = ?,
                travel_time = ?, using_car = ?, walk_to_car = ?,
                car_time = ?, best_car = ?, status = 'assigned',
                rejected_by = ?, all_rejected = 0
            WHERE id = ?
        """, (new_engineer['id'], new_engineer['name'],
              travel_time, 1 if using_car else 0,
              route['walk_to_car'], route['best_car_time'],
              best_car['device_id'] if best_car else None,
              rejected_str, request_id))

        if using_car and best_car:
            cur.execute("UPDATE transport SET assigned_to = ? WHERE id = ?",
                        (request_id, best_car['id']))
        set_engineer_busy(conn, new_engineer['id'], 'ВС ' + aircraft)
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'reassigned': True,
            'rejected_engineer_id': rejected_by,
            'selected': {
                'engineer': {
                    'id': new_engineer['id'],
                    'name': new_engineer['name'],
                    'device_id': normalize_device_id(
                        new_engineer['device_id'],
                        get_engineer_number_from_device(new_engineer['device_id'])
                    ),
                    'specialization': new_engineer['specialization'],
                    'coords_lat': new_engineer['coords_lat'],
                    'coords_lng': new_engineer['coords_lng']
                },
                'travel_time': travel_time,
                'using_car': using_car,
                'walk_time': route['walk_time'],
                'walk_to_car': route['walk_to_car'],
                'car_time': route['best_car_time'],
                'best_car': best_car['device_id'] if using_car else None,
                'best_car_obj': {
                    'id': best_car['id'],
                    'deviceId': best_car['device_id'],
                    'lat': best_car['lat'],
                    'lng': best_car['lng'],
                    'speed': best_car['speed']
                } if using_car else None
            }
        })

    required_skill = FAULT_SKILL.get(fault_type, 'general')
    cur.execute("SELECT id, status FROM engineers WHERE specialization = ?",
                (required_skill,))
    all_spec = [dict(r) for r in cur.fetchall()]
    busy_spec = [e for e in all_spec if e['status'] == 'busy']
    free_spec = [e for e in all_spec if e['status'] == 'free']
    can_assign = [e for e in free_spec if str(e['id']) not in rejected_prev]
    all_rejected = 1 if len(can_assign) == 0 else 0

    cur.execute("""
        UPDATE requests
        SET status = 'queued',
            engineer_id = NULL, engineer_name = NULL,
            travel_time = 0, using_car = 0, walk_to_car = 0,
            car_time = 0, best_car = NULL,
            rejected_by = ?,
            all_rejected = ?,
            delay_started_at = COALESCE(delay_started_at, CURRENT_TIMESTAMP),
            delay_reason = CASE
                WHEN delay_reason = '' OR delay_reason IS NULL
                THEN 'Ожидание инженера'
                ELSE delay_reason
            END
        WHERE id = ?
    """, (rejected_str, all_rejected, request_id))
    conn.commit()
    conn.close()

    if busy_spec:
        _schedule_recheck(request_id)
        return jsonify({
            'success': True,
            'reassigned': False,
            'queued': True,
            'delay_started': True,
            'all_rejected': bool(all_rejected),
            'recheck_in': RECHECK_DELAY_SEC,
            'message': f'Все специалисты заняты. Проверка через {RECHECK_DELAY_SEC} сек.'
        })

    return jsonify({
        'success': True,
        'reassigned': False,
        'queued': True,
        'delay_started': True,
        'all_rejected': bool(all_rejected),
        'message': 'Нет инженеров с нужной специализацией. Заявка в очереди.'
    })


# ============================================================
# [MAN] Задержка рейса — POST /approve_delay
# ============================================================
@app.route('/api/requests/<request_id>/approve_delay', methods=['POST'])
def approve_delay(request_id):
    data = request.get_json() or {}
    minutes = int(data.get('minutes') or 0)
    reason = (data.get('reason') or '').strip()
    dispatcher_name = (data.get('dispatcher_name') or 'Диспетчер').strip()

    if minutes <= 0 or minutes > 720:
        return jsonify({'success': False, 'error': 'Некорректная длительность'}), 400
    if not reason:
        return jsonify({'success': False, 'error': 'Укажите причину'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, flight_cancelled FROM requests WHERE id = ?", (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
    if row['flight_cancelled']:
        conn.close()
        return jsonify({'success': False, 'error': 'Рейс уже отменён'}), 400

    cur.execute("""
        UPDATE requests
        SET delay_minutes = ?, delay_reason = ?, delay_approved_by = ?,
            delay_started_at = COALESCE(delay_started_at, CURRENT_TIMESTAMP)
        WHERE id = ?
    """, (minutes, reason, dispatcher_name, request_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'request_id': request_id,
                    'delay_minutes': minutes, 'delay_reason': reason,
                    'delay_approved_by': dispatcher_name})


# ============================================================
# [MAN] Отмена рейса — заявка УДАЛЯЕТСЯ из БД
# ============================================================
@app.route('/api/requests/<request_id>/cancel_flight', methods=['POST'])
def cancel_flight(request_id):
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()
    dispatcher_name = (data.get('dispatcher_name') or 'Диспетчер').strip()

    if not reason:
        return jsonify({'success': False, 'error': 'Укажите причину отмены рейса'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, aircraft, engineer_id, flight_cancelled, status
        FROM requests WHERE id = ?
    """, (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
    if row['flight_cancelled']:
        conn.close()
        return jsonify({'success': False, 'error': 'Рейс уже отменён'}), 400

    engineer_id = row['engineer_id']
    aircraft = row['aircraft'] or 'ВС'

    if engineer_id:
        other = engineer_has_active_requests(conn, engineer_id, request_id)
        if other == 0:
            cur.execute("UPDATE engineers SET status = 'free', task = NULL WHERE id = ?",
                        (engineer_id,))
            print(f'[FLIGHT-CANCEL] {engineer_id} → free')

    cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to = ?",
                (request_id,))

    cur.execute("DELETE FROM requests WHERE id = ?", (request_id,))

    conn.commit()
    conn.close()

    print(f'[FLIGHT-CANCEL] Рейс {aircraft} (заявка {request_id}) ОТМЕНЁН и УДАЛЁН '
          f'({dispatcher_name}: {reason})')

    try_reassign_queued()

    return jsonify({
        'success': True,
        'request_id': request_id,
        'flight_cancelled': True,
        'deleted': True,
        'reason': reason,
        'cancelled_by': dispatcher_name,
        'message': f'Рейс {aircraft} отменён, заявка удалена.'
    })


# ============================================================
# [MIX] Освобождение инженера — POST /complete/<eng_id>
# ============================================================
@app.route('/api/complete/<eng_id>', methods=['POST'])
def complete_engineer(eng_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM requests
        WHERE engineer_id = ? AND status NOT IN ('completed', 'cancelled', 'flight_cancelled')
    """, (eng_id,))
    active = cur.fetchall()

    if active:
        conn.close()
        return jsonify({'success': False, 'reason': 'has_active_requests',
                        'active_count': len(active)})

    cur.execute("UPDATE transport SET assigned_to = NULL WHERE assigned_to IN "
                "(SELECT id FROM requests WHERE engineer_id = ?)", (eng_id,))
    cur.execute("UPDATE engineers SET status = 'free', task = NULL WHERE id = ?",
                (eng_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()

    try_reassign_queued()
    return jsonify({'success': ok})


@app.route('/api/clear_all_requests', methods=['POST'])
def clear_all_requests():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM requests")
    cur.execute("UPDATE engineers SET status = 'free', task = NULL")
    cur.execute("UPDATE transport SET assigned_to = NULL")
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/clear_all_pilot_requests', methods=['POST'])
def clear_all_pilot_requests():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM requests WHERE source = 'pilot'")
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# [AI] Аудио — стриминг с поддержкой Range
# ============================================================
def _decode_data_url(data_url):
    if not data_url:
        return b''
    if ',' in data_url:
        data_url = data_url.split(',', 1)[1]
    return base64.b64decode(data_url)


def _guess_ext(mime):
    if not mime:
        return 'webm'
    m = mime.lower()
    if 'mp4' in m or 'm4a' in m: return 'm4a'
    if 'ogg' in m or 'opus' in m: return 'ogg'
    if 'mpeg' in m or 'mp3' in m: return 'mp3'
    if 'wav' in m: return 'wav'
    return 'webm'


@app.route('/api/requests/<request_id>/audio', methods=['GET'])
def stream_pilot_audio(request_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, source, pilot_audio, pilot_audio_mime
        FROM requests WHERE id = ?
    """, (request_id,))
    row = cur.fetchone()
    conn.close()

    if not row or row['source'] != 'pilot' or not row['pilot_audio']:
        abort(404)

    raw = _decode_data_url(row['pilot_audio'])
    if not raw:
        abort(404)

    mime = row['pilot_audio_mime'] or 'audio/webm'
    total = len(raw)
    range_header = request.headers.get('Range', None)

    if range_header:
        try:
            units, _, ranges = range_header.partition('=')
            start_s, _, end_s = ranges.partition('-')
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else total - 1
            if end >= total: end = total - 1
            if start > end or start < 0: start = 0
            chunk = raw[start:end + 1]

            resp = Response(chunk, 206, mimetype=mime, direct_passthrough=True)
            resp.headers['Content-Range'] = f'bytes {start}-{end}/{total}'
            resp.headers['Accept-Ranges'] = 'bytes'
            resp.headers['Content-Length'] = str(len(chunk))
            resp.headers['Cache-Control'] = 'no-store'
            return resp
        except Exception as e:
            print(f'[AUDIO] Range parse error: {e}')

    resp = Response(raw, 200, mimetype=mime, direct_passthrough=True)
    resp.headers['Accept-Ranges'] = 'bytes'
    resp.headers['Content-Length'] = str(total)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


# ============================================================
# [MIX] Whisper — распознавание голосовых заявок
# ============================================================
_whisper_model = None
_whisper_available = None


def get_whisper():
    global _whisper_model, _whisper_available
    if _whisper_available is False:
        return None
    if _whisper_model is not None:
        return _whisper_model
    try:
        import whisper  # type: ignore
        model_name = os.environ.get('WHISPER_MODEL', 'small')
        print(f'[WHISPER] Загружаю модель "{model_name}"...')
        _whisper_model = whisper.load_model(model_name)
        _whisper_available = True
        return _whisper_model
    except Exception as e:
        print(f'[WHISPER] Недоступен: {e}')
        _whisper_available = False
        return None


def _convert_to_wav(input_path):
    ffmpeg_bin = None
    if os.path.exists(FFMPEG_PATH):
        ffmpeg_bin = FFMPEG_PATH
    else:
        found = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
        if found:
            ffmpeg_bin = found
    if not ffmpeg_bin:
        return None
    out_path = input_path + '.wav'
    try:
        result = subprocess.run(
            [ffmpeg_bin, '-y', '-i', input_path, '-ac', '1', '-ar', '16000',
             '-f', 'wav', '-loglevel', 'error', out_path],
            capture_output=True, timeout=120)
        if result.returncode != 0:
            return None
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 100:
            return None
        return out_path
    except Exception:
        return None


# [MAN] Словарь ключевых слов для парсинга поломки из речи
FAULT_KEYWORDS = [
    (['утечка масла', 'масл'], 'engine_oil'),
    (['перегрев двигател', 'перегрев'], 'engine_overheat'),
    (['вибрац', 'тряс'], 'engine_vibration'),
    (['не запускается двигател', 'запуск двигател'], 'engine_start'),
    (['утечка топлив', 'топлив'], 'fuel_leak'),
    (['топливн', 'fuel'], 'fuel_system'),
    (['отказ двигател', 'двигател', 'engine'], 'engine_failure'),
    (['навигац', 'nav', 'курс'], 'avionics_nav'),
    (['радиосвяз', 'радио', 'связь'], 'avionics_radio'),
    (['автопилот'], 'avionics_autopilot'),
    (['транспондер', 'ответчик'], 'avionics_transponder'),
    (['дисплей', 'экран'], 'avionics_display'),
    (['gps'], 'avionics_gps'),
    (['утечка гидравлик', 'гидравлик'], 'hydraulic_leak'),
    (['давление гидравлик'], 'hydraulic_pressure'),
    (['генератор'], 'electrical_generator'),
    (['аккумулятор', 'батаре'], 'electrical_battery'),
    (['короткое замыкание', 'кз'], 'electrical_short'),
    (['освещени', 'свет'], 'electrical_lighting'),
    (['электроснабж', 'электрик', 'electr'], 'electrical'),
    (['шасси', 'landing gear', 'стойк'], 'landing_gear'),
    (['тормоз'], 'brake_system'),
    (['закрылк', 'flap'], 'flap_issue'),
    (['элерон'], 'aileron_issue'),
    (['руль направлени', 'rudder'], 'rudder_issue'),
    (['крыл', 'wing'], 'wing_damage'),
    (['фюзеляж', 'fuselage'], 'fuselage_damage'),
    (['двер', 'door'], 'door_issue'),
    (['пневматик', 'pneumatic'], 'pneumatic'),
    (['кондиционер', 'air condition', 'климат'], 'air_condition'),
    (['разгерметизац', 'герметичн', 'pressur'], 'pressurization'),
    (['кислород', 'oxygen'], 'oxygen_system'),
    (['пожар', 'огн', 'fire'], 'fire_system'),
    (['противообледен', 'обледен', 'deic'], 'deicing_system'),
]


def parse_pilot_text(text):
    result = {'aircraft': None, 'fault_type': None,
              'terminal': None, 'parking_id': None}
    if not text:
        return result
    lower = text.lower()

    m = re.search(r'\b(su[\s\-]?(\d{3,4}))\b', lower)
    if m:
        result['aircraft'] = 'SU-' + m.group(2)
    else:
        m = re.search(r'\bборт[а-я]*\s+(\d{3,4})\b', lower)
        if m:
            result['aircraft'] = 'SU-' + m.group(1)
        else:
            m = re.search(r'\b(\d{4})\b', text)
            if m:
                result['aircraft'] = 'SU-' + m.group(1)

    for keys, code in FAULT_KEYWORDS:
        for k in keys:
            if k in lower:
                result['fault_type'] = code
                break
        if result['fault_type']:
            break

    m = re.search(r'терминал[аеуы]?\s*([a-fA-Fа-яА-Я])', lower)
    if m:
        t = m.group(1).upper()
        t_map = {'А':'A','Б':'B','В':'B','С':'C','Д':'D','Е':'E','Ф':'F'}
        if t in 'ABCDEF':
            result['terminal'] = t
        elif t in t_map:
            result['terminal'] = t_map[t]
    else:
        m = re.search(r'\b([bcdef])\b', lower)
        if m:
            result['terminal'] = m.group(1).upper()

    m = re.search(r'(стоянк[аеуи]|выход[аеу]?)\s*(\d{1,3})', lower)
    if m:
        result['parking_id'] = m.group(2)
    else:
        m = re.search(r'\b(1[0-4]\d)\b', text)
        if m:
            result['parking_id'] = m.group(1)
        else:
            m = re.search(r'\b([1-5]\d|60)\b', text)
            if m:
                result['parking_id'] = m.group(1)

    return result


@app.route('/api/requests/<request_id>/transcribe', methods=['POST'])
def transcribe_pilot_audio(request_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, source, pilot_audio, pilot_audio_mime
        FROM requests WHERE id = ?
    """, (request_id,))
    row = cur.fetchone()
    conn.close()

    if not row or row['source'] != 'pilot' or not row['pilot_audio']:
        return jsonify({'success': False, 'error': 'Нет аудиозаписи'}), 400

    model = get_whisper()
    if model is None:
        return jsonify({'success': False, 'error': 'whisper_unavailable'}), 200

    raw = _decode_data_url(row['pilot_audio'])
    ext = _guess_ext(row['pilot_audio_mime'])

    tmp_path = None
    wav_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.' + ext) as f:
            f.write(raw)
            tmp_path = f.name

        wav_path = _convert_to_wav(tmp_path)
        audio_for_whisper = wav_path if wav_path else tmp_path

        result = model.transcribe(
            audio_for_whisper, language='ru', fp16=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.6, logprob_threshold=-1.0)

        text = (result.get('text') or '').strip()
        parsed = parse_pilot_text(text)

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE requests
            SET pilot_audio_text = ?,
                aircraft = COALESCE(?, aircraft),
                fault_type = COALESCE(?, fault_type),
                terminal = COALESCE(?, terminal),
                parking_id = COALESCE(?, parking_id)
            WHERE id = ?
        """, (text, parsed['aircraft'], parsed['fault_type'],
              parsed['terminal'], parsed['parking_id'], request_id))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'text': text,
                        'engine': 'whisper', 'parsed': parsed})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        for p in (tmp_path, wav_path):
            if p:
                try: os.unlink(p)
                except Exception: pass


# ============================================================
# [AI] Точка входа
# ============================================================
if __name__ == '__main__':
    init_db()
    if os.environ.get('WHISPER_WARMUP') == '1':
        get_whisper()
    app.run(host='0.0.0.0', port=5000, debug=True)