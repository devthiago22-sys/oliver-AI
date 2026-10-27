"""Exportação dos dados do Oliver para SIG (QGIS, ArcGIS, Google Earth).

Camadas:
  municipios  polígonos dos municípios (malha do IBGE) ou, sem a malha, pontos das sedes,
              com risco de fogo calculado pela rede neural, clima, focos e sinalização de 3 meses
  focos       pontos dos focos de calor das últimas 48 h (INPE)

Formatos (todos em WGS 84, EPSG:4326, longitude/latitude em graus):
  shp   Shapefile (.zip com .shp .shx .dbf .prj .cpg)  · ArcGIS, QGIS
  gpkg  GeoPackage (.gpkg, as duas camadas num arquivo) · QGIS, ArcGIS Pro
  geojson GeoJSON (.zip com um arquivo por camada)      · QGIS, web
  kml   KML (.kml)                                       · Google Earth
  csv   CSV (.zip) com latitude/longitude e geometria WKT · planilhas, QGIS

Só usa a biblioteca padrão do Python: os formatos são gravados aqui mesmo.
"""
import csv
import io
import json
import math
import os
import sqlite3
import struct
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from . import regional

BRT = timezone(timedelta(hours=-3))
MALHA_PATH = os.path.join(os.path.dirname(__file__), 'malha_ma.json')
FORMATOS = {
    'shp': ('Shapefile', '.zip', 'application/zip'),
    'gpkg': ('GeoPackage', '.gpkg', 'application/geopackage+sqlite3'),
    'geojson': ('GeoJSON', '.zip', 'application/zip'),
    'kml': ('KML', '.kml', 'application/vnd.google-earth.kml+xml'),
    'csv': ('CSV', '.zip', 'application/zip'),
}
PRJ_WGS84 = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
             'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')
WKT_4326 = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
            'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,'
            'AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]')

