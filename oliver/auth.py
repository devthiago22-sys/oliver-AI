"""Contas de usuário do Oliver (senhas com hash).

Banco:
  - DATABASE_URL definida (ex.: Supabase) → Postgres, via psycopg
  - sem DATABASE_URL → SQLite no arquivo oliver.db (computador local, PythonAnywhere)
"""
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
PG = DATABASE_URL.startswith(('postgres://', 'postgresql://'))
DB_PATH = os.environ.get('OLIVER_DB', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'oliver.db'))
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
RESET_TTL = 60 * 60  # link de recuperação vale 1 hora

if PG:
    import psycopg
    from psycopg.rows import dict_row
    ERROS_DUPLICADO = (psycopg.errors.UniqueViolation, sqlite3.IntegrityError)
else:
    ERROS_DUPLICADO = (sqlite3.IntegrityError,)


class AuthError(ValueError):
    """Erro com mensagem que pode ser mostrada ao usuário."""


@contextmanager
def _db():
    if PG:
        # prepare_threshold=None: compatível com o pooler do Supabase (Supavisor)
        con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    else:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def _q(con, sql, args=()):
    cur = con.cursor()
    cur.execute(sql.replace('?', '%s') if PG else sql, args)
    return cur


def _um(cur):
    row = cur.fetchone()
    return dict(row) if row is not None else None


def init_db():
    with _db() as con:
        if PG:
            _q(con, '''CREATE TABLE IF NOT EXISTS users (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL)''')
            _q(con, '''CREATE TABLE IF NOT EXISTS password_resets (
                token TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at DOUBLE PRECISION NOT NULL, used INTEGER NOT NULL DEFAULT 0)''')
        else:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS password_resets (
                    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
            ''')


def ping():
    """Consulta mínima ao banco (usada pela verificação de saúde; mantém o Supabase ativo)."""
    with _db() as con:
        return _q(con, 'SELECT count(*) AS n FROM users').fetchone() is not None


def _check_password(password):
    if len(password) < 8:
        raise AuthError('A senha precisa ter pelo menos 8 caracteres.')


def signup(name, email, password):
    name, email = (name or '').strip(), (email or '').strip().lower()
    if not name:
        raise AuthError('Informe seu nome.')
    if not EMAIL_RE.match(email):
        raise AuthError('Informe um e-mail válido.')
    _check_password(password or '')
    args = (name, email, generate_password_hash(password), time.time())
    try:
        with _db() as con:
            if PG:
                uid = _q(con, 'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?) RETURNING id',
                         args).fetchone()['id']
            else:
                uid = _q(con, 'INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)', args).lastrowid
            return {'id': uid, 'name': name, 'email': email}
    except ERROS_DUPLICADO:
        raise AuthError('Já existe uma conta com esse e-mail.')


def login(user, password):
    """Aceita o e-mail ou o nome cadastrado."""
    user = (user or '').strip()
    with _db() as con:
        row = _um(_q(con, 'SELECT * FROM users WHERE email = ? OR lower(name) = lower(?) ORDER BY id LIMIT 1',
                     (user.lower(), user)))
    if not row or not check_password_hash(row['password_hash'], password or ''):
        raise AuthError('E-mail, usuário ou senha incorretos.')
    return {'id': row['id'], 'name': row['name'], 'email': row['email']}


def get_user(user_id):
    with _db() as con:
        return _um(_q(con, 'SELECT id, name, email FROM users WHERE id = ?', (user_id,)))


def create_reset(email):
    """Cria um link de recuperação. Devolve o token ou None se o e-mail não existir."""
    email = (email or '').strip().lower()
    with _db() as con:
        row = _um(_q(con, 'SELECT id FROM users WHERE email = ?', (email,)))
        if not row:
            return None
        token = secrets.token_urlsafe(32)
        _q(con, 'INSERT INTO password_resets (token, user_id, expires_at) VALUES (?, ?, ?)',
           (token, row['id'], time.time() + RESET_TTL))
        return token


def reset_password(token, password):
    _check_password(password or '')
    with _db() as con:
        row = _um(_q(con, 'SELECT * FROM password_resets WHERE token = ?', (token or '',)))
        if not row or row['used'] or row['expires_at'] < time.time():
            raise AuthError('Este link de recuperação é inválido ou expirou. Peça um novo.')
        _q(con, 'UPDATE users SET password_hash = ? WHERE id = ?', (generate_password_hash(password), row['user_id']))
        _q(con, 'UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
