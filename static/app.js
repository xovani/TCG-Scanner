const $ = (id) => document.getElementById(id);
let photo = null;
let busy = false;
let previewUrl = null;
let detailRequest = 0;
let photoToken = null;
let activeList = null;
let listSummary = [];
let listBusy = false;
let lastAddedToken = null;
let lastAddedCardId = null;
let webcamMode = false;
let webcamStream = null;
let cameraOpening = false;
let continuousActive = false;

function token() {
  return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function status(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
function setBusy(value) {
  busy = value;
  for (const id of ['scan', 'search', 'rotate', 'camera', 'gallery', 'language', 'scan-quantity', 'auto-add']) {
    $(id).disabled = value || continuousActive || (['scan', 'rotate'].includes(id) && !photo);
  }
  $('status').classList.toggle('busy', value);
  $('results').setAttribute('aria-busy', String(value));
  updateListControls();
}
async function jsonRequest(url, options = {}) {
  const response = await fetch(url, { ...options, signal: options.signal || AbortSignal.timeout(180000) });
  let data;
  try { data = await response.json(); } catch { throw new Error('Resposta inesperada do servidor. Confira o terminal no computador.'); }
  if (!response.ok) throw new Error(data.error || 'Não foi possível concluir a consulta.');
  return data;
}
function reportError(error) {
  status(error.name === 'TimeoutError' ? 'A leitura demorou demais. Tente novamente; a primeira execução precisa preparar os modelos.' : error.message || 'Falha na conexão com o computador.', true);
}
function showPreview(blob) {
  photo = blob;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(blob);
  $('preview').src = previewUrl;
  $('preview').hidden = false;
  $('placeholder').hidden = true;
}
function canvasBlob(canvas) {
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Não consegui preparar a foto.')), 'image/jpeg', .92));
}
async function loadPhoto(file) {
  if (!file || busy || listBusy || continuousActive) return;
  setBusy(true);
  status('Preparando a foto…');
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, 2400 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    showPreview(await canvasBlob(canvas));
    photoToken = token();
    $('results').replaceChildren(); $('empty').hidden = false;
    $('ocr-section').hidden = true; $('ocr-text').textContent = '';
    status('Foto pronta. Toque em “Ler e identificar card”.');
  } catch { status('Não consegui abrir essa foto. Escolha uma imagem JPG, PNG ou WebP.', true); }
  finally { setBusy(false); }
}
for (const id of ['camera', 'gallery']) {
  $(id).addEventListener('change', (event) => { loadPhoto(event.target.files[0]); event.target.value = ''; });
}
$('rotate').addEventListener('click', async () => {
  if (busy || !photo) return;
  setBusy(true);
  try {
    const bitmap = await createImageBitmap(photo);
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.height; canvas.height = bitmap.width;
    const context = canvas.getContext('2d');
    context.translate(canvas.width, 0); context.rotate(Math.PI / 2); context.drawImage(bitmap, 0, 0);
    bitmap.close(); showPreview(await canvasBlob(canvas));
    status('Foto girada. Faça uma nova leitura.');
    $('results').replaceChildren(); $('empty').hidden = false; $('ocr-section').hidden = true;
  } catch (error) { reportError(error); }
  finally { setBusy(false); }
});

function safeImage(base, quality = 'low') {
  if (typeof base !== 'string' || !base.startsWith('https://assets.tcgdex.net/')) return null;
  const image = document.createElement('img'); image.src = `${base}/${quality}.webp`;
  image.alt = 'Imagem de referência do catálogo'; image.loading = 'lazy';
  image.addEventListener('error', () => { image.removeAttribute('src'); image.alt = 'Imagem indisponível'; }, { once: true });
  return image;
}
function renderResults(data, language, sourceToken = null) {
  $('results').replaceChildren();
  $('empty').hidden = data.matches.length > 0;
  if ('text' in data) { $('ocr-text').textContent = data.text; $('ocr-section').hidden = !data.text; }
  status((data.message || 'Confira as possíveis correspondências.') + (data.stale ? ' Usando catálogo salvo; atualização indisponível.' : ''));
  for (const card of data.matches) {
    const button = document.createElement('button'); button.className = 'result-card'; button.type = 'button';
    const image = safeImage(card.image); if (image) button.append(image);
    const title = document.createElement('strong'); title.textContent = card.name;
    const subtitle = document.createElement('small'); subtitle.textContent = `Nº ${card.localId} · ${card.set_id}`;
    const badge = document.createElement('span'); badge.className = 'match';
    badge.textContent = card.number_match ? 'Nome + número compatíveis' : 'Possível correspondência';
    button.append(title, subtitle, badge);
    button.addEventListener('click', () => showDetail(card, language, sourceToken));
    $('results').append(button);
  }
}
$('scan').addEventListener('click', async () => {
  if (!photo || busy || listBusy || continuousActive || webcamMode) return;
  if ($('auto-add').checked && !activeList) { status('Crie ou selecione uma lista antes de acrescentar cards.', true); return; }
  if (!$('scan-quantity').reportValidity()) return;
  setBusy(true); status('Lendo o card… Na primeira vez, a preparação pode levar alguns minutos.');
  const language = $('language').value;
  const form = new FormData(); form.append('image', photo, 'card.jpg'); form.append('language', language);
  form.append('quantity', $('scan-quantity').value); form.append('token', photoToken);
  if ($('auto-add').checked) form.append('list_id', activeList.id);
  $('results').replaceChildren(); $('empty').hidden = true; $('ocr-section').hidden = true;
  try {
    const data = await jsonRequest('/api/scan', { method: 'POST', body: form });
    renderResults(data, language, photoToken);
    if (data.list) {
      activeList = data.list; lastAddedToken = photoToken;
      if (data.added) lastAddedCardId = data.selected?.id || null;
      renderList({ revealAdded: data.added }); await refreshSummaries();
      listStatus(data.added ? 'Card identificado e salvo na lista ativa.' : 'Esta foto já foi acrescentada. Para mais cópias, use o botão + na lista.');
    }
  }
  catch (error) { reportError(error); $('empty').hidden = false; }
  finally { setBusy(false); }
});
$('search-form').addEventListener('submit', async (event) => {
  event.preventDefault(); if (busy || listBusy || continuousActive) return;
  setBusy(true); status('Consultando o catálogo…');
  const language = $('language').value;
  const query = new URLSearchParams({ name: $('name').value.trim(), number: $('number').value.trim(), set: $('set-code').value.trim(), language });
  try {
    const data = await jsonRequest(`/api/search?${query}`);
    if (!data.matches.length) data.message = 'Nenhum card encontrado. Confira o nome, o número e o idioma.';
    renderResults(data, language);
  } catch (error) { reportError(error); }
  finally { setBusy(false); }
});
async function showDetail(card, language, sourceToken = null) {
  if (continuousActive) return;
  const id = ++detailRequest;
  const content = $('detail-content'); content.textContent = 'Buscando detalhes…'; $('detail-dialog').showModal();
  try {
    const data = await jsonRequest(`/api/cards/${encodeURIComponent(card.id)}?language=${language}`);
    if (id !== detailRequest) return;
    content.replaceChildren();
    const image = safeImage(data.image, 'high'); if (image) content.append(image);
    const title = document.createElement('h2'); title.textContent = data.name;
    const description = document.createElement('p');
    description.textContent = `${data.set?.name || card.set_id} · Nº ${data.localId}${data.set?.cardCount?.official ? '/' + data.set.cardCount.official : ''}`;
    const rarity = document.createElement('p'); rarity.textContent = `Raridade: ${data.rarity || 'não informada'} · ID: ${data.id}`;
    content.append(title, description, rarity);
    const add = document.createElement('button'); add.type = 'button'; add.className = 'button primary';
    add.textContent = activeList ? `Adicionar à lista: ${activeList.name}` : 'Selecione uma lista para adicionar';
    const feedback = document.createElement('p'); feedback.setAttribute('role', 'status');
    if (sourceToken && sourceToken === lastAddedToken) { add.disabled = true; add.textContent = 'Esta foto já foi adicionada'; }
    add.addEventListener('click', async () => {
      if (busy || listBusy || continuousActive || !activeList) { listStatus('Selecione uma lista e aguarde a operação atual.', true); return; }
      const destination = activeList.id;
      const amount = Number($('scan-quantity').value);
      if (!$('scan-quantity').reportValidity()) return;
      listBusy = true; updateListControls(); add.disabled = true;
      try {
        const data = await jsonRequest(`/api/lists/${destination}/items`, jsonOptions('POST', {
          card_id: card.id, language, quantity: amount, token: sourceToken || token()
        }));
        activeList = data.list; if (sourceToken) lastAddedToken = sourceToken;
        if (data.added) lastAddedCardId = card.id;
        renderList({ revealAdded: data.added }); await refreshSummaries();
        listStatus(data.added ? `${amount} × ${card.name} salvo(s) em ${activeList.name}.` : 'Esta foto já foi adicionada à lista.');
        $('detail-dialog').close(); detailRequest++;
      } catch (error) { add.disabled = false; feedback.textContent = error.message; listStatus(error.message, true); }
      finally { listBusy = false; updateListControls(); }
    });
    content.append(add, feedback);
  } catch (error) { if (id === detailRequest) content.textContent = error.message; }
}
$('close-dialog').addEventListener('click', () => { detailRequest++; $('detail-dialog').close(); });
$('detail-dialog').addEventListener('cancel', () => detailRequest++);
$('open-help').addEventListener('click', () => $('help-dialog').showModal());
$('close-help').addEventListener('click', () => $('help-dialog').close());
$('language').addEventListener('change', () => {
  $('results').replaceChildren(); $('empty').hidden = false;
  $('ocr-section').hidden = true; status('Idioma alterado. Faça uma nova leitura ou busca.');
});
if ($('access-url')) {
  jsonRequest('/api/access').then(data => { $('access-url').textContent = data.url; $('access-url').href = data.url; }).catch(() => { $('access-url').textContent = 'Consulte o endereço no terminal.'; });
}

function jsonOptions(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
function listStatus(message, error = false) {
  $('list-status').textContent = message;
  $('list-status').classList.toggle('list-error', error);
}
function updateListControls() {
  const locked = busy || listBusy || continuousActive || cameraOpening;
  for (const id of ['active-list', 'new-list', 'new-list-name', 'rename-list', 'delete-list', 'download-list', 'copy-list', 'export-format']) {
    $(id).disabled = locked || (['active-list', 'rename-list', 'delete-list'].includes(id) && !activeList)
      || (['download-list', 'copy-list'].includes(id) && !activeList?.items.length);
  }
  for (const control of $('list-items').querySelectorAll('button, input')) control.disabled = locked;
  $('scan').disabled = locked || !photo;
  $('rotate').disabled = locked || !photo;
  $('search').disabled = locked;
  for (const id of ['language', 'scan-quantity', 'auto-add', 'camera', 'gallery']) $(id).disabled = locked;
  if (typeof updateWebcamControls === 'function') updateWebcamControls();
}
async function refreshSummaries() {
  const data = await jsonRequest('/api/lists'); listSummary = data.lists;
  $('active-list').replaceChildren();
  for (const list of listSummary) {
    const option = document.createElement('option'); option.value = list.id; option.textContent = `${list.name} (${list.total})`;
    $('active-list').append(option);
  }
  if (activeList) $('active-list').value = activeList.id;
}
function renderList({ revealAdded = false, preserveScroll = false } = {}) {
  const container = $('list-items');
  const previousScroll = preserveScroll ? container.scrollTop : 0;
  container.replaceChildren();
  $('scan-destination').textContent = activeList ? `Lista ativa: ${activeList.name}` : 'Crie ou selecione uma lista em Minhas listas.';
  $('list-total').textContent = `${activeList?.total || 0} cards`;
  if (!activeList?.items.length) {
    const empty = document.createElement('p'); empty.className = 'privacy'; empty.textContent = 'Lista vazia. Leia um card ou busque e adicione um candidato.';
    container.append(empty); updateListControls(); return;
  }
  for (const item of activeList.items) {
    const row = document.createElement('div'); row.className = 'list-item';
    row.dataset.cardId = item.card_id;
    if (item.card_id === lastAddedCardId) row.classList.add('recently-added');
    const description = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = item.name;
    const subtitle = document.createElement('small'); subtitle.textContent = `${item.set_name} · ${item.set_code || item.set_id} ${item.number}`;
    description.append(title, subtitle);
    if (!item.set_code) { const warning = document.createElement('small'); warning.textContent = 'Código de exportação não informado pelo catálogo'; warning.className = 'list-error'; description.append(warning); }
    const controls = document.createElement('div'); controls.className = 'quantity-controls';
    const count = document.createElement('input');
    count.type = 'number'; count.min = '0'; count.max = '999'; count.step = '1'; count.required = true;
    count.inputMode = 'numeric'; count.value = String(item.quantity); count.className = 'quantity-input';
    count.dataset.quantityControl = 'quantity';
    count.setAttribute('aria-label', `Quantidade de ${item.name}`);
    count.title = 'Digite a quantidade e pressione Enter ou saia do campo para salvar. Zero remove o card.';
    const commitCount = (restoreFocus = false) => {
      if (busy || listBusy || continuousActive || cameraOpening) return;
      if (!count.checkValidity() || !Number.isInteger(count.valueAsNumber)) {
        count.value = String(item.quantity);
        listStatus('Digite uma quantidade inteira de 0 a 999. Zero remove o card.', true);
        return;
      }
      if (count.valueAsNumber !== item.quantity) void changeQuantity(item, count.valueAsNumber, restoreFocus ? 'quantity' : null);
    };
    count.addEventListener('change', () => commitCount());
    count.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); commitCount(true); }
      if (event.key === 'Escape') { event.preventDefault(); count.value = String(item.quantity); count.blur(); }
    });
    for (const [label, accessible, amount, controlName] of [['−', `Diminuir quantidade de ${item.name}`, item.quantity - 1, 'decrease'], ['+', `Aumentar quantidade de ${item.name}`, item.quantity + 1, 'increase']]) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'button secondary'; button.textContent = label; button.setAttribute('aria-label', accessible);
      button.dataset.quantityControl = controlName;
      button.addEventListener('click', () => changeQuantity(item, amount, controlName));
      controls.append(button); if (label === '−') controls.append(count);
    }
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'text-button'; remove.textContent = 'Remover';
    remove.setAttribute('aria-label', `Remover ${item.name} da lista`); remove.addEventListener('click', () => changeQuantity(item, 0));
    controls.append(remove); row.append(description, controls); container.append(row);
  }
  updateListControls();
  container.scrollTop = previousScroll;
  requestAnimationFrame(() => {
    if (!revealAdded) { container.scrollTop = previousScroll; return; }
    const recent = container.querySelector('.recently-added');
    if (!recent) return;
    const area = container.getBoundingClientRect();
    const item = recent.getBoundingClientRect();
    if (item.bottom > area.bottom) container.scrollTop += item.bottom - area.bottom;
    else if (item.top < area.top) container.scrollTop -= area.top - item.top;
  });
}
async function changeQuantity(item, amount, focusControl = null) {
  if (!activeList || busy || listBusy || continuousActive || cameraOpening) return;
  listBusy = true; updateListControls();
  try {
    activeList = await jsonRequest(`/api/lists/${activeList.id}/items/${encodeURIComponent(item.card_id)}`, jsonOptions('PATCH', { quantity: amount }));
    renderList({ preserveScroll: true }); await refreshSummaries(); listStatus('Quantidade salva.');
  } catch (error) { renderList({ preserveScroll: true }); listStatus(error.message, true); }
  finally {
    listBusy = false; updateListControls();
    if (focusControl) {
      const row = [...$('list-items').children].find(node => node.dataset.cardId === item.card_id);
      row?.querySelector(`[data-quantity-control="${focusControl}"]`)?.focus({ preventScroll: true });
    }
  }
}
$('active-list').addEventListener('change', async () => {
  if (busy || listBusy || continuousActive) return;
  const previous = activeList?.id;
  listBusy = true; updateListControls();
  try {
    activeList = await jsonRequest(`/api/lists/${$('active-list').value}`);
    lastAddedToken = null; lastAddedCardId = null;
    try { localStorage.setItem('active-list', activeList.id); } catch { /* preferência opcional */ }
    renderList(); listStatus(`Cards serão acrescentados em ${activeList.name}.`);
  } catch (error) { if (previous) $('active-list').value = previous; listStatus(error.message, true); }
  finally { listBusy = false; updateListControls(); }
});
$('new-list-form').addEventListener('submit', async (event) => {
  event.preventDefault(); if (busy || listBusy || continuousActive) return;
  const name = $('new-list-name').value.trim(); if (!name) return;
  listBusy = true; updateListControls();
  try {
    activeList = await jsonRequest('/api/lists', jsonOptions('POST', { name }));
    $('new-list-name').value = ''; lastAddedToken = null; lastAddedCardId = null;
    try { localStorage.setItem('active-list', activeList.id); } catch { /* preferência opcional */ }
    renderList(); await refreshSummaries(); listStatus(`Lista ${activeList.name} criada e selecionada.`);
  } catch (error) { listStatus(error.message, true); }
  finally { listBusy = false; updateListControls(); }
});
$('rename-list').addEventListener('click', async () => {
  if (!activeList || busy || listBusy || continuousActive) return;
  const name = prompt('Novo nome da lista:', activeList.name); if (name === null || !name.trim()) return;
  listBusy = true; updateListControls();
  try {
    activeList = await jsonRequest(`/api/lists/${activeList.id}`, jsonOptions('PATCH', { name: name.trim() }));
    renderList(); await refreshSummaries(); listStatus('Nome da lista atualizado.');
  } catch (error) { listStatus(error.message, true); }
  finally { listBusy = false; updateListControls(); }
});
$('delete-list').addEventListener('click', async () => {
  if (!activeList || busy || listBusy || continuousActive || cameraOpening) return;
  const target = activeList;
  if (!confirm(`Apagar a lista “${target.name}” e todos os seus ${target.total} cards?\n\nEssa exclusão é permanente. As outras listas serão mantidas. Se for a última lista, será criada uma nova lista vazia.`)) return;
  listBusy = true; updateListControls();
  try {
    const result = await jsonRequest(`/api/lists/${target.id}`, { method: 'DELETE' });
    activeList = result.list;
    lastAddedToken = null; lastAddedCardId = null;
    try { localStorage.setItem('active-list', activeList.id); } catch { /* preferência opcional */ }
    renderList(); await refreshSummaries();
    listStatus(`Lista “${target.name}” apagada. Lista ativa: ${activeList.name}.`);
  } catch (error) { listStatus(error.message, true); }
  finally { listBusy = false; updateListControls(); }
});
async function exportList(copy) {
  if (!activeList || busy || listBusy || continuousActive) return;
  listBusy = true; updateListControls();
  try {
    const format = $('export-format').value;
    const response = await fetch(`/api/lists/${activeList.id}/export?format=${format}`, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) { const data = await response.json(); throw new Error(data.error || 'Falha ao exportar.'); }
    const text = await response.text();
    if (copy) {
      try { await navigator.clipboard.writeText(text); listStatus(format === 'liga' ? 'Lista copiada no padrão Liga Pokémon. Cole na procura de cartas.' : 'Lista copiada. Cole no TCG Live configurado em inglês ou no Limitless.'); }
      catch {
        $('detail-content').replaceChildren();
        const textarea = document.createElement('textarea'); textarea.value = text; textarea.readOnly = true; textarea.rows = 15; textarea.setAttribute('aria-label', 'Texto da lista para copiar');
        $('detail-content').append(textarea); $('detail-dialog').showModal(); textarea.select();
        listStatus('Selecione e copie o texto da janela, ou use Baixar .txt.');
      }
    } else {
      const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
      const link = document.createElement('a'); link.href = url;
      const filename = activeList.name.replace(/[^\p{L}\p{N}_-]+/gu, '-').slice(0, 60) || 'lista';
      link.download = `${filename}-${format}.txt`; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      listStatus(format === 'liga' ? 'Arquivo exportado no padrão Liga Pokémon para procura de cartas.' : 'Arquivo exportado em inglês. Importe no TCG Live ou cole no Limitless.');
    }
  } catch (error) { listStatus(error.message, true); }
  finally { listBusy = false; updateListControls(); }
}
$('download-list').addEventListener('click', () => exportList(false));
$('copy-list').addEventListener('click', () => exportList(true));
async function initializeLists() {
  listBusy = true; updateListControls();
  try {
    await refreshSummaries();
    if (!listSummary.length) activeList = await jsonRequest('/api/lists', jsonOptions('POST', { name: 'Minha lista' }));
    else {
      let preferred; try { preferred = localStorage.getItem('active-list'); } catch { /* preferência opcional */ }
      const selected = listSummary.find(list => list.id === preferred) || listSummary[0];
      activeList = await jsonRequest(`/api/lists/${selected.id}`);
    }
    await refreshSummaries(); renderList();
  } catch (error) { listStatus(`Não consegui carregar as listas: ${error.message}`, true); }
  finally { listBusy = false; updateListControls(); }
}
initializeLists();
