"""Relatório em PDF do Oliver, gerado no servidor com ReportLab.

Recebe as análises que a pessoa viu na tela e devolve os bytes de um PDF A4
com resumo, gráficos, dados usados e fontes de cada análise.
"""
import io
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String, Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

BRT = timezone(timedelta(hours=-3))
INK = colors.HexColor('#1d2b2a')
MUTED = colors.HexColor('#56655f')
LINE = colors.HexColor('#c9d1ca')
PAPER = colors.HexColor('#edf0ea')
GRID = colors.HexColor('#e2e7e2')
RISCO = {'Baixo': colors.HexColor('#3e7c4f'), 'Moderado': colors.HexColor('#b8820f'), 'Alto': colors.HexColor('#b23a1a')}
COR_SERIE = {'fogo-1': colors.HexColor('#a8321a'), 'fogo-2': colors.HexColor('#c88a3c'), 'agua-1': colors.HexColor('#2f7fb8')}
COR_DOMINIO = {'fire': colors.HexColor('#b23a1a'), 'panorama': colors.HexColor('#b23a1a'), 'flood': colors.HexColor('#1e5c86')}
TITULOS = {'fire': 'Risco de queimadas', 'flood': 'Risco de alagamento', 'panorama': 'Panorama do Maranhão'}
NOMES = {'fire': 'Queimadas', 'flood': 'Alagamento', 'panorama': 'Panorama do Maranhão'}
TITULO_GRAFICO = {'fire': 'Focos de calor por dia', 'panorama': 'Focos de calor no Maranhão por dia', 'flood': 'Chuva por dia'}
MAX_ANALISES = 30

