"""Oliver regional: conversa simples sobre um município do Maranhão.

A pessoa diz a cidade (e, para alagamento, responde três perguntas sobre o
imóvel). O Oliver busca os dados que o coletor juntou de órgãos oficiais
(INPE, INMET) e de uma fonte complementar (Open-Meteo), passa pela rede
neural e devolve a análise.
"""
import json
import math
from datetime import datetime, timedelta, timezone
import os
import threading
import time
import unicodedata
import urllib.request

from .neural import NEURAL_AI

DADOS_URL = os.environ.get('OLIVER_DADOS_URL', 'https://raw.githubusercontent.com/devthiago22-sys/oliver-AI/dados/maranhao.json')
DADOS_LOCAL = os.environ.get('OLIVER_DADOS_LOCAL', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saida', 'maranhao.json'))
CACHE_SEGUNDOS = 600
BRT = timezone(timedelta(hours=-3))

FONTES = {
    'INPE': ('INPE · Programa Queimadas (BDQueimadas)', 'https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/'),
    'INMET': ('INMET · Instituto Nacional de Meteorologia', 'https://portal.inmet.gov.br/'),
    'Open-Meteo': ('Open-Meteo (modelos meteorológicos; fonte complementar)', 'https://open-meteo.com/'),
    'IBGE': ('IBGE · municípios e códigos', 'https://www.ibge.gov.br/'),
}
CLASSES_INPE = ((0.15, 'mínimo'), (0.40, 'baixo'), (0.70, 'médio'), (0.95, 'alto'), (9, 'crítico'))
DIRECOES = ('norte', 'nordeste', 'leste', 'sudeste', 'sul', 'sudoeste', 'oeste', 'noroeste')

_cache = {'dados': None, 'em': 0.0}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def carregar_dados(forcar=False):
    with _lock:
        if _cache['dados'] and not forcar and time.time() - _cache['em'] < CACHE_SEGUNDOS:
            return _cache['dados']
        dados = None
        try:
            req = urllib.request.Request(f"{DADOS_URL}?t={int(time.time() // 300)}", headers={'User-Agent': 'Oliver-TCC'})
            with urllib.request.urlopen(req, timeout=15) as r:
                dados = json.loads(r.read().decode('utf-8'))
        except Exception:
            if os.path.exists(DADOS_LOCAL):
                with open(DADOS_LOCAL, encoding='utf-8') as f:
                    dados = json.load(f)
        if dados:
            _cache.update(dados=dados, em=time.time())
            _indice.clear()
        return _cache['dados']


def normalizar(txt):
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ascii', 'ignore').decode()
    return ' ' + ' '.join(''.join(c if c.isalnum() else ' ' for c in txt.lower()).split()) + ' '


_indice = []


def indice_municipios(dados):
    if not _indice:
        for cod, m in dados['municipios'].items():
            _indice.append((normalizar(m['nome']), cod))
        _indice.sort(key=lambda x: -len(x[0]))
    return _indice


APELIDOS = {' slz ': ' sao luis ', ' ribamar ': ' sao jose de ribamar ', ' imperatris ': ' imperatriz '}
# Palavras comuns da conversa que nunca devem ser confundidas com nome de cidade.
PALAVRAS_CONVERSA = set('''risco riscos queimada queimadas fogo fogos incendio alagamento alagamentos enchente chuva cidade
cidades municipio municipios estado estados maranhao quero saber ver tambem agora hoje como esta qual quais tem perigo
predio casa imovel relatorio pdf junto juntar ficar substituir adicionar remover tirar sim nao obrigado oi ola bom dia
tarde noite mais menos perto longe rua andar subsolo terreo apartamento vezes sempre nunca sei
minha meu minhas meus onde moro regiao cidade'''.split())


def achar_municipios(texto, dados):
    """Encontra os municípios citados no texto.

    Devolve (códigos encontrados em ordem, sugestão). Primeiro procura o nome exato
    (sem acento e sem maiúsculas); o nome mais longo vence ("São José de Ribamar" antes
    de "São José"). Se não achar nada, tenta nomes parecidos ("Santo Inês" → Santa Inês):
    muito parecido é aceito direto; meio parecido volta como sugestão para confirmar.
    """
    import difflib
    t = normalizar(texto)
    for apelido, nome in APELIDOS.items():
        t = t.replace(apelido, nome)
    achados, resto = [], t
    for nome, cod in indice_municipios(dados):
        pos = resto.find(nome)
        if pos >= 0:
            achados.append((pos, cod))
            resto = resto[:pos] + ' ' + '#' * (len(nome) - 2) + ' ' + resto[pos + len(nome):]
    if achados:
        return [cod for _, cod in sorted(achados)], None

    # Nomes parecidos: compara só o "miolo" do nome. "do Maranhão" aparece em muitos nomes
    # e na conversa ("como está o Maranhão"), então não pode contar como semelhança.
    palavras = [p for p in t.split() if p != 'maranhao']
    melhor, nota = None, 0.0
    for nome, cod in indice_municipios(dados):
        alvo = nome.replace(' do maranhao ', ' ').replace(' maranhao ', ' ').strip()
        if len(alvo) < 4:
            continue
        n = len(alvo.split())
        for i in range(len(palavras) - n + 1):
            trecho = palavras[i:i + n]
            if all(p in PALAVRAS_CONVERSA for p in trecho):
                continue
            janela = ' '.join(trecho)
            if abs(len(janela) - len(alvo)) > 3:
                continue
            r = difflib.SequenceMatcher(None, janela, alvo).ratio()
            if r > nota:
                melhor, nota = cod, r
    if melhor and nota >= 0.88:
        return [melhor], None
    if melhor and nota >= 0.75 and len(dados['municipios'][melhor]['nome']) >= 5:
        return [], melhor
    return [], None


def achar_municipio(texto, dados):
    cods, _ = achar_municipios(texto, dados)
    return cods[0] if cods else None


def compasso(graus):
    if graus is None:
        return None
    return DIRECOES[int(((graus % 360) + 22.5) // 45) % 8]


def oposto(direcao):
    return DIRECOES[(DIRECOES.index(direcao) + 4) % 8] if direcao else None


def classe_inpe(v):
    if v is None:
        return None
    for limite, nome in CLASSES_INPE:
        if v < limite:
            return nome
    return 'crítico'


def secura_vegetacao(clima):
    """Secura da vegetação (%), o maior valor entre duas estimativas:
    - dias seguidos sem chuva relevante (< 5 mm/dia): 0 dia → 10 %, 45 dias ou mais → 100 %;
    - chuva dos últimos 30 dias: 0 mm → 100 %, 150 mm ou mais → 0 %."""
    por_dias = 10 + float(clima.get('dias_sem_chuva') or 0) * 2
    por_30d = 100 * (1 - min(1.0, float(clima['chuva_30d']) / 150)) if clima.get('chuva_30d') is not None else 0
    return round(max(0.0, min(100.0, max(por_dias, por_30d))), 1)


def fmt(v, casas=1):
    if v is None:
        return 'sem dado'
    return f'{v:.{casas}f}'.replace('.', ',')


def hora_dados(dados):
    try:
        return dados['gerado_em'].replace('T', ' ')[:16].split(' ')
    except Exception:
        return ['', '']


def data_br(iso):
    """'2026-10-26 13:17' → '26/10/2026 às 13:17'"""
    try:
        d, h = iso.replace('T', ' ')[:16].split(' ')
        a, m, dia = d.split('-')
        return f'{dia}/{m}/{a} às {h}'
    except Exception:
        return iso


# ---------------------------------------------------------------------------
# Análises
# ---------------------------------------------------------------------------
def entradas_fogo(m):
    c = m.get('clima', {})
    vento, umidade, dias = c.get('vento_kmh'), c.get('umidade'), c.get('dias_sem_chuva')
    if vento is None or umidade is None or dias is None:
        return None
    return {
        'vento': max(0.0, min(100.0, float(vento))),
        'umidade': max(0.0, min(100.0, float(umidade))),
        'secura': secura_vegetacao(c),
        'declividade': max(0.0, min(100.0, float(m.get('declividade') or 0))),
    }


def risco_fogo(m):
    e = entradas_fogo(m)
    if not e:
        return None, None
    return NEURAL_AI.classify_fire(e['vento'], e['umidade'], e['secura'], e['declividade']), e


def _linhas_prob(pred):
    return [{'metric': f'Probabilidade · {k}', 'value': f'{v:.1f}%', 'risk': k,
             'explanation': 'Probabilidade de classe retornada pelo Oliver Neural Engine.'} for k, v in pred['probabilities'].items()]


def _fonte_txt(fonte, extra=''):
    return f'Fonte: {fonte}{extra}.'


def analise_fogo(cod, dados):
    m = dados['municipios'][cod]
    c, f = m.get('clima', {}), m.get('focos', {})
    pred, e = risco_fogo(m)
    if not pred:
        return None
    direcao = compasso(c.get('vento_dir'))
    estacao = f" (estação {c['estacao']}, a {c.get('estacao_dist_km')} km)" if c.get('fonte_vento') == 'INMET' and c.get('estacao') else ''
    rows = [
        {'metric': 'Município', 'value': f"{m['nome']} – MA", 'risk': 'Indeterminado', 'explanation': _fonte_txt('IBGE')},
        {'metric': 'Focos de calor (últimas 24 h)', 'value': str(f.get('h24', 0)), 'risk': 'Alto' if f.get('h24') else 'Baixo',
         'explanation': _fonte_txt('INPE · BDQueimadas', f" · {f.get('h48', 0)} nas últimas 48 h")},
        {'metric': 'Velocidade do vento', 'value': f"{fmt(c.get('vento_kmh'))} km/h", 'risk': 'Indeterminado',
         'explanation': _fonte_txt(c.get('fonte_vento', '-'), estacao)},
        {'metric': 'Direção do vento', 'value': f"de {direcao}" if direcao else 'sem dado', 'risk': 'Indeterminado',
         'explanation': (f'Um fogo tenderia a avançar para o {oposto(direcao)}. ' if direcao else '') + _fonte_txt(c.get('fonte_vento', '-'))},
        {'metric': 'Umidade relativa do ar', 'value': f"{fmt(c.get('umidade'), 0)} %", 'risk': 'Indeterminado',
         'explanation': _fonte_txt(c.get('fonte_vento', '-'), estacao)},
        {'metric': 'Dias seguidos sem chuva relevante', 'value': fmt(c.get('dias_sem_chuva'), 0), 'risk': 'Indeterminado',
         'explanation': _fonte_txt(c.get('fonte_dias_sem_chuva', '-'), ' · dias com menos de 5 mm de chuva')},
        {'metric': 'Chuva nos últimos 30 dias', 'value': f"{fmt(c.get('chuva_30d'))} mm" if c.get('chuva_30d') is not None else 'sem dado', 'risk': 'Indeterminado',
         'explanation': _fonte_txt('Open-Meteo')},
        {'metric': 'Secura estimada da vegetação', 'value': f"{fmt(e['secura'], 0)} %", 'risk': 'Indeterminado',
         'explanation': 'Calculada pelo Oliver a partir dos dias sem chuva e da chuva dos últimos 30 dias.'},
        {'metric': 'Declividade do terreno', 'value': f"{fmt(m.get('declividade'))} %", 'risk': 'Indeterminado',
         'explanation': 'Estimada pela elevação em torno da sede do município (Open-Meteo / Copernicus DEM).'},
    ]
    if f.get('risco_inpe_max') is not None:
        rows.append({'metric': 'Risco de fogo calculado pelo INPE', 'value': f"{fmt(f['risco_inpe_max'], 2)} ({classe_inpe(f['risco_inpe_max'])})",
                     'risk': 'Indeterminado', 'explanation': _fonte_txt('INPE', ' · maior valor entre os focos do município, escala 0 a 1')})
    for a in m.get('avisos', [])[:3]:
        rows.append({'metric': 'Aviso meteorológico ativo', 'value': str(a.get('evento')), 'risk': 'Alto',
                     'explanation': _fonte_txt('INMET', f" · severidade {a.get('severidade') or '-'}")})
    rows.append({'metric': 'Risco estimado de propagação', 'value': f"{pred['score']}/100", 'risk': pred['level'],
                 'explanation': 'Classificação da rede neural do Oliver com os dados acima.'})
    rows += _linhas_prob(pred)

    focos_txt = (f"Há {f['h24']} foco(s) de calor registrado(s) pelo INPE nas últimas 24 horas."
                 if f.get('h24') else 'O INPE não registrou focos de calor no município nas últimas 24 horas.')
    vento_txt = f"vento de {fmt(c.get('vento_kmh'), 0)} km/h vindo do {direcao}" if direcao else f"vento de {fmt(c.get('vento_kmh'), 0)} km/h"
    reply = (f"Em {m['nome']}, o risco de propagação de fogo agora é {pred['level'].lower()} (índice {pred['score']}/100). "
             f"{focos_txt} As condições usadas foram {vento_txt}, umidade de {fmt(c.get('umidade'), 0)} % "
             f"e {fmt(c.get('chuva_30d'), 0)} mm de chuva nos últimos 30 dias (vegetação {fmt(e['secura'], 0)} % seca).")
    if f.get('h24') and pred['level'] == 'Baixo':
        reply += ' Mesmo com risco baixo de o fogo se espalhar, há focos ativos na região: não é hora de queimar nada.'
    saz = sinalizacao(cod)
    reply += texto_sinalizacao(saz, f"em {m['nome']}")
    acoes = ['Não use fogo para limpar terreno ou queimar lixo, principalmente com o tempo seco.']
    if f.get('h24'):
        acoes.insert(0, 'Se vir fogo ou fumaça perto de casas ou da mata, ligue 193 (Bombeiros).')
    if pred['level'] == 'Alto':
        acoes.append('Mantenha aceiros limpos em volta de roças, cercas e casas.')
    acoes.append('Acompanhe os alertas oficiais da Defesa Civil (199) e do INPE.')
    r = _resultado('fire', m, dados, pred, rows, reply, acoes, fontes=['INPE', c.get('fonte_vento'), c.get('fonte_dias_sem_chuva'), 'IBGE'])
    r['regional']['sazonal'] = saz
    return r


IMOVEL = {'subsolo': ('Prédio com subsolo ou garagem subterrânea', 1.0),
          'terreo': ('Casa ou térreo', 0.75),
          'alto': ('Apartamento em andar alto', 0.25)}
RIO = {'perto': ('Perto (até cerca de 200 m)', 150.0), 'medio': ('Mais ou menos (até cerca de 1 km)', 800.0),
       'longe': ('Longe ou não tem', 3000.0), 'nao_sei': ('Não sabe', 1500.0)}
RUA = {'sim': ('Costuma alagar', 1.0), 'as_vezes': ('Às vezes alaga', 0.5), 'nao': ('Não costuma alagar', 0.0),
       'nao_sei': ('Não sabe', 0.5)}


def analise_alagamento(cod, dados, resp):
    m = dados['municipios'][cod]
    c = m.get('clima', {})
    if c.get('chuva_24h') is None or c.get('chuva_prev_24h') is None:
        return None
    imovel, rio, rua = IMOVEL[resp['imovel']], RIO[resp['rio']], RUA[resp['rua']]
    pred = NEURAL_AI.classify_flood(c['chuva_24h'], c['chuva_prev_24h'], rio[1], rua[1], imovel[1])
    rows = [
        {'metric': 'Município', 'value': f"{m['nome']} – MA", 'risk': 'Indeterminado', 'explanation': _fonte_txt('IBGE')},
        {'metric': 'Chuva nas últimas 24 h', 'value': f"{fmt(c['chuva_24h'])} mm", 'risk': 'Indeterminado', 'explanation': _fonte_txt(c.get('fonte_chuva', '-'))},
        {'metric': 'Chuva prevista nas próximas 24 h', 'value': f"{fmt(c['chuva_prev_24h'])} mm", 'risk': 'Indeterminado', 'explanation': _fonte_txt(c.get('fonte_chuva', '-'))},
        {'metric': 'Tipo de imóvel', 'value': imovel[0], 'risk': 'Indeterminado', 'explanation': 'Informado por você.'},
        {'metric': 'Rio, córrego ou mangue por perto', 'value': rio[0], 'risk': 'Indeterminado', 'explanation': 'Informado por você.'},
        {'metric': 'A rua costuma alagar?', 'value': rua[0], 'risk': 'Indeterminado', 'explanation': 'Informado por você (usado como condição da drenagem).'},
    ]
    for a in m.get('avisos', [])[:3]:
        rows.append({'metric': 'Aviso meteorológico ativo', 'value': str(a.get('evento')), 'risk': 'Alto',
                     'explanation': _fonte_txt('INMET', f" · severidade {a.get('severidade') or '-'}")})
    rows.append({'metric': 'Risco estimado de alagamento', 'value': f"{pred['score']}/100", 'risk': pred['level'],
                 'explanation': 'Classificação da rede neural do Oliver com a chuva e as respostas sobre o imóvel.'})
    rows += _linhas_prob(pred)
    reply = (f"Para o seu imóvel em {m['nome']}, o risco de alagamento agora é {pred['level'].lower()} (índice {pred['score']}/100). "
             f"Choveu {fmt(c['chuva_24h'])} mm nas últimas 24 horas e a previsão é de {fmt(c['chuva_prev_24h'])} mm nas próximas 24 horas.")
    acoes = ['Se a água começar a entrar, desligue a energia no quadro de luz antes de mexer em aparelhos.',
             'Não atravesse ruas alagadas a pé ou de carro.']
    if resp['imovel'] == 'subsolo':
        acoes.insert(0, 'Em chuva forte, tire carros e objetos de valor do subsolo com antecedência.')
    acoes.append('Em emergência, ligue 199 (Defesa Civil) ou 193 (Bombeiros).')
    return _resultado('flood', m, dados, pred, rows, reply, acoes, fontes=[c.get('fonte_chuva'), 'INMET' if m.get('avisos') else None, 'IBGE'])


def grafico_focos(m, dados):
    """Focos de calor por dia (7 dias): no município e nos municípios vizinhos (sede a até 60 km)."""
    h = dados.get('historico_focos')
    if not h or 'historico_focos' not in m:
        return None
    vizinhos = [0] * len(h['dias'])
    nomes = []
    for cod, outro in dados['municipios'].items():
        if cod == m['codigo'] or 'historico_focos' not in outro:
            continue
        if _dist(m, outro) <= 60:
            nomes.append(outro['nome'])
            for i, v in enumerate(outro['historico_focos']):
                vizinhos[i] += v
    return {'tipo': 'focos', 'dias': h['dias'],
            'series': [{'nome': m['nome'], 'valores': m['historico_focos'], 'cor': 'fogo-1'},
                       {'nome': 'Municípios vizinhos (até 60 km)', 'valores': vizinhos, 'cor': 'fogo-2'}],
            'vizinhos': sorted(nomes), 'unidade': 'focos', 'fonte': 'INPE · BDQueimadas'}


# ---------------------------------------------------------------------------
# Sinalização de 1 a 3 meses (histórico mensal do INPE)
# ---------------------------------------------------------------------------
MESES = ('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
         'novembro', 'dezembro')
CLIMA_PATH = os.path.join(os.path.dirname(__file__), 'climatologia_ma.json')
_clima = {'dados': None, 'mtime': 0}


def carregar_climatologia():
    try:
        mtime = os.path.getmtime(CLIMA_PATH)
    except OSError:
        return None
    if _clima['dados'] is None or mtime != _clima['mtime']:
        with open(CLIMA_PATH, encoding='utf-8') as f:
            _clima.update(dados=json.load(f), mtime=mtime)
    return _clima['dados']


def sinalizacao(cod=None, hoje=None):
    """Próximos 3 meses pelo histórico: média de focos, faixa, chance de haver fogo e força da temporada.

    É a sazonalidade observada nos anos anteriores (não é uma previsão do tempo).
    """
    clima = carregar_climatologia()
    if not clima:
        return None
    base = clima['estado'] if cod is None else clima['municipios'].get(cod)
    if not base:
        return None
    hoje = hoje or datetime.now(BRT)
    perfil = [m['media'] for m in base['meses']]
    total = sum(perfil) or 1
    n = len(clima['anos'])
    pico = sorted(range(12), key=lambda i: -perfil[i])[:2]
    proximos = []
    for k in (1, 2, 3):
        i = (hoje.month - 1 + k) % 12
        ano = hoje.year + (hoje.month - 1 + k) // 12
        m = base['meses'][i]
        parte = m['media'] / total
        nivel = 'Alta' if parte >= 0.15 else 'Média' if parte >= 0.07 else 'Baixa'
        if total < 3:
            nivel = 'Baixa'
        proximos.append({'mes': MESES[i], 'indice_mes': i, 'ano': ano, 'media': m['media'], 'min': m['min'], 'max': m['max'],
                         'anos_com_foco': m['anos_com_foco'], 'anos': n,
                         'chance': round(100 * m['anos_com_foco'] / n), 'temporada': nivel})
    return {
        'periodo': f"{clima['anos'][0]}–{clima['anos'][-1]}", 'anos': n, 'fonte': clima.get('fonte', 'INPE'),
        'perfil': perfil, 'mes_atual': hoje.month - 1, 'meses_pico': [MESES[i] for i in pico],
        'total_medio_ano': round(sum(perfil), 1), 'proximos': proximos,
        'grafico': {'tipo': 'mensal', 'rotulos': [x[:3] for x in MESES], 'destaque': [p['indice_mes'] for p in proximos],
                    'unidade': 'focos', 'fonte': f"INPE · satélite de referência, média de {clima['anos'][0]} a {clima['anos'][-1]}",
                    'series': [{'nome': 'Média de focos no mês', 'valores': perfil, 'cor': 'fogo-1'}]},
    }


def texto_sinalizacao(s, onde):
    """onde já vem com a preposição: "em Balsas", "no Maranhão"."""
    if not s:
        return ''
    if s['total_medio_ano'] < 1:
        return f" Pelo histórico do INPE ({s['periodo']}), quase não há focos de queimada {onde} em nenhum mês do ano."
    partes = [f"{p['mes']} costuma ter {fmt(p['media'], 0)} focos em média (houve algum foco em {p['anos_com_foco']} de "
              f"{p['anos']} anos, {p['chance']}%; temporada {p['temporada'].lower()})" for p in s['proximos']]
    return (f" Próximos 3 meses {onde}, pelo histórico do INPE de {s['periodo']}: " + '; '.join(partes) + '.'
            f" Os meses de mais queimadas costumam ser {s['meses_pico'][0]} e {s['meses_pico'][1]}.")


def grafico_chuva(m):
    c = m.get('clima', {})
    if not c.get('chuva_7d'):
        return None
    return {'tipo': 'chuva', 'dias': c.get('datas_chuva_7d', []),
            'series': [{'nome': f"Chuva em {m['nome']}", 'valores': c['chuva_7d'], 'cor': 'agua-1'}],
            'previsao': c.get('chuva_prev_24h'), 'unidade': 'mm', 'fonte': 'Open-Meteo'}


def _resultado(domain, m, dados, pred, rows, reply, acoes, fontes):
    perto = [f for f in dados.get('focos', []) if _dist(m, f) <= 60][:150]
    lista_fontes = []
    for s in fontes:
        if s and s in FONTES and FONTES[s] not in lista_fontes:
            lista_fontes.append(FONTES[s])
    return {
        'domain': domain, 'complete': True, 'location': f"{m['nome']} – MA", 'overall_risk': pred['level'],
        'reply': reply, 'findings': rows, 'actions': acoes,
        'regional': {
            'municipio': {'codigo': m['codigo'], 'nome': m['nome'], 'lat': m['lat'], 'lon': m['lon']},
            'dados_de': data_br(dados.get('gerado_em', '')),
            'focos_proximos': [{'lat': f['lat'], 'lon': f['lon'], 'data': f.get('data_hora_utc'), 'satelite': f.get('satelite'),
                                'frp': f.get('frp'), 'municipio': dados['municipios'].get(f['municipio'], {}).get('nome', '')} for f in perto],
            'fontes': [{'nome': n, 'url': u} for n, u in lista_fontes],
            'avisos': m.get('avisos', []),
            'grafico': grafico_focos(m, dados) if domain == 'fire' else grafico_chuva(m),
            'confianca': {'nivel': pred['level'], 'probabilidades': pred['probabilities']},
        },
    }


def _dist(m, f):
    r = 6371.0
    p1, p2 = math.radians(m['lat']), math.radians(f['lat'])
    dl = math.radians(f['lon'] - m['lon'])
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def panorama(dados):
    """Retrato geral do Maranhão: onde estão os focos de queimada agora e os maiores incêndios."""
    mun = dados['municipios']
    hist = dados.get('historico_focos') or {}
    total_dia = hist.get('total_estado') or []
    total24 = sum(m['focos'].get('h24', 0) for m in mun.values())
    total48 = len(dados.get('focos', []))
    total7 = sum(total_dia)

    riscos, contagem = {}, {'Baixo': 0, 'Moderado': 0, 'Alto': 0}
    for cod, m in mun.items():
        pred, _ = risco_fogo(m)
        if pred:
            riscos[cod] = pred
            contagem[pred['level']] += 1

    def chave(item):
        cod, m = item
        return (-m['focos'].get('h24', 0), -m['focos'].get('h48', 0), -sum(m.get('historico_focos') or []))
    ordem = [(cod, m) for cod, m in sorted(mun.items(), key=chave)
             if m['focos'].get('h48', 0) or sum(m.get('historico_focos') or [])][:10]
    ranking = [{'nome': m['nome'], 'h24': m['focos'].get('h24', 0), 'h48': m['focos'].get('h48', 0),
                'd7': sum(m.get('historico_focos') or []), 'nivel': riscos.get(cod, {}).get('level', '-'),
                'score': riscos.get(cod, {}).get('score')} for cod, m in ordem]

    com_frp = [f for f in dados.get('focos', []) if f.get('frp')]
    maiores = sorted(com_frp, key=lambda f: -f['frp'])[:5]
    maiores = [{'municipio': mun.get(f['municipio'], {}).get('nome', ''), 'frp': round(f['frp'], 1),
                'data': f.get('data_hora_utc'), 'satelite': f.get('satelite'), 'lat': f['lat'], 'lon': f['lon']} for f in maiores]

    partes = [f"Nas últimas 24 horas, o INPE registrou {total24} foco(s) de calor no Maranhão "
              f"({total48} em 48 horas{f' e {total7} em 7 dias' if total7 else ''})."]
    if len(total_dia) >= 4:
        ontem, anteriores = total_dia[-2], total_dia[:-2]
        media = sum(anteriores) / len(anteriores)
        if media:
            comp = 'acima' if ontem > media * 1.1 else 'abaixo' if ontem < media * 0.9 else 'perto'
            partes.append(f"Ontem foram {ontem} focos, {comp} da média dos {len(anteriores)} dias anteriores ({round(media)} por dia).")
    if ranking:
        partes.append('Onde há mais focos agora: ' + ', '.join(f"{r['nome']} ({r['h24']})" for r in ranking[:5] if r['h24'])
                      .rstrip(': ') + '.' if any(r['h24'] for r in ranking[:5]) else
                      'Nenhum município teve focos nas últimas 24 horas; os maiores números recentes estão em ' +
                      ', '.join(r['nome'] for r in ranking[:3]) + '.')
    if maiores:
        mf = maiores[0]
        partes.append(f"O fogo mais intenso detectado foi em {mf['municipio']}, com potência radiativa (FRP) de "
                      f"{fmt(mf['frp'])} MW, em {_hora_br(mf['data'])}.")
    partes.append(f"Pela rede neural do Oliver, {contagem['Alto']} municípios estão com risco alto de o fogo se espalhar, "
                  f"{contagem['Moderado']} com risco moderado e {contagem['Baixo']} com risco baixo.")
    saz = sinalizacao(None)
    reply = ' '.join(partes) + texto_sinalizacao(saz, 'no Maranhão')

    rows = [{'metric': f"{i + 1}º · {r['nome']}", 'value': f"{r['h24']} focos", 'risk': r['nivel'] if r['nivel'] in ('Baixo', 'Moderado', 'Alto') else 'Indeterminado',
             'explanation': f"48 h: {r['h48']} · 7 dias: {r['d7']} · risco de propagação {str(r['nivel']).lower()}. Fonte: INPE."}
            for i, r in enumerate(ranking)]
    nivel = 'Alto' if contagem['Alto'] else 'Moderado' if contagem['Moderado'] else 'Baixo'
    return {
        'domain': 'panorama', 'complete': True, 'location': 'Maranhão', 'overall_risk': nivel, 'reply': reply,
        'findings': rows,
        'actions': ['Se vir fogo ou fumaça perto de casas ou da mata, ligue 193 (Bombeiros).',
                    'Não use fogo para limpar terreno ou queimar lixo, principalmente com o tempo seco.',
                    'Acompanhe os alertas da Defesa Civil (199) e do INPE.'],
        'regional': {
            'municipio': {'codigo': '21', 'nome': 'Maranhão', 'lat': -5.0, 'lon': -45.3},
            'dados_de': data_br(dados.get('gerado_em', '')),
            'focos_proximos': [{'lat': f['lat'], 'lon': f['lon'], 'data': f.get('data_hora_utc'), 'satelite': f.get('satelite'),
                                'frp': f.get('frp'), 'municipio': mun.get(f['municipio'], {}).get('nome', '')}
                               for f in dados.get('focos', [])[:800]],
            'fontes': [{'nome': n, 'url': u} for n, u in (FONTES['INPE'], FONTES['Open-Meteo'], FONTES['IBGE'])],
            'contagem': contagem, 'focos_24h': total24, 'focos_48h': total48, 'focos_7d': total7,
            'ranking_focos': ranking, 'maiores_focos': maiores,
            'sazonal': saz,
            'grafico': ({'tipo': 'focos', 'dias': hist['dias'], 'unidade': 'focos', 'fonte': 'INPE · BDQueimadas',
                         'series': [{'nome': 'Maranhão', 'valores': total_dia, 'cor': 'fogo-1'}]} if hist else None),
        },
    }


def _hora_br(utc):
    try:
        from datetime import datetime, timedelta
        d = datetime.strptime(str(utc)[:16], '%Y-%m-%d %H:%M') - timedelta(hours=3)
        return d.strftime('%d/%m às %H:%M')
    except ValueError:
        return str(utc or '')


# ---------------------------------------------------------------------------
# Conversa
# ---------------------------------------------------------------------------
PALAVRAS_FOGO = (' queimad', ' fogo', ' incendi', ' foco', ' queima', ' fumaca', ' brasa')
PALAVRAS_AGUA = (' alag', ' enchente', ' inunda', ' agua ', ' cheia', ' transbord')
PALAVRAS_AMBOS = (' os dois', ' ambos', ' tudo', ' todos', ' as duas', ' fogo e alag', ' queimada e alag')
PALAVRAS_PANORAMA = (' maranhao todo', ' todo o maranhao', ' todo maranhao', ' estado todo', ' panorama', ' ranking',
                     ' quais cidades', ' quais municipios', ' onde tem mais', ' no estado', ' resumo do maranhao',
                     ' como esta o maranhao', ' situacao do maranhao', ' maranhao hoje', ' maranhao como um todo')
OUTROS_ESTADOS = (' piaui', ' teresina', ' para ', ' belem', ' tocantins', ' palmas', ' ceara', ' fortaleza', ' bahia',
                  ' sao paulo', ' rio de janeiro', ' minas gerais', ' goias', ' brasilia', ' pernambuco', ' recife')


def _tem(t, palavras):
    return any(p in t for p in palavras)


PALAVRAS_MESES = (' proximos meses', ' proximo mes', ' daqui a', ' meses', ' previsao', ' tendencia', ' temporada',
                  ' janeiro', ' fevereiro', ' marco ', ' abril', ' maio', ' junho', ' julho', ' agosto', ' setembro',
                  ' outubro', ' novembro', ' dezembro')


def _intencao(t):
    if _tem(t, PALAVRAS_AMBOS):
        return 'both'
    fogo, agua = _tem(t, PALAVRAS_FOGO), _tem(t, PALAVRAS_AGUA)
    if fogo and agua:
        return 'both'
    if not fogo and not agua and _tem(t, PALAVRAS_MESES):
        return 'fire'
    return 'fire' if fogo else 'flood' if agua else None


def _resp_imovel(t):
    if _tem(t, (' subsolo', ' garagem subterr', ' porao', ' garagem no subsolo')):
        return 'subsolo'
    if _tem(t, (' andar alto', ' apartamento', ' andar ', ' pavimento', ' predio alto', ' cobertura')):
        return 'alto'
    if _tem(t, (' casa', ' terreo', ' loja', ' comercio', ' barraco', ' sitio', ' chacara', ' rua ')):
        return 'terreo'
    return None


def _resp_rio(t):
    if ' nao sei ' in t or ' sei la ' in t or ' nao sabe ' in t:
        return 'nao_sei'
    if _tem(t, (' mais ou menos', ' medio', ' uns ', ' algumas quadras', ' 1 km', ' um quilometro', ' meio')):
        return 'medio'
    if _tem(t, (' nao ', ' longe', ' nenhum', ' nada ')):
        return 'longe'
    if _tem(t, (' sim', ' perto', ' do lado', ' ao lado', ' na frente', ' fundo', ' colado')):
        return 'perto'
    return None


def _resp_rua(t):
    if ' nao sei ' in t or ' sei la ' in t or ' nao sabe ' in t:
        return 'nao_sei'
    if _tem(t, (' as vezes', ' de vez em quando', ' raramente', ' pouco', ' so quando')):
        return 'as_vezes'
    if _tem(t, (' nao', ' nunca', ' jamais')):
        return 'nao'
    if _tem(t, (' sim', ' sempre', ' muito', ' toda ', ' bastante', ' alaga')):
        return 'sim'
    return None


PERGUNTAS = {
    'imovel': ('Que tipo de imóvel você quer avaliar?', [v[0] for v in IMOVEL.values()]),
    'rio': ('Tem rio, córrego, igarapé, mangue ou lagoa perto do imóvel?', [v[0] for v in RIO.values()]),
    'rua': ('Quando chove forte, a rua costuma alagar?', ['Sim, costuma alagar', 'Às vezes', 'Não', 'Não sei']),
}
PARSERS = {'imovel': _resp_imovel, 'rio': _resp_rio, 'rua': _resp_rua}


def _pergunta(state, campo, prefixo=''):
    state['aguardando'] = campo
    texto, opcoes = PERGUNTAS[campo]
    return {'domain': 'regional', 'complete': False, 'reply': (prefixo + ' ' + texto).strip(), 'options': opcoes,
            'state': state, 'overall_risk': 'Aguardando dados', 'findings': [], 'actions': []}


def _pedir(state, texto, opcoes=None):
    return {'domain': 'regional', 'complete': False, 'reply': texto, 'options': opcoes or [], 'state': state,
            'overall_risk': 'Aguardando dados', 'findings': [], 'actions': []}


def _nomes(cods, dados):
    nomes = [dados['municipios'][c]['nome'] for c in cods]
    return nomes[0] if len(nomes) == 1 else ', '.join(nomes[:-1]) + ' e ' + nomes[-1]


def conversar(message, state):
    state = dict(state or {})
    state.setdefault('alagamento', {})
    if state.get('cidade') and not state.get('cidades'):
        state['cidades'] = [state['cidade']]
    dados = carregar_dados()
    if not dados:
        return _pedir(state, 'Não consegui carregar os dados oficiais agora. Tente de novo em alguns minutos.')
    t = normalizar(message)
    cidades_msg, sugestao = [], None

    # 1) confirmação de um nome parecido ("Você quis dizer Santa Inês?")
    confirmar = state.pop('confirmar', None)
    if confirmar:
        if _tem(t, (' sim', ' isso', ' essa', ' exato', ' pode ser', ' certo', ' ela ')):
            cidades_msg = [confirmar]
        elif _tem(t, (' nao ',)) and not achar_municipios(message, dados)[0]:
            return _pedir(state, 'Tudo bem. Escreva o nome da cidade do Maranhão do jeito que ela é chamada oficialmente.')

    # 2) resposta a uma pergunta pendente sobre o imóvel
    campo = state.get('aguardando')
    respondeu = False
    if campo and not cidades_msg:
        valor = PARSERS[campo](t)
        if valor:
            state['alagamento'][campo] = valor
            state['aguardando'] = None
            respondeu = True
        elif not (achar_municipios(message, dados)[0] or _intencao(t) or _tem(t, PALAVRAS_PANORAMA)):
            return _pergunta(state, campo, 'Não entendi. Pode escolher uma das opções?')

    # "Risco de queimadas na minha cidade", "no meu imóvel": a pessoa ainda vai dizer qual é a cidade.
    if not respondeu and not cidades_msg and not achar_municipios(message, dados)[0] and _tem(t, (' minha cidade', ' meu imovel', ' minha casa', ' meu predio', ' onde eu moro', ' minha regiao')):
        nova = _intencao(t)
        estado = {'alagamento': {}, 'intencao': nova or state.get('intencao')}
        assunto = {'fire': 'o risco de queimadas', 'flood': 'o risco de alagamento', 'both': 'os riscos'}.get(estado['intencao'], 'os riscos')
        return _pedir(estado, f'Qual é a sua cidade no Maranhão? Escreva o nome e eu busco {assunto} com os dados oficiais.')

    # 3) cidades citadas (exatas ou parecidas)
    if not cidades_msg and not respondeu:
        cidades_msg, sugestao = achar_municipios(message, dados)
    if not cidades_msg and sugestao and not _tem(t, PALAVRAS_PANORAMA):
        state['confirmar'] = sugestao
        nome = dados['municipios'][sugestao]['nome']
        return _pedir(state, f'Não encontrei essa cidade com esse nome. Você quis dizer {nome}?', [f'Sim, {nome}', 'Não'])

    # 4) panorama do estado
    if _tem(t, PALAVRAS_PANORAMA) and not cidades_msg:
        r = panorama(dados)
        r['state'] = {'alagamento': {}, 'intencao': state.get('intencao')}
        r['options'] = ['Risco de queimadas na minha cidade'] + ([f"Queimadas em {r['regional']['ranking_focos'][0]['nome']}"] if r['regional']['ranking_focos'] else [])
        return r

    outro_estado = _tem(t, OUTROS_ESTADOS)
    if cidades_msg and cidades_msg != state.get('cidades'):
        if set(cidades_msg) != set(state.get('cidades') or []):
            state['alagamento'] = {}      # outra cidade, outro imóvel
            state['aguardando'] = None
        state['cidades'] = cidades_msg
    nova = None if respondeu else _intencao(t)
    if nova:
        state['intencao'] = nova

    if not state.get('cidades'):
        if outro_estado:
            return _pedir(state, 'Por enquanto eu analiso só os municípios do Maranhão. Qual cidade do Maranhão você quer ver?')
        if ' maranhao ' in t:
            r = panorama(dados)
            r['state'] = state
            r['options'] = ['Risco de queimadas na minha cidade']
            return r
        return _pedir(state, 'Para eu buscar os dados oficiais, me diga a cidade do Maranhão. Por exemplo: "Barra do Corda" ou "Imperatriz". '
                             'Você pode citar mais de uma cidade.', ['Como está o Maranhão hoje?'])
    cods = state['cidades']
    if not state.get('intencao'):
        return _pedir(state, f'Certo, {_nomes(cods, dados)}. Você quer saber o risco de queimadas, de alagamento ou os dois?',
                      ['Queimadas', 'Alagamento', 'Os dois'])

    # 5) perguntas do imóvel (só para alagamento)
    if state['intencao'] in ('flood', 'both'):
        for campo in ('imovel', 'rio', 'rua'):
            if campo not in state['alagamento']:
                pref = ''
                if campo == 'imovel':
                    onde = f' em {_nomes(cods, dados)}' if len(cods) == 1 else ''
                    pref = f'Para o alagamento{onde}, preciso saber três coisas simples sobre o imóvel.'
                    if len(cods) > 1:
                        pref += ' Vou usar as mesmas respostas para todas as cidades.'
                return _pergunta(state, campo, pref)

    # 6) análise de cada cidade
    relatorios, sem_dados = [], []
    for cod in cods:
        feitos = 0
        if state['intencao'] in ('fire', 'both'):
            r = analise_fogo(cod, dados)
            if r:
                relatorios.append(r)
                feitos += 1
        if state['intencao'] in ('flood', 'both'):
            r = analise_alagamento(cod, dados, state['alagamento'])
            if r:
                relatorios.append(r)
                feitos += 1
        if not feitos:
            sem_dados.append(cod)
    if not relatorios:
        return _pedir({'cidades': cods, 'alagamento': {}, 'intencao': state['intencao']},
                      f'Os dados de clima de {_nomes(cods, dados)} não estão disponíveis agora. Tente de novo em alguns minutos.')
    texto = ' '.join(r['reply'] for r in relatorios)
    if sem_dados:
        texto += f' Não há dados de clima de {_nomes(sem_dados, dados)} agora.'
    if outro_estado:
        texto += ' Cidades de outros estados ficaram de fora: por enquanto eu analiso só o Maranhão.'
    texto += f" Dados atualizados em {data_br(dados.get('gerado_em', ''))}."
    outro = {'fire': 'Ver também o risco de alagamento', 'flood': 'Ver também o risco de queimadas'}.get(state['intencao'])
    opcoes = ['Gerar relatório em PDF'] + ([outro] if outro else []) + ['Como está o Maranhão hoje?']
    pior = max((r['overall_risk'] for r in relatorios), key=lambda n: ('Baixo', 'Moderado', 'Alto').index(n))
    return {'domain': 'regional', 'complete': True, 'reply': texto, 'reports': relatorios,
            'location': ', '.join(r['location'] for r in relatorios), 'overall_risk': pior, 'options': opcoes,
            'state': {'cidades': cods, 'cidade': cods[-1], 'intencao': state['intencao'],
                      'alagamento': state['alagamento'] if state['intencao'] != 'fire' else {}},
            'findings': [], 'actions': []}