# (nome ≤ 10 letras, tipo C/N, tamanho, casas decimais, descrição)
CAMPOS_MUN = [
    ('cod_ibge', 'C', 7, 0, 'Código IBGE do município'),
    ('nome', 'C', 60, 0, 'Nome do município'),
    ('risco', 'C', 10, 0, 'Risco de propagação de fogo pela rede neural do Oliver: Baixo, Moderado ou Alto'),
    ('indice', 'N', 4, 0, 'Índice de risco de fogo, de 0 a 100'),
    ('p_baixo', 'N', 6, 1, 'Probabilidade da classe Baixo (%)'),
    ('p_moder', 'N', 6, 1, 'Probabilidade da classe Moderado (%)'),
    ('p_alto', 'N', 6, 1, 'Probabilidade da classe Alto (%)'),
    ('focos_24h', 'N', 6, 0, 'Focos de calor nas últimas 24 h (INPE, locais distintos)'),
    ('focos_48h', 'N', 6, 0, 'Focos de calor nas últimas 48 h (INPE, locais distintos)'),
    ('focos_7d', 'N', 6, 0, 'Focos de calor nos últimos 7 dias (INPE, locais distintos por dia)'),
    ('vento_kmh', 'N', 7, 1, 'Velocidade do vento (km/h)'),
    ('vento_dir', 'N', 5, 0, 'Direção de onde vem o vento (graus; 0 = norte, 90 = leste)'),
    ('vento_de', 'C', 9, 0, 'Direção de onde vem o vento (nome)'),
    ('umidade', 'N', 5, 0, 'Umidade relativa do ar (%)'),
    ('fte_vento', 'C', 10, 0, 'Fonte do vento e da umidade: INMET (estação) ou Open-Meteo'),
    ('dias_secos', 'N', 4, 0, 'Dias seguidos com menos de 5 mm de chuva'),
    ('chuva_24h', 'N', 7, 1, 'Chuva nas últimas 24 h (mm)'),
    ('chuva_prev', 'N', 7, 1, 'Chuva prevista para as próximas 24 h (mm)'),
    ('chuva_30d', 'N', 7, 1, 'Chuva nos últimos 30 dias (mm)'),
    ('secura', 'N', 5, 0, 'Secura estimada da vegetação (%)'),
    ('declive', 'N', 6, 1, 'Declividade do terreno em torno da sede (%)'),
    ('avisos', 'N', 3, 0, 'Número de avisos meteorológicos ativos do INMET'),
    ('aviso_txt', 'C', 160, 0, 'Avisos ativos do INMET (evento e severidade)'),
    ('m1_mes', 'C', 9, 0, 'Próximo mês'),
    ('m1_media', 'N', 8, 1, 'Média histórica de focos no próximo mês (INPE)'),
    ('m1_temp', 'C', 8, 0, 'Temporada de queimadas no próximo mês: Baixa, Média ou Alta'),
    ('m2_mes', 'C', 9, 0, 'Daqui a 2 meses'),
    ('m2_media', 'N', 8, 1, 'Média histórica de focos daqui a 2 meses (INPE)'),
    ('m2_temp', 'C', 8, 0, 'Temporada daqui a 2 meses'),
    ('m3_mes', 'C', 9, 0, 'Daqui a 3 meses'),
    ('m3_media', 'N', 8, 1, 'Média histórica de focos daqui a 3 meses (INPE)'),
    ('m3_temp', 'C', 8, 0, 'Temporada daqui a 3 meses'),
    ('pico', 'C', 30, 0, 'Meses com mais queimadas no histórico do INPE'),
    ('lat_sede', 'N', 10, 5, 'Latitude da sede do município'),
    ('lon_sede', 'N', 10, 5, 'Longitude da sede do município'),
    ('dados_em', 'C', 16, 0, 'Data e hora da coleta dos dados (horário de Brasília)'),
]
CAMPOS_FOCO = [
    ('municipio', 'C', 60, 0, 'Município do foco'),
    ('cod_ibge', 'C', 7, 0, 'Código IBGE do município'),
    ('data_utc', 'C', 16, 0, 'Última detecção (UTC)'),
    ('data_local', 'C', 16, 0, 'Última detecção (horário de Brasília)'),
    ('primeira', 'C', 16, 0, 'Primeira detecção nas 48 h (UTC)'),
    ('detec', 'N', 5, 0, 'Quantas vezes os satélites detectaram fogo nesse local'),
    ('satelite', 'C', 80, 0, 'Satélites que detectaram'),
    ('frp_mw', 'N', 9, 1, 'Potência radiativa do fogo (MW); quanto maior, mais intenso'),
    ('bioma', 'C', 20, 0, 'Bioma'),
    ('lat', 'N', 10, 5, 'Latitude'),
    ('lon', 'N', 10, 5, 'Longitude'),
]
CAMADAS = {'municipios': CAMPOS_MUN, 'focos': CAMPOS_FOCO}
_malha = {'dados': None, 'mtime': 0}


# ---------------------------------------------------------------------------
# Montagem das camadas
# ---------------------------------------------------------------------------
def carregar_malha():
    try:
        mtime = os.path.getmtime(MALHA_PATH)
    except OSError:
        return None
    if _malha['dados'] is None or mtime != _malha['mtime']:
        with open(MALHA_PATH, encoding='utf-8') as f:
            _malha.update(dados=json.load(f), mtime=mtime)
    return _malha['dados']


