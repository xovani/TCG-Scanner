let webcamGeneration = 0;
let continuousTimer = null;
let countdownTimer = null;
let audioContext = null;
let previousWebcamCard = null;
let previousWebcamList = null;
let emptyWebcamFrames = 0;

function webcamStatus(message, error = false) {
  $('webcam-status').textContent = message;
  $('webcam-status').classList.toggle('list-error', error);
}

function updateWebcamControls() {
  const processing = busy || listBusy || cameraOpening;
  const live = Boolean(webcamStream?.getVideoTracks().some(track => track.readyState === 'live'));
  $('source-file').disabled = processing;
  $('source-webcam').disabled = processing;
  $('source-file').setAttribute('aria-pressed', String(!webcamMode));
  $('source-webcam').setAttribute('aria-pressed', String(webcamMode));
  $('source-file').className = `button ${webcamMode ? 'secondary' : 'primary'}`;
  $('source-webcam').className = `button ${webcamMode ? 'primary' : 'secondary'}`;
  $('file-controls').hidden = webcamMode;
  $('webcam-controls').hidden = !webcamMode;
  $('scan').hidden = webcamMode;
  $('webcam-device').disabled = processing || continuousActive || !$('webcam-device').options[0]?.value;
  $('refresh-webcams').disabled = processing || continuousActive;
  $('open-webcam').disabled = processing || continuousActive || live;
  $('close-webcam').disabled = !live && !cameraOpening;
  $('capture-webcam').disabled = processing || continuousActive || !live;
  $('start-continuous').disabled = processing || continuousActive || !live || !activeList;
  $('stop-continuous').disabled = !continuousActive;
  $('scan-delay').disabled = processing || continuousActive;
  $('avoid-stationary').disabled = processing || continuousActive;
}

function cameraError(error) {
  const messages = {
    NotAllowedError: 'Acesso à webcam negado. Permita a câmera nas configurações do navegador e do Windows.',
    NotFoundError: 'Nenhuma webcam disponível. Conecte ou habilite uma câmera e clique em Atualizar.',
    NotReadableError: 'Não consegui abrir a webcam. Feche outros aplicativos que estejam usando essa câmera e tente novamente.',
    OverconstrainedError: 'A webcam selecionada não está disponível. Atualize a lista e selecione outra câmera.',
    SecurityError: 'A câmera foi bloqueada pelas permissões do navegador ou do Windows.'
  };
  return messages[error.name] || error.message || 'Não consegui acessar a webcam.';
}

function mediaAvailable() {
  if (!navigator.mediaDevices?.getUserMedia || !navigator.mediaDevices?.enumerateDevices) {
    throw new Error('Para usar a webcam, abra este aplicativo no computador por http://127.0.0.1:5000 ou localhost. Acesso por IP da rede exige HTTPS para a webcam no navegador.');
  }
}

async function listWebcams() {
  mediaAvailable();
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput');
  const current = webcamStream?.getVideoTracks()[0]?.getSettings().deviceId || $('webcam-device').value;
  $('webcam-device').replaceChildren();
  devices.forEach((device, index) => {
    const option = document.createElement('option');
    option.value = device.deviceId; option.textContent = device.label || `Webcam ${index + 1}`;
    $('webcam-device').append(option);
  });
  if (!devices.length) {
    const option = document.createElement('option'); option.value = ''; option.textContent = 'Nenhuma webcam encontrada'; $('webcam-device').append(option);
  } else if (devices.some(device => device.deviceId === current)) $('webcam-device').value = current;
  updateWebcamControls();
  return devices;
}

function cropRegion() {
  const video = $('webcam-video');
  const height = Math.min(video.videoHeight * .9, video.videoWidth * .9 * 88 / 63);
  const width = height * 63 / 88;
  return { x: (video.videoWidth - width) / 2, y: (video.videoHeight - height) / 2, width, height };
}

function updateGuide() {
  const video = $('webcam-video');
  if (!video.videoWidth || !video.videoHeight) return;
  const crop = cropRegion();
  // A prévia usa object-fit: contain; desconta as faixas laterais do vídeo.
  const scale = Math.min(video.clientWidth / video.videoWidth, video.clientHeight / video.videoHeight);
  $('webcam-guide').style.width = `${crop.width * scale}px`;
  $('webcam-guide').style.height = `${crop.height * scale}px`;
  $('webcam-guide').hidden = false;
}

function releaseWebcam() {
  const stream = webcamStream;
  webcamStream = null;
  if (stream) stream.getTracks().forEach(track => track.stop());
  $('webcam-video').srcObject = null;
  $('webcam-video').hidden = true;
  $('webcam-guide').hidden = true;
  $('webcam-placeholder').hidden = false;
}

