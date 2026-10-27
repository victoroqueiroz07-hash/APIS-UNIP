"""Dados meteorológicos atuais, sem ocorrências simuladas.

Open-Meteo: precipitação atual MODELO NUMÉRICO em mm no intervalo retornado,
convertida para intensidade equivalente em mm/h. Não é dado medido nem mapa
oficial de alagamentos. RainViewer: imagens recentes de radar observado.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import math
import os
import re
import tempfile

BASE = Path(__file__).resolve().parent
CACHE = BASE / 'cache_chuva_v2.json'
CACHE_RADAR = BASE / 'cache_radar.json'
ENDPOINT = 'https://api.open-meteo.com/v1/forecast'
RADAR_ENDPOINT = 'https://api.rainviewer.com/public/weather-maps.json'
INTERVALO_CHUVA = timedelta(minutes=20)
VALIDADE_CHUVA = timedelta(minutes=75)
INTERVALO_RADAR = timedelta(minutes=8)
VALIDADE_RADAR = timedelta(minutes=30)
REPETIR_FALHA = timedelta(minutes=3)
TRAVA = Lock()
ULTIMA_TENTATIVA_CHUVA = None
ULTIMA_TENTATIVA_RADAR = None

# 7 x 7 coordenadas amostradas no modelo meteorológico, cobrindo o Grande ABC e adjacências.
# A resolução do modelo é inferior à da grade: interpolação não gera precisão por rua.
LATITUDES = [-23.82, -23.78, -23.74, -23.70, -23.66, -23.62, -23.58]
LONGITUDES = [-46.72, -46.66, -46.60, -46.54, -46.48, -46.42, -46.36]
GRADE = [(lat, lon) for lat in LATITUDES for lon in LONGITUDES]


def agora_utc():
    return datetime.now(timezone.utc)


def ler_cache(caminho):
    try:
        dado = json.loads(caminho.read_text(encoding='utf-8'))
        return dado if isinstance(dado, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def salvar_cache(caminho, dados):
    fd, nome = tempfile.mkstemp(prefix='clima_', suffix='.tmp', dir=str(caminho.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        os.replace(nome, caminho)
    finally:
        if os.path.exists(nome):
            os.unlink(nome)


def idade(dados):
    try:
        atualizacao = datetime.fromisoformat(dados['consultado_em'])
        return agora_utc() - atualizacao if atualizacao.tzinfo else None
    except (ValueError, KeyError, TypeError):
        return None


def baixar_json(url, timeout=20):
    req = Request(url, headers={'User-Agent': 'AlertaABCAcademico/2.0'})
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def consultar_modelo(baixar=baixar_json):
    pontos = []
    horarios = []
    horarios_previsao = None
    pontos_previsao = []
    # Lotes reduzem a chance de extrapolar limite de coordenadas por chamada.
    for inicio in range(0, len(GRADE), 15):
        fatia = GRADE[inicio:inicio + 15]
        parametros = {
            'latitude': ','.join(str(lat) for lat, _ in fatia),
            'longitude': ','.join(str(lon) for _, lon in fatia),
            'current': 'precipitation',
            'hourly': 'precipitation',
            'forecast_hours': 24,
            'timezone': 'America/Sao_Paulo',
        }
        resposta = baixar(ENDPOINT + '?' + urlencode(parametros))
        registros = resposta if isinstance(resposta, list) else [resposta]
        if len(registros) != len(fatia):
            raise ValueError('A API retornou menos coordenadas do que o solicitado.')
        for (lat, lon), dado in zip(fatia, registros):
            atual = dado.get('current', {})
            intervalo = atual.get('interval')
            valor = atual.get('precipitation')
            horario = atual.get('time')
            if not isinstance(intervalo, (int, float)) or not 0 < intervalo <= 10800:
                raise ValueError('Intervalo da precipitação inválido na Open-Meteo.')
            if not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
                raise ValueError('Precipitação ausente ou inválida em uma amostra.')
            if not isinstance(horario, str):
                raise ValueError('Hora da precipitação não informada pela API.')
            # Converte quantidade de água no intervalo (mm) para a intensidade
            # equivalente de uma hora. Não é uma medição de pluviômetro.
            mm_h = valor * 3600.0 / intervalo
            pontos.append({'latitude': lat, 'longitude': lon,
                           'precipitacao_mm': round(valor, 3),
                           'intervalo_segundos': intervalo,
                           'intensidade_mm_h': round(mm_h, 3)})
            horarios.append(horario)
            hourly = dado.get('hourly') or {}
            horas = hourly.get('time')
            quantidades = hourly.get('precipitation')
            if not isinstance(horas, list) or not isinstance(quantidades, list) or len(horas) != 24 or len(quantidades) != 24:
                raise ValueError('Previsão horária incompleta; eram esperadas 24 horas.')
            if not all(isinstance(h, str) for h in horas):
                raise ValueError('Horário previsto inválido.')
            if horarios_previsao is None:
                horarios_previsao = horas
            elif horarios_previsao != horas:
                raise ValueError('Horários da previsão divergentes entre coordenadas.')
            if any(not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in quantidades):
                raise ValueError('A previsão inclui valores ausentes ou inválidos.')
            maximo = max(quantidades)
            indice_maximo = quantidades.index(maximo)
            pontos_previsao.append({'latitude': lat, 'longitude': lon,
                                    'intensidade_mm_h': round(maximo, 3),
                                    'acumulado_24h_mm': round(sum(quantidades), 3),
                                    'horario_pico': horas[indice_maximo] if maximo > 0 else None})
    if len(pontos) != len(GRADE) or len(pontos_previsao) != len(GRADE) or len(set(horarios)) != 1:
        raise ValueError('As amostras não foram retornadas no mesmo horário meteorológico.')
    # Rejeita dados remotos de uma execução antiga do modelo (horário local SP).
    horario_local = datetime.fromisoformat(horarios[0]).replace(tzinfo=timezone(timedelta(hours=-3)))
    atraso = (agora_utc() - horario_local.astimezone(timezone.utc)).total_seconds()
    if not -1800 <= atraso <= 7200:
        raise ValueError('Modelo meteorológico retornou um horário desatualizado.')
    # forecast_hours retorna uma série iniciada na hora atual e com 24 intervalos.
    # Os instantes que compõem a série devem estar próximos do horário presente.
    primeira_hora = datetime.fromisoformat(horarios_previsao[0]).replace(tzinfo=timezone(timedelta(hours=-3)))
    atraso_previsao = (agora_utc() - primeira_hora.astimezone(timezone.utc)).total_seconds()
    if not -3600 <= atraso_previsao <= 7200:
        raise ValueError('A previsão horária recebida está desatualizada.')
    return {'consultado_em': agora_utc().isoformat(timespec='seconds'),
            'horario_modelo': horarios[0],
            'inicio_previsao': horarios_previsao[0],
            'fim_previsao': horarios_previsao[-1],
            'pontos_previsao_24h': pontos_previsao,
            'pontos': pontos,
            'latitudes': LATITUDES, 'longitudes': LONGITUDES,
            'fonte': 'Open-Meteo (estimativa atual de modelo meteorológico)',
            'descricao': 'Chuva atual estimada e pico horário previsto nas próximas 24 horas, em mm/h. Não são medições diretas nem mapas oficiais de alagamento.'}


def consultar_radar_remoto(baixar=baixar_json):
    conteudo = baixar(RADAR_ENDPOINT)
    if not isinstance(conteudo, dict):
        raise ValueError('Radar retornou formato inválido.')
    # Hospedagem fixada para evitar URLs externas arbitrárias no frontend.
    if conteudo.get('host') != 'https://tilecache.rainviewer.com':
        raise ValueError('Host de radar não autorizado.')
    quadros = (conteudo.get('radar') or {}).get('past') or []
    if not isinstance(quadros, list) or not quadros:
        raise ValueError('Nenhuma imagem recente de radar disponível.')
    quadro = max(quadros, key=lambda item: item.get('time', -1))
    momento = int(quadro['time'])
    caminho = quadro['path']
    if not isinstance(caminho, str) or not re.fullmatch(r'/v2/radar/[A-Za-z0-9]+', caminho):
        raise ValueError('Caminho de radar inválido.')
    diferenca = abs((agora_utc() - datetime.fromtimestamp(momento, tz=timezone.utc)).total_seconds())
    if diferenca > 45 * 60:
        raise ValueError('Imagem de radar desatualizada.')
    return {'consultado_em': agora_utc().isoformat(timespec='seconds'),
            'horario_radar': datetime.fromtimestamp(momento, tz=timezone.utc).isoformat(timespec='seconds'),
            'tile_url': 'https://tilecache.rainviewer.com' + caminho + '/256/{z}/{x}/{y}/2/1_0.png',
            'fonte': 'RainViewer (radar de precipitação observada, cores Universal Blue)',
            'descricao': 'Imagens recentes de radar; alcance e disponibilidade variam conforme cobertura. Resolução gratuita até zoom 7.'}


def _atualizar(caminho, intervalo, ultima_tentativa, funcao):
    dados = ler_cache(caminho)
    tempo = idade(dados)
    if tempo is not None and timedelta(0) <= tempo < intervalo:
        return dados, ultima_tentativa
    if ultima_tentativa and agora_utc() - ultima_tentativa < REPETIR_FALHA:
        return dados, ultima_tentativa
    ultima_tentativa = agora_utc()
    try:
        dados = funcao()
        salvar_cache(caminho, dados)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        pass  # O endpoint retornará indisponibilidade quando não houver cache válido.
    return dados, ultima_tentativa


def obter_painel_chuva():
    global ULTIMA_TENTATIVA_CHUVA
    with TRAVA:
        dado, ULTIMA_TENTATIVA_CHUVA = _atualizar(
            CACHE, INTERVALO_CHUVA, ULTIMA_TENTATIVA_CHUVA, consultar_modelo)
        tempo = idade(dado)
        if tempo is None or not timedelta(0) <= tempo < VALIDADE_CHUVA:
            return {'disponivel': False, 'pontos': [],
                    'mensagem': 'Modelo de chuva indisponível ou desatualizado. Não serão exibidos dados de demonstração.'}
        return {**dado, 'disponivel': True,
                'mensagem': 'Estimativa atual de precipitação recebida.',
                'aviso': 'Estimativa meteorológica, não medição direta e não mapa oficial de alagamentos.'}


def obter_radar():
    global ULTIMA_TENTATIVA_RADAR
    with TRAVA:
        dado, ULTIMA_TENTATIVA_RADAR = _atualizar(
            CACHE_RADAR, INTERVALO_RADAR, ULTIMA_TENTATIVA_RADAR, consultar_radar_remoto)
        tempo = idade(dado)
        if tempo is None or not timedelta(0) <= tempo < VALIDADE_RADAR:
            return {'disponivel': False, 'mensagem': 'Radar recente indisponível. Verifique a conexão ou a cobertura local.'}
        # Uma imagem antiga não pode ser rotulada como radar ao vivo.
        try:
            delta = abs((agora_utc() - datetime.fromisoformat(dado['horario_radar'])).total_seconds())
            if delta > 45 * 60:
                raise ValueError('Imagem antiga')
        except (KeyError, ValueError, TypeError):
            return {'disponivel': False, 'mensagem': 'Sem imagem de radar suficientemente recente.'}
        return {**dado, 'disponivel': True, 'mensagem': 'Imagem recente de radar disponível.'}


