"""Fluxo conversacional do Oliver.

Junta as mensagens do usuário, extrai os dados de cada cenário e, quando
todos estão presentes, chama a rede neural.
"""
import re

from .neural import NEURAL_AI

PROVIDER = 'Oliver · motor neural local'
NUM = r"([+-]?\d+(?:[.,]\d+)?)"
# Entre o nome do campo e o número: no máximo 28 caracteres, sem atravessar
# ";", "," ou quebra de linha (evita pegar o número do campo seguinte).
GAP = r"[^\d+\-;,\n]{0,28}"
DIRECTIONS = ('nordeste', 'noroeste', 'sudeste', 'sudoeste', 'norte', 'sul', 'leste', 'oeste')


def _number(text, patterns):
    """Devolve o ÚLTIMO valor informado para o campo (permite corrigir um dado)."""
    for pattern in patterns:
        found = None
        for m in re.finditer(pattern + GAP + NUM, text, re.I):
            try:
                found = float(m.group(1).replace(',', '.'))
            except ValueError:
                pass
        if found is not None:
            return found
    return None


LOCATION_RE = r"(?:localiza[cç][aã]o|local(?:\s+do\s+pr[eé]dio)?|cidade|munic[ií]pio|regi[aã]o)\s*(?:[:=]|\bé\b)\s*(.+)"
NEXT_FIELD = (r"(?:foco\s+ativo|fogo\s+ativo|velocidade\s+do\s+vento|vento|dire[cç][aã]o(?:\s+do\s+vento)?|umidade|humidade|secura|"
              r"vegeta[cç][aã]o|declividade|inclina[cç][aã]o|chuva|precipita[cç][aã]o|previs[aã]o|dist[aâ]ncia|proximidade|"
              r"drenagem|piso|pavimento|andar)\s*[:=]")


def _location(text):
    value = None
    for m in re.finditer(LOCATION_RE, text, re.I):
        value = m.group(1)
    if not value:
        return None
    value = re.split(r"(?:[;.!?\n]|,\s*(?=" + NEXT_FIELD + r")|\s+(?=" + NEXT_FIELD + r"))", value, maxsplit=1, flags=re.I)[0]
    value = value.strip(" ,:-")
    return value[:120] or None


def _without_location(text):
    """Texto sem os nomes de local (para "Rio Grande do Norte" não virar direção Norte)."""
    def cut(m):
        loc = m.group(1)
        loc = re.split(r"(?:[;.!?\n]|,\s*(?=" + NEXT_FIELD + r")|\s+(?=" + NEXT_FIELD + r"))", loc, maxsplit=1, flags=re.I)
        return ' ' + (loc[1] if len(loc) > 1 else '')
    return re.sub(LOCATION_RE, cut, text, flags=re.I)


def _direction(text):
    text = _without_location(text)
    found = None
    for m in re.finditer(r'(?:dire[cç][aã]o\s+do\s+vento|vento\s+(?:de|do|para|vindo\s+do))\s*[:=]?\s*(' + '|'.join(DIRECTIONS) + r')\b', text, re.I):
        found = m.group(1)
    if not found:
        for m in re.finditer(r'\b(' + '|'.join(DIRECTIONS) + r')\b', text, re.I):
            found = m.group(1)
    return found.capitalize() if found else None


def _last_choice(text, options):
    """Entre várias opções (regex → valor), devolve a que aparece por último no texto."""
    best, pos = None, -1
    for pattern, value in options:
        for m in re.finditer(pattern, text, re.I):
            if m.start() > pos:
                best, pos = value, m.start()
    return best


def _field_row(name, value, unit=''):
    if isinstance(value, (int, float)):
        shown = f'{value:g} {unit}'.strip()
    else:
        shown = value or 'Não informado'
    return {
        'metric': name, 'value': shown, 'risk': 'Indeterminado',
        'explanation': 'Informação reunida na conversa.' if value is not None else 'Oliver precisa deste dado para continuar.',
    }


def _base(domain, **extra):
    out = {'provider': PROVIDER, 'mode': 'local', 'model': 'Oliver Neural Engine', 'domain': domain, 'complete': False}
    out.update(extra)
    return out


def _ask(domain, missing, rows):
    names = '; '.join(missing)
    example = ('Exemplo: Localização: Chapada dos Veadeiros; fogo ativo: sim; vento: 30 km/h; direção do vento: norte; '
               'umidade: 35%; secura da vegetação: 70%; declividade: 20%.' if domain == 'fire' else
               'Exemplo: Localização: Centro de Recife; chuva acumulada: 60 mm; chuva prevista: 40 mm; '
               'distância do rio: 500 m; drenagem: ruim; piso vulnerável: térreo.')
    return _base(domain,
                 reply=f"Ainda preciso destes dados para montar a análise: {names}. Você pode enviar tudo numa mensagem só "
                       f"ou responder por partes. Use os nomes dos campos e as unidades para eu associar cada valor. {example}",
                 overall_risk='Aguardando dados', findings=rows,
                 actions=['A análise só será calculada quando os dados necessários forem reunidos.'])


