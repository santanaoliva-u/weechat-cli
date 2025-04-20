# -*- coding: utf-8 -*-
#
# matrix_http.py — Plugin Matrix para WeeChat sin dependencias PyO3
#
# Autor:<urielsantanaoliva@gmail.com>
# Versión: 2.1.1
# Licencia: MIT
# Descripción: Soporte para el protocolo Matrix en WeeChat a través de HTTP
#
# Copyright (c) 2025 santanaoliva_u. Todos los derechos reservados.
# Este software se proporciona "tal cual", sin garantías de ningún tipo.
#
# Requisitos:
#   pip install aiohttp
#
# Instalación:
#   1. Coloca este archivo en ~/.weechat/python/
#   2. Cárgalo en WeeChat con: /python load matrix_http.py
#   3. Conecta a tu servidor Matrix con: /matrix connect
#
#   Instrucciones
# /python load ~/.weechat/python/matrix_http.py
# 
# /set plugins.var.python.matrix.homeserver "https://matrix.org"
# /set plugins.var.python.matrix.username "@username:matrix.org"
# /set plugins.var.python.matrix.password "youpassword"
# /set plugins.var.python.matrix.reconnect_interval 30
# /matrix connect
#


import weechat
import asyncio
import aiohttp
import uuid
import logging
import os
import traceback
from threading import Thread
from queue import Queue

SCRIPT_NAME    = "matrix"
SCRIPT_AUTHOR  = "Jesus Uriel Santana Oliva"
SCRIPT_VERSION = "2.1.1"
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC    = "Matrix support en WeeChat via HTTP"

# 1) Registro del plugin
if not weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "", ""):
    raise Exception("Error al registrar el script en WeeChat")

# 2) Configuración por defecto
_defaults = {
    "homeserver": ("https://matrix.org", "Matrix homeserver URL"),
    "username":   ("",               "Matrix username (e.g., @user:matrix.org)"),
    "password":   ("",               "Matrix password"),
    "reconnect_interval": ("30",     "Segundos entre reintentos de conexión")
}
for opt, (val, desc) in _defaults.items():
    if not weechat.config_is_set_plugin(opt):
        weechat.config_set_plugin(opt, val)
        weechat.config_set_desc_plugin(opt, desc)

# 3) Logging a ~/.weechat/matrix/matrix.log
_weechat_dir = weechat.info_get("weechat_dir", "") or os.path.expanduser("~/.weechat")
_log_dir = os.path.join(_weechat_dir, "matrix")
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(_log_dir, "matrix.log"),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("matrix")
logger.debug("Script iniciado")  # Log inicial para confirmar que el script se cargó

