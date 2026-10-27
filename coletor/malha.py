"""Contornos (polígonos) dos 217 municípios do Maranhão, para a exportação em SIG.

Fonte principal: IBGE · API de malhas (v3). Reserva: geodata-br (derivado da malha do IBGE).
Simplifica as linhas (Douglas-Peucker, ~150 m) para o arquivo ficar leve e salva em
oliver/malha_ma.json. Rode à mão quando o IBGE publicar malha nova:
GitHub Actions > "Atualizar malha dos municípios" > Run workflow.
"""
import json
import os
import sys
import time
import urllib.request

URLS = [
    ('IBGE · Malha municipal (API de malhas v3)',
     'https://servicodados.ibge.gov.br/api/v3/malhas/estados/21?formato=application/vnd.geo%2Bjson'
     '&qualidade=intermediaria&intrarregiao=municipio'),
    ('geodata-br (derivado da malha municipal do IBGE)',
     'https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-21-mun.json'),
]
SAIDA = os.path.join(os.path.dirname(__file__), '..', 'oliver', 'malha_ma.json')
TOLERANCIA = 0.0015  # graus (~150 m)
UA = {'User-Agent': 'Oliver-TCC/1.0 (projeto academico)'}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def baixar(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:  # noqa: BLE001
            log(f'tentativa {i + 1}: {e}')
            time.sleep(5 * (i + 1))
    return None


def _dist_seg(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** .5
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** .5


def simplificar(pts, tol):
    """Douglas-Peucker iterativo; mantém primeiro e último ponto."""
    if len(pts) < 5:
        return pts
    manter = [False] * len(pts)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pts) - 1)]
    while pilha:
        i, j = pilha.pop()
        maior, idx = 0, None
        for k in range(i + 1, j):
            d = _dist_seg(pts[k], pts[i], pts[j])
            if d > maior:
                maior, idx = d, k
        if idx is not None and maior > tol:
            manter[idx] = True
            pilha += [(i, idx), (idx, j)]
    out = [p for p, m in zip(pts, manter) if m]
    return out if len(out) >= 4 else pts[:1] + pts[len(pts) // 3:len(pts) // 3 + 1] + pts[2 * len(pts) // 3:2 * len(pts) // 3 + 1] + pts[:1]


def main():
    for fonte, url in URLS:
        gj = baixar(url)
        if not gj or not gj.get('features'):
            log(f'{fonte}: sem dados')
            continue
        municipios = {}
        for f in gj['features']:
            pr = f.get('properties') or {}
            cod = str(pr.get('codarea') or pr.get('id') or pr.get('CD_MUN') or pr.get('cod') or '').strip()[:7]
            g = f.get('geometry') or {}
            polys = g['coordinates'] if g.get('type') == 'MultiPolygon' else [g.get('coordinates') or []]
            novo = []
            for poly in polys:
                aneis = []
                for anel in poly:
                    s = [[round(x, 5), round(y, 5)] for x, y in simplificar([tuple(p[:2]) for p in anel], TOLERANCIA)]
                    if s[0] != s[-1]:
                        s.append(s[0])
                    if len(s) >= 4:
                        aneis.append(s)
                if aneis:
                    novo.append(aneis)
            if cod and novo:
                municipios[cod] = novo
        if len(municipios) < 200:
            log(f'{fonte}: só {len(municipios)} municípios, tentando a próxima fonte')
            continue
        with open(SAIDA, 'w', encoding='utf-8') as fh:
            json.dump({'fonte': fonte, 'gerado_em': time.strftime('%Y-%m-%d'), 'crs': 'EPSG:4326',
                       'municipios': municipios}, fh, separators=(',', ':'))
        log(f'OK: {fonte} · {len(municipios)} municípios · {os.path.getsize(SAIDA) // 1024} KB')
        return
    log('Nenhuma fonte respondeu.')
    sys.exit(1)


if __name__ == '__main__':
    main()
