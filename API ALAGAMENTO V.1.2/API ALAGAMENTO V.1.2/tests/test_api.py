"""Testes automatizados. Execute no projeto: python -m unittest discover -s tests -v"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mainalagado as servidor


class TestesApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.arquivo = Path(self.tmp.name) / 'ocorrencias.json'
        self.alvo = patch.object(servidor, 'ARQUIVO_JSON', self.arquivo)
        self.alvo.start()
        servidor.app.config['TESTING'] = True
        self.cliente = servidor.app.test_client()

    def tearDown(self):
        self.alvo.stop()
        self.tmp.cleanup()

    def test_pagina_principal(self):
        resposta = self.cliente.get('/')
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b'Mapa de calor', resposta.data)

    def test_cadastro_sem_gps_edicao_comentario_e_exclusoes(self):
        # Seleção por clique envia coordenadas, sem obrigatoriedade de GPS.
        resposta = self.cliente.post('/api/ocorrencias', json={
            'latitude': -23.69, 'longitude': -46.56, 'descricao': 'Rua alagada'
        })
        self.assertEqual(resposta.status_code, 201)
        id_ponto = resposta.json['dados']['id']
        self.assertEqual(len(self.cliente.get('/api/ocorrencias').json), 1)

        resposta = self.cliente.post(f'/api/ocorrencias/{id_ponto}/comentarios', json={'texto': 'Água alta'})
        self.assertEqual(resposta.status_code, 201)
        id_comentario = resposta.json['dados']['id']

        resposta = self.cliente.put(f'/api/ocorrencias/{id_ponto}/comentarios/{id_comentario}',
                                    json={'texto': 'Água baixando'})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json['dados']['texto'], 'Água baixando')

        resposta = self.cliente.delete(f'/api/ocorrencias/{id_ponto}/comentarios/{id_comentario}')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.cliente.get('/api/ocorrencias').json[0]['comentarios'], [])

        resposta = self.cliente.delete(f'/api/ocorrencias/{id_ponto}')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.cliente.get('/api/ocorrencias').json, [])

    def test_validacoes_e_nao_encontrados(self):
        self.assertEqual(self.cliente.post('/api/ocorrencias', json={'latitude': 91, 'longitude': -40}).status_code, 400)
        self.assertEqual(self.cliente.post('/api/ocorrencias', json={'latitude': 'abc', 'longitude': 0}).status_code, 400)
        self.assertEqual(self.cliente.post('/api/ocorrencias', json={'latitude': 0, 'longitude': 0, 'descricao': 'x' * 1001}).status_code, 400)
        self.assertEqual(self.cliente.delete('/api/ocorrencias/inexistente').status_code, 404)
        self.assertEqual(self.cliente.post('/api/ocorrencias/inexistente/comentarios', json={'texto':'oi'}).status_code, 404)

    def test_dados_antigos_sem_campo_comentarios(self):
        self.arquivo.write_text(json.dumps([{'id': 'antigo', 'latitude': 0, 'longitude': 0,
                                            'descricao': 'Teste', 'data': '01/01/2026 00:00:00'}]), encoding='utf-8')
        resposta = self.cliente.post('/api/ocorrencias/antigo/comentarios', json={'texto':'Novo comentário'})
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(len(self.cliente.get('/api/ocorrencias').json[0]['comentarios']), 1)


if __name__ == '__main__':
    unittest.main()
