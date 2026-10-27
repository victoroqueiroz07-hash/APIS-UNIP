'use strict';

// AlertaABC — frontend. Não depende de GPS para registrar ocorrências.
const $ = (id) => document.getElementById(id);
const CENTRO_ABC = [-23.677, -46.548];
const CAMADA_OSM = {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
};

if (typeof L === 'undefined') {
  $('mensagem').textContent = 'Não foi possível carregar a biblioteca do mapa. Verifique sua conexão com a internet.';
  throw new Error('Leaflet não carregado');
}

const mapaOcorrencias = L.map('mapa-ocorrencias').setView(CENTRO_ABC, 12);
const mapaChuva = L.map('mapa-chuva').setView(CENTRO_ABC, 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', CAMADA_OSM).addTo(mapaOcorrencias);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', CAMADA_OSM).addTo(mapaChuva);
const camadaOcorrencias = L.layerGroup().addTo(mapaOcorrencias);
let marcadorSelecao = null;
let pontoSelecionado = null;
let ocorrencias = [];
let mapaDeCalor = null;
let camadaRadar = null;
let limiteGrade = null;
let modeloAtual = null;
let radarAtual = null;
let chuvaFoiConsultada = false;

function mensagem(texto, erro = false) {
  const el = $('mensagem');
  el.textContent = texto;
  el.style.color = erro ? '#b42335' : '#067c71';
}
function mensagemPopup(container, texto) {
  let erro = container.querySelector('.popup-erro');
  if (!erro) {
    erro = textoElemento('p', '');
    erro.className = 'popup-erro';
    container.append(erro);
  }
  erro.textContent = texto;
}
function textoElemento(tag, texto, classe = '') {
  const el = document.createElement(tag);
  el.textContent = texto ?? '';
  if (classe) el.className = classe;
  return el;
}
function botaoPopup(rotulo, classe, tarefa, container) {
  const botao = textoElemento('button', rotulo, 'popup-botao ' + classe);
  botao.type = 'button';
  botao.addEventListener('click', async () => {
    botao.disabled = true;
    try { await tarefa(); }
    catch (erro) { mensagemPopup(container, erro.message); }
    finally { botao.disabled = false; }
  });
  return botao;
}
function opcoesJson(method, objeto) {
  return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(objeto)};
}
async function api(url, opcoes = {}) {
  const resposta = await fetch(url, opcoes);
  let dados;
  try { dados = await resposta.json(); }
  catch (_) { throw new Error('Resposta inválida do servidor. Confira o terminal do VS Code.'); }
  if (!resposta.ok) throw new Error(dados.erro || 'Erro na comunicação com o servidor.');
  return dados;
}
function dataLegivel(value) {
  if (!value) return 'Não informada';
  const data = new Date(value);
  return Number.isNaN(data.getTime()) ? value : data.toLocaleString('pt-BR');
}

