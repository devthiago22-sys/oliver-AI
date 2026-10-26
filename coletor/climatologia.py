"""Histórico mensal de focos de queimada no Maranhão (base da sinalização de 1 a 3 meses).

Baixa os arquivos anuais do INPE com os focos do "satélite de referência" (a série
oficial que o INPE usa para comparar anos) e conta, para cada município e para o
estado, quantos focos houve em cada mês de cada ano.

Saída: oliver/climatologia_ma.json (fica no repositório; o site lê do disco).
Rode uma vez por ano, quando o INPE publicar o arquivo do ano anterior
(GitHub Actions > "Atualizar histórico de queimadas" > Run workflow).
"""
import csv
import io
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

ANOS = list(range(int(os.environ.get('ANO_INICIAL', 2015)), datetime.now().year))  # anos completos
URL_MA = 'https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/EstadosBr_sat_ref/MA/focos_br_ma_ref_{ano}.zip'
URL_BR = 'https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_sat_ref/focos_br_ref_{ano}.zip'
MUNICIPIOS = 'https://raw.githubusercontent.com/devthiago22-sys/oliver-AI/dados/maranhao.json'
SAIDA = os.path.join(os.path.dirname(__file__), '..', 'oliver', 'climatologia_ma.json')
UA = {'User-Agent': 'Oliver-TCC/1.0 (projeto academico)'}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def baixar(url, timeout=180):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def normalizar(txt):
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ascii', 'ignore').decode()
    return ' '.join(txt.lower().replace('-', ' ').replace("'", ' ').split())


def coluna(campos, *opcoes):
    norm = {normalizar(c).replace(' ', '_'): c for c in campos}
    for o in opcoes:
        if o in norm:
            return norm[o]
    return None


def ler_ano(ano):
    """Devolve as linhas do CSV do ano (só Maranhão), tentando o arquivo estadual e depois o nacional."""
    for url, filtrar in ((URL_MA.format(ano=ano), False), (URL_BR.format(ano=ano), True)):
        try:
            conteudo = baixar(url)
        except urllib.error.HTTPError as e:
            log(f'{ano}: {url.rsplit("/", 1)[1]} → HTTP {e.code}')
            continue
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nome = next(n for n in z.namelist() if n.lower().endswith('.csv'))
            texto = z.read(nome).decode('utf-8', 'replace')
        leitor = csv.DictReader(io.StringIO(texto))
        campos = leitor.fieldnames or []
        c_estado = coluna(campos, 'estado', 'uf')
        linhas = [r for r in leitor if not filtrar or normalizar(r.get(c_estado, '')) in ('maranhao', 'ma')]
        log(f'{ano}: {url.rsplit("/", 1)[1]} · {len(linhas)} focos no MA · colunas: {campos}')
        return linhas, campos
    return None, None


def main():
    municipios = json.loads(baixar(MUNICIPIOS, 60).decode('utf-8'))['municipios']
    por_nome = {normalizar(m['nome']): cod for cod, m in municipios.items()}
    por_cod6 = {cod[:6]: cod for cod in municipios}  # alguns arquivos usam o código IBGE de 6 dígitos

    contagem = {cod: {} for cod in municipios}   # cod → ano → [12 meses]
    estado = {}
    anos_ok, sem_municipio = [], 0
    for ano in ANOS:
        linhas, campos = ler_ano(ano)
        if linhas is None:
            continue
        c_data = coluna(campos, 'data_pas', 'data_hora_gmt', 'datahora', 'data_hora', 'data')
        c_mun = coluna(campos, 'municipio', 'municipio_nome', 'nome_municipio')
        c_id = coluna(campos, 'municipio_id', 'id_municipio', 'cod_municipio', 'geocodigo')
        if not c_data:
            log(f'{ano}: coluna de data não encontrada, ano ignorado')
            continue
        anos_ok.append(ano)
        estado[ano] = [0] * 12
        for r in linhas:
            try:
                mes = int(str(r[c_data])[5:7])
            except (ValueError, KeyError):
                continue
            if not 1 <= mes <= 12:
                continue
            estado[ano][mes - 1] += 1
            cod = None
            if c_id:
                v = str(r.get(c_id) or '').strip().split('.')[0]
                cod = v if v in municipios else por_cod6.get(v[:6])
            if not cod and c_mun:
                cod = por_nome.get(normalizar(r.get(c_mun, '')))
            if not cod:
                sem_municipio += 1
                continue
            contagem[cod].setdefault(ano, [0] * 12)[mes - 1] += 1

    if len(anos_ok) < 5:
        log('Poucos anos baixados; nada foi salvo.')
        sys.exit(1)

    def resumo(series):
        """series: lista (um item por ano) de 12 contagens mensais."""
        n = len(series)
        meses = []
        for m in range(12):
            vals = sorted(s[m] for s in series)
            meses.append({
                'media': round(sum(vals) / n, 1),
                'mediana': vals[n // 2] if n % 2 else round((vals[n // 2 - 1] + vals[n // 2]) / 2, 1),
                'min': vals[0], 'max': vals[-1],
                'anos_com_foco': sum(1 for v in vals if v > 0),
            })
        return meses

    saida = {
        'gerado_em': datetime.now().strftime('%Y-%m-%d'),
        'fonte': 'INPE · Programa Queimadas · focos do satélite de referência (arquivos anuais)',
        'anos': anos_ok,
        'estado': {'meses': resumo([estado[a] for a in anos_ok]),
                   'por_ano': {str(a): estado[a] for a in anos_ok}},
        'municipios': {},
    }
    for cod, por_ano in contagem.items():
        series = [por_ano.get(a, [0] * 12) for a in anos_ok]
        saida['municipios'][cod] = {'meses': resumo(series), 'total_medio_ano': round(sum(sum(s) for s in series) / len(anos_ok), 1)}
    with open(SAIDA, 'w', encoding='utf-8') as f:
        json.dump(saida, f, ensure_ascii=False, separators=(',', ':'))
    log(f'OK: {len(anos_ok)} anos ({anos_ok[0]}–{anos_ok[-1]}), {sem_municipio} focos sem município identificado, '
        f'{os.path.getsize(SAIDA) // 1024} KB')
    medias = [m['media'] for m in saida['estado']['meses']]
    log('Média de focos por mês no MA:', dict(zip('jan fev mar abr mai jun jul ago set out nov dez'.split(), medias)))


if __name__ == '__main__':
    main()