def _utc_para_brt(s):
    try:
        return (datetime.strptime(str(s)[:16], '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc).astimezone(BRT)
                .strftime('%Y-%m-%d %H:%M'))
    except ValueError:
        return ''


def montar(cidades=None, camadas=('municipios', 'focos')):
    """Devolve {camada: {'tipo': 'Point'|'MultiPolygon', 'feicoes': [(props, coords)]}} e metadados."""
    dados = regional.carregar_dados()
    if not dados:
        raise ValueError('Os dados oficiais não estão disponíveis agora. Tente de novo em alguns minutos.')
    mun = dados['municipios']
    cods = [c for c in (cidades or []) if c in mun] or list(mun)
    estado_todo = len(cods) == len(mun)
    gerado = dados.get('gerado_em', '').replace('T', ' ')[:16]
    malha = carregar_malha()
    usar_poligonos = bool(malha) and all(c in malha['municipios'] for c in cods)
    out = {}

    if 'municipios' in camadas:
        feicoes = []
        for cod in sorted(cods, key=lambda c: mun[c]['nome']):
            m = mun[cod]
            c = m.get('clima', {})
            f = m.get('focos', {})
            pred, e = regional.risco_fogo(m)
            saz = regional.sinalizacao(cod)
            prox = (saz or {}).get('proximos') or [{}, {}, {}]
            avisos = m.get('avisos') or []
            p = (pred or {}).get('probabilidades') or (pred or {}).get('probabilities') or {}
            props = {
                'cod_ibge': cod, 'nome': m['nome'], 'risco': (pred or {}).get('level'), 'indice': (pred or {}).get('score'),
                'p_baixo': p.get('Baixo'), 'p_moder': p.get('Moderado'), 'p_alto': p.get('Alto'),
                'focos_24h': f.get('h24', 0), 'focos_48h': f.get('h48', 0), 'focos_7d': sum(m.get('historico_focos') or []),
                'vento_kmh': c.get('vento_kmh'), 'vento_dir': c.get('vento_dir'),
                'vento_de': regional.compasso(c.get('vento_dir')), 'umidade': c.get('umidade'),
                'fte_vento': c.get('fonte_vento'), 'dias_secos': c.get('dias_sem_chuva'),
                'chuva_24h': c.get('chuva_24h'), 'chuva_prev': c.get('chuva_prev_24h'), 'chuva_30d': c.get('chuva_30d'),
                'secura': (e or {}).get('secura'), 'declive': m.get('declividade'),
                'avisos': len(avisos),
                'aviso_txt': '; '.join(f"{a.get('evento')} ({a.get('severidade') or '-'})" for a in avisos)[:160] or None,
                'pico': ' e '.join((saz or {}).get('meses_pico') or []) or None,
                'lat_sede': m['lat'], 'lon_sede': m['lon'], 'dados_em': gerado,
            }
            for k, pm in enumerate(prox[:3], start=1):
                props[f'm{k}_mes'] = pm.get('mes')
                props[f'm{k}_media'] = pm.get('media')
                props[f'm{k}_temp'] = pm.get('temporada')
            geo = malha['municipios'][cod] if usar_poligonos else [m['lon'], m['lat']]
            feicoes.append((props, geo))
        out['municipios'] = {'tipo': 'MultiPolygon' if usar_poligonos else 'Point', 'feicoes': feicoes}

    if 'focos' in camadas:
        sel = set(cods)
        sedes = [mun[c] for c in cods]
        feicoes = []
        for fo in dados.get('focos', []):
            if not estado_todo and fo.get('municipio') not in sel and \
                    not any(regional._dist(s, fo) <= 60 for s in sedes):
                continue
            props = {
                'municipio': mun.get(fo.get('municipio'), {}).get('nome'), 'cod_ibge': fo.get('municipio'),
                'data_utc': str(fo.get('data_hora_utc') or '')[:16], 'data_local': _utc_para_brt(fo.get('data_hora_utc')),
                'primeira': str(fo.get('primeira_utc') or '')[:16] or None, 'detec': fo.get('deteccoes', 1),
                'satelite': fo.get('satelite'), 'frp_mw': fo.get('frp'), 'bioma': fo.get('bioma'),
                'lat': fo['lat'], 'lon': fo['lon'],
            }
            feicoes.append((props, [fo['lon'], fo['lat']]))
        out['focos'] = {'tipo': 'Point', 'feicoes': feicoes}

    meta = {
        'gerado_em': gerado, 'estado_todo': estado_todo,
        'municipios': [mun[c]['nome'] for c in cods] if not estado_todo else ['Maranhão (217 municípios)'],
        'malha': malha.get('fonte') if usar_poligonos else None,
    }
    return out, meta


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------
def _area(anel):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anel, anel[1:])) / 2


def _orientar(anel, horario):
    """horario=True → sentido dos ponteiros do relógio (área negativa)."""
    return anel if (_area(anel) < 0) == horario else list(reversed(anel))


