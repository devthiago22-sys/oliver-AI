"""Contas de usuário do Oliver (SQLite + senhas com hash)."""
import os
import re
import secrets
import sqlite3
import time

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get('OLIVER_DB', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'oliver.db'))
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
RESET_TTL = 60 * 60  # link de recuperação vale 1 hora


class AuthError(ValueError):
    """Erro com mensagem que pode ser mostrada ao usuário."""


def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _db() as con:
        con.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS password_resets (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );
        ''')


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
    try:
        with _db() as con:
            cur = con.execute('INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
                              (name, email, generate_password_hash(password), time.time()))
            return {'id': cur.lastrowid, 'name': name, 'email': email}
    except sqlite3.IntegrityError:
        raise AuthError('Já existe uma conta com esse e-mail.')


def login(user, password):
    """Aceita o e-mail ou o nome cadastrado."""
    user = (user or '').strip()
    with _db() as con:
        row = con.execute('SELECT * FROM users WHERE email = ? OR lower(name) = lower(?)', (user.lower(), user)).fetchone()
    if not row or not check_password_hash(row['password_hash'], password or ''):
        raise AuthError('E-mail, usuário ou senha incorretos.')
    return {'id': row['id'], 'name': row['name'], 'email': row['email']}


def get_user(user_id):
    with _db() as con:
        row = con.execute('SELECT id, name, email FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def create_reset(email):
    """Cria um link de recuperação. Devolve o token ou None se o e-mail não existir."""
    email = (email or '').strip().lower()
    with _db() as con:
        row = con.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if not row:
            return None
        token = secrets.token_urlsafe(32)
        con.execute('INSERT INTO password_resets (token, user_id, expires_at) VALUES (?, ?, ?)',
                    (token, row['id'], time.time() + RESET_TTL))
        return token


def reset_password(token, password):
    _check_password(password or '')
    with _db() as con:
        row = con.execute('SELECT * FROM password_resets WHERE token = ?', (token or '',)).fetchone()
        if not row or row['used'] or row['expires_at'] < time.time():
            raise AuthError('Este link de recuperação é inválido ou expirou. Peça um novo.')
        con.execute('UPDATE users SET password_hash = ? WHERE id = ?', (generate_password_hash(password), row['user_id']))
        con.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
