"""Testes meteorológicos sem rede; não gera chuva fictícia para o site."""
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta, timezone, datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import weather_service as weather


class TestesMeteorologia(unittest.TestCase):
    def test_49_amostras_reais_e_conversao_mm_por_hora(self):
        horario_sp = weather.agora_utc().astimezone(timezone(timedelta(hours=-3))).strftime('%Y-%m-%dT%H:%M')
        base_hora = weather.agora_utc().astimezone(timezone(timedelta(hours=-3))).replace(minute=0, second=0, microsecond=0)
        horas_previstas = [(base_hora + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(24)]
        def api_falsa(url):
            query = parse_qs(urlparse(url).query)
            count = len(query['latitude'][0].split(','))
            self.assertEqual(query['current'][0], 'precipitation')
            self.assertEqual(query['hourly'][0], 'precipitation')
            self.assertEqual(query['forecast_hours'][0], '24')
            return [
                {'current': {'precipitation': 1.5, 'interval': 900, 'time': horario_sp},
                 'hourly': {'time': horas_previstas, 'precipitation': [0.0]*6 + [2.5] + [0.0]*17}}
                for _ in range(count)
            ]
        dados = weather.consultar_modelo(baixar=api_falsa)
        self.assertEqual(len(dados['pontos']), 49)
        self.assertEqual(dados['pontos'][0]['intensidade_mm_h'], 6.0)
        self.assertEqual(dados['pontos'][0]['precipitacao_mm'], 1.5)
        self.assertEqual(len(dados['pontos_previsao_24h']), 49)
        self.assertEqual(dados['pontos_previsao_24h'][0]['intensidade_mm_h'], 2.5)
        self.assertEqual(dados['pontos_previsao_24h'][0]['acumulado_24h_mm'], 2.5)
        self.assertEqual(dados['pontos_previsao_24h'][0]['horario_pico'], horas_previstas[6])
        self.assertEqual(len(dados['latitudes']), 7)
        self.assertEqual(len(dados['longitudes']), 7)

    def test_uma_amostra_invalida_provoca_erro_sem_inventar_chuva(self):
        def api_falsa(url):
            count = len(parse_qs(urlparse(url).query)['latitude'][0].split(','))
            return [{'current': {'precipitation': None, 'interval': 900, 'time': '2026-10-22T14:15'}}] * count
        with self.assertRaises(ValueError):
            weather.consultar_modelo(baixar=api_falsa)

    def test_sem_chuva_24h_nao_cria_valores_ficticios(self):
        horario_sp = weather.agora_utc().astimezone(timezone(timedelta(hours=-3))).strftime('%Y-%m-%dT%H:%M')
        base_hora = weather.agora_utc().astimezone(timezone(timedelta(hours=-3))).replace(minute=0, second=0, microsecond=0)
        horas = [(base_hora + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(24)]
        def consulta(url):
            count = len(parse_qs(urlparse(url).query)['latitude'][0].split(','))
            return [{'current': {'precipitation': 0, 'interval': 900, 'time': horario_sp},
                     'hourly': {'time': horas, 'precipitation': [0.0] * 24}}
                    for _ in range(count)]
        dados = weather.consultar_modelo(baixar=consulta)
        self.assertTrue(all(p['intensidade_mm_h'] == 0 for p in dados['pontos']))
        self.assertTrue(all(p['intensidade_mm_h'] == 0 for p in dados['pontos_previsao_24h']))

    def test_previsao_incompleta_e_rejeitada(self):
        horario_sp = weather.agora_utc().astimezone(timezone(timedelta(hours=-3))).strftime('%Y-%m-%dT%H:%M')
        def consulta(url):
            count = len(parse_qs(urlparse(url).query)['latitude'][0].split(','))
            return [{'current': {'precipitation': 0, 'interval': 900, 'time': horario_sp},
                     'hourly': {'time': ['2026-10-22T12:00'], 'precipitation': [0.5]}}
                    for _ in range(count)]
        with self.assertRaises(ValueError):
            weather.consultar_modelo(baixar=consulta)

    def test_falha_na_api_nao_inventa_chuva(self):
        with tempfile.TemporaryDirectory() as pasta:
            with patch.object(weather, 'CACHE', Path(pasta) / 'cache.json'):
                with patch.object(weather, 'ULTIMA_TENTATIVA_CHUVA', None):
                    with patch.object(weather, 'consultar_modelo', side_effect=OSError('sem internet')):
                        resposta = weather.obter_painel_chuva()
                        self.assertFalse(resposta['disponivel'])
                        self.assertEqual(resposta['pontos'], [])

    def test_cache_vencido_nao_e_mostrado(self):
        with tempfile.TemporaryDirectory() as pasta:
            with patch.object(weather, 'CACHE', Path(pasta) / 'cache.json'):
                antigo = (weather.agora_utc() - timedelta(hours=3)).isoformat()
                weather.salvar_cache(weather.CACHE, {'consultado_em': antigo, 'pontos': [{'intensidade_mm_h': 25}]})
                with patch.object(weather, 'ULTIMA_TENTATIVA_CHUVA', None):
                    with patch.object(weather, 'consultar_modelo', side_effect=OSError('sem internet')):
                        resposta = weather.obter_painel_chuva()
                        self.assertFalse(resposta['disponivel'])
                        self.assertEqual(resposta['pontos'], [])

    def test_radar_com_metadata_recente(self):
        timestamp = int(weather.agora_utc().timestamp()) - 60
        def mock(_):
            return {'host': 'https://tilecache.rainviewer.com',
                    'radar': {'past': [{'time': timestamp, 'path': '/v2/radar/abcdef123456'}]}}
        dados = weather.consultar_radar_remoto(baixar=mock)
        self.assertIn('/256/{z}/{x}/{y}/2/1_0.png', dados['tile_url'])

    def test_radar_antigo_rejeitado(self):
        timestamp = int(weather.agora_utc().timestamp()) - (3 * 3600)
        def mock(_):
            return {'host': 'https://tilecache.rainviewer.com',
                    'radar': {'past': [{'time': timestamp, 'path': '/v2/radar/abcdef123456'}]}}
        with self.assertRaises(ValueError):
            weather.consultar_radar_remoto(baixar=mock)


if __name__ == '__main__':
    unittest.main()