def _detect_domain(text):
    full = text.lower()
    if any(x in full for x in ('fogo', 'queimada', 'incêndio', 'incendio', 'foco ativo', 'propagação')):
        return 'fire'
    if any(x in full for x in ('alagamento', 'enchente', 'inundação', 'inundacao', 'prédio', 'predio', 'chuva', 'drenagem')):
        return 'flood'
    return ''


def _fire(all_text):
    loc = _location(all_text)
    wind = _number(all_text, [r'(?:velocidade\s+do\s+)?vento(?:\s+velocidade)?', r'wind'])
    humidity = _number(all_text, [r'umidade(?:\s+relativa)?', r'humidade'])
    dryness = _number(all_text, [r'secura(?:\s+da\s+vegeta[cç][aã]o)?', r'vegeta[cç][aã]o(?:\s+seca)?', r'\bseca'])
    slope = _number(all_text, [r'declividade', r'inclina[cç][aã]o', r'relevo'])
    direction = _direction(all_text)
    active = _last_choice(all_text, [
        (r'\b(?:fogo|foco|inc[eê]ndio)\s+ativo\s*(?:agora)?\s*[:=]?\s*sim\b|\bsim,?\s+(?:h[aá]|existe)\s+fogo\b', 'Sim'),
        (r'\bsem\s+fogo\s+ativo\b|\b(?:fogo|foco|inc[eê]ndio)\s+ativo\s*(?:agora)?\s*[:=]?\s*n[aã]o\b|\bn[aã]o\s+(?:h[aá]|existe)\s+(?:fogo|foco)\b', 'Não'),
    ])
    required = [('Local', loc, ''), ('Fogo ativo agora?', active, ''), ('Velocidade do vento', wind, 'km/h'),
                ('Direção do vento', direction, ''), ('Umidade relativa', humidity, '%'),
                ('Secura da vegetação', dryness, '%'), ('Declividade', slope, '%')]
    missing = [name for name, value, _ in required if value is None]
    rows = [_field_row(name, value, unit) for name, value, unit in required]
    if missing:
        return _ask('fire', missing, rows)
    if any(not 0 <= v <= 100 for v in (wind, humidity, dryness, slope)):
        return _base('fire', reply='Alguns valores estão fora da faixa esperada (0 a 100 para velocidade, umidade, secura e declividade). '
                                   'Revise também as unidades.',
                     overall_risk='Aguardando correção', findings=rows, actions=['Corrija os parâmetros e envie novamente.'])
    pred = NEURAL_AI.classify_fire(wind, humidity, dryness, slope)
    rows.append({'metric': 'Direção potencial inicial', 'value': direction, 'risk': 'Indeterminado',
                 'explanation': 'Indica apenas a direção do vento informada; não representa uma simulação geográfica do avanço do fogo.'})
    rows.append({'metric': 'Risco estimado de propagação', 'value': f"{pred['score']}/100", 'risk': pred['level'],
                 'explanation': 'Classificação da rede neural para as condições ambientais informadas.'})
    rows.extend({'metric': f'Probabilidade · {k}', 'value': f'{v:.1f}%', 'risk': k,
                 'explanation': 'Probabilidade de classe retornada pelo Oliver Neural Engine.'} for k, v in pred['probabilities'].items())
    return _base('fire', model='Oliver Neural Engine · módulo fogo', complete=True, location=loc,
                 reply=f"Concluí a triagem para {loc}. O cenário foi classificado como risco {pred['level'].lower()} de propagação "
                       f"(índice demonstrativo {pred['score']}/100). Direção informada do vento: {direction}. Isso não é uma previsão "
                       f"geográfica real nem substitui dados de satélite e meteorologia.",
                 overall_risk=pred['level'], findings=rows,
                 actions=['Confirme foco e condições meteorológicas com fontes oficiais.',
                          'Se houver fogo ativo, acione as equipes oficiais; não use esta demonstração para orientar combate.'])


