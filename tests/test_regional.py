"""Testes da conversa regional com um conjunto de dados pequeno e fixo."""
import json
import os
import tempfile
import unittest

DADOS = {
    'gerado_em': '2026-10-26T13:14-03:00',
    'fontes': {},
    'municipios': {
        '2111300': {'codigo': '2111300', 'nome': 'São Luís', 'lat': -2.53, 'lon': -44.3, 'declividade': 1.0,
                    'clima': {'vento_kmh': 15, 'vento_dir': 45, 'umidade': 60, 'fonte_vento': 'Open-Meteo',
                              'chuva_24h': 30, 'chuva_prev_24h': 60, 'fonte_chuva': 'Open-Meteo',
                              'dias_sem_chuva': 1, 'chuva_30d': 120, 'fonte_dias_sem_chuva': 'Open-Meteo'},
                    'focos': {'h24': 0, 'h48': 0}, 'avisos': []},
        '2101608': {'codigo': '2101608', 'nome': 'Barra do Corda', 'lat': -5.5, 'lon': -45.25, 'declividade': 8.0,
                    'clima': {'vento_kmh': 25, 'vento_dir': 90, 'umidade': 25, 'fonte_vento': 'Open-Meteo',
                              'chuva_24h': 0, 'chuva_prev_24h': 0, 'fonte_chuva': 'Open-Meteo',
                              'dias_sem_chuva': 40, 'chuva_30d': 3, 'fonte_dias_sem_chuva': 'Open-Meteo'},
                    'focos': {'h24': 4, 'h48': 9}, 'avisos': [{'evento': 'Baixa umidade', 'severidade': 'Perigo'}]},
        '2111201': {'codigo': '2111201', 'nome': 'São José de Ribamar', 'lat': -2.56, 'lon': -44.05, 'declividade': 1.0,
                    'clima': {'vento_kmh': 18, 'vento_dir': 45, 'umidade': 65, 'fonte_vento': 'Open-Meteo',
                              'chuva_24h': 5, 'chuva_prev_24h': 5, 'fonte_chuva': 'Open-Meteo',
                              'dias_sem_chuva': 3, 'chuva_30d': 90, 'fonte_dias_sem_chuva': 'Open-Meteo'},
                    'focos': {'h24': 0, 'h48': 0}, 'avisos': []},
    },
    'focos': [{'lat': -5.45, 'lon': -45.2, 'data_hora_utc': '2026-10-26 14:10:00', 'satelite': 'GOES-19', 'municipio': '2101608'}],
}


class RegionalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(DADOS, cls.tmp, ensure_ascii=False)
        cls.tmp.close()
        os.environ['OLIVER_DADOS_URL'] = 'http://127.0.0.1:9/indisponivel'
        from oliver import regional
        regional.DADOS_URL = os.environ['OLIVER_DADOS_URL']
        regional.DADOS_LOCAL = cls.tmp.name
        regional.carregar_dados(forcar=True)
        cls.regional = regional

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.tmp.name)

    def conversa(self, msgs):
        from oliver.chat import assistant
        st, r = {}, None
        for m in msgs:
            r = assistant({'message': m, 'state': st})
            st = r.get('state', st)
        return r

    def test_fogo_em_uma_frase(self):
        r = self.conversa(['qual o risco de queimada em barra do corda?'])
        self.assertTrue(r['complete'])
        self.assertEqual(r['reports'][0]['domain'], 'fire')
        self.assertIn('Barra do Corda', r['reply'])

    def test_cidade_seca_tem_risco_maior_que_cidade_umida(self):
        seca = self.conversa(['fogo em barra do corda'])['reports'][0]
        umida = self.conversa(['fogo em são luís'])['reports'][0]
        nota = lambda rep: int(next(f['value'] for f in rep['findings'] if f['metric'].startswith('Risco estimado')).split('/')[0])
        self.assertGreater(nota(seca), nota(umida))

    def test_alagamento_faz_tres_perguntas(self):
        r = self.conversa(['alagamento', 'sao luis'])
        self.assertEqual(r['state']['aguardando'], 'imovel')
        r = self.conversa(['alagamento', 'sao luis', 'Casa ou térreo', 'Não sabe', 'Sim, costuma alagar'])
        self.assertTrue(r['complete'])
        self.assertEqual(r['reports'][0]['domain'], 'flood')

    def test_nome_mais_longo_vence(self):
        r = self.conversa(['moro em São José de Ribamar, tem perigo de fogo?'])
        self.assertIn('São José de Ribamar', r['reply'])

    def test_outro_estado(self):
        r = self.conversa(['e em teresina, no piauí?'])
        self.assertFalse(r['complete'])
        self.assertIn('Maranhão', r['reply'])

    def test_panorama(self):
        r = self.conversa(['como está o maranhão hoje?'])
        self.assertEqual(r['domain'], 'panorama')
        self.assertEqual(r['regional']['ranking'][0]['nome'], 'Barra do Corda')

    def test_nome_parecido(self):
        r = self.conversa(['fogo em barra da corda'])
        self.assertIn('Barra do Corda', r['reply'])

    def test_varias_cidades(self):
        r = self.conversa(['queimadas em são luís e barra do corda'])
        self.assertEqual([x['location'] for x in r['reports']], ['São Luís – MA', 'Barra do Corda – MA'])

    def test_lembra_o_assunto_na_cidade_nova(self):
        r = self.conversa(['fogo em são luís', 'e barra do corda?'])
        self.assertTrue(r['complete'])
        self.assertEqual(r['reports'][0]['domain'], 'fire')
        self.assertIn('Barra do Corda', r['reply'])

    def test_os_dois(self):
        r = self.conversa(['são luís', 'Os dois', 'apartamento', 'longe', 'não'])
        self.assertEqual([x['domain'] for x in r['reports']], ['fire', 'flood'])


if __name__ == '__main__':
    unittest.main()
