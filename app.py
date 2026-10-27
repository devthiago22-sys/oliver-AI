"""Servidor web do Oliver.

Rode com:  python app.py
Depois abra http://127.0.0.1:5000 no navegador.
"""
import os
import secrets
import smtplib
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from email.message import EmailMessage
from functools import wraps

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session

from oliver import auth
from oliver.chat import assistant

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, 'static')

app = Flask(__name__, static_folder=STATIC, static_url_path='')
if os.environ.get('RENDER') or os.environ.get('OLIVER_PROXY'):
    # Atrás do proxy do Render: confia no esquema (https) e no IP informados por ele.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.permanent_session_lifetime = timedelta(days=30)
PRODUCTION = os.environ.get('OLIVER_ENV') == 'production'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=PRODUCTION,   # no site publicado (HTTPS) o cookie só trafega criptografado
    MAX_CONTENT_LENGTH=1024 * 1024,     # o maior pedido é o relatório com várias cidades
)


def _secret_key():
    """Chave das sessões: variável OLIVER_SECRET ou um arquivo gerado na primeira execução."""
    if os.environ.get('OLIVER_SECRET'):
        return os.environ['OLIVER_SECRET']
    path = os.path.join(BASE, 'secret.key')
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.secret_key = _secret_key()
auth.init_db()


def current_user():
    """Usuário da sessão. Nome e e-mail ficam no cookie assinado, sem consultar o banco a cada pedido."""
    uid = session.get('user_id')
    if not uid:
        return None
    if session.get('user_name'):
        return {'id': uid, 'name': session['user_name'], 'email': session.get('user_email', '')}
    user = auth.get_user(uid)
    if user:
        session['user_name'], session['user_email'] = user['name'], user['email']
    return user