async function openWebcam(deviceId = '') {
  if (busy || listBusy || cameraOpening || continuousActive) return;
  cameraOpening = true; updateListControls();
  webcamStatus('Abrindo webcam… Autorize o acesso se o navegador solicitar.');
  const generation = ++webcamGeneration;
  releaseWebcam();
  try {
    mediaAvailable();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false, video: { ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        width: { ideal: 1920 }, height: { ideal: 1080 } }
    });
    if (generation !== webcamGeneration) { stream.getTracks().forEach(track => track.stop()); return; }
    webcamStream = stream;
    $('webcam-video').srcObject = stream;
    await $('webcam-video').play();
    if (generation !== webcamGeneration) return;
    $('webcam-video').hidden = false;
    $('webcam-placeholder').hidden = true; updateGuide();
    stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => {
      if (webcamStream !== stream) return;
      stopContinuous('A webcam foi desconectada. Atualize a lista para reconectar.');
      releaseWebcam(); updateListControls();
    }));
    await listWebcams();
    previousWebcamCard = null; previousWebcamList = null; emptyWebcamFrames = 0;
    webcamStatus('Webcam pronta. Enquadre o card inteiro na moldura e escolha leitura única ou contínua.');
  } catch (error) {
    if (generation === webcamGeneration) { releaseWebcam(); webcamStatus(cameraError(error), true); }
  } finally {
    cameraOpening = false; updateListControls();
  }
}

async function prepareSound() {
  if (!$('beep-enabled').checked) return;
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) throw new Error('Áudio indisponível');
    audioContext ||= new Audio();
    if (audioContext.state !== 'running') await audioContext.resume();
  } catch { webcamStatus('O navegador não liberou o áudio. A leitura pode continuar; use Testar bip para tentar novamente.', true); }
}

function recognitionBeep() {
  if (!$('beep-enabled').checked || audioContext?.state !== 'running') return;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  const now = audioContext.currentTime;
  oscillator.frequency.value = 880;
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(.12, now + .015);
  gain.gain.exponentialRampToValueAtTime(.001, now + .16);
  oscillator.connect(gain); gain.connect(audioContext.destination);
  oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  oscillator.start(now); oscillator.stop(now + .18);
}

async function captureWebcam() {
  const video = $('webcam-video');
  if (!webcamStream || video.readyState < 2 || video.videoWidth < 150) throw new Error('A webcam ainda não enviou uma imagem. Aguarde e tente novamente.');
  const crop = cropRegion();
  const scale = Math.min(1, 2400 / crop.height);
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(crop.width * scale); canvas.height = Math.round(crop.height * scale);
  canvas.getContext('2d').drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, canvas.width, canvas.height);
  return canvasBlob(canvas);
}

function stopContinuous(message = 'Leitura contínua parada. A webcam permanece aberta.') {
  continuousActive = false;
  webcamGeneration++;
  clearTimeout(continuousTimer); clearInterval(countdownTimer);
  continuousTimer = null; countdownTimer = null;
  webcamStatus(busy ? `${message} A leitura em andamento será finalizada; nenhuma nova captura será iniciada.` : message);
  updateListControls();
}

function scheduleNextScan(generation, message) {
  if (!continuousActive || generation !== webcamGeneration) return;
  const delay = Number($('scan-delay').value);
  const deadline = performance.now() + delay;
  const update = () => webcamStatus(`${message} Próxima leitura em ${Math.max(0, (deadline - performance.now()) / 1000).toFixed(1).replace('.', ',')} s.`);
  update(); countdownTimer = setInterval(update, 200);
  continuousTimer = setTimeout(() => {
    clearInterval(countdownTimer); countdownTimer = null;
    if (continuousActive && generation === webcamGeneration) void readWebcam(true, generation);
  }, delay);
}

