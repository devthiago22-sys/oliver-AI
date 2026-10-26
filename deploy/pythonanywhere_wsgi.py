# Configuração WSGI do Oliver para o PythonAnywhere.
#
# No PythonAnywhere: aba "Web" > seção "Code" > clique no arquivo "WSGI configuration file",
# apague todo o conteúdo e cole este arquivo, trocando SEU_USUARIO pelo seu usuário.
import os
import sys

PROJETO = '/home/SEU_USUARIO/oliver-AI'
if PROJETO not in sys.path:
    sys.path.insert(0, PROJETO)

os.environ['OLIVER_ENV'] = 'production'
# Opcional: e-mail para a recuperação de senha (sem isso, o link aparece no "Server log").
# os.environ['OLIVER_SMTP_HOST'] = 'smtp.gmail.com'
# os.environ['OLIVER_SMTP_PORT'] = '587'
# os.environ['OLIVER_SMTP_USER'] = 'seu-email@gmail.com'
# os.environ['OLIVER_SMTP_PASSWORD'] = 'sua-senha-de-app'

from app import app as application  # noqa: E402