def login_required_api(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({'error': 'Sua sessão expirou. Entre novamente.'}), 401
        return view(*args, **kwargs)
    return wrapper


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ---------- Limite de tentativas (protege login e recuperação contra força bruta) ----------
_attempts = defaultdict(deque)
_attempts_lock = threading.Lock()


def too_many(key, limit, window):
    """True se `key` já fez `limit` tentativas nos últimos `window` segundos."""
    now = time.time()
    with _attempts_lock:
        q = _attempts[key]
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        return False


def client_ip():
    # Atrás do proxy do PythonAnywhere/Render o IP real vem neste cabeçalho.
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()


@app.after_request
def security_headers(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('Referrer-Policy', 'same-origin')
    return resp


# ---------- Saúde (usada pelo GitHub para manter o site e o banco acordados) ----------
@app.get('/saude')
def saude():
    try:
        auth.ping()
        banco = 'ok'
    except Exception as e:  # noqa: BLE001
        app.logger.error('Banco indisponível: %s', e)
        banco = 'erro'
    return jsonify({'site': 'ok', 'banco': banco}), (200 if banco == 'ok' else 503)


# ---------- Páginas ----------
@app.get('/')
def login_page():
    if current_user():
        return redirect('/oliver')
    return send_from_directory(STATIC, 'login.html')


@app.get('/oliver')
def oliver_page():
    if not current_user():
        return redirect('/')
    return send_from_directory(STATIC, 'index.html')


# ---------- Contas ----------
@app.errorhandler(auth.AuthError)
def auth_error(err):
    return jsonify({'error': str(err)}), 400


@app.post('/api/auth/signup')
def api_signup():
    data = body()
    if too_many(('signup', client_ip()), limit=10, window=3600):
        return jsonify({'error': 'Muitas contas criadas a partir desta conexão. Tente mais tarde.'}), 429
    user = auth.signup(data.get('name'), data.get('email'), data.get('password'))
    return jsonify({'ok': True, 'user': user})


@app.post('/api/auth/login')
def api_login():
    data = body()
    if too_many(('login', client_ip()), limit=10, window=300):
        return jsonify({'error': 'Muitas tentativas de login. Espere alguns minutos e tente de novo.'}), 429
    user = auth.login(data.get('user'), data.get('password'))
    session.clear()
    session['user_id'] = user['id']
    session['user_name'], session['user_email'] = user['name'], user['email']
    session.permanent = bool(data.get('remember'))
    return jsonify({'ok': True, 'user': user})


@app.post('/api/auth/logout')
def api_logout():
    session.clear()
    return jsonify({'ok': True})


@app.get('/api/auth/me')
def api_me():
    user = current_user()
    if not user:
        return jsonify({'error': 'Não autenticado.'}), 401
    return jsonify({'user': user})


def send_reset_email(to, link):
    """Envia o link por e-mail se houver SMTP configurado; senão, mostra no terminal."""
    host = os.environ.get('OLIVER_SMTP_HOST')
    if not host:
        print('\n' + '=' * 70)
        print(f' Recuperação de senha para {to}')
        print(f' (sem servidor de e-mail configurado, o link aparece aqui)')
        print(f' {link}')
        print('=' * 70 + '\n', flush=True)
        return
    msg = EmailMessage()
    msg['Subject'] = 'Oliver · Recuperação de senha'
    msg['From'] = os.environ.get('OLIVER_SMTP_FROM', os.environ.get('OLIVER_SMTP_USER', 'oliver@localhost'))
    msg['To'] = to
    msg.set_content(f'Olá!\n\nPara criar uma nova senha no Oliver, abra o link abaixo (vale por 1 hora):\n\n{link}\n\n'
                    'Se você não pediu a recuperação, ignore este e-mail.')
    with smtplib.SMTP(host, int(os.environ.get('OLIVER_SMTP_PORT', 587))) as smtp:
        smtp.starttls()
        if os.environ.get('OLIVER_SMTP_USER'):
            smtp.login(os.environ['OLIVER_SMTP_USER'], os.environ.get('OLIVER_SMTP_PASSWORD', ''))
        smtp.send_message(msg)


@app.post('/api/auth/recover')
def api_recover():
    email = (body().get('email') or '').strip().lower()
    if too_many(('recover', client_ip()), limit=5, window=900):
        return jsonify({'error': 'Muitos pedidos de recuperação. Espere alguns minutos e tente de novo.'}), 429
    token = auth.create_reset(email)
    if token:
        send_reset_email(email, f"{request.host_url.rstrip('/')}/?reset={token}")
    # A resposta é a mesma exista ou não a conta, para não revelar quais e-mails estão cadastrados.
    return jsonify({'ok': True})


@app.post('/api/auth/reset')
def api_reset():
    data = body()
    auth.reset_password(data.get('token'), data.get('password'))
    return jsonify({'ok': True})


# ---------- Oliver ----------
@app.post('/api/oliver')
@login_required_api
def api_oliver():
    try:
        return jsonify(assistant(body()))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.post('/api/relatorio')
@login_required_api
def api_relatorio():
    """Gera o PDF das análises enviadas e devolve como arquivo para baixar."""
    from oliver.relatorio import gerar_pdf
    user = current_user()
    if too_many(('pdf', user['id']), limit=20, window=600):
        return jsonify({'error': 'Muitos relatórios em pouco tempo. Espere alguns minutos.'}), 429
    try:
        pdf = gerar_pdf(body().get('analises'), usuario=user.get('name'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    nome = f"oliver-relatorio-{time.strftime('%Y-%m-%d-%H%M')}.pdf"
    return Response(pdf, mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="{nome}"',
        'Cache-Control': 'no-store',
    })


@app.post('/api/sig')
@login_required_api
def api_sig():
    """Dados georreferenciados (Shapefile, GeoPackage, GeoJSON, KML ou CSV) para usar em SIG."""
    from oliver.sig import exportar
    user = current_user()
    if too_many(('sig', user['id']), limit=30, window=600):
        return jsonify({'error': 'Muitos downloads em pouco tempo. Espere alguns minutos.'}), 429
    data = body()
    cidades = data.get('cidades') if data.get('escopo') == 'cidades' else None
    if cidades is not None and (not isinstance(cidades, list) or not all(isinstance(c, str) for c in cidades)):
        return jsonify({'error': 'Lista de municípios inválida.'}), 400
    camadas = data.get('camadas') if isinstance(data.get('camadas'), list) else ['municipios', 'focos']
    try:
        conteudo, nome, mime = exportar(str(data.get('formato', 'shp')), cidades, camadas)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return Response(conteudo, mimetype=mime, headers={
        'Content-Disposition': f'attachment; filename="{nome}"',
        'Cache-Control': 'no-store',
    })


if __name__ == '__main__':
    print('\n  Oliver rodando em http://127.0.0.1:5000  (Ctrl+C para parar)\n')
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)), debug=False)