async function carregarOcorrencias(idParaAbrir = null) {
  ocorrencias = await api('/api/ocorrencias');
  camadaOcorrencias.clearLayers();
  $('total-ocorrencias').textContent = ocorrencias.length;
  for (const ocorrencia of ocorrencias) {
    const lat = Number(ocorrencia.latitude);
    const lon = Number(ocorrencia.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    const marcador = L.marker([lat, lon]).addTo(camadaOcorrencias);
    marcador.bindPopup(() => criarPopup(ocorrencia), {maxWidth: 340, autoPanPadding: [35, 35]});
    if (idParaAbrir === ocorrencia.id) marcador.openPopup();
  }
}

function criarPopup(ocorrencia) {
  const div = textoElemento('div', '', 'popup-conteudo');
  div.append(textoElemento('h3', 'Relato de alagamento'));
  div.append(textoElemento('p', ocorrencia.descricao));
  div.append(textoElemento('time', ocorrencia.data || dataLegivel(ocorrencia.criado_em)));
  const separador = document.createElement('hr');
  separador.className = 'popup-separador';
  div.append(separador);
  div.append(botaoPopup('Excluir este ponto', 'perigo', async () => {
    if (!window.confirm('Excluir definitivamente este ponto e todos os comentários?')) return;
    const resposta = await api('/api/ocorrencias/' + encodeURIComponent(ocorrencia.id), {method: 'DELETE'});
    mapaOcorrencias.closePopup();
    await carregarOcorrencias();
    mensagem(resposta.mensagem);
  }, div));
  div.append(textoElemento('h4', `Comentários (${(ocorrencia.comentarios || []).length})`));

  if (!(ocorrencia.comentarios || []).length) {
    div.append(textoElemento('p', 'Nenhum comentário cadastrado.', 'mensagem-vazia'));
  }
  for (const comentario of (ocorrencia.comentarios || [])) {
    const area = textoElemento('section', '', 'popup-comentario');
    area.append(textoElemento('p', comentario.texto));
    area.append(textoElemento('time', dataLegivel(comentario.data) + (comentario.editado_em ? ' · editado' : '')));
    area.append(document.createElement('br'));
    area.append(botaoPopup('Editar', 'secundario', async () => {
      if (area.querySelector('textarea')) return;
      const campo = document.createElement('textarea');
      campo.maxLength = 500;
      campo.value = comentario.texto;
      campo.setAttribute('aria-label', 'Editar comentário');
      const btnSalvar = botaoPopup('Salvar alterações', '', async () => {
        const atualizado = campo.value.trim();
        if (!atualizado) { mensagemPopup(div, 'O comentário não pode ficar vazio.'); return; }
        await api(`/api/ocorrencias/${encodeURIComponent(ocorrencia.id)}/comentarios/${encodeURIComponent(comentario.id)}`,
          opcoesJson('PUT', {texto: atualizado}));
        await carregarOcorrencias(ocorrencia.id);
      }, div);
      const btnCancelar = botaoPopup('Cancelar', 'secundario', async () => {
        campo.remove(); btnSalvar.remove(); btnCancelar.remove();
      }, div);
      area.append(campo, btnSalvar, btnCancelar);
      campo.focus();
    }, div));
    area.append(botaoPopup('Excluir', 'perigo', async () => {
      if (!window.confirm('Excluir este comentário?')) return;
      await api(`/api/ocorrencias/${encodeURIComponent(ocorrencia.id)}/comentarios/${encodeURIComponent(comentario.id)}`, {method: 'DELETE'});
      await carregarOcorrencias(ocorrencia.id);
    }, div));
    div.append(area);
  }
  const formulario = textoElemento('div', '', 'popup-form');
  const campoNovo = document.createElement('textarea');
  campoNovo.maxLength = 500;
  campoNovo.placeholder = 'Escreva um comentário...';
  campoNovo.setAttribute('aria-label', 'Escreva um comentário');
  formulario.append(campoNovo);
  formulario.append(botaoPopup('Enviar comentário', '', async () => {
    const texto = campoNovo.value.trim();
    if (!texto) { mensagemPopup(div, 'Digite um comentário.'); return; }
    await api(`/api/ocorrencias/${encodeURIComponent(ocorrencia.id)}/comentarios`, opcoesJson('POST', {texto}));
    await carregarOcorrencias(ocorrencia.id);
  }, div));
  div.append(formulario);
  return div;
}

function selecionarPonto(lat, lon) {
  pontoSelecionado = {latitude: lat, longitude: lon};
  $('ponto-escolhido').textContent = `Latitude ${lat.toFixed(6)} · Longitude ${lon.toFixed(6)}`;
  if (marcadorSelecao) marcadorSelecao.remove();
  marcadorSelecao = L.circleMarker([lat, lon], {
    radius: 10, color: '#fff', weight: 3, fillColor: '#0baf82', fillOpacity: 1
  }).addTo(mapaOcorrencias).bindPopup('Local escolhido para cadastrar um novo alagamento.');
  mensagem('Local selecionado. Agora você pode registrar o alagamento.');
}
mapaOcorrencias.on('click', (evento) => selecionarPonto(evento.latlng.lat, evento.latlng.lng));
$('botao-gps').addEventListener('click', () => {
  if (!navigator.geolocation) {
    mensagem('Seu navegador não oferece acesso ao GPS.', true);
    return;
  }
  mensagem('O navegador poderá solicitar autorização para sua localização...');
  navigator.geolocation.getCurrentPosition(posicao => {
    selecionarPonto(posicao.coords.latitude, posicao.coords.longitude);
    mapaOcorrencias.setView([posicao.coords.latitude, posicao.coords.longitude], 16);
  }, () => mensagem('Localização não autorizada ou indisponível. Você pode clicar no mapa normalmente.', true),
  {enableHighAccuracy: true, timeout: 10000});
});
$('botao-registrar').addEventListener('click', async () => {
  if (!pontoSelecionado) { mensagem('Primeiro clique em um ponto do mapa.', true); return; }
  const botao = $('botao-registrar');
  botao.disabled = true;
  try {
    const resultado = await api('/api/ocorrencias', opcoesJson('POST', {
      ...pontoSelecionado, descricao: $('descricao').value.trim()
    }));
    $('descricao').value = '';
    $('ponto-escolhido').textContent = 'Nenhum ponto selecionado.';
    pontoSelecionado = null;
    if (marcadorSelecao) { marcadorSelecao.remove(); marcadorSelecao = null; }
    await carregarOcorrencias(resultado.dados.id);
    mensagem(resultado.mensagem);
  } catch (erro) { mensagem(erro.message, true); }
  finally { botao.disabled = false; }
});
$('atualizar-ocorrencias').addEventListener('click', async () => {
  try { await carregarOcorrencias(); mensagem('Ocorrências atualizadas.'); }
  catch (erro) { mensagem(erro.message, true); }
});

// Paleta fixa de intensidade equivalente de chuva (mm/h) do MODELO.
// As cores são mais saturadas visualmente, mas os limiares não mudam.
const FAIXAS_COR = [
  [0.1, [34, 141, 231]], [1, [35, 199, 120]],
  [3, [245, 233, 76]], [6, [255, 157, 52]],
  [12, [233, 58, 70]], [20, [158, 39, 130]]
];
function corDaChuva(valor) {
  if (valor < 0.1) return [0, 0, 0, 0];
  let anterior = FAIXAS_COR[0];
  for (let i = 1; i < FAIXAS_COR.length; i++) {
    const seguinte = FAIXAS_COR[i];
    if (valor <= seguinte[0]) {
      const frac = (valor - anterior[0]) / (seguinte[0] - anterior[0]);
      const rgb = anterior[1].map((canal, index) => Math.round(canal + (seguinte[1][index] - canal) * frac));
      return [...rgb, 228];
    }
    anterior = seguinte;
  }
  return [...FAIXAS_COR[FAIXAS_COR.length - 1][1], 228];
}
function valorInterpolado(lat, lon, dados) {
  const lats = dados.latitudes, lons = dados.longitudes;
  if (lat < lats[0] || lat > lats[lats.length - 1] || lon < lons[0] || lon > lons[lons.length - 1]) return null;
  // Posições igualmente espaçadas; interpolação bilinear entre 4 amostras da API.
  const li = Math.min(lats.length - 2, Math.floor((lat - lats[0]) / (lats[1] - lats[0])));
  const ci = Math.min(lons.length - 2, Math.floor((lon - lons[0]) / (lons[1] - lons[0])));
  const fy = Math.max(0, Math.min(1, (lat - lats[li]) / (lats[li + 1] - lats[li])));
  const fx = Math.max(0, Math.min(1, (lon - lons[ci]) / (lons[ci + 1] - lons[ci])));
  const largura = lons.length;
  const v00 = dados.pontos[li * largura + ci].intensidade_mm_h;
  const v01 = dados.pontos[li * largura + ci + 1].intensidade_mm_h;
  const v10 = dados.pontos[(li + 1) * largura + ci].intensidade_mm_h;
  const v11 = dados.pontos[(li + 1) * largura + ci + 1].intensidade_mm_h;
  return (1 - fy) * ((1 - fx) * v00 + fx * v01) + fy * ((1 - fx) * v10 + fx * v11);
}
function construirImagemDeCalor(dados) {
  const canvas = document.createElement('canvas');
  canvas.width = 700; canvas.height = 510;
  const ctx = canvas.getContext('2d');
  const pixels = ctx.createImageData(canvas.width, canvas.height);
  const lats = dados.latitudes, lons = dados.longitudes;
  const minLat = lats[0], maxLat = lats[lats.length - 1];
  const minLon = lons[0], maxLon = lons[lons.length - 1];
  // Calcula a cor de cada pixel usando APENAS os valores retornados pela API.
  // Não adiciona hotspots, dados falsos ou pontos comunitários.
  for (let y = 0; y < canvas.height; y++) {
    const lat = maxLat - y * (maxLat - minLat) / (canvas.height - 1);
    for (let x = 0; x < canvas.width; x++) {
      const lon = minLon + x * (maxLon - minLon) / (canvas.width - 1);
      const estimado = valorInterpolado(lat, lon, dados);
      const rgba = corDaChuva(estimado ?? 0);
      const i = (y * canvas.width + x) * 4;
      pixels.data[i] = rgba[0];
      pixels.data[i + 1] = rgba[1];
      pixels.data[i + 2] = rgba[2];
      // Suaviza apenas bordas do recorte geográfico, sem alterar intensidade.
      const borda = Math.min(x, y, canvas.width - 1 - x, canvas.height - 1 - y);
      const suavizacao = Math.min(1, borda / 27);
      pixels.data[i + 3] = Math.round(rgba[3] * suavizacao);
    }
  }
  ctx.putImageData(pixels, 0, 0);
  return canvas.toDataURL('image/png');
}
function removerCamadasChuva() {
  if (mapaDeCalor) { mapaChuva.removeLayer(mapaDeCalor); mapaDeCalor = null; }
  if (camadaRadar) { mapaChuva.removeLayer(camadaRadar); camadaRadar = null; }
  if (limiteGrade) { mapaChuva.removeLayer(limiteGrade); limiteGrade = null; }
}
function alterarOpacidade() {
  const opacidade = Number($('opacidade').value) / 100;
  $('texto-opacidade').textContent = `${$('opacidade').value}%`;
  if (mapaDeCalor) mapaDeCalor.setOpacity(opacidade);
  if (camadaRadar) camadaRadar.setOpacity(opacidade);
}
function modoChuva() {
  return $('modo-previsao').checked ? 'previsao' : $('modo-radar').checked ? 'radar' : 'calor';
}
function pontosParaModo(dados, modo) {
  return modo === 'previsao' ? dados.pontos_previsao_24h : dados.pontos;
}
function enquadrarMapa() {
  // Corrige a inicialização do Leaflet enquanto a aba estava escondida.
  mapaChuva.invalidateSize(true);
  mapaChuva.fitBounds([[-23.82, -46.72], [-23.58, -46.36]], {
    padding: [24, 24], maxZoom: 11, animate: false
  });
}
function atualizarResumoChuva(dados, modo) {
  $('horario-atualizacao').textContent = modo === 'radar'
    ? dataLegivel(dados.horario_radar)
    : modo === 'previsao'
      ? `${dados.inicio_previsao} até ${dados.fim_previsao} (horário de SP)`
      : `${dados.horario_modelo} (horário de SP)`;
  $('horario-consulta').textContent = dataLegivel(dados.consultado_em);
  if (modo !== 'radar') {
    const lista = pontosParaModo(dados, modo);
    const max = Math.max(0, ...lista.map(p => p.intensidade_mm_h));
    $('max-chuva').textContent = `${max.toFixed(1)} mm/h`;
    $('descricao-indicador').textContent = modo === 'previsao' ? 'maior pico horário previsto em 24h' : 'maior intensidade atual estimada';
    $('status-chuva').textContent = max < 0.1
      ? (modo === 'previsao'
          ? 'A previsão consultada não indica chuva significativa nas próximas 24 horas nesta região. A área tracejada mostra onde os dados foram consultados.'
          : 'Sem chuva significativa neste momento. A área tracejada indica onde o modelo foi consultado.')
      : modo === 'previsao'
        ? 'O mapa indica a MAIOR intensidade prevista em algum momento das próximas 24 horas. As cores não representam chuva simultânea.'
        : 'Mapa de chuva atual carregado. As cores não representam probabilidade de alagamento.';
  } else {
    $('max-chuva').textContent = 'Radar';
    $('descricao-indicador').textContent = 'observação recente';
    $('status-chuva').textContent = 'Radar recente carregado. A cobertura e a resolução dependem do provedor.';
  }
  $('status-chuva').dataset.erro = 'false';
}
async function consultarChuva(forcar = false) {
  const modo = modoChuva();
  $('legenda-calor').hidden = modo === 'radar';
  $('legenda-radar').hidden = modo !== 'radar';
  $('status-chuva').textContent = modo === 'radar' ? 'Consultando o radar...' : 'Consultando a Open-Meteo...';
  $('status-chuva').dataset.erro = 'false';
  const botao = $('botao-atualizar-chuva');
  botao.disabled = true;
  removerCamadasChuva();
  try {
    if (modo !== 'radar') {
      if (!modeloAtual || forcar) modeloAtual = await api('/api/chuva');
      if (!modeloAtual.disponivel) throw new Error(modeloAtual.mensagem);
      const pontos = pontosParaModo(modeloAtual, modo);
      if (!Array.isArray(pontos) || pontos.length !== 49) throw new Error('Grade meteorológica incompleta.');
      const bounds = [[modeloAtual.latitudes[0], modeloAtual.longitudes[0]],
        [modeloAtual.latitudes.at(-1), modeloAtual.longitudes.at(-1)]];
      // Contorno mostra a área coberta pelo modelo mesmo quando a precipitação é zero.
      limiteGrade = L.rectangle(bounds, {color: '#168c9c', weight: 2, opacity: 0.85,
        fill: false, dashArray: '7 5', interactive: false}).addTo(mapaChuva);
      mapaDeCalor = L.imageOverlay(construirImagemDeCalor({...modeloAtual, pontos}), bounds, {interactive: false}).addTo(mapaChuva);
      atualizarResumoChuva(modeloAtual, modo);
    } else {
      if (!radarAtual || forcar) radarAtual = await api('/api/radar');
      if (!radarAtual.disponivel) throw new Error(radarAtual.mensagem);
      // URL criada pelo servidor a partir de metadados atuais da RainViewer.
      // A versão pública de 2026 permite apenas Universal Blue e zoom nativo 7.
      camadaRadar = L.tileLayer(radarAtual.tile_url, {
        opacity: 0.9, maxNativeZoom: 7, maxZoom: 19, tileSize: 256,
        attribution: 'Radar: <a href="https://www.rainviewer.com/" target="_blank" rel="noopener">RainViewer</a>'
      }).addTo(mapaChuva);
      atualizarResumoChuva(radarAtual, modo);
    }
    alterarOpacidade();
    if (modo !== 'radar') enquadrarMapa();
    chuvaFoiConsultada = true;
  } catch (erro) {
    $('max-chuva').textContent = '—';
    $('horario-atualizacao').textContent = 'Sem dados atuais';
    $('horario-consulta').textContent = '—';
    $('status-chuva').textContent = erro.message;
    $('status-chuva').dataset.erro = 'true';
  } finally { botao.disabled = false; }
}
$('botao-atualizar-chuva').addEventListener('click', () => consultarChuva(true));
$('modo-calor').addEventListener('change', () => consultarChuva());
$('modo-previsao').addEventListener('change', () => consultarChuva());
$('modo-radar').addEventListener('change', () => consultarChuva());
$('opacidade').addEventListener('input', alterarOpacidade);
mapaChuva.on('click', (evento) => {
  const modo = modoChuva();
  if (modo === 'radar' || !modeloAtual?.disponivel) return;
  const lista = pontosParaModo(modeloAtual, modo);
  const valor = valorInterpolado(evento.latlng.lat, evento.latlng.lng, {...modeloAtual, pontos: lista});
  if (valor === null) return;
  L.popup().setLatLng(evento.latlng).setContent(
    `<strong>${modo === 'previsao' ? 'Pico horário previsto em 24h' : 'Chuva atual estimada'}:</strong> ${valor.toFixed(2)} mm/h<br>` +
    '<small>Interpolação do modelo Open-Meteo, não medição nesta rua. No modo previsão os picos podem ocorrer em horários diferentes.</small>'
  ).openOn(mapaChuva);
});
// Enquanto a página estiver aberta, renova os dados a cada 10 minutos.
// O servidor usa cache (modelo 20min; radar 8min). Sem conexão, dados antigos
// deixam de aparecer após a validade; não há hotspots de demonstração.
setInterval(() => {
  if (!document.hidden) {
    modeloAtual = null;
    radarAtual = null;
    if (!$('secao-chuva').hidden) consultarChuva(true);
  }
}, 10 * 60 * 1000);
function alternarAba(aba) {
  const chuva = aba === 'chuva';
  $('secao-ocorrencias').hidden = chuva;
  $('secao-chuva').hidden = !chuva;
  $('secao-ocorrencias').classList.toggle('oculto', chuva);
  $('secao-chuva').classList.toggle('oculto', !chuva);
  $('aba-ocorrencias').classList.toggle('ativo', !chuva);
  $('aba-chuva').classList.toggle('ativo', chuva);
  $('aba-ocorrencias').setAttribute('aria-selected', String(!chuva));
  $('aba-chuva').setAttribute('aria-selected', String(chuva));
  // Leaflet precisa recalcular dimensões após a aba deixar de estar oculta.
  setTimeout(() => {
    if (chuva) enquadrarMapa();
    else mapaOcorrencias.invalidateSize();
  }, 110);
  if (chuva && !chuvaFoiConsultada) consultarChuva();
}
$('aba-ocorrencias').addEventListener('click', () => alternarAba('ocorrencias'));
$('aba-chuva').addEventListener('click', () => alternarAba('chuva'));
window.addEventListener('resize', () => { mapaOcorrencias.invalidateSize(); mapaChuva.invalidateSize(); });
carregarOcorrencias().catch(e => mensagem('Não foi possível carregar as ocorrências: ' + e.message, true));
