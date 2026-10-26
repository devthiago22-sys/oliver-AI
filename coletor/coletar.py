"""Coletor de dados do Oliver para os municípios do Maranhão.

Roda de hora em hora no GitHub Actions (.github/workflows/coletar.yml) e gera
``saida/maranhao.json``, publicado no branch ``dados`` do repositório. O site
lê esse arquivo; assim ele não precisa acessar o INPE e o INMET diretamente.

Fontes:
  - INPE · Programa Queimadas (BDQueimadas): focos de calor do dia e do dia anterior,
    com dias sem chuva, precipitação e risco de fogo calculados pelo INPE.
  - INMET: estações automáticas (vento e umidade) e avisos meteorológicos ativos.
    A API de estações pode exigir token; defina o segredo INMET_TOKEN se tiver um.
  - Open-Meteo: fonte complementar de clima (modelos meteorológicos) quando o INMET
    não responde, e chuva das últimas/próximas 24 h e dias sem chuva.
  - IBGE (via lista pública de municípios com coordenadas): nomes, códigos e posição.

Só usa a biblioteca padrão do Python.
"""
import csv
import io
import json
import math
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UF_MA = 21
DIAS_HISTORICO = 7
BRT = timezone(timedelta(hours=-3))
SAIDA = os.environ.get('OLIVER_SAIDA', os.path.join(os.path.dirname(__file__), '..', 'saida', 'maranhao.json'))
DADOS_ANTERIORES = os.environ.get(
    'OLIVER_DADOS_ANTERIORES',
    'https://raw.githubusercontent.com/devthiago22-sys/oliver-AI/dados/maranhao.json')
MUNICIPIOS_CSV = 'https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv'
IBGE_MA = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/21/municipios'
INPE_FOCOS = 'https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/focos_diario_br_{data}.csv'
INMET_ESTACOES = 'https://apitempo.inmet.gov.br/estacao/dados/{data}/{hora}'
INMET_ESTACOES_TOKEN = 'https://apitempo.inmet.gov.br/token/estacao/dados/{data}/{hora}/{token}'
INMET_AVISOS = 'https://apiprevmet3.inmet.gov.br/avisos/ativos'
OPEN_METEO = 'https://api.open-meteo.com/v1/forecast'
OPEN_METEO_ELEVACAO = 'https://api.open-meteo.com/v1/elevation'
UA = {'User-Agent': 'Oliver-TCC/1.0 (projeto academico; github.com/devthiago22-sys/oliver-AI)'}