def _bbox(feicoes, tipo):
    xs, ys = [], []
    for _, g in feicoes:
        if tipo == 'Point':
            xs.append(g[0]); ys.append(g[1])
        else:
            for poly in g:
                for x, y in poly[0]:
                    xs.append(x); ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


def _geojson_geom(tipo, g):
    if tipo == 'Point':
        return {'type': 'Point', 'coordinates': g}
    # RFC 7946: anel externo anti-horário, buracos horários
    return {'type': 'MultiPolygon', 'coordinates': [[_orientar(a, i > 0) for i, a in enumerate(p)] for p in g]}


def _wkt(tipo, g):
    if tipo == 'Point':
        return f'POINT ({g[0]} {g[1]})'
    return 'MULTIPOLYGON (' + ', '.join('(' + ', '.join('(' + ', '.join(f'{x} {y}' for x, y in a) + ')' for a in p) + ')'
                                      for p in g) + ')'


def _wkb(tipo, g):
    if tipo == 'Point':
        return struct.pack('<BIdd', 1, 1, g[0], g[1])
    partes = [struct.pack('<BII', 1, 6, len(g))]
    for p in g:
        partes.append(struct.pack('<BII', 1, 3, len(p)))
        for a in p:
            partes.append(struct.pack('<I', len(a)))
            partes.append(b''.join(struct.pack('<dd', x, y) for x, y in a))
    return b''.join(partes)


# ---------------------------------------------------------------------------
# Escritores
# ---------------------------------------------------------------------------
def _limpo(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def escrever_geojson(nome, camada):
    fc = {'type': 'FeatureCollection', 'name': nome,
          'features': [{'type': 'Feature', 'properties': {k: _limpo(v) for k, v in p.items()},
                        'geometry': _geojson_geom(camada['tipo'], g)} for p, g in camada['feicoes']]}
    return json.dumps(fc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def escrever_csv(campos, camada):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in campos] + ['wkt'])
    for p, g in camada['feicoes']:
        w.writerow(['' if p.get(c[0]) is None else p.get(c[0]) for c in campos] + [_wkt(camada['tipo'], g)])
    return '﻿'.encode('utf-8') + buf.getvalue().encode('utf-8')


def _dbf(campos, linhas):
    hoje = datetime.now()
    n_campos = len(campos)
    tam_reg = 1 + sum(c[2] for c in campos)
    cab = struct.pack('<BBBBIHH20x', 3, hoje.year - 1900, hoje.month, hoje.day, len(linhas), 32 + 32 * n_campos + 1, tam_reg)
    desc = b''.join(struct.pack('<11sc4xBB14x', c[0].encode('ascii'), c[1].encode('ascii'), c[2], c[3]) for c in campos)
    regs = []
    for p in linhas:
        r = [b' ']
        for nome, tipo, tam, dec, _ in campos:
            v = _limpo(p.get(nome))
            if tipo == 'C':
                b = ('' if v is None else str(v)).encode('utf-8')[:tam]
                while b:  # não corta um caractere acentuado pela metade
                    try:
                        b.decode('utf-8')
                        break
                    except UnicodeDecodeError:
                        b = b[:-1]
                r.append(b.ljust(tam, b' '))
            else:
                if v is None or v == '':
                    s = ''
                else:
                    s = f'{float(v):.{dec}f}' if dec else str(int(round(float(v))))
                r.append(s.encode('ascii')[:tam].rjust(tam, b' '))
        regs.append(b''.join(r))
    return cab + desc + b'\r' + b''.join(regs) + b'\x1a'