def _flood(all_text):
    loc = _location(all_text)
    rain = _number(all_text, [r'(?<!de\s)(?:chuva(?!\s+prevista)(?:\s+acumulada)?|precipita[cç][aã]o(?!\s+prevista)(?:\s+acumulada)?)'
                              r'(?:\s+(?:nas?\s+)?[uú]ltimas?\s+24\s*h)?'])
    forecast = _number(all_text, [r'(?:previs[aã]o(?:\s+de)?\s+chuva|chuva\s+prevista|precipita[cç][aã]o\s+prevista)'
                                  r'(?:\s+(?:nas?\s+)?pr[oó]ximas?\s+24\s*h)?'])
    distance = _number(all_text, [r'dist[aâ]ncia\s+(?:do|da|de)\s+(?:rio|c[oó]rrego|corpo\s+d[’\']?[aá]gua)',
                                  r'proximidade\s+(?:do|da)\s+(?:rio|c[oó]rrego)'])
    drainage = _last_choice(all_text, [
        (r'\bdrenagem\s*(?:[:=]\s*)?(?:boa|adequada)\b|\bbueiros\s+livres\b|\bescoamento\s+bom\b', ('Boa', 0.0)),
        (r'\bdrenagem\s*(?:[:=]\s*)?(?:regular|moderada)\b|\bbueiros\s+parcialmente\s+obstru[ií]dos\b', ('Regular', 0.5)),
        (r'\bdrenagem\s*(?:[:=]\s*)?(?:ruim|prec[aá]ria|bloqueada)\b|\bbueiros\s+(?:entupidos|obstru[ií]dos)\b', ('Ruim', 1.0)),
    ])
    floor = _last_choice(all_text, [
        (r'\b(?:subsolo|por[aã]o|garagem\s+subterr[aâ]nea)\b', ('Subsolo/porão', 1.0)),
        (r'\b(?:piso\s+|andar\s+)?t[eé]rreo\b', ('Térreo', 0.75)),
        (r'\b(?:pavimento\s+elevado|andar\s+alto|acima\s+do\s+t[eé]rreo)\b', ('Pavimento elevado', 0.25)),
    ])
    required = [('Local do prédio', loc, ''), ('Chuva acumulada nas últimas 24 h', rain, 'mm'),
                ('Chuva prevista nas próximas 24 h', forecast, 'mm'), ('Distância de rio/córrego', distance, 'm'),
                ('Condição da drenagem', drainage[0] if drainage else None, ''),
                ('Piso mais vulnerável', floor[0] if floor else None, '')]
    missing = [name for name, value, _ in required if value is None]
    rows = [_field_row(name, value, unit) for name, value, unit in required]
    if missing:
        return _ask('flood', missing, rows)
    if rain < 0 or forecast < 0 or distance < 0:
        return _base('flood', reply='Chuva e distância não podem ser negativas. Revise os valores.',
                     overall_risk='Aguardando correção', findings=rows, actions=['Corrija os parâmetros e envie novamente.'])
    pred = NEURAL_AI.classify_flood(rain, forecast, distance, drainage[1], floor[1])
    rows.append({'metric': 'Risco estimado de alagamento', 'value': f"{pred['score']}/100", 'risk': pred['level'],
                 'explanation': 'Classificação da rede neural com chuva, proximidade, drenagem e piso vulnerável informados.'})
    rows.extend({'metric': f'Probabilidade · {k}', 'value': f'{v:.1f}%', 'risk': k,
                 'explanation': 'Probabilidade de classe retornada pelo Oliver Neural Engine.'} for k, v in pred['probabilities'].items())
    return _base('flood', model='Oliver Neural Engine · módulo alagamento', complete=True, location=loc,
                 reply=f"Concluí a triagem para {loc}. O cenário foi classificado como risco {pred['level'].lower()} de alagamento "
                       f"(índice demonstrativo {pred['score']}/100). A estimativa depende das informações fornecidas e não consulta "
                       f"chuva, rios ou mapas em tempo real.",
                 overall_risk=pred['level'], findings=rows,
                 actions=['Compare o cenário com alertas meteorológicos e hidrológicos oficiais.',
                          'Se houver água acumulada, evite áreas alagadas e instalações elétricas; acione manutenção/emergência conforme a situação.'])


def assistant(data):
    message = str(data.get('message', '')).strip()[:12000]
    if not message:
        raise ValueError('Escreva uma mensagem para Oliver.')
    history = data.get('history', [])
    if not isinstance(history, list):
        history = []
    prior = '\n'.join(str(t.get('text', '')) for t in history[-12:] if isinstance(t, dict) and t.get('role') == 'user')
    all_text = prior + '\n' + message
    domain = str(data.get('domain', 'auto'))
    if domain == 'auto':
        domain = _detect_domain(all_text)
    if domain == 'fire':
        return _fire(all_text)
    if domain == 'flood':
        return _flood(all_text)
    return _base('', reply='Oi, eu sou o Oliver. Posso analisar a propagação de um foco de fogo ou o risco de alagamento de um prédio. '
                           'Escolha um cenário abaixo ou me diga qual dos dois você quer avaliar.',
                 overall_risk='Aguardando cenário', findings=[],
                 actions=['Selecione “Propagação de fogo” ou “Alagamento predial” para começar.'])