log_fontes = {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def baixar(url, timeout=40, tentativas=3):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            erro = e
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # rede instável: tenta de novo
            erro = e
        time.sleep(2 * (i + 1))
    raise erro


def baixar_json(url, **kw):
    return json.loads(baixar(url, **kw).decode('utf-8'))


def normalizar(txt):
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ascii', 'ignore').decode()
    return ' '.join(txt.lower().replace('-', ' ').replace("'", ' ').split())


def dist_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def lotes(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------------------
# Municípios (estático, reaproveitado entre execuções)
# ---------------------------------------------------------------------------
def carregar_municipios(anteriores):
    if anteriores and len(anteriores.get('municipios', {})) >= 200:
        base = {}
        for cod, m in anteriores['municipios'].items():
            base[cod] = {k: m[k] for k in ('codigo', 'nome', 'lat', 'lon', 'elevacao', 'declividade') if k in m}
        if all('declividade' in m for m in base.values()):
            log(f'municípios: {len(base)} reaproveitados da coleta anterior')
            return base

    texto = baixar(MUNICIPIOS_CSV).decode('utf-8')
    coords = {}
    for row in csv.DictReader(io.StringIO(texto)):
        if int(row['codigo_uf']) == UF_MA:
            coords[row['codigo_ibge']] = (row['nome'], float(row['latitude']), float(row['longitude']))
    nomes = {}
    try:
        for m in baixar_json(IBGE_MA):
            nomes[str(m['id'])] = m['nome']
        log_fontes['ibge'] = {'ok': True}
    except Exception as e:
        log('IBGE indisponível, usando nomes da lista de coordenadas:', e)
        log_fontes['ibge'] = {'ok': False, 'erro': str(e)[:200]}
    base = {}
    for cod, (nome, lat, lon) in coords.items():
        base[cod] = {'codigo': cod, 'nome': nomes.get(cod, nome), 'lat': round(lat, 5), 'lon': round(lon, 5)}
    log(f'municípios: {len(base)} carregados')
    calcular_declividade(base)
    return base


def calcular_declividade(base):
    """Declividade aproximada (%) em torno da sede: 5 pontos de elevação a ~2 km."""
    d = 0.018  # ~2 km em graus
    pontos = []
    for cod, m in base.items():
        for dlat, dlon in ((0, 0), (d, 0), (-d, 0), (0, d), (0, -d)):
            pontos.append((cod, m['lat'] + dlat, m['lon'] + dlon))
    elev = []
    for lote in lotes(pontos, 100):
        q = urllib.parse.urlencode({'latitude': ','.join(f'{p[1]:.4f}' for p in lote),
                                    'longitude': ','.join(f'{p[2]:.4f}' for p in lote)})
        elev += baixar_json(f'{OPEN_METEO_ELEVACAO}?{q}')['elevation']
        time.sleep(0.5)
    for i, cod in enumerate(base):
        c, n, s, e, w = elev[i * 5:(i + 1) * 5]
        dist = 2 * d * 111_000  # metros entre os pontos opostos
        grad = max(abs(n - s) / dist, abs(e - w) / (dist * math.cos(math.radians(base[cod]['lat']))))
        base[cod]['elevacao'] = round(c)
        base[cod]['declividade'] = round(min(100.0, grad * 100), 1)


# ---------------------------------------------------------------------------
# INPE · focos de calor
# ---------------------------------------------------------------------------
def coletar_focos(base, agora):
    por_nome = {normalizar(m['nome']): cod for cod, m in base.items()}
    focos = []
    erros = []
    dias = [(agora - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(DIAS_HISTORICO - 1, -1, -1)]
    for dia_txt in dias:
        dia = datetime.strptime(dia_txt, '%Y-%m-%d')
        url = INPE_FOCOS.format(data=dia.strftime('%Y%m%d'))
        try:
            texto = baixar(url, timeout=90).decode('utf-8', 'replace')
        except Exception as e:
            erros.append(f'{dia:%Y-%m-%d}: {e}')
            continue
        for row in csv.DictReader(io.StringIO(texto)):
            if normalizar(row.get('estado', '')) != 'maranhao':
                continue
            cod = str(row.get('municipio_id') or '').strip()
            if cod not in base:
                cod = por_nome.get(normalizar(row.get('municipio', '')))
            if not cod:
                continue

            def num(k):
                try:
                    v = float(row.get(k) or 'nan')
                    return None if math.isnan(v) or v < 0 else v  # INPE usa -999 para "sem valor"
                except ValueError:
                    return None
            focos.append({
                'id': row.get('id'), 'lat': float(row['lat']), 'lon': float(row['lon']),
                'data_hora_utc': row.get('data_hora_gmt'), 'satelite': row.get('satelite'),
                'municipio': cod, 'dias_sem_chuva': num('numero_dias_sem_chuva'),
                'precipitacao': num('precipitacao'), 'risco_fogo': num('risco_fogo'), 'frp': num('frp'),
                'bioma': row.get('bioma'), 'arquivo': dia_txt,
            })
    # O satélite geoestacionário (GOES) detecta o mesmo fogo a cada 10 minutos. Para contar
    # focos como uma pessoa entende, junta as detecções no mesmo local (~1 km) e guarda a
    # mais recente, com o número de detecções e os satélites que viram o fogo.
    unicos = {f['id']: f for f in focos if f['id']}

    # Histórico diário (7 dias): locais distintos com fogo por município e por dia.
    celulas = {}
    for f in unicos.values():
        celulas.setdefault((f['municipio'], f['arquivo']), set()).add((round(f['lat'], 2), round(f['lon'], 2)))
    historico = {}
    for (cod, dia_txt), locais_dia in celulas.items():
        historico.setdefault(cod, [0] * len(dias))[dias.index(dia_txt)] = len(locais_dia)
    total_dia = [sum(h[i] for h in historico.values()) for i in range(len(dias))]
    log(f'INPE histórico: focos por dia no MA {dict(zip(dias, total_dia))}')

    # Lista detalhada: só as últimas 48 h (arquivos de ontem e de hoje).
    unicos = {k: f for k, f in unicos.items() if f['arquivo'] >= dias[-2]}
    deteccoes = len(unicos)
    locais = {}
    for f in sorted(unicos.values(), key=lambda f: f['data_hora_utc'] or ''):
        chave = (f['municipio'], round(f['lat'], 2), round(f['lon'], 2))
        if chave in locais:
            antigo = locais[chave]
            f['deteccoes'] = antigo['deteccoes'] + 1
            f['primeira_utc'] = antigo['primeira_utc']
            f['satelites'] = sorted(set(antigo['satelites']) | {f['satelite']})
        else:
            f['deteccoes'], f['primeira_utc'], f['satelites'] = 1, f['data_hora_utc'], [f['satelite']]
        locais[chave] = f
    focos = sorted(locais.values(), key=lambda f: f['data_hora_utc'] or '', reverse=True)
    for f in focos:
        f['satelite'] = ', '.join(s for s in f.pop('satelites') if s)
    for f in focos:
        f.pop('arquivo', None)
    hoje_ok = not any(e.startswith(dias[-1]) or e.startswith(dias[-2]) for e in erros)
    log_fontes['inpe_focos'] = {'ok': hoje_ok, 'erros': erros, 'focos_ma_48h': len(focos), 'deteccoes_48h': deteccoes}
    log(f'INPE: {len(focos)} focos (locais distintos) e {deteccoes} detecções no Maranhão em 48 h', erros or '')

    limite_24h = (agora - timedelta(hours=24)).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    resumo = {}
    for f in focos:
        r = resumo.setdefault(f['municipio'], {'h24': 0, 'h48': 0, 'risco_inpe_max': None,
                                               'dias_sem_chuva_inpe': None, 'ultimo_utc': None})
        r['h48'] += 1
        if (f['data_hora_utc'] or '') >= limite_24h:
            r['h24'] += 1
        if f['risco_fogo'] is not None:
            r['risco_inpe_max'] = max(r['risco_inpe_max'] or 0, f['risco_fogo'])
        if f['dias_sem_chuva'] is not None:
            r['dias_sem_chuva_inpe'] = max(r['dias_sem_chuva_inpe'] or 0, f['dias_sem_chuva'])
        r['ultimo_utc'] = max(r['ultimo_utc'] or '', f['data_hora_utc'] or '')
    return focos, resumo, {'dias': dias, 'por_municipio': historico, 'total_estado': total_dia}


# ---------------------------------------------------------------------------
# INMET · estações automáticas e avisos
# ---------------------------------------------------------------------------
def coletar_inmet_estacoes(agora):
    token = os.environ.get('INMET_TOKEN', '').strip()
    utc = agora.astimezone(timezone.utc)
    erros = []
    for atraso in range(1, 5):  # os dados da hora cheia demoram a sair
        t = utc - timedelta(hours=atraso)
        data, hora = t.strftime('%Y-%m-%d'), t.strftime('%H00')
        url = (INMET_ESTACOES_TOKEN.format(data=data, hora=hora, token=token) if token
               else INMET_ESTACOES.format(data=data, hora=hora))
        try:
            dados = baixar_json(url, timeout=30, tentativas=2)
        except Exception as e:
            erros.append(f'{data} {hora}: {e}')
            if '403' in str(e) or '401' in str(e):
                break
            continue
        estacoes = []
        for d in dados if isinstance(dados, list) else []:
            try:
                if d.get('UF') not in ('MA', 'PI', 'TO', 'PA'):
                    continue
                vel = d.get('VEN_VEL')
                umd = d.get('UMD_INS')
                if vel in (None, '') or umd in (None, ''):
                    continue
                estacoes.append({
                    'codigo': d.get('CD_ESTACAO'), 'nome': d.get('DC_NOME'), 'uf': d.get('UF'),
                    'lat': float(d['VL_LATITUDE']), 'lon': float(d['VL_LONGITUDE']),
                    'vento_kmh': round(float(vel) * 3.6, 1),
                    'vento_dir': float(d['VEN_DIR']) if d.get('VEN_DIR') not in (None, '') else None,
                    'umidade': float(umd), 'medicao_utc': f"{data} {hora[:2]}:00",
                })
            except (KeyError, TypeError, ValueError):
                continue
        if estacoes:
            log_fontes['inmet_estacoes'] = {'ok': True, 'estacoes': len(estacoes), 'hora_utc': f'{data} {hora}'}
            log(f'INMET: {len(estacoes)} estações com dados ({data} {hora} UTC)')
            return estacoes
        erros.append(f'{data} {hora}: resposta sem estações')
    log_fontes['inmet_estacoes'] = {'ok': False, 'erros': erros[-3:]}
    log('INMET estações indisponível:', erros[-1:] if erros else '')
    return []


def coletar_inmet_avisos(base):
    codigos = set(base)
    por_mun = {}
    try:
        dados = baixar_json(INMET_AVISOS, timeout=30)
    except Exception as e:
        log_fontes['inmet_avisos'] = {'ok': False, 'erro': str(e)[:200]}
        log('INMET avisos indisponível:', e)
        return por_mun

    def visitar(no):
        if isinstance(no, dict):
            geos = no.get('geocodes') or no.get('geocode') or no.get('municipios')
            if geos and (no.get('descricao') or no.get('evento')):
                lista = geos if isinstance(geos, list) else str(geos).replace(';', ',').split(',')
                aviso = {
                    'evento': no.get('descricao') or no.get('evento'),
                    'severidade': no.get('severidade') or no.get('grau'),
                    'inicio': no.get('inicio') or no.get('data_inicio'),
                    'fim': no.get('fim') or no.get('data_fim'),
                    'riscos': no.get('riscos'), 'instrucoes': no.get('instrucoes'),
                }
                for g in lista:
                    g = str(g).strip()[:7]
                    if g in codigos:
                        por_mun.setdefault(g, []).append(aviso)
            for v in no.values():
                visitar(v)
        elif isinstance(no, list):
            for v in no:
                visitar(v)

    visitar(dados)
    log_fontes['inmet_avisos'] = {'ok': True, 'municipios_com_aviso': len(por_mun)}
    log(f'INMET avisos: {len(por_mun)} municípios do MA com aviso ativo')
    return por_mun


# ---------------------------------------------------------------------------
# Open-Meteo · clima complementar
# ---------------------------------------------------------------------------
def coletar_open_meteo(base):
    cods = list(base)
    atual, chuva, secos = {}, {}, {}
    for lote in lotes(cods, 50):
        lat = ','.join(str(base[c]['lat']) for c in lote)
        lon = ','.join(str(base[c]['lon']) for c in lote)
        q1 = urllib.parse.urlencode({
            'latitude': lat, 'longitude': lon, 'timezone': 'America/Fortaleza',
            'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m',
            'hourly': 'precipitation', 'past_hours': 24, 'forecast_hours': 24, 'wind_speed_unit': 'kmh',
        })
        r1 = baixar_json(f'{OPEN_METEO}?{q1}')
        r1 = r1 if isinstance(r1, list) else [r1]
        q2 = urllib.parse.urlencode({
            'latitude': lat, 'longitude': lon, 'timezone': 'America/Fortaleza',
            'daily': 'precipitation_sum', 'past_days': 60, 'forecast_days': 1,
        })
        r2 = baixar_json(f'{OPEN_METEO}?{q2}')
        r2 = r2 if isinstance(r2, list) else [r2]
        for cod, a, b in zip(lote, r1, r2):
            cur = a.get('current', {})
            atual[cod] = {'vento_kmh': cur.get('wind_speed_10m'), 'vento_dir': cur.get('wind_direction_10m'),
                          'umidade': cur.get('relative_humidity_2m'), 'temperatura': cur.get('temperature_2m'),
                          'hora_local': cur.get('time')}
            horas = a.get('hourly', {})
            tempos, prec = horas.get('time', []), horas.get('precipitation', [])
            agora_local = cur.get('time', '')
            passado = sum(p or 0 for t, p in zip(tempos, prec) if t <= agora_local)
            futuro = sum(p or 0 for t, p in zip(tempos, prec) if t > agora_local)
            chuva[cod] = {'chuva_24h': round(passado, 1), 'chuva_prev_24h': round(futuro, 1)}
            diarios = b.get('daily', {}).get('precipitation_sum', [])[:-1]  # sem o dia de hoje (incompleto)
            # Garoa de modelo (< 5 mm) não molha a vegetação de verdade: conta os dias seguidos abaixo disso.
            n = 0
            for p in reversed(diarios):
                if (p or 0) >= 5.0:
                    break
                n += 1
            datas = b.get('daily', {}).get('time', [])[:-1]
            secos[cod] = {'dias': n, 'chuva_30d': round(sum(p or 0 for p in diarios[-30:]), 1),
                          'chuva_7d': [round(p or 0, 1) for p in diarios[-7:]], 'datas_7d': datas[-7:]}
        time.sleep(1)
    log_fontes['open_meteo'] = {'ok': True, 'municipios': len(atual)}
    log(f'Open-Meteo: {len(atual)} municípios')
    return atual, chuva, secos


# ---------------------------------------------------------------------------
def main():
    agora = datetime.now(BRT)
    anteriores = None
    try:
        anteriores = baixar_json(DADOS_ANTERIORES, tentativas=1)
    except Exception as e:
        log('Sem coleta anterior (normal na primeira vez):', e)

    base = carregar_municipios(anteriores)
    focos, resumo_focos, historico = coletar_focos(base, agora)
    estacoes = coletar_inmet_estacoes(agora)
    avisos = coletar_inmet_avisos(base)
    try:
        om_atual, om_chuva, om_secos = coletar_open_meteo(base)
    except Exception as e:
        log('Open-Meteo indisponível:', e)
        log_fontes['open_meteo'] = {'ok': False, 'erro': str(e)[:200]}
        om_atual, om_chuva, om_secos = {}, {}, {}

    municipios = {}
    for cod, m in base.items():
        item = dict(m)
        clima = {}
        # vento e umidade: estação do INMET mais próxima (até 80 km), senão Open-Meteo
        est = min(estacoes, key=lambda e: dist_km(m['lat'], m['lon'], e['lat'], e['lon']), default=None)
        if est and dist_km(m['lat'], m['lon'], est['lat'], est['lon']) <= 80:
            clima.update({'vento_kmh': est['vento_kmh'], 'vento_dir': est['vento_dir'], 'umidade': est['umidade'],
                          'fonte_vento': 'INMET', 'estacao': est['nome'], 'estacao_codigo': est['codigo'],
                          'estacao_dist_km': round(dist_km(m['lat'], m['lon'], est['lat'], est['lon'])),
                          'medicao': est['medicao_utc'] + ' UTC'})
        elif cod in om_atual:
            a = om_atual[cod]
            clima.update({'vento_kmh': a['vento_kmh'], 'vento_dir': a['vento_dir'], 'umidade': a['umidade'],
                          'fonte_vento': 'Open-Meteo', 'medicao': (a['hora_local'] or '').replace('T', ' ') + ' (horário local)'})
        if cod in om_atual:
            clima['temperatura'] = om_atual[cod].get('temperatura')
        if cod in om_chuva:
            clima.update(om_chuva[cod])
            clima['fonte_chuva'] = 'Open-Meteo'
        rf = resumo_focos.get(cod)
        if rf and rf.get('dias_sem_chuva_inpe') is not None:
            clima['dias_sem_chuva'] = rf['dias_sem_chuva_inpe']
            clima['fonte_dias_sem_chuva'] = 'INPE'
        elif cod in om_secos:
            clima['dias_sem_chuva'] = om_secos[cod]['dias']
            clima['fonte_dias_sem_chuva'] = 'Open-Meteo'
        if cod in om_secos:
            clima['chuva_30d'] = om_secos[cod]['chuva_30d']
            clima['chuva_7d'] = om_secos[cod]['chuva_7d']
            clima['datas_chuva_7d'] = om_secos[cod]['datas_7d']
        item['clima'] = clima
        item['historico_focos'] = historico['por_municipio'].get(cod, [0] * len(historico['dias']))
        item['focos'] = rf or {'h24': 0, 'h48': 0, 'risco_inpe_max': None, 'dias_sem_chuva_inpe': None, 'ultimo_utc': None}
        item['avisos'] = avisos.get(cod, [])
        municipios[cod] = item

    saida = {
        'gerado_em': agora.isoformat(timespec='minutes'),
        'estado': 'Maranhão',
        'fontes': log_fontes,
        'municipios': municipios,
        'focos': focos,
        'historico_focos': {'dias': historico['dias'], 'total_estado': historico['total_estado']},
        'estacoes_inmet': [{k: e[k] for k in ('codigo', 'nome', 'uf', 'lat', 'lon')} for e in estacoes],
    }
    os.makedirs(os.path.dirname(os.path.abspath(SAIDA)), exist_ok=True)
    with open(SAIDA, 'w', encoding='utf-8') as f:
        json.dump(saida, f, ensure_ascii=False, separators=(',', ':'))
    log(f'OK: {SAIDA} ({os.path.getsize(SAIDA) // 1024} KB)')
    log(json.dumps(log_fontes, ensure_ascii=False, indent=1))
    if not municipios or not (log_fontes.get('inpe_focos', {}).get('ok') or log_fontes.get('open_meteo', {}).get('ok')):
        sys.exit(1)


if __name__ == '__main__':
    main()