def escrever_shapefile(campos, camada):
    """Devolve (shp, shx, dbf)."""
    tipo_shp = 1 if camada['tipo'] == 'Point' else 5
    conteudos = []
    for _, g in camada['feicoes']:
        if tipo_shp == 1:
            conteudos.append(struct.pack('<idd', 1, g[0], g[1]))
            continue
        aneis = []
        for poly in g:  # Shapefile: anel externo horário, buracos anti-horários
            aneis += [_orientar(a, i == 0) for i, a in enumerate(poly)]
        pts = [pt for a in aneis for pt in a]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        partes, acc = [], 0
        for a in aneis:
            partes.append(acc)
            acc += len(a)
        conteudos.append(struct.pack('<i4dii', 5, min(xs), min(ys), max(xs), max(ys), len(aneis), len(pts))
                         + struct.pack(f'<{len(partes)}i', *partes)
                         + b''.join(struct.pack('<dd', x, y) for x, y in pts))
    minx, miny, maxx, maxy = _bbox(camada['feicoes'], camada['tipo'])

    def cabecalho(tamanho_bytes):
        return (struct.pack('>i5ii', 9994, 0, 0, 0, 0, 0, tamanho_bytes // 2)
                + struct.pack('<ii4d4d', 1000, tipo_shp, minx, miny, maxx, maxy, 0, 0, 0, 0))

    registros, indice, offset = [], [], 100
    for i, c in enumerate(conteudos, start=1):
        registros.append(struct.pack('>ii', i, len(c) // 2) + c)
        indice.append(struct.pack('>ii', offset // 2, len(c) // 2))
        offset += 8 + len(c)
    shp = cabecalho(offset) + b''.join(registros)
    shx = cabecalho(100 + 8 * len(conteudos)) + b''.join(indice)
    dbf = _dbf(campos, [p for p, _ in camada['feicoes']])
    return shp, shx, dbf


def escrever_geopackage(camadas):
    fd, caminho = tempfile.mkstemp(suffix='.gpkg')
    os.close(fd)
    try:
        con = sqlite3.connect(caminho)
        con.execute('PRAGMA application_id = 1196444487')  # "GPKG"
        con.execute('PRAGMA user_version = 10300')
        con.executescript('''
            CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
              organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
            CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
              description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
              min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
              CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
            CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,
              geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
              CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
              CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
              CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
        ''')
        con.executemany('INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)', [
            ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined', 'undefined cartesian coordinate reference system'),
            ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined', 'undefined geographic coordinate reference system'),
            ('WGS 84 geodetic', 4326, 'EPSG', 4326, WKT_4326, 'longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid'),
        ])
        for nome, (campos, camada) in camadas.items():
            tipo_sql = 'POINT' if camada['tipo'] == 'Point' else 'MULTIPOLYGON'
            colunas = ', '.join(f'"{c[0]}" {"TEXT" if c[1] == "C" else ("REAL" if c[3] else "INTEGER")}' for c in campos)
            con.execute(f'CREATE TABLE "{nome}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom {tipo_sql}, {colunas})')
            minx, miny, maxx, maxy = _bbox(camada['feicoes'], camada['tipo'])
            con.execute('INSERT INTO gpkg_contents (table_name, data_type, identifier, description, min_x, min_y, max_x, max_y, srs_id) '
                        'VALUES (?,?,?,?,?,?,?,?,4326)',
                        (nome, 'features', nome, 'Oliver · ' + nome, minx, miny, maxx, maxy))
            con.execute('INSERT INTO gpkg_geometry_columns VALUES (?,?,?,4326,0,0)', (nome, 'geom', tipo_sql))
            linhas = []
            for p, g in camada['feicoes']:
                if camada['tipo'] == 'Point':
                    env = (g[0], g[0], g[1], g[1])
                else:
                    xs = [x for poly in g for x, _ in poly[0]]
                    ys = [y for poly in g for _, y in poly[0]]
                    env = (min(xs), max(xs), min(ys), max(ys))
                blob = b'GP' + struct.pack('<BBi4d', 0, 0b00000011, 4326, *env) + _wkb(camada['tipo'], g)
                linhas.append([sqlite3.Binary(blob)] + [_limpo(p.get(c[0])) for c in campos])
            marcas = ', '.join('?' * (len(campos) + 1))
            nomes = ', '.join(['geom'] + [f'"{c[0]}"' for c in campos])
            con.executemany(f'INSERT INTO "{nome}" ({nomes}) VALUES ({marcas})', linhas)
        con.commit()
        con.close()
        with open(caminho, 'rb') as f:
            return f.read()
    finally:
        os.unlink(caminho)


KML_CORES = {'Baixo': 'ff4f7c3e', 'Moderado': 'ff0f82b8', 'Alto': 'ff1a3ab2', None: 'ff888888'}  # aabbggrr


def escrever_kml(camadas, meta):
    def coords(anel):
        return ' '.join(f'{x},{y},0' for x, y in anel)

    def extended(campos, p):
        return '<ExtendedData>' + ''.join(
            f'<Data name="{c[0]}"><displayName>{escape(c[4])}</displayName><value>{escape("" if p.get(c[0]) is None else str(p.get(c[0])))}</value></Data>'
            for c in campos) + '</ExtendedData>'

    estilos = ''.join(
        f'<Style id="risco_{n or "sem"}"><LineStyle><color>ff3a2b1d</color><width>1</width></LineStyle>'
        f'<PolyStyle><color>{"8c" + cor[2:]}</color></PolyStyle><IconStyle><color>{cor}</color></IconStyle></Style>'
        for n, cor in KML_CORES.items())
    estilos += ('<Style id="foco"><IconStyle><color>ff1f6aef</color><scale>0.7</scale><Icon>'
                '<href>http://maps.google.com/mapfiles/kml/shapes/firedept.png</href></Icon></IconStyle></Style>')
    pastas = []
    if 'municipios' in camadas:
        campos, cam = camadas['municipios']
        pms = []
        for p, g in cam['feicoes']:
            if cam['tipo'] == 'Point':
                geo = f'<Point><coordinates>{g[0]},{g[1]},0</coordinates></Point>'
            else:
                polys = ''.join(
                    '<Polygon><outerBoundaryIs><LinearRing><coordinates>' + coords(poly[0]) + '</coordinates></LinearRing></outerBoundaryIs>'
                    + ''.join('<innerBoundaryIs><LinearRing><coordinates>' + coords(h) + '</coordinates></LinearRing></innerBoundaryIs>' for h in poly[1:])
                    + '</Polygon>' for poly in g)
                geo = f'<MultiGeometry>{polys}</MultiGeometry>'
            desc = (f"Risco de fogo: {p.get('risco') or '-'} ({p.get('indice') if p.get('indice') is not None else '-'}/100). "
                    f"Focos 24 h: {p.get('focos_24h')}; 7 dias: {p.get('focos_7d')}.")
            pms.append(f'<Placemark><name>{escape(str(p["nome"]))}</name><description>{escape(desc)}</description>'
                       f'<styleUrl>#risco_{p.get("risco") or "sem"}</styleUrl>{extended(campos, p)}{geo}</Placemark>')
        pastas.append('<Folder><name>Municípios · risco de fogo</name>' + ''.join(pms) + '</Folder>')
    if 'focos' in camadas:
        campos, cam = camadas['focos']
        pms = [f'<Placemark><name>Foco · {escape(str(p.get("municipio") or ""))}</name>'
               f'<TimeStamp><when>{escape(str(p.get("data_utc") or "").replace(" ", "T"))}:00Z</when></TimeStamp>'
               f'<styleUrl>#foco</styleUrl>{extended(campos, p)}<Point><coordinates>{g[0]},{g[1]},0</coordinates></Point></Placemark>'
               for p, g in cam['feicoes']]
        pastas.append('<Folder><name>Focos de calor (48 h, INPE)</name>' + ''.join(pms) + '</Folder>')
    doc = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f'<name>Oliver · Maranhão · {escape(meta["gerado_em"])}</name>'
           f'<description>{escape(leiame(camadas, meta, "kml"))}</description>{estilos}{"".join(pastas)}</Document></kml>')
    return doc.encode('utf-8')


def leiame(camadas, meta, formato):
    linhas = [
        'OLIVER · DADOS GEORREFERENCIADOS · MARANHÃO',
        '',
        f'Dados coletados em: {meta["gerado_em"]} (horário de Brasília)',
        f'Abrangência: {", ".join(meta["municipios"])}',
        'Sistema de referência: WGS 84 (EPSG:4326), longitude e latitude em graus decimais.',
        f'Formato: {FORMATOS[formato][0]}',
        '',
        'CAMADAS',
    ]
    if 'municipios' in camadas:
        tipo = 'polígonos' if camadas['municipios'][1]['tipo'] == 'MultiPolygon' else 'pontos das sedes municipais'
        linhas.append(f'- municipios: {len(camadas["municipios"][1]["feicoes"])} feições ({tipo}).'
                      + (f' Contornos: {meta["malha"]}, simplificados (~150 m).' if meta.get('malha') else ''))
    if 'focos' in camadas:
        linhas.append(f'- focos: {len(camadas["focos"][1]["feicoes"])} focos de calor das últimas 48 h (pontos). '
                      'Detecções repetidas no mesmo local (~1 km) foram agrupadas.')
    for nome, (campos, _) in camadas.items():
        linhas += ['', f'CAMPOS · {nome}'] + [f'  {c[0]:<11}{c[4]}' for c in campos]
    linhas += [
        '', 'FONTES',
        '- Focos de calor: INPE · Programa Queimadas (BDQueimadas).',
        '- Avisos meteorológicos: INMET.',
        '- Vento e umidade: estação automática do INMET mais próxima (até 80 km) ou Open-Meteo.',
        '- Chuva, dias secos, chuva de 30 dias e declividade: Open-Meteo (modelos meteorológicos e Copernicus DEM).',
        '- Sinalização de 3 meses: média mensal de focos do INPE (satélite de referência, 2015 em diante).',
        '- Municípios e códigos: IBGE.',
        '',
        'AVISO: protótipo acadêmico (TCC). O risco é uma triagem feita por uma rede neural treinada com dados sintéticos',
        'e não substitui os alertas da Defesa Civil, do INPE, do INMET ou do Cemaden.',
    ]
    if formato == 'shp':
        linhas += ['', 'Shapefile: os arquivos .dbf estão em UTF-8 (indicado no .cpg).']
    if formato == 'csv':
        linhas += ['', 'CSV: separador vírgula, ponto decimal, UTF-8. No QGIS: Camada > Adicionar camada > Texto delimitado,',
                   'geometria pela coluna "wkt" (ou pelas colunas de latitude/longitude), SRC EPSG:4326.']
    return '\n'.join(linhas)


def exportar(formato, cidades=None, camadas=('municipios', 'focos')):
    """Devolve (bytes, nome_do_arquivo, mimetype)."""
    if formato not in FORMATOS:
        raise ValueError('Formato desconhecido. Use shp, gpkg, geojson, kml ou csv.')
    camadas = [c for c in camadas if c in CAMADAS] or ['municipios', 'focos']
    dados_camadas, meta = montar(cidades, camadas)
    pares = {nome: (CAMADAS[nome], dados_camadas[nome]) for nome in camadas}
    carimbo = datetime.now(BRT).strftime('%Y-%m-%d-%H%M')
    sufixo = 'maranhao' if meta['estado_todo'] else (
        regional.normalizar(meta['municipios'][0]).strip().replace(' ', '-') if len(meta['municipios']) == 1 else
        f'{len(meta["municipios"])}-municipios')
    base = f'oliver-sig-{sufixo}-{carimbo}'
    _, ext, mime = FORMATOS[formato]

    if formato == 'gpkg':
        return escrever_geopackage(pares), base + ext, mime
    if formato == 'kml':
        return escrever_kml(pares, meta), base + ext, mime
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('LEIAME.txt', leiame(pares, meta, formato).encode('utf-8'))
        for nome, (campos, cam) in pares.items():
            if formato == 'geojson':
                z.writestr(f'{nome}.geojson', escrever_geojson(nome, cam))
            elif formato == 'csv':
                z.writestr(f'{nome}.csv', escrever_csv(campos, cam))
            else:
                shp, shx, dbf = escrever_shapefile(campos, cam)
                z.writestr(f'{nome}.shp', shp)
                z.writestr(f'{nome}.shx', shx)
                z.writestr(f'{nome}.dbf', dbf)
                z.writestr(f'{nome}.prj', PRJ_WGS84)
                z.writestr(f'{nome}.cpg', 'UTF-8')
    return buf.getvalue(), base + ext, mime