_base = getSampleStyleSheet()
S = {
    'body': ParagraphStyle('body', parent=_base['Normal'], fontName='Helvetica', fontSize=9.5, leading=13.5, textColor=INK),
    'small': ParagraphStyle('small', parent=_base['Normal'], fontName='Helvetica', fontSize=8, leading=10.5, textColor=MUTED),
    'cell': ParagraphStyle('cell', parent=_base['Normal'], fontName='Helvetica', fontSize=8.8, leading=11.5, textColor=INK),
    'cellb': ParagraphStyle('cellb', parent=_base['Normal'], fontName='Helvetica-Bold', fontSize=8.8, leading=11.5, textColor=INK),
    'h2': ParagraphStyle('h2', parent=_base['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=INK, spaceBefore=8, spaceAfter=4),
    'h3': ParagraphStyle('h3', parent=_base['Heading3'], fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=INK, spaceBefore=8, spaceAfter=3),
    'cover_t': ParagraphStyle('ct', fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=colors.white),
    'cover_s': ParagraphStyle('cs', fontName='Helvetica', fontSize=10.5, leading=14, textColor=colors.white),
    'cover_r': ParagraphStyle('cr', fontName='Helvetica', fontSize=9, leading=12, textColor=colors.white, alignment=TA_RIGHT),
}


def _t(v):
    return escape(str(v if v is not None else ''))


def _p(txt, estilo='body'):
    return Paragraph(_t(txt), S[estilo])


def _num(v, padrao=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return padrao


def _fmt(v, unidade):
    return f'{v:.1f}'.replace('.', ',') if unidade == 'mm' else str(int(round(v)))


def _dia(iso, i, total, tipo):
    if tipo == 'focos' and i == total - 1:
        return 'hoje'
    partes = str(iso).split('-')
    return f'{partes[2]}/{partes[1]}' if len(partes) == 3 else str(iso)


def _probs(data):
    out = {}
    for f in data.get('findings') or []:
        m = str(f.get('metric', ''))
        if m.startswith('Probabilidade · '):
            out[m.split(' · ', 1)[1]] = _num(str(f.get('value', '0')).replace('%', '').replace(',', '.'))
    return out


def _indice(data):
    for f in data.get('findings') or []:
        if str(f.get('metric', '')).startswith('Risco estimado'):
            return int(_num(str(f.get('value', '0')).split('/')[0]))
    return None


def _quando(at):
    try:
        d = datetime.fromisoformat(str(at).replace('Z', '+00:00')).astimezone(BRT)
        return d.strftime('%d/%m/%Y às %H:%M')
    except ValueError:
        return ''


def _utc_br(s):
    try:
        d = datetime.strptime(str(s)[:16], '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc).astimezone(BRT)
        return d.strftime('%d/%m %H:%M')
    except ValueError:
        return str(s or '')


def _valor(f):
    if f.get('metric') == 'Condição da drenagem':
        return {'0': 'Boa', '0.5': 'Regular', '1': 'Ruim'}.get(str(f.get('value')).strip(), f.get('value'))
    return f.get('value')


# ---------------------------------------------------------------------------
# Desenhos
# ---------------------------------------------------------------------------
def termometro(indice, nivel, largura=105 * mm):
    d = Drawing(largura, 16 * mm)
    y, h = 5 * mm, 3.2 * mm
    w = (largura - 2) / 3
    for i, z in enumerate(('Baixo', 'Moderado', 'Alto')):
        d.add(Rect(i * (w + 1), y, w, h, rx=1.2, ry=1.2, fillColor=RISCO[z] if z == nivel else PAPER, strokeColor=None))
    x = max(0, min(100, indice)) / 100 * largura
    d.add(Rect(x - 0.4 * mm, y - 1.4 * mm, 0.8 * mm, h + 2.8 * mm, fillColor=INK, strokeColor=None))
    d.add(String(min(max(x, 4 * mm), largura - 4 * mm), y + h + 3 * mm, str(indice), fontName='Helvetica-Bold', fontSize=11,
                 fillColor=INK, textAnchor='middle'))
    for v, anc in ((0, 'start'), (50, 'middle'), (100, 'end')):
        d.add(String(v / 100 * largura, 0.6 * mm, str(v), fontName='Helvetica', fontSize=7, fillColor=MUTED, textAnchor=anc))
    return d


def _nice_max(v):
    if v <= 4:
        return 4
    import math
    exp = 10 ** math.floor(math.log10(v))
    for f in (1, 2, 2.5, 5, 10):
        if f * exp >= v:
            return f * exp
    return 10 * exp


def grafico(g, largura=170 * mm, altura=62 * mm):
    """Colunas por dia; duas séries viram colunas empilhadas. Previsão de chuva em coluna listrada."""
    dias = list(g.get('dias') or g.get('rotulos') or [])[:14]
    destaque = set(g.get('destaque') or [])
    series = [s for s in (g.get('series') or [])[:2]]
    if not dias or not series:
        return None
    unidade, tipo = g.get('unidade', ''), g.get('tipo', '')
    previsao = _num(g['previsao'], None) if tipo == 'chuva' and g.get('previsao') is not None else None
    n = len(dias)
    slots = n + (1 if previsao is not None else 0)
    ml, mr, mb = 12 * mm, 3 * mm, 8 * mm
    mt = 11 * mm if len(series) > 1 else 5 * mm
    d = Drawing(largura, altura)
    banda = (largura - ml - mr) / slots
    bw = min(7 * mm, banda * 0.55)
    totais = [sum(_num((s.get('valores') or [0] * n)[i] if i < len(s.get('valores') or []) else 0) for s in series) for i in range(n)]
    maximo = _nice_max(max([1.0] + totais + ([previsao] if previsao else [])))

    def y(v):
        return mb + (altura - mt - mb) * (v / maximo)

    def x(i):
        return ml + banda * i + banda / 2

    for k in range(3):
        v = maximo / 2 * k
        d.add(Line(ml, y(v), largura - mr, y(v), strokeColor=GRID if k else colors.HexColor('#9aa69f'), strokeWidth=0.6))
        d.add(String(ml - 2 * mm, y(v) - 2.5, str(int(v)) if float(v).is_integer() else _fmt(v, 'mm'),
                     fontName='Helvetica', fontSize=7, fillColor=MUTED, textAnchor='end'))

    def coluna(cx, base, topo, cor, arredonda, hachura=False):
        if topo - base < 0.3:
            return
        r = min(1.2 * mm, (topo - base), bw / 2) if arredonda else 0
        x0, x1 = cx - bw / 2, cx + bw / 2
        p = Path(fillColor=None if hachura else cor, strokeColor=cor if hachura else None, strokeWidth=0.8)
        p.moveTo(x0, base)
        p.lineTo(x0, topo - r)
        p.curveTo(x0, topo, x0, topo, x0 + r, topo)
        p.lineTo(x1 - r, topo)
        p.curveTo(x1, topo, x1, topo, x1, topo - r)
        p.lineTo(x1, base)
        p.closePath()
        d.add(p)
        if hachura:
            passo = 1.6 * mm
            k = -(topo - base)
            while k < bw:
                xa, ya = x0 + max(0, k), base + max(0, -k)
                xb = min(x1, x0 + k + (topo - base))
                yb = base + (xb - x0 - k)
                if xb > xa:
                    d.add(Line(xa, ya, xb, yb, strokeColor=cor, strokeWidth=0.7))
                k += passo

    pico = totais.index(max(totais)) if totais else -1
    for i, dia in enumerate(dias):
        acum = 0.0
        segs = []
        for s in series:
            vals = s.get('valores') or []
            v = _num(vals[i]) if i < len(vals) else 0
            if v <= 0:
                continue
            base = y(acum) + (0.6 if acum > 0 else 0)
            acum += v
            apagado = destaque and i not in destaque
            segs.append((base, y(acum), colors.HexColor('#d9ccbf') if apagado else COR_SERIE.get(s.get('cor'), INK)))
        for k, (base, topo, cor) in enumerate(segs):
            coluna(x(i), base, topo, cor, k == len(segs) - 1)
        rotular = (i in destaque) if destaque else (i == pico or i == n - 1)
        if rotular and totais[i] > 0:
            d.add(String(x(i), y(totais[i]) + 1.5 * mm, _fmt(totais[i], unidade), fontName='Helvetica-Bold', fontSize=8,
                         fillColor=INK, textAnchor='middle'))
        d.add(String(x(i), mb - 4.5 * mm, str(dia) if tipo == 'mensal' else _dia(dia, i, n, 'focos' if tipo != 'chuva' else 'chuva'), fontName='Helvetica',
                     fontSize=7, fillColor=MUTED, textAnchor='middle'))
    if previsao is not None:
        cor = COR_SERIE['agua-1']
        coluna(x(n), y(0), y(previsao), cor, True, hachura=True)
        d.add(String(x(n), y(previsao) + 1.5 * mm, _fmt(previsao, 'mm'), fontName='Helvetica-Bold', fontSize=8, fillColor=INK, textAnchor='middle'))
        d.add(String(x(n), mb - 4.5 * mm, 'próx. 24 h', fontName='Helvetica', fontSize=7, fillColor=MUTED, textAnchor='middle'))
    if len(series) > 1:
        lx = ml
        for s in series:
            d.add(Rect(lx, altura - 4 * mm, 3 * mm, 3 * mm, rx=0.8, ry=0.8, fillColor=COR_SERIE.get(s.get('cor'), INK), strokeColor=None))
            nome = str(s.get('nome', ''))[:45]
            d.add(String(lx + 4.5 * mm, altura - 3.6 * mm, nome, fontName='Helvetica', fontSize=8, fillColor=INK))
            lx += 10 * mm + len(nome) * 1.65 * mm
    if all(t == 0 for t in totais) and not previsao:
        msg = 'Sem chuva nos últimos 7 dias' if tipo == 'chuva' else 'Nenhum foco de calor nos últimos 7 dias'
        d.add(String((ml + largura - mr) / 2, (mb + altura - mt) / 2, msg, fontName='Helvetica', fontSize=9, fillColor=MUTED, textAnchor='middle'))
    return d


def legenda_grafico(g):
    if g.get('tipo') == 'mensal':
        return f"Média de focos de queimada em cada mês do ano; em destaque, os próximos 3 meses. Fonte: {g.get('fonte', '')}."
    if g.get('tipo') == 'chuva':
        return f"Milímetros de chuva por dia nos últimos 7 dias e a previsão para as próximas 24 horas (coluna listrada). Fonte: {g.get('fonte', '')}."
    viz = g.get('vizinhos') or []
    extra = ''
    if viz:
        extra = ' Vizinhos considerados: ' + ', '.join(map(str, viz[:8])) + (f' e mais {len(viz) - 8}' if len(viz) > 8 else '') + '.'
    return f"Locais distintos com fogo detectado por satélite em cada dia. \"Hoje\" ainda está em andamento. Fonte: {g.get('fonte', '')}.{extra}"


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------
def tabela(cabecalho, linhas, larguras, negrito_col0=True):
    dados = [[Paragraph(_t(c), S['cellb']) for c in cabecalho]]
    for ln in linhas:
        dados.append([c if not isinstance(c, (str, int, float)) else
                      Paragraph(_t(c), S['cellb'] if (j == 0 and negrito_col0) else S['cell']) for j, c in enumerate(ln)])
    t = Table(dados, colWidths=larguras, repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, LINE),
        ('BACKGROUND', (0, 0), (-1, 0), PAPER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


COR_TEMPORADA = {'Baixa': RISCO['Baixo'], 'Média': RISCO['Moderado'], 'Alta': RISCO['Alto']}


def bloco_sazonal(sz, onde, largura):
    """Seção "Próximos 3 meses": tabela + gráfico da média mensal."""
    if not sz:
        return []
    out = [Paragraph('Próximos 3 meses', S['h3'])]
    if _num(sz.get('total_medio_ano')) < 1:
        return out + [_p(f"Pelo histórico do INPE ({sz.get('periodo')}), quase não há focos de queimada {onde} em nenhum mês do ano.")]
    picos = sz.get('meses_pico') or ['', '']
    out.append(_p(f"O que costuma acontecer {onde} nos próximos meses, pelo histórico do INPE de {sz.get('periodo')}. "
                  f"Os meses de mais queimadas costumam ser {picos[0]} e {picos[1]}. Isto é o padrão dos anos anteriores, "
                  f"não uma previsão do tempo."))
    linhas = []
    for pm in sz.get('proximos') or []:
        cor = COR_TEMPORADA.get(pm.get('temporada'), INK).hexval()[2:]
        linhas.append([f"{str(pm.get('mes', '')).capitalize()} de {pm.get('ano')}", f"{_num(pm.get('media')):.0f}",
                       f"{pm.get('anos_com_foco')} de {pm.get('anos')} anos ({pm.get('chance')}%)",
                       f"{pm.get('min')} a {pm.get('max')}",
                       Paragraph(f'<font color="#{cor}"><b>{_t(pm.get("temporada"))}</b></font>', S['cell'])])
    out.append(tabela(['Mês', 'Média de focos', 'Teve fogo em', 'Menor e maior ano', 'Temporada'], linhas,
                      [34 * mm, 26 * mm, 44 * mm, 34 * mm, largura - 138 * mm]))
    g = sz.get('grafico')
    if g:
        dr = grafico(g, largura, 52 * mm)
        if dr:
            out += [Spacer(1, 2 * mm), dr, _p(legenda_grafico(g), 'small')]
    return [KeepTogether(out)]


def _nivel_par(nivel):
    cor = RISCO.get(nivel, INK).hexval()[2:]
    return Paragraph(f'<font color="#{cor}"><b>Risco {_t(str(nivel).lower())}</b></font>', S['cell'])


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------
def gerar_pdf(analises, usuario=None):
    analises = [a for a in (analises or []) if isinstance(a, dict) and isinstance(a.get('data'), dict)][:MAX_ANALISES]
    if not analises:
        raise ValueError('Não há análises para colocar no relatório.')
    agora = datetime.now(BRT)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
                            title='Oliver · Relatório de risco de queimadas e alagamento', author='Oliver (TCC)',
                            subject='Triagem de risco no Maranhão')
    largura = A4[0] - 32 * mm
    hist = []

    # Capa
    cidades = []
    for a in analises:
        loc = str(a['data'].get('location', '')).replace(' – MA', '')
        if a['data'].get('domain') != 'panorama' and loc not in cidades:
            cidades.append(loc)
    capa = Table([[
        [Paragraph('Oliver', S['cover_t']), Spacer(1, 2 * mm),
         Paragraph('Relatório de risco de queimadas<br/>e alagamento · Maranhão', S['cover_s'])],
        [Paragraph(f'Gerado em<br/><b>{agora.strftime("%d/%m/%Y às %H:%M")}</b><br/>{len(analises)} '
                   f'{"análises" if len(analises) > 1 else "análise"}'
                   + (f'<br/>{_t(usuario)}' if usuario else ''), S['cover_r'])],
    ]], colWidths=[largura * 0.55, largura * 0.45], rowHeights=[30 * mm])
    capa.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#b23a1a')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#1e5c86')),
        ('VALIGN', (0, 0), (0, 0), 'MIDDLE'), ('VALIGN', (1, 0), (1, 0), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7 * mm), ('RIGHTPADDING', (0, 0), (-1, -1), 7 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 5 * mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 5 * mm),
    ]))
    hist += [capa, Spacer(1, 6 * mm)]
    if cidades:
        hist.append(_p('Municípios analisados: ' + ', '.join(cidades) + '.'))

    # Resumo
    hist.append(Paragraph('Resumo', S['h2']))
    linhas = []
    for a in analises:
        r = a['data']
        dom = r.get('domain')
        p = _probs(r)
        idx = _indice(r)
        linhas.append([NOMES.get(dom, 'Análise'), r.get('location', '-'), _nivel_par(r.get('overall_risk')),
                       '–' if idx is None else f'{idx}/100',
                       f"{max(p.values()):.1f}%".replace('.', ',') if p else '–'])
    hist.append(tabela(['Análise', 'Local', 'Classificação', 'Índice', 'Confiança'], linhas,
                       [30 * mm, 52 * mm, 38 * mm, 22 * mm, largura - 142 * mm]))

    fontes = {}
    for n_a, a in enumerate(analises):
        r, at = a['data'], a.get('at')
        dom = r.get('domain', 'fire')
        reg = r.get('regional') or {}
        for f in reg.get('fontes') or []:
            fontes[str(f.get('url', ''))] = str(f.get('nome', ''))
        cor = COR_DOMINIO.get(dom, INK)
        hist.append(PageBreak())
        titulo = Table([[Paragraph(f'<font color="#{cor.hexval()[2:]}">{_t(TITULOS.get(dom, "Análise"))}'
                                   f'{" · " + _t(r.get("location")) if dom != "panorama" else ""}</font>',
                                   ParagraphStyle('t', parent=S['h2'], fontSize=15, leading=19, spaceBefore=0))]],
                       colWidths=[largura])
        titulo.setStyle(TableStyle([('LINEBEFORE', (0, 0), (0, 0), 5, cor), ('LEFTPADDING', (0, 0), (0, 0), 4 * mm)]))
        hist.append(titulo)
        meta = f'Análise feita em {_quando(at)}' if _quando(at) else ''
        if reg.get('dados_de'):
            meta += f' · dados coletados em {reg["dados_de"]}'
        hist += [_p(meta, 'small'), Spacer(1, 3 * mm)]

        g = reg.get('grafico')
        if dom == 'panorama':
            hist.append(_p(r.get('reply', '')))
            if g:
                dr = grafico(g, largura)
                if dr:
                    hist += [Paragraph(TITULO_GRAFICO['panorama'], S['h3']), dr, _p(legenda_grafico(g), 'small')]
            hist.append(Paragraph('Municípios com mais focos de calor agora', S['h3']))
            hist.append(tabela(['Posição e município', '24 h', '48 h', '7 dias', 'Risco de propagação'],
                               [[f"{i + 1}º · {x.get('nome')}", str(x.get('h24', 0)), str(x.get('h48', 0)), str(x.get('d7', 0)),
                                 _nivel_par(x.get('nivel')) if x.get('nivel') in RISCO else '-']
                                for i, x in enumerate((reg.get('ranking_focos') or [])[:10])],
                               [62 * mm, 18 * mm, 18 * mm, 20 * mm, largura - 118 * mm]))
            maiores = reg.get('maiores_focos') or []
            if maiores:
                hist.append(Paragraph('Focos mais intensos (últimas 48 h)', S['h3']))
                hist.append(tabela(['Município', 'Intensidade (FRP)', 'Data e hora', 'Satélite', 'Coordenadas'],
                                   [[f.get('municipio', ''), f"{_num(f.get('frp')):.1f} MW".replace('.', ','), _utc_br(f.get('data')),
                                     f.get('satelite') or '-', f"{_num(f.get('lat')):.3f}, {_num(f.get('lon')):.3f}"] for f in maiores[:5]],
                                   [44 * mm, 28 * mm, 26 * mm, 36 * mm, largura - 134 * mm]))
                hist.append(_p('A potência radiativa do fogo (FRP) mede a energia liberada: quanto maior, mais forte o incêndio.', 'small'))
            hist += bloco_sazonal(reg.get('sazonal'), 'no Maranhão', largura)
            c_ = reg.get('contagem') or {}
            hist.append(_p(f"Risco de o fogo se espalhar, segundo a rede neural do Oliver: {c_.get('Alto', 0)} municípios com risco alto, "
                           f"{c_.get('Moderado', 0)} moderado e {c_.get('Baixo', 0)} baixo."))
        else:
            idx = _indice(r) or 0
            nivel = r.get('overall_risk')
            veredito = Table([[
                [_p('Classificação', 'small'),
                 Paragraph(f'<font color="#{RISCO.get(nivel, INK).hexval()[2:]}"><b>Risco {_t(str(nivel).lower())}</b></font>',
                           ParagraphStyle('v', fontName='Helvetica-Bold', fontSize=16, leading=20))],
                [_p('Índice de risco (0 a 100)', 'small'), termometro(idx, nivel)],
            ]], colWidths=[largura - 110 * mm, 110 * mm])
            veredito.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
            hist.append(veredito)
            if g:
                dr = grafico(g, largura)
                if dr:
                    hist.append(KeepTogether([Paragraph(TITULO_GRAFICO.get(dom, 'Gráfico'), S['h3']), dr, _p(legenda_grafico(g), 'small')]))
            p = _probs(r)
            if p:
                melhor = max(p, key=p.get)
                conf = Table([[_p(f'A rede neural classificou como risco {melhor.lower()}, com '
                                  f'{p[melhor]:.1f}% de confiança.'.replace('.', ',', 1))]], colWidths=[largura])
                conf.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PAPER), ('TOPPADDING', (0, 0), (-1, -1), 5),
                                          ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
                hist += [Spacer(1, 3 * mm), conf]
            if dom == 'fire':
                hist += bloco_sazonal(reg.get('sazonal'), f"em {str(r.get('location', '')).replace(' – MA', '')}", largura)
            linhas = [[f.get('metric'), _valor(f), f.get('explanation', '')] for f in (r.get('findings') or [])
                      if not str(f.get('metric', '')).startswith(('Probabilidade', 'Risco estimado'))]
            hist.append(Paragraph('Dados usados e suas fontes' if reg else 'Dados informados', S['h3']))
            hist.append(tabela(['Item', 'Valor', 'Fonte / observação'], linhas, [50 * mm, 42 * mm, largura - 92 * mm]))
            hist += [CondPageBreak(30 * mm), Paragraph('Conclusão do Oliver', S['h3']), _p(r.get('reply', ''))]
            focos = (reg.get('focos_proximos') or [])[:15]
            if dom == 'fire' and focos:
                hist.append(Paragraph('Focos de calor próximos (até 60 km, últimas 48 h · INPE)', S['h3']))
                hist.append(tabela(['Município', 'Data e hora', 'Satélite', 'Coordenadas'],
                                   [[f.get('municipio', ''), _utc_br(f.get('data')), f.get('satelite') or '-',
                                     f"{_num(f.get('lat')):.3f}, {_num(f.get('lon')):.3f}"] for f in focos],
                                   [48 * mm, 30 * mm, 42 * mm, largura - 120 * mm], negrito_col0=False))
                total = reg.get('total_focos_proximos') or len(reg.get('focos_proximos') or [])
                if total > 15:
                    hist.append(_p(f'Mostrando 15 de {total} focos.', 'small'))
        avisos = reg.get('avisos') or []
        if avisos and dom != 'panorama':
            hist.append(Paragraph('Avisos meteorológicos ativos (INMET)', S['h3']))
            for av in avisos[:5]:
                txt = f"<b>{_t(av.get('evento'))}</b>"
                if av.get('severidade'):
                    txt += f" · {_t(av.get('severidade'))}"
                if av.get('inicio'):
                    txt += f" · de {_t(av.get('inicio'))}"
                if av.get('fim'):
                    txt += f" até {_t(av.get('fim'))}"
                hist.append(Paragraph('• ' + txt, S['body']))
        acoes = r.get('actions') or []
        if acoes:
            hist.append(Paragraph('Recomendações', S['h3']))
            hist += [Paragraph('• ' + _t(x), S['body']) for x in acoes[:8]]

    # Fontes, método e aviso
    hist.append(PageBreak())
    if fontes:
        hist.append(Paragraph('Fontes dos dados', S['h2']))
        hist += [Paragraph(f'• {_t(nome)} · {_t(url)}', S['body']) for url, nome in fontes.items()]
        hist.append(Spacer(1, 2 * mm))
        hist.append(_p('Vento e umidade vêm da estação automática do INMET mais próxima (até 80 km) quando ela responde; caso '
                       'contrário, do Open-Meteo. Chuva, dias sem chuva e chuva dos últimos 30 dias: Open-Meteo. Focos de calor: '
                       'INPE. Avisos meteorológicos: INMET. Os dados são coletados de hora em hora.', 'small'))
    hist.append(Paragraph('Como o Oliver calcula', S['h2']))
    for txt in (
        'O Oliver usa duas redes neurais do tipo perceptron multicamadas (MLP), uma para cada risco. Cada rede tem uma camada '
        'oculta com 10 neurônios (ativação tanh) e uma saída softmax com três classes: baixo, moderado e alto.',
        '<b>Queimadas:</b> velocidade do vento, umidade relativa do ar, secura da vegetação e declividade do terreno. A secura é o '
        'maior valor entre duas estimativas: dias seguidos com menos de 5 mm de chuva (0 dia = 10 %, 45 dias ou mais = 100 %) e '
        'chuva dos últimos 30 dias (0 mm = 100 %, 150 mm ou mais = 0 %). A declividade é estimada pela elevação em torno da sede '
        'do município.',
        '<b>Alagamento:</b> chuva das últimas 24 horas, chuva prevista para as próximas 24 horas, proximidade de rio ou córrego, '
        'se a rua costuma alagar (drenagem) e o tipo de imóvel. As três últimas vêm das respostas da pessoa.',
        'O índice de 0 a 100 combina as probabilidades: 100 × (0,5 × P(moderado) + P(alto)). A classificação é a classe com maior '
        'probabilidade, e a confiança é o valor dessa probabilidade.',
    ):
        hist.append(Paragraph(txt, S['body']))
        hist.append(Spacer(1, 2 * mm))
    aviso = Table([[[Paragraph('<font color="#b23a1a"><b>Aviso importante</b></font>', S['h3']),
                     _p('Protótipo acadêmico (TCC). As redes neurais foram treinadas com exemplos sintéticos e usam dados públicos do '
                        'momento da coleta. O resultado é uma triagem e não substitui os alertas da Defesa Civil, do INPE, do INMET '
                        'ou do Cemaden. Em emergência, ligue 193 (Bombeiros) ou 199 (Defesa Civil).')]]], colWidths=[largura])
    aviso.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 1.2, colors.HexColor('#b23a1a')),
                               ('LEFTPADDING', (0, 0), (-1, -1), 4 * mm), ('RIGHTPADDING', (0, 0), (-1, -1), 4 * mm),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 4 * mm)]))
    hist += [Spacer(1, 3 * mm), aviso]

    def rodape(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(16 * mm, 12 * mm, A4[0] - 16 * mm, 12 * mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 8 * mm, 'Oliver · Relatório de risco de queimadas e alagamento · protótipo acadêmico')
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f'Página {doc_.page}')
        canvas.restoreState()

    doc.build(hist, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
