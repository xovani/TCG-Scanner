"""Teste da interface com catálogo/OCR simulados e banco temporário.

Requer requirements-dev.txt e Google Chrome já instalado. Não usa as listas reais.
"""
import io
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image
from playwright.sync_api import expect, sync_playwright
from waitress import create_server

from app import create_app
from test_lists import LINES, METADATA, fake_catalog
from scanner.lists import ListStore


def check_desktop_layout(page, webcam=False):
    for width, height in ((1280, 720), (1366, 768), (1920, 1080)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(80)
        measurements = page.evaluate("""() => {
          const rect = selector => { const r=document.querySelector(selector).getBoundingClientRect();
            return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}; };
          const capture=document.querySelector('.capture-panel');
          return {width:innerWidth,height:innerHeight, pageHeight:document.documentElement.scrollHeight,
            pageWidth:document.documentElement.scrollWidth, capture:rect('.capture-panel'), list:rect('.list-panel'),
            export:rect('#copy-list'), footer:rect('footer'), captureOverflow:capture.scrollHeight-capture.clientHeight,
            scan:rect(document.querySelector('#webcam-controls').hidden ? '#scan' : '#start-continuous')};
        }""")
        assert measurements["pageHeight"] <= height + 1, measurements
        assert measurements["pageWidth"] <= width + 1, measurements
        assert abs(measurements["capture"]["top"] - measurements["list"]["top"]) < 2, measurements
        assert measurements["list"]["left"] > measurements["capture"]["right"], measurements
        assert measurements["export"]["bottom"] <= height, measurements
        assert measurements["scan"]["bottom"] <= measurements["capture"]["bottom"], measurements
        assert measurements["footer"]["bottom"] <= height + 1, measurements
        assert measurements["captureOverflow"] <= 2, measurements
        if webcam:
            guide = page.evaluate("""() => {const r=document.querySelector('#webcam-guide').getBoundingClientRect(); return r.width/r.height;}""")
            assert abs(guide - 63 / 88) < .01, guide
    page.set_viewport_size({"width": 1366, "height": 768})
    page.screenshot(path=str(ROOT / "data" / ("qa-layout-webcam.png" if webcam else "qa-layout-file.png")))


def exercise_webcam(context, base_url, mocked_reader):
    """Câmeras simuladas via MediaStream de canvas; não acessa hardware do usuário."""
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    requests_at = []
    page.on("request", lambda request: requests_at.append(time.monotonic()) if request.url.endswith("/api/scan") else None)
    page.add_init_script("""(() => {
      window.__cameraRequests = []; window.__mockStreams = []; window.__canvases = [];
      window.__availableCameras = [{deviceId:'integrated',label:'Webcam integrada',kind:'videoinput'},
        {deviceId:'phone',label:'Celular vinculado ao Windows',kind:'videoinput'}];
      window.__denyCamera = false; window.__beeps = 0;
      navigator.mediaDevices.enumerateDevices = async () => window.__availableCameras;
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        if (window.__denyCamera) throw new DOMException('Negado no teste', 'NotAllowedError');
        window.__cameraRequests.push(constraints);
        const selected = constraints.video.deviceId?.exact || 'integrated';
        const canvas = document.createElement('canvas'); canvas.width = selected === 'phone' ? 720 : 1280; canvas.height = selected === 'phone' ? 1280 : 720;
        const ctx = canvas.getContext('2d'); let frame = 0;
        const draw = () => { ctx.fillStyle='#ecefe3'; ctx.fillRect(0,0,1280,720);
          ctx.fillStyle='#496636'; ctx.font='30px sans-serif'; ctx.fillText('Card simulado '+frame++,480,180); };
        draw(); setInterval(draw,100); window.__canvases.push(canvas);
        const stream = canvas.captureStream(10);
        stream.getVideoTracks()[0].getSettings = () => ({deviceId:selected});
        window.__mockStreams.push(stream); return stream;
      };
      const Audio = window.AudioContext;
      window.AudioContext = class extends Audio {
        createOscillator() { const o=super.createOscillator(); const start=o.start.bind(o);
          o.start=(...args)=>{window.__beeps++; start(...args);}; return o; }
      };
    })();""")
    try:
        page.goto(base_url)
        expect(page.locator("#active-list")).to_be_enabled()
        page.locator("#new-list-name").fill("Webcam")
        page.locator("#new-list").click()
        expect(page.locator("#list-total")).to_have_text("0 cards")
        expect(page.locator("#active-list")).to_be_enabled()
        page.select_option("#language", "en")
        page.locator("#source-webcam").click()
        expect(page.locator("#file-controls")).to_be_hidden()
        page.locator("#open-webcam").click()
        expect(page.locator("#webcam-device")).to_be_enabled()
        expect(page.locator("#webcam-device option")).to_have_count(2)
        page.select_option("#webcam-device", "phone")
        expect(page.locator("#capture-webcam")).to_be_enabled()
        assert page.evaluate("window.__cameraRequests.at(-1).video.deviceId.exact") == "phone"
        assert page.evaluate("window.__cameraRequests.every(r => r.audio === false)")
        assert page.evaluate("window.__mockStreams[0].getTracks().every(t => t.readyState === 'ended')")
        page.evaluate("window.__availableCameras.push({deviceId:'usb',label:'Webcam USB',kind:'videoinput'}); navigator.mediaDevices.dispatchEvent(new Event('devicechange'))")
        expect(page.locator("#webcam-device option")).to_have_count(3)
        page.locator(".webcam-options summary").click()
        page.select_option("#scan-delay", "2000")
        page.locator(".webcam-options summary").click()
        page.locator("#start-continuous").click()
        expect(page.locator("#list-total")).to_have_text("1 cards")
        expect(page.locator("#webcam-status")).to_contain_text("já foi contado", timeout=10000)
        expect(page.locator("#list-total")).to_have_text("1 cards")
        assert len(requests_at) >= 2 and requests_at[1] - requests_at[0] >= 1.95, requests_at
        assert page.evaluate("window.__beeps") == 1
        page.locator("#stop-continuous").click()
        stopped_count = len(requests_at)
        page.wait_for_timeout(2300)
        assert len(requests_at) == stopped_count, "Ainda houve captura após Parar"

        mocked_reader.return_value = []
        page.locator("#start-continuous").click()
        expect(page.locator("#webcam-status")).to_contain_text("Área livre", timeout=10000)
        mocked_reader.return_value = LINES
        expect(page.locator("#list-total")).to_have_text("2 cards", timeout=10000)
        page.locator("#stop-continuous").click()
        expect(page.locator("#start-continuous")).to_be_enabled()

        page.locator(".webcam-options summary").click()
        page.locator("#avoid-stationary").uncheck()
        page.locator(".webcam-options summary").click()
        page.locator("#start-continuous").click()
        expect(page.locator("#list-total")).to_have_text("4 cards", timeout=10000)
        page.locator("#stop-continuous").click()
        expect(page.locator("#start-continuous")).to_be_enabled()
        assert page.evaluate("window.__beeps") == 4

        read_started, release_read = threading.Event(), threading.Event()
        def delayed_read(image):
            read_started.set()
            release_read.wait(timeout=10)
            return LINES
        mocked_reader.side_effect = delayed_read
        page.locator("#start-continuous").click()
        deadline = time.monotonic() + 8
        while not read_started.is_set() and time.monotonic() < deadline:
            # Mantém o Playwright processando os eventos de rede durante a espera.
            page.wait_for_timeout(100)
        assert read_started.is_set(), "Leitura atrasada não iniciou"
        page.locator("#stop-continuous").click()
        release_read.set()
        expect(page.locator("#start-continuous")).to_be_enabled(timeout=10000)
        expect(page.locator("#list-total")).to_have_text("4 cards")
        mocked_reader.side_effect = None
        page.locator("#capture-webcam").click()
        expect(page.locator("#list-total")).to_have_text("5 cards")
        expect(page.locator("#capture-webcam")).to_be_enabled()
        assert page.evaluate("window.__beeps") == 5

        check_desktop_layout(page, webcam=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(ROOT / "data" / "qa-webcam.png"), full_page=True)
        page.locator("#close-webcam").click()
        assert page.evaluate("window.__mockStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))")
        page.evaluate("window.__denyCamera = true")
        page.locator("#open-webcam").click()
        expect(page.locator("#webcam-status")).to_contain_text("negado")
        page.locator("#source-file").click()
        expect(page.locator("#file-controls")).to_be_visible()
        assert not errors, errors
        print("Webcams aprovadas: seleção de 3 dispositivos simulados, troca/liberação, ciclos de 2 s, bip após salvar, proteção de repetição, nova cópia, captura única, parada durante OCR e erro de permissão.")
    finally:
        mocked_reader.side_effect = None
        mocked_reader.return_value = LINES
        page.close()


def exercise_list_delete(context, base_url):
    page = context.new_page()
    try:
        page.goto(base_url)
        expect(page.locator('#active-list')).to_be_enabled()
        page.locator('#new-list-name').fill('Apagar teste')
        page.locator('#new-list').click()
        expect(page.locator('#list-status')).to_contain_text('criada')
        expect(page.locator('#active-list')).to_be_enabled()
        list_id = page.locator('#active-list').input_value()
        added = context.request.post(f'{base_url}/api/lists/{list_id}/items', data={
            'card_id': 'sv03-125', 'language': 'en', 'quantity': 2, 'token': 'delete-browser-test'
        })
        assert added.ok, added.text()
        page.reload()
        expect(page.locator('#list-total')).to_have_text('2 cards')
        expect(page.locator('#delete-list')).to_be_enabled()

        def cancel(dialog):
            assert 'Apagar teste' in dialog.message and '2 cards' in dialog.message
            dialog.dismiss()
        page.once('dialog', cancel)
        page.locator('#delete-list').click()
        expect(page.locator('#list-total')).to_have_text('2 cards')
        assert context.request.get(f'{base_url}/api/lists/{list_id}').ok

        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#delete-list').click()
        expect(page.locator('#active-list')).not_to_have_value(list_id)
        expect(page.locator('#delete-list')).to_be_enabled()
        assert not context.request.get(f'{base_url}/api/lists/{list_id}').ok
        remaining = context.request.get(f'{base_url}/api/lists').json()['lists']
        assert next(deck for deck in remaining if deck['name'] == 'Treino')['total'] == 3

        # Deixa apenas a lista ativa para conferir a exclusão da última lista na tela.
        active_id = page.locator('#active-list').input_value()
        for deck in remaining:
            if deck['id'] != active_id:
                assert context.request.delete(f"{base_url}/api/lists/{deck['id']}").ok
        page.reload()
        expect(page.locator('#delete-list')).to_be_enabled()
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#delete-list').click()
        expect(page.locator('#active-list')).not_to_have_value(active_id)
        expect(page.locator('#list-total')).to_have_text('0 cards')
        expect(page.locator('#download-list')).to_be_disabled()
        assert len(context.request.get(f'{base_url}/api/lists').json()['lists']) == 1
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        print('Apagar lista aprovado: cancelar, confirmar, preservar outras listas e substituir a última por uma lista vazia.')
    finally:
        page.close()


def exercise_quantity_editing(context, base_url, database_path):
    store = ListStore(database_path)
    deck = store.create('Quantidades e rolagem')
    for index in range(1, 41):
        store.add(deck['id'], {**METADATA, 'card_id': f'test-{index:02}', 'name': f'Card {index:02}'}, 1, f'seed-card-{index:02}')
    page = context.new_page()
    try:
        page.goto(base_url)
        expect(page.locator('#active-list')).to_be_enabled()
        page.select_option('#active-list', deck['id'])
        expect(page.locator('#list-total')).to_have_text('40 cards')
        expect(page.locator('#scan')).to_be_disabled()
        page.select_option('#language', 'en')
        photo = io.BytesIO()
        Image.new('RGB', (500, 700), 'white').save(photo, 'JPEG')
        page.locator('#gallery').set_input_files({'name': 'card.jpg', 'mimeType': 'image/jpeg', 'buffer': photo.getvalue()})
        expect(page.locator('#scan')).to_be_enabled()
        page.locator('#scan').click()
        expect(page.locator('#list-total')).to_have_text('41 cards')
        expect(page.locator('#scan')).to_be_enabled()
        assert page.locator('#list-items').evaluate('(el) => el.scrollTop > 0'), 'A nova leitura deve continuar revelando o card incluído'

        row = page.locator('.list-item[data-card-id="test-10"]')
        row.scroll_into_view_if_needed()
        scroll = page.locator('#list-items').evaluate('(el) => el.scrollTop')
        assert scroll > 0
        field = row.locator('.quantity-input')
        row.get_by_role('button', name='Aumentar quantidade de Card 10', exact=True).click()
        expect(field).to_have_value('2')
        expect(field).to_be_enabled()
        assert abs(page.locator('#list-items').evaluate('(el) => el.scrollTop') - scroll) < 2
        row.get_by_role('button', name='Diminuir quantidade de Card 10', exact=True).click()
        expect(field).to_have_value('1')
        expect(field).to_be_enabled()
        assert abs(page.locator('#list-items').evaluate('(el) => el.scrollTop') - scroll) < 2

        field.fill('12'); field.press('Enter')
        expect(page.locator('#list-total')).to_have_text('52 cards')
        expect(field).to_be_enabled(); expect(field).to_be_focused()
        assert abs(page.locator('#list-items').evaluate('(el) => el.scrollTop') - scroll) < 2
        field.fill('7'); field.press('Tab')
        expect(page.locator('#list-total')).to_have_text('47 cards')
        expect(field).to_be_enabled()
        field.fill('1.5'); field.press('Enter')
        expect(field).to_have_value('7')
        expect(page.locator('#list-total')).to_have_text('47 cards')
        field.fill('9'); field.press('Escape')
        expect(field).to_have_value('7')
        assert store.get(deck['id'])['total'] == 47
        field.fill('0'); field.press('Enter')
        expect(row).to_have_count(0)
        expect(page.locator('#list-total')).to_have_text('40 cards')
        assert abs(page.locator('#list-items').evaluate('(el) => el.scrollTop') - scroll) < 2
        page.reload()
        expect(page.locator('#list-total')).to_have_text('40 cards')
        assert store.get(deck['id'])['total'] == 40
        print('Quantidades aprovadas: digitar/Enter/Tab, validar inteiro, Escape, zero para remover, persistência e rolagem estável ao usar +/- com o último card fora da tela.')
    finally:
        page.close()


def main():
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not chrome.exists():
        raise RuntimeError("Google Chrome não encontrado no caminho padrão.")
    with tempfile.TemporaryDirectory() as folder, patch("app.catalog", fake_catalog()), \
            patch("app.reader.read", return_value=LINES) as mocked_reader:
        app = create_app(database_path=Path(folder) / "lists.sqlite3")
        server = create_server(app, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                try:
                    context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
                    # Fontes/imagens remotas não são necessárias para verificar os controles.
                    context.route("https://**/*", lambda route: route.abort())
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.effective_port}")
                    expect(page.locator("#active-list")).to_be_enabled()
                    expect(page.locator("#list-total")).to_have_text("0 cards")
                    page.select_option("#language", "en")
                    photo = io.BytesIO()
                    Image.new("RGB", (500, 700), "white").save(photo, "JPEG")
                    page.locator("#gallery").set_input_files({"name": "card.jpg", "mimeType": "image/jpeg", "buffer": photo.getvalue()})
                    expect(page.locator("#scan")).to_be_enabled()
                    page.locator("#scan-quantity").fill("2")
                    page.locator("#scan").click()
                    expect(page.locator("#list-total")).to_have_text("2 cards")
                    expect(page.locator("#scan")).to_be_enabled()
                    page.locator("#scan").click()
                    expect(page.locator("#status")).to_contain_text("já foi adicionada")
                    expect(page.locator("#list-total")).to_have_text("2 cards")
                    expect(page.locator("#scan")).to_be_enabled()

                    page.locator("#new-list-name").fill("Treino")
                    page.locator("#new-list").click()
                    expect(page.locator("#list-total")).to_have_text("0 cards")
                    expect(page.locator("#active-list")).to_be_enabled()
                    page.locator("#name").fill("Charizard ex")
                    page.locator("#number").fill("125")
                    page.locator("#set-code").fill("OBF")
                    page.locator("#search").click()
                    expect(page.locator(".result-card")).to_have_count(1)
                    page.locator(".result-card").click()
                    page.get_by_role("button", name="Adicionar à lista: Treino", exact=True).click()
                    expect(page.locator("#list-total")).to_have_text("2 cards")
                    page.get_by_role("button", name="Aumentar quantidade de Charizard ex", exact=True).click()
                    expect(page.locator("#list-total")).to_have_text("3 cards")
                    expect(page.locator("#download-list")).to_be_enabled()
                    expect(page.locator("#export-format option")).to_have_count(2)
                    page.select_option("#export-format", "tcglive")
                    with page.expect_download() as download_info:
                        page.locator("#download-list").click()
                    text = Path(download_info.value.path()).read_text(encoding="utf-8")
                    assert "3 Charizard ex OBF 125" in text, text
                    assert "Total Cards: 3" in text, text
                    page.select_option("#export-format", "liga")
                    with page.expect_download() as liga_download:
                        page.locator("#download-list").click()
                    liga_text = Path(liga_download.value.path()).read_text(encoding="utf-8")
                    assert liga_text == "3 Charizard ex (125/197)\n", liga_text
                    page.reload()
                    expect(page.locator("#list-total")).to_have_text("3 cards")
                    lists = context.request.get(f"http://127.0.0.1:{server.effective_port}/api/lists").json()["lists"]
                    first = next(item for item in lists if item["name"] == "Minha lista")
                    page.select_option("#active-list", first["id"])
                    expect(page.locator("#list-total")).to_have_text("2 cards")
                    expect(page.get_by_role("button", name="Remover Charizard ex da lista", exact=True)).to_be_enabled()
                    page.get_by_role("button", name="Remover Charizard ex da lista", exact=True).click()
                    expect(page.locator("#list-total")).to_have_text("0 cards")
                    second = next(item for item in lists if item["name"] == "Treino")
                    expect(page.locator("#active-list")).to_be_enabled()
                    page.select_option("#active-list", second["id"])
                    expect(page.locator("#list-total")).to_have_text("3 cards")
                    expect(page.locator("footer")).to_contain_text("Desenvolvido por Giovani Oliveira")
                    page.locator("#open-help").click()
                    expect(page.locator("#help-dialog")).to_be_visible()
                    page.locator("#close-help").click()
                    check_desktop_layout(page)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Layout excede a largura do celular"
                    assert not errors, errors
                    output = ROOT / "data" / "qa-mobile.png"
                    output.parent.mkdir(exist_ok=True)
                    page.screenshot(path=str(output), full_page=True)
                    print("Interface aprovada: leitura automática, duplicação evitada, múltiplas listas, busca, quantidades, download, persistência e largura móvel.")
                    exercise_webcam(context, f"http://127.0.0.1:{server.effective_port}", mocked_reader)
                    exercise_quantity_editing(context, f"http://127.0.0.1:{server.effective_port}", Path(folder) / 'lists.sqlite3')
                    exercise_list_delete(context, f"http://127.0.0.1:{server.effective_port}")
                finally:
                    browser.close()
        finally:
            server.close()
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