# 4) Cliente Matrix vía HTTP
class MatrixHTTP:
    def __init__(self):
        self.hs        = None
        self.user      = None
        self.passw     = None
        self.token     = None
        self.user_id   = None
        self.since     = None
        self.session   = None
        self.queue     = Queue()
        self.buffers   = {}
        # Crear y arrancar el loop de asyncio en un hilo
        self.loop = asyncio.new_event_loop()
        logger.debug("Iniciando bucle de eventos en un hilo separado")
        t = Thread(target=self._run_loop, daemon=True)
        t.start()

    def _run_loop(self):
        try:
            asyncio.set_event_loop(self.loop)
            logger.debug("Bucle de eventos iniciado")
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Error en el bucle de eventos: {str(e)}")
            logger.error(traceback.format_exc())

    async def _login(self):
        try:
            logger.debug("Iniciando login")
            self.hs    = weechat.config_get_plugin("homeserver").rstrip("/")
            self.user  = weechat.config_get_plugin("username")
            self.passw = weechat.config_get_plugin("password")
            logger.debug(f"Configuración: homeserver={self.hs}, username={self.user}")
            if not all([self.hs, self.user, self.passw]):
                weechat.prnt("", "[matrix] Faltan homeserver/usuario/clave")
                logger.warning("Faltan homeserver/usuario/clave")
                return
            self.session = aiohttp.ClientSession()
            url = f"{self.hs}/_matrix/client/v3/login"
            payload = {"type":"m.login.password","user":self.user,"password":self.passw}
            logger.debug(f"Enviando solicitud de login a {url}")
            async with self.session.post(url, json=payload) as resp:
                res = await resp.json()
            logger.debug(f"Respuesta del login: {res}")
            if "access_token" not in res:
                weechat.prnt("", f"[matrix] Login fallido: {res}")
                logger.error(f"Login fallido: {res}")
                return
            self.token   = res["access_token"]
            self.user_id = res.get("user_id")
            weechat.prnt("", f"[matrix] Conectado como {self.user_id}")
            logger.info(f"Conectado como {self.user_id}")
            # Arranca el bucle de sync inmediatamente
            asyncio.run_coroutine_threadsafe(self._sync_loop(), self.loop)
        except Exception as e:
            weechat.prnt("", f"[matrix] Error en login: {str(e)}")
            logger.error(f"Error en login: {str(e)}")
            logger.error(traceback.format_exc())

    async def _sync_loop(self):
        try:
            logger.debug("Iniciando bucle de sincronización")
            headers = {"Authorization": f"Bearer {self.token}"}
            url     = f"{self.hs}/_matrix/client/v3/sync"
            while True:
                params = {"timeout": 30000}
                if self.since:
                    params["since"] = self.since
                logger.debug(f"Sincronizando con {url}, params={params}")
                async with self.session.get(url, headers=headers, params=params) as resp:
                    data = await resp.json()
                self.since = data.get("next_batch", self.since)
                rooms = data.get("rooms", {}).get("join", {})
                for rid, info in rooms.items():
                    for ev in info.get("timeline", {}).get("events", []):
                        if ev.get("type") == "m.room.message":
                            sender = ev["sender"]
                            body   = ev["content"].get("body", "")
                            self.queue.put((rid, sender, body))
                            logger.debug(f"Mensaje recibido en {rid} de {sender}: {body}")
        except Exception as e:
            logger.error(f"Error en sync_loop: {str(e)}")
            logger.error(traceback.format_exc())

    def disconnect(self):
        try:
            logger.debug("Desconectando")
            if self.session:
                asyncio.run_coroutine_threadsafe(self.session.close(), self.loop)
            self.loop.call_soon_threadsafe(self.loop.stop)
            weechat.prnt("", "[matrix] Desconectado")
            logger.info("Desconectado")
        except Exception as e:
            logger.error(f"Error al desconectar: {str(e)}")
            logger.error(traceback.format_exc())

    def join(self, room_id):
        try:
            logger.debug(f"Intentando unirse a la sala {room_id}")
            headers = {"Authorization": f"Bearer {self.token}"}
            url = f"{self.hs}/_matrix/client/v3/rooms/{room_id}/join"
            asyncio.run_coroutine_threadsafe(self.session.post(url, headers=headers), self.loop)
            weechat.prnt("", f"[matrix] Te uniste a {room_id}")
            logger.info(f"Te uniste a {room_id}")
        except Exception as e:
            logger.error(f"Error al unirse a la sala {room_id}: {str(e)}")
            logger.error(traceback.format_exc())

    def send(self, room_id, msg):
        try:
            logger.debug(f"Enviando mensaje a {room_id}: {msg}")
            txn     = uuid.uuid4().hex
            headers = {"Authorization": f"Bearer {self.token}"}
            url     = f"{self.hs}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}"
            content = {"msgtype":"m.text","body":msg}
            asyncio.run_coroutine_threadsafe(self.session.put(url, headers=headers, json=content), self.loop)
            buf = self._get_buffer(room_id)
            weechat.prnt(buf, f"{self.user_id}: {msg}")
            logger.info(f"Mensaje enviado a {room_id}: {msg}")
        except Exception as e:
            logger.error(f"Error al enviar mensaje a {room_id}: {str(e)}")
            logger.error(traceback.format_exc())

    def list_rooms(self):
        try:
            logger.debug("Listando salas")
            weechat.prnt("", "[matrix] Salas unidas:")
            for rid in self.buffers:
                weechat.prnt("", f"- {rid}")
                logger.info(f"Sala listada: {rid}")
        except Exception as e:
            logger.error(f"Error al listar salas: {str(e)}")
            logger.error(traceback.format_exc())

    def _get_buffer(self, room_id):
        try:
            if room_id not in self.buffers:
                buf = weechat.buffer_new(f"matrix.{room_id}", "input_cb", "", "close_cb", "")
                weechat.buffer_set(buf, "title", f"Matrix: {room_id}")
                self.buffers[room_id] = buf
                logger.debug(f"Buffer creado para {room_id}")
            return self.buffers[room_id]
        except Exception as e:
            logger.error(f"Error al crear buffer para {room_id}: {str(e)}")
            logger.error(traceback.format_exc())

    def process_queue(self, data, remaining):
        try:
            while not self.queue.empty():
                rid, sender, body = self.queue.get()
                buf = self._get_buffer(rid)
                weechat.prnt(buf, f"{sender}: {body}")
                logger.debug(f"Procesando mensaje de la cola: {sender} en {rid}: {body}")
            return weechat.WEECHAT_RC_OK
        except Exception as e:
            logger.error(f"Error al procesar cola: {str(e)}")
            logger.error(traceback.format_exc())
            return weechat.WEECHAT_RC_OK

# Instanciar cliente
M = MatrixHTTP()

# Definir una función global para el callback del timer
def process_queue_callback(data, remaining):
    return M.process_queue(data, remaining)

# Registrar el hook de timer usando la función global
weechat.hook_timer(500, 0, 0, "process_queue_callback", "")

# 5) Comando /matrix
def cmd_matrix(data, buffer, args):
    try:
        logger.debug(f"Comando recibido: {args}")
        argv = args.split()
        if not argv:
            weechat.prnt("", "[matrix] Uso: connect|disconnect|join|send|list")
            logger.warning("Comando vacío")
            return weechat.WEECHAT_RC_OK
        cmd = argv[0]
        if cmd == "connect":
            logger.debug("Ejecutando /matrix connect")
            future = asyncio.run_coroutine_threadsafe(M._login(), M.loop)
            # Esperar un momento para que la coroutine tenga tiempo de ejecutarse
            future.result(timeout=5)
        elif cmd == "disconnect":
            M.disconnect()
        elif cmd == "join" and len(argv) > 1:
            M.join(argv[1])
        elif cmd == "send" and len(argv) > 2:
            M.send(argv[1], " ".join(argv[2:]))
        elif cmd == "list":
            M.list_rooms()
        else:
            weechat.prnt("", "[matrix] Comando desconocido")
            logger.warning(f"Comando desconocido: {cmd}")
        return weechat.WEECHAT_RC_OK
    except Exception as e:
        weechat.prnt("", f"[matrix] Error en comando: {str(e)}")
        logger.error(f"Error en comando {args}: {str(e)}")
        logger.error(traceback.format_exc())
        return weechat.WEECHAT_RC_OK

weechat.hook_command(
    "matrix",
    "Matrix: connect/disconnect/join/send/list",
    "connect|disconnect|join <room>|send <room> <msg>|list",
    "",
    "",
    "cmd_matrix",
    ""
)
