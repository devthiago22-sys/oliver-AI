"""Contas: funciona com SQLite (padrão) e com Postgres (quando DATABASE_URL está definida)."""
import os
import tempfile
import unittest
import uuid


class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from oliver import auth
        if not auth.PG:
            fd, cls.caminho = tempfile.mkstemp(suffix='.db')
            os.close(fd)
            auth.DB_PATH = cls.caminho
        auth.init_db()
        cls.auth = auth

    @classmethod
    def tearDownClass(cls):
        if not cls.auth.PG:
            os.unlink(cls.caminho)

    def email(self):
        return f'teste-{uuid.uuid4().hex[:10]}@exemplo.com'

    def test_criar_entrar_e_recuperar(self):
        a, email = self.auth, self.email()
        u = a.signup('Maria Teste', email, 'Senha123!')
        self.assertTrue(u['id'])
        self.assertEqual(a.login(email.upper(), 'Senha123!')['id'], u['id'])
        with self.assertRaises(a.AuthError):
            a.login(email, 'errada123')
        with self.assertRaises(a.AuthError):
            a.signup('Outra', email, 'Senha123!')
        token = a.create_reset(email)
        a.reset_password(token, 'NovaSenha9')
        self.assertEqual(a.login(email, 'NovaSenha9')['id'], u['id'])
        with self.assertRaises(a.AuthError):
            a.reset_password(token, 'OutraSenha9')     # link já usado
        self.assertIsNone(a.create_reset('ninguem@exemplo.com'))
        self.assertEqual(a.get_user(u['id'])['email'], email)
        self.assertTrue(a.ping())


if __name__ == '__main__':
    unittest.main()
