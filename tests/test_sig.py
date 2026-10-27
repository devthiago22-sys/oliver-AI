"""Testes da exportação para SIG: cada formato abre e tem as feições esperadas."""
import io
import json
import os
import sqlite3
import struct
import tempfile
import unittest
import zipfile

from tests.test_regional import DADOS


class SigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(DADOS, cls.tmp, ensure_ascii=False)
        cls.tmp.close()
        from oliver import regional, sig
        regional.DADOS_URL = 'http://127.0.0.1:9/indisponivel'
        regional.DADOS_LOCAL = cls.tmp.name
        regional.carregar_dados(forcar=True)
        # malha de teste: São Luís com um buraco, Barra do Corda com duas partes
        cls.malha = {'fonte': 'teste', 'municipios': {
            '2111300': [[[[-44.4, -2.6], [-44.2, -2.6], [-44.2, -2.4], [-44.4, -2.4], [-44.4, -2.6]],
                         [[-44.35, -2.55], [-44.35, -2.5], [-44.3, -2.5], [-44.3, -2.55], [-44.35, -2.55]]]],
            '2101608': [[[[-45.3, -5.6], [-45.3, -5.4], [-45.1, -5.4], [-45.1, -5.6], [-45.3, -5.6]]],
                        [[[-45.0, -5.6], [-45.0, -5.5], [-44.9, -5.5], [-44.9, -5.6], [-45.0, -5.6]]]],
            '2111201': [[[[-44.1, -2.6], [-44.0, -2.6], [-44.0, -2.5], [-44.1, -2.5], [-44.1, -2.6]]]],
        }}
        cls.sig = sig
        cls.original = sig.carregar_malha
        sig.carregar_malha = lambda: cls.malha

    @classmethod
    def tearDownClass(cls):
        cls.sig.carregar_malha = cls.original
        os.unlink(cls.tmp.name)

    def test_shapefile(self):
        dado, nome, _ = self.sig.exportar('shp', ['2111300', '2101608'])
        self.assertTrue(nome.endswith('.zip'))
        z = zipfile.ZipFile(io.BytesIO(dado))
        shp, shx, dbf = z.read('municipios.shp'), z.read('municipios.shx'), z.read('municipios.dbf')
        self.assertEqual(struct.unpack('>i', shp[:4])[0], 9994)
        self.assertEqual(struct.unpack('>i', shp[24:28])[0] * 2, len(shp))
        self.assertEqual(struct.unpack('<i', shp[32:36])[0], 5)              # polígono
        self.assertEqual(len(shx), 100 + 8 * 2)
        self.assertEqual(struct.unpack('<I', dbf[4:8])[0], 2)                 # 2 registros
        self.assertEqual(z.read('municipios.cpg'), b'UTF-8')
        self.assertIn(b'WGS_1984', z.read('focos.prj'))

    def test_geopackage(self):
        dado, _, _ = self.sig.exportar('gpkg')
        fd, caminho = tempfile.mkstemp(suffix='.gpkg')
        os.write(fd, dado)
        os.close(fd)
        try:
            con = sqlite3.connect(caminho)
            self.assertEqual(con.execute('PRAGMA application_id').fetchone()[0], 0x47504B47)
            camadas = dict(con.execute('SELECT table_name, geometry_type_name FROM gpkg_geometry_columns'))
            self.assertEqual(camadas, {'municipios': 'MULTIPOLYGON', 'focos': 'POINT'})
            self.assertEqual(con.execute('SELECT count(*) FROM municipios').fetchone()[0], 3)
            risco = con.execute("SELECT risco FROM municipios WHERE nome = 'Barra do Corda'").fetchone()[0]
            self.assertIn(risco, ('Baixo', 'Moderado', 'Alto'))
            con.close()
        finally:
            os.unlink(caminho)

    def test_geojson_orientacao(self):
        dado, _, _ = self.sig.exportar('geojson', ['2111300'])
        gj = json.loads(zipfile.ZipFile(io.BytesIO(dado)).read('municipios.geojson'))
        aneis = gj['features'][0]['geometry']['coordinates'][0]
        area = lambda a: sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(a, a[1:]))
        self.assertGreater(area(aneis[0]), 0)   # externo anti-horário
        self.assertLess(area(aneis[1]), 0)      # buraco horário

    def test_kml_e_csv(self):
        kml, _, _ = self.sig.exportar('kml', ['2101608'])
        self.assertIn(b'<kml', kml)
        self.assertEqual(kml.count(b'<Polygon>'), 2)
        dado, _, _ = self.sig.exportar('csv', ['2101608'])
        texto = zipfile.ZipFile(io.BytesIO(dado)).read('focos.csv').decode('utf-8-sig')
        self.assertIn('POINT (-45.2 -5.45)', texto)

    def test_conversa_pede_sig(self):
        from oliver.chat import assistant
        r = assistant({'message': 'quero os dados de barra do corda em shapefile para o qgis', 'state': {}})
        self.assertEqual(r['sig']['auto'], {'formato': 'shp', 'escopo': 'cidades', 'cidades': ['2101608']})


if __name__ == '__main__':
    unittest.main()