async function readWebcam(continuous = false, generation = webcamGeneration) {
  if (busy || listBusy || !webcamStream) return;
  if (!activeList && (continuous || $('auto-add').checked)) { webcamStatus('Crie ou selecione uma lista antes da leitura.', true); return; }
  if (!$('scan-quantity').reportValidity()) return;
  setBusy(true); webcamStatus('Lendo o card na webcam…');
  let nextMessage = 'Posicione o próximo card.';
  let failed = false;
  try {
    const image = await captureWebcam();
    const captureToken = token();
    const lang = $('language').value;
    const listId = activeList?.id;
    const amount = Number($('scan-quantity').value);
    const form = new FormData(); form.append('image', image, 'webcam.jpg'); form.append('language', lang);
    // Reconhecer e salvar em etapas permite parar sem incluir uma leitura ainda não reconhecida.
    const data = await jsonRequest('/api/scan', { method: 'POST', body: form });
    if (generation !== webcamGeneration) return;
    renderResults(data, lang, captureToken);
    const selected = data.selected;
    if (!selected) {
      if (!data.text?.trim()) {
        emptyWebcamFrames++;
        if (emptyWebcamFrames >= 2) {
          previousWebcamCard = null; nextMessage = 'Área livre. Pode apresentar outra cópia.';
        } else nextMessage = 'Nenhum texto legível. Retire o card para liberar a próxima cópia.';
      } else { emptyWebcamFrames = 0; nextMessage = 'Edição não confirmada. Ajuste a posição ou pare para escolher um candidato.'; }
    } else {
      emptyWebcamFrames = 0;
      const repeated = continuous && $('avoid-stationary').checked && previousWebcamCard === selected.id && previousWebcamList === listId;
      if (repeated) {
        nextMessage = 'Este card já foi contado. Troque o card ou retire-o até aparecer “Área livre”.';
        status(nextMessage);
      } else if (continuous || $('auto-add').checked) {
        const saved = await jsonRequest(`/api/lists/${listId}/items`, jsonOptions('POST', {
          card_id: selected.id, language: lang, quantity: amount, token: captureToken
        }));
        // Mesmo após Parar, uma inclusão já enviada deve aparecer na lista se foi concluída.
        activeList = saved.list; lastAddedToken = captureToken;
        if (saved.added) lastAddedCardId = selected.id;
        previousWebcamCard = selected.id;
        previousWebcamList = listId;
        renderList({ revealAdded: saved.added });
        if (saved.added) recognitionBeep();
        nextMessage = `${amount} × ${selected.name} salvo(s). Troque o card.`;
        status(nextMessage); listStatus(nextMessage);
        await refreshSummaries();
      } else nextMessage = `${selected.name} identificado. Inclusão automática desativada.`;
    }
  } catch (error) {
    if (generation !== webcamGeneration) return;
    failed = true;
    reportError(error);
    if (continuous) stopContinuous('Leitura pausada após uma falha. Confira a lista antes de reiniciar.');
    webcamStatus(error.message || 'Falha ao ler a webcam.', true);
  } finally {
    setBusy(false);
    if (continuous && continuousActive && generation === webcamGeneration) scheduleNextScan(generation, nextMessage);
    else if (generation === webcamGeneration && !failed) webcamStatus(nextMessage);
  }
}

$('source-file').addEventListener('click', () => {
  if (busy || listBusy || cameraOpening) return;
  stopContinuous(); releaseWebcam(); webcamMode = false; updateListControls();
});
$('source-webcam').addEventListener('click', () => {
  if (busy || listBusy || cameraOpening) return;
  webcamMode = true; updateListControls();
});
$('open-webcam').addEventListener('click', () => void openWebcam($('webcam-device').value));
$('webcam-device').addEventListener('change', () => void openWebcam($('webcam-device').value));
$('refresh-webcams').addEventListener('click', async () => {
  if (busy || listBusy || cameraOpening || continuousActive) return;
  if (!webcamStream) { await openWebcam(); return; }
  try { await listWebcams(); webcamStatus('Lista de webcams atualizada.'); }
  catch (error) { webcamStatus(cameraError(error), true); }
});
$('close-webcam').addEventListener('click', () => {
  stopContinuous('Webcam desligada.'); releaseWebcam(); updateListControls();
});
$('capture-webcam').addEventListener('click', async () => {
  if (busy || listBusy || continuousActive) return;
  await prepareSound(); await readWebcam();
});
$('start-continuous').addEventListener('click', async () => {
  if (busy || listBusy || continuousActive || !webcamStream || !activeList) return;
  if (!$('scan-quantity').reportValidity()) return;
  continuousActive = true;
  $('auto-add').checked = true;
  const generation = ++webcamGeneration;
  updateListControls();
  await prepareSound();
  if (!continuousActive || generation !== webcamGeneration) return;
  await readWebcam(true, generation);
});
$('stop-continuous').addEventListener('click', () => stopContinuous());
$('test-beep').addEventListener('click', async () => { await prepareSound(); recognitionBeep(); });
$('webcam-video').addEventListener('resize', updateGuide);
new ResizeObserver(updateGuide).observe($('webcam-video'));
navigator.mediaDevices?.addEventListener('devicechange', async () => {
  if (!webcamMode || cameraOpening) return;
  try { await listWebcams(); } catch { /* O usuário pode atualizar a lista manualmente. */ }
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden && continuousActive) stopContinuous('Leitura pausada porque a aba deixou de estar visível.');
});
window.addEventListener('pagehide', () => { stopContinuous(); releaseWebcam(); });
updateWebcamControls();
