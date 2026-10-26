import unittest

from oliver.chat import assistant


def conversa(mensagens, domain='auto'):
    history, resp = [], None
    for m in mensagens:
        resp = assistant({'message': m, 'history': history, 'domain': domain})
        history.append({'role': 'user', 'text': m})
    return resp


def valores(resp):
    return {f['metric']: f['value'] for f in resp['findings']}


class FogoTest(unittest.TestCase):
    def test_dados_completos(self):
        r = conversa(['Localização: Chapada dos Veadeiros; fogo ativo: sim; vento: 30 km/h; direção do vento: norte; '
                      'umidade: 35%; secura da vegetação: 70%; declividade: 20%.'], 'fire')
        self.assertTrue(r['complete'])
        self.assertIn(r['overall_risk'], ('Baixo', 'Moderado', 'Alto'))

    def test_faltando_dados(self):
        r = conversa(['Quero analisar propagação de fogo.'])
        self.assertEqual(r['domain'], 'fire')
        self.assertFalse(r['complete'])

    def test_local_com_nome_de_direcao(self):
        r = conversa(['Localização: Rio Grande do Norte; fogo ativo: sim; direção do vento: sul; vento: 30 km/h; '
                      'umidade: 35%; secura da vegetação: 70%; declividade: 20%.'], 'fire')
        self.assertEqual(valores(r)['Direção do vento'], 'Sul')

    def test_direcao_antes_da_velocidade(self):
        r = conversa(['Local: Natal; fogo ativo: sim; direção do vento: norte; umidade: 35%; vento: 40 km/h; '
                      'secura: 80%; declividade: 10%'], 'fire')
        self.assertEqual(valores(r)['Velocidade do vento'], '40 km/h')

    def test_fora_da_faixa(self):
        r = conversa(['Local: X; fogo ativo: não; vento: 150 km/h; direção do vento: sul; umidade: 35%; '
                      'secura: 80%; declividade: 10%'], 'fire')
        self.assertFalse(r['complete'])


class AlagamentoTest(unittest.TestCase):
    def test_ordem_trocada(self):
        r = conversa(['Localização: Centro; chuva prevista: 40 mm; chuva acumulada: 60 mm; distância do rio: 500 m; '
                      'drenagem: ruim; piso vulnerável: térreo.'], 'flood')
        v = valores(r)
        self.assertEqual(v['Chuva acumulada nas últimas 24 h'], '60 mm')
        self.assertEqual(v['Chuva prevista nas próximas 24 h'], '40 mm')
        self.assertEqual(v['Condição da drenagem'], 'Ruim')

    def test_por_partes_e_correcao(self):
        r = conversa(['quero analisar alagamento', 'local: Bairro X', 'chuva acumulada 120 mm, chuva prevista 90 mm',
                      'distância do rio: 100 m; drenagem boa; subsolo', 'na verdade drenagem ruim'], 'flood')
        self.assertTrue(r['complete'])
        self.assertEqual(valores(r)['Condição da drenagem'], 'Ruim')


if __name__ == '__main__':
    unittest.main()
