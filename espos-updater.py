# ESPOS Updater con pywebview
# Requisitos:
#   pip install pywebview[mshtml] requests pyserial

import os
import threading
import time
import requests
import serial.tools.list_ports
import webview
import json

# Configuración del repositorio
GITHUB_OWNER = 'espos-project'
GITHUB_REPO = 'espos'
LATEST_BIN = 'latest.bin'
ESP_URL = 'http://192.168.4.1/upload'
BAUD_RATE = 9600
# Usar la raíz del servidor como comprobación de estado
STATUS_PATH = 'http://192.168.4.1/'

class Api:
    __pywebview_rpc__ = ['start_update', 'select_custom_bin']
    def __dir__(self):
        return self.__pywebview_rpc__

    def __init__(self):
        self.window = None
        self.port = None
        self.custom_bin = None

    def init_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        options = ''.join(f"<option value='{p}'>{p}</option>" for p in ports)
        opts_json = json.dumps(options)
        self.window.evaluate_js(
            f"document.getElementById('comports').innerHTML = {opts_json};"
        )

    def select_custom_bin(self):
        try:
            paths = webview.create_file_dialog(
                self.window, webview.OPEN_DIALOG,
                file_types=('Binary files (*.bin)',),
                allow_multiple=False
            )
            if paths:
                path = paths[0]
            else:
                return
        except AttributeError:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                path = filedialog.askopenfilename(
                    filetypes=[('Binarios', '*.bin')]
                )
                root.destroy()
                if not path:
                    return
            except Exception as e:
                return self._alert(f"Error al abrir diálogo: {e}")
        self.custom_bin = path
        name = os.path.basename(self.custom_bin)
        name_json = json.dumps(name)
        self.window.evaluate_js(
            f"document.getElementById('customBinLabel').innerText = {name_json};"
        )

    def start_update(self, port):
        self.port = port
        self.window.evaluate_js(
            "document.getElementById('portModal').style.display='none';"
        )
        threading.Thread(target=self._workflow, daemon=True).start()

    def _workflow(self):
        # 1) Serial
        self._log(f"🔌 Abriendo {self.port}@{BAUD_RATE}...")
        try:
            import serial
            with serial.Serial(self.port, BAUD_RATE, timeout=2) as s:
                s.write(b'update\n')
            self._log("✅ Comando 'update' enviado.")
        except Exception as e:
            return self._alert(f"Error serial: {e}")

        # 2) Obtener .bin
        if self.custom_bin:
            bin_path = self.custom_bin
            self._log(f"📦 Usando bin personalizado: {os.path.basename(bin_path)}")
        else:
            bin_path = LATEST_BIN
            self._log("🔍 Descargando .bin de la última release...")
            try:
                api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest'
                r = requests.get(api_url, timeout=10)
                r.raise_for_status()
                asset = next((a for a in r.json().get('assets', []) if a['name'].endswith('.bin')), None)
                if not asset:
                    return self._alert('No se encontró .bin en la última release.')
                dl = asset['browser_download_url']
                r2 = requests.get(dl, stream=True, timeout=20)
                r2.raise_for_status()
                with open(bin_path, 'wb') as f:
                    for chunk in r2.iter_content(1024):
                        f.write(chunk)
                self._log("✅ Descarga completada.")
            except Exception as e:
                return self._alert(f"Error descarga: {e}")

        # 3) Espera AP (sin ping, usando HTTP polling)
        self.window.evaluate_js(
            "document.getElementById('waitModal').style.display='flex';"
        )
        self._log("⌛ Esperando que el ESP32 entre en modo DFU...")
        # Intentar conectar a la raíz cada segundo
        while True:
            try:
                resp = requests.get(STATUS_PATH, timeout=1)
                if resp.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        self.window.evaluate_js(
            "document.getElementById('waitModal').style.display='none';"
        )
        self._log("🔗 AP detectado. Subiendo firmware...")
        self._log("⚠️ NO DESCONECTES TU ESP32. PODRÍA QUEDAR INUTILIZABLE ⚠️")

        # 4) Upload
        try:
            with open(bin_path, 'rb') as f:
                files = {'update': (os.path.basename(bin_path), f, 'application/octet-stream')}
                r3 = requests.post(ESP_URL, files=files, timeout=30)
            if r3.status_code == 200:
                self._log("🎉 ESPOS ha sido actualizado a la última versión. El ESP32 se reiniciará.")
            else:
                self._alert(f"Subida fallida: {r3.status_code}")
        except Exception as e:
            self._alert(f"Error upload: {e}")

    def _log(self, msg):
        safe = msg.replace('`', '')
        message_json = json.dumps("\n" + safe)
        self.window.evaluate_js(
            f"document.getElementById('status').innerText += {message_json};"
        )

    def _alert(self, text):
        alert_json = json.dumps(text)
        self.window.evaluate_js(f"alert({alert_json});")

# HTML con opción para bin personalizado + footer
html = '''<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>ESPOS Updater</title>
<style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#0f0;font-family:'Share Tech Mono',monospace;padding:20px;position:relative;min-height:100vh}
#status{white-space:pre-wrap;border:1px solid #0f0;padding:10px;height:200px;overflow:auto}
button{background:none;border:2px solid #0f0;color:#0f0;padding:10px;cursor:pointer;margin:10px 0}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.9);display:flex;align-items:center;justify-content:center}
.modalContent{background:#111;border:2px solid #0f0;padding:20px;text-align:center;width:300px}
select, input[type=file]{width:100%;padding:5px;margin:10px 0;background:#000;color:#0f0;border:1px solid #0f0}
#footer{position:fixed;bottom:5px;right:10px;opacity:0.2;font-size:12px;pointer-events:none}
</style></head><body>
<h2>ESPOS Updater</h2>
<div id="status">&gt; listo...</div>
<button onclick="document.getElementById('portModal').style.display='flex';">
  ⚡ Actualizar ESP
</button>
<div id="portModal" class="modal" style="display:none">
  <div class="modalContent">
    <h2>Actualizar con la última versión de ESPOS</h2>
    <h3>Selecciona puerto COM</h3>
    <select id="comports"></select>
    <h3>O carga tu .bin personalizado</h3>
    <button onclick="window.pywebview.api.select_custom_bin()">
      📁 Elegir .bin
    </button>
    <div id="customBinLabel" style="margin-bottom:10px;">(Ningún bin seleccionado)</div>
    <button onclick="window.pywebview.api.start_update(document.getElementById('comports').value)">
      Conectar y subir
    </button>
  </div>
</div>
<div id="waitModal" class="modal" style="display:none">
  <div class="modalContent">
    <h3>▶ Conecta este dispositivo al punto de acceso DFU de tu ESP32</h3>
    <small style="color:#0a0;">(Se ocultará al detectar)</small>
  </div>
</div>
<div id="footer">
  ESPOS Updater – v1.1: https://github.com/espos-project/espos-updater
</div>
</body>
</html>'''

if __name__ == '__main__':
    api = Api()
    window = webview.create_window('ESPOS Updater', html=html, js_api=api)
    api.window = window
    window.events.loaded += api.init_ports
    webview.start(gui='chromium', debug=False)
