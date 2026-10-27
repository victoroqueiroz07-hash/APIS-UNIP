"""Mapa colaborativo de alagamentos: aplicativo Flask para projeto acadêmico.

Execute com: python mainalagado.py
"""
from datetime import datetime
from pathlib import Path
from threading import RLock
import json
import math
import os
import tempfile
import uuid

from flask import Flask, jsonify, render_template, request

from weather_service import obter_painel_chuva, obter_radar

BASE = Path(__file__).resolve().parent
ARQUIVO_JSON = BASE / "ocorrencias.json"
BLOQUEIO = RLock()

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def gravar_json_atomicamente(caminho, dados):
    fd, temporario = tempfile.mkstemp(prefix="dados_", suffix=".tmp", dir=str(caminho.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        os.replace(temporario, caminho)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def ler_ocorrencias():
    with BLOQUEIO:
        if not ARQUIVO_JSON.exists():
            gravar_json_atomicamente(ARQUIVO_JSON, [])
        with ARQUIVO_JSON.open(encoding="utf-8") as arquivo:
            conteudo = json.load(arquivo)
            if not isinstance(conteudo, list):
                raise ValueError("O arquivo de ocorrências precisa conter uma lista JSON.")
            # Compatível com dados criados antes da função de comentários.
            for ocorrencia in conteudo:
                ocorrencia.setdefault("comentarios", [])
            return conteudo


def localizar(dados, identificador):
    return next((item for item in dados if item.get("id") == identificador), None)


def dados_json():
    valor = request.get_json(silent=True)
    return valor if isinstance(valor, dict) else None


def mensagem_erro(texto, codigo):
    return jsonify(erro=texto), codigo


def texto_valido(valor, tamanho, obrigatorio=True):
    if not isinstance(valor, str) or len(valor) > tamanho:
        return None
    valor = valor.strip()
    return valor if valor or not obrigatorio else None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/ocorrencias")
def listar_ocorrencias():
    return jsonify(ler_ocorrencias())


@app.post("/api/ocorrencias")
def registrar_ocorrencia():
    payload = dados_json()
    if payload is None:
        return mensagem_erro("Envie um JSON válido.", 400)
    try:
        lat = float(payload.get("latitude"))
        lon = float(payload.get("longitude"))
    except (TypeError, ValueError, OverflowError):
        return mensagem_erro("Latitude e longitude devem ser números.", 400)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return mensagem_erro("Coordenadas geográficas inválidas.", 400)
    descricao = texto_valido(payload.get("descricao", ""), 1000, obrigatorio=False)
    if descricao is None:
        return mensagem_erro("A descrição deve conter até 1.000 caracteres.", 400)
    ocorrencia = {
        "id": str(uuid.uuid4()),
        "latitude": lat,
        "longitude": lon,
        "descricao": descricao or "Alagamento relatado por um usuário.",
        "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "criado_em": agora(),
        "comentarios": [],
    }
    with BLOQUEIO:
        dados = ler_ocorrencias()
        dados.append(ocorrencia)
        gravar_json_atomicamente(ARQUIVO_JSON, dados)
    return jsonify(mensagem="Ocorrência registrada com sucesso.", dados=ocorrencia), 201


@app.delete("/api/ocorrencias/<identificador>")
def excluir_ocorrencia(identificador):
    with BLOQUEIO:
        dados = ler_ocorrencias()
        ocorrencia = localizar(dados, identificador)
        if ocorrencia is None:
            return mensagem_erro("Ocorrência não encontrada.", 404)
        dados.remove(ocorrencia)
        gravar_json_atomicamente(ARQUIVO_JSON, dados)
    return jsonify(mensagem="Ocorrência e comentários excluídos.")


@app.post("/api/ocorrencias/<identificador>/comentarios")
def adicionar_comentario(identificador):
    payload = dados_json()
    texto = texto_valido(payload.get("texto"), 500) if payload else None
    if texto is None:
        return mensagem_erro("Escreva um comentário de 1 a 500 caracteres.", 400)
    with BLOQUEIO:
        dados = ler_ocorrencias()
        ocorrencia = localizar(dados, identificador)
        if ocorrencia is None:
            return mensagem_erro("Ocorrência não encontrada.", 404)
        comentario = {"id": str(uuid.uuid4()), "texto": texto, "data": agora()}
        ocorrencia["comentarios"].append(comentario)
        gravar_json_atomicamente(ARQUIVO_JSON, dados)
    return jsonify(mensagem="Comentário adicionado.", dados=comentario), 201


@app.put("/api/ocorrencias/<identificador>/comentarios/<comentario_id>")
def editar_comentario(identificador, comentario_id):
    payload = dados_json()
    texto = texto_valido(payload.get("texto"), 500) if payload else None
    if texto is None:
        return mensagem_erro("Escreva um comentário de 1 a 500 caracteres.", 400)
    with BLOQUEIO:
        dados = ler_ocorrencias()
        ocorrencia = localizar(dados, identificador)
        if ocorrencia is None:
            return mensagem_erro("Ocorrência não encontrada.", 404)
        comentario = localizar(ocorrencia["comentarios"], comentario_id)
        if comentario is None:
            return mensagem_erro("Comentário não encontrado.", 404)
        comentario.update(texto=texto, editado_em=agora())
        gravar_json_atomicamente(ARQUIVO_JSON, dados)
    return jsonify(mensagem="Comentário editado.", dados=comentario)


@app.delete("/api/ocorrencias/<identificador>/comentarios/<comentario_id>")
def excluir_comentario(identificador, comentario_id):
    with BLOQUEIO:
        dados = ler_ocorrencias()
        ocorrencia = localizar(dados, identificador)
        if ocorrencia is None:
            return mensagem_erro("Ocorrência não encontrada.", 404)
        comentario = localizar(ocorrencia["comentarios"], comentario_id)
        if comentario is None:
            return mensagem_erro("Comentário não encontrado.", 404)
        ocorrencia["comentarios"].remove(comentario)
        gravar_json_atomicamente(ARQUIVO_JSON, dados)
    return jsonify(mensagem="Comentário excluído.")


@app.get("/api/chuva")
def consultar_chuva():
    """A estimativa atual tem validade limitada; não é mapa oficial de inundação."""
    return jsonify(obter_painel_chuva())


@app.get("/api/radar")
def consultar_radar():
    """Fornece apenas metadados e URLs válidas para radar recente."""
    return jsonify(obter_radar())


@app.get("/api/saude")
def saude():
    return jsonify(status="ok")


if __name__ == "__main__":
    # Atualiza o cache na primeira consulta e periodicamente enquanto a página estiver aberta.
    # Sem servidor ligado, não existe monitoramento em segundo plano.
    print("Abra no navegador: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
