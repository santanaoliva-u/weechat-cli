import weechat
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.events import NewMessage
import logging
import os
import json
import asyncio
import time
from queue import Queue

SCRIPT_NAME    = "telegram"
SCRIPT_AUTHOR  = "santanaoliva_u"
SCRIPT_VERSION = "1.0.12"
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC    = "Telegram account support for WeeChat"

# Globals
logger      = None
CONFIG_DIR  = None
SESSION_DIR = None
loop        = None
manager     = None
tasks       = []  # Track async tasks


def update_weechat_dir():
    global CONFIG_DIR, SESSION_DIR
    weechat_dir = weechat.info_get("weechat_dir", "") or os.path.expanduser("~/.weechat")
    CONFIG_DIR  = os.path.join(weechat_dir, "telegram")
    SESSION_DIR = os.path.join(CONFIG_DIR, "sessions")
    os.makedirs(SESSION_DIR, exist_ok=True)
    if not os.access(SESSION_DIR, os.W_OK):
        weechat.prnt("", f"Telegram: No write permissions for session directory: {SESSION_DIR}")
        logger.error(f"No write permissions for session directory: {SESSION_DIR}")
    logger.debug("Updated session directory: %s", SESSION_DIR)

def setup_logging():
    global logger, CONFIG_DIR, SESSION_DIR
    weechat_dir = os.path.expanduser("~/.weechat")
    CONFIG_DIR  = os.path.join(weechat_dir, "telegram")
    SESSION_DIR = os.path.join(CONFIG_DIR, "sessions")
    os.makedirs(SESSION_DIR, exist_ok=True)
    log_file = os.path.join(CONFIG_DIR, "telegram.log")
    logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(SCRIPT_NAME)
    logger.debug("Session directory: %s", SESSION_DIR)

def setup_config():
    defaults = {
        "api_id": ("", "Telegram API ID from my.telegram.org"),
        "api_hash": ("", "Telegram API Hash from my.telegram.org"),
        "reconnect_interval": ("30", "Seconds between message checks")
    }
    for key, (val, desc) in defaults.items():
        if not weechat.config_is_set_plugin(key):
            weechat.config_set_plugin(key, val)
            weechat.config_set_desc_plugin(key, desc)

# --- Account Manager --------------------------------------------------------

class TelegramAccountManager:
    def __init__(self):
        self.clients      = {}  # phone -> TelegramClient
        self.buffers      = {}  # (phone, chat_id) -> buffer
        self.queue        = Queue()
        self.file         = os.path.join(CONFIG_DIR, "accounts.json")
        self.accounts     = self._load_accounts()
        self.pending_auth = {}  # phone -> TelegramClient during auth

    def _load_accounts(self):
        if os.path.isfile(self.file):
            try:
                with open(self.file) as f:
                    return json.load(f)
            except Exception as e:
                if logger:
                    logger.exception("Error loading accounts: %s", e)
                else:
                    weechat.prnt("", f"Telegram: Error loading accounts: {e}")
        return {}

    def _save_accounts(self):
        try:
            with open(self.file, 'w') as f:
                json.dump(self.accounts, f, indent=2)
            if logger:
                logger.info("Accounts saved")
        except Exception as e:
            if logger:
                logger.exception("Error saving accounts: %s", e)
            else:
                weechat.prnt("", f"Telegram: Error saving accounts: {e}")

    async def add(self, phone):
        if logger:
            logger.debug(f"Attempting to add phone: {phone}")
        api_id = weechat.config_get_plugin("api_id")
        api_hash = weechat.config_get_plugin("api_hash")
        if logger:
            logger.debug(f"API ID: {api_id}, API Hash: {api_hash}")
        if not api_id or not api_hash:
            weechat.prnt("", "Telegram: set api_id & api_hash first")
            if logger:
                logger.error("API ID or API Hash not set")
            return

        try:
            api_id = int(api_id)
        except ValueError:
            weechat.prnt("", "Telegram: api_id must be a number")
            if logger:
                logger.error("Invalid api_id: not a number")
            return

        session = os.path.join(SESSION_DIR, f"{phone}.session")
        client = None
        try:
            if logger:
                logger.debug(f"Creating TelegramClient for session: {session}")
            client = TelegramClient(session, api_id, api_hash)
            if not client:
                weechat.prnt("", f"Telegram: failed to create client for {phone}")
                if logger:
                    logger.error(f"Failed to create TelegramClient for {phone}")
                return
            if logger:
                logger.debug(f"Connecting to Telegram for phone {phone}")
            await client.connect()
            if logger:
                logger.info(f"Connected to Telegram for phone {phone}")
        except Exception as e:
            weechat.prnt("", f"Telegram: failed to connect for {phone}: {e}")
            if logger:
                logger.exception(f"Connection error for {phone}: {e}")
            return

        try:
            if logger:
                logger.debug(f"Sending code request to {phone}")
            await client.send_code_request(phone)
            if logger:
                logger.info(f"Code request sent to {phone}")
            weechat.prnt("", f"Telegram: code sent to {phone}, run /telegram code {phone} <CODE>")
            self.pending_auth[phone] = client
        except Exception as e:
            weechat.prnt("", f"Telegram: failed to send code to {phone}: {e}")
            if logger:
                logger.exception(f"Code request error for {phone}: {e}")
            if client:
                await client.disconnect()
            return

    async def code(self, phone, code):
        if logger:
            logger.debug(f"Processing code for phone: {phone}, code: {code}")
        client = self.pending_auth.get(phone)
        if not client:
            weechat.prnt("", f"Telegram: no pending auth for {phone}")
            if logger:
                logger.error(f"No pending auth for {phone}")
            return
        try:
            await client.sign_in(phone, code)
            if logger:
                logger.info(f"Successful sign-in for {phone}")
        except SessionPasswordNeededError:
            weechat.prnt("", f"Telegram: account has 2FA, enter password with /telegram password {phone} <password>")
            if logger:
                logger.info(f"2FA required for {phone}")
            return
        except Exception as e:
            weechat.prnt("", f"Telegram: sign_in failed: {e}")
            if logger:
                logger.exception(f"Auth code error for {phone}: {e}")
            await client.disconnect()
            self.pending_auth.pop(phone, None)
            return

        self.accounts[phone] = {"session": os.path.basename(client.session.filename)}
        self._save_accounts()
        weechat.prnt("", f"Telegram: account {phone} authenticated and saved")
        await client.disconnect()
        self.pending_auth.pop(phone, None)

    async def password(self, phone, password):
        if logger:
            logger.debug(f"Processing password for phone: {phone}")
        client = self.pending_auth.get(phone)
        if not client:
            weechat.prnt("", f"Telegram: no pending auth for {phone}")
            if logger:
                logger.error(f"No pending auth for {phone}")
            return
        try:
            await client.sign_in(password=password)
            if logger:
                logger.info(f"Successful 2FA sign-in for {phone}")
        except Exception as e:
            weechat.prnt("", f"Telegram: password auth failed: {e}")
            if logger:
                logger.exception(f"Password auth error for {phone}: {e}")
            await client.disconnect()
            self.pending_auth.pop(phone, None)
            return

        self.accounts[phone] = {"session": os.path.basename(client.session.filename)}
        self._save_accounts()
        weechat.prnt("", f"Telegram: account {phone} authenticated and saved")
        await client.disconnect()
        self.pending_auth.pop(phone, None)

    async def connect(self, phone):
        if logger:
            logger.debug(f"Attempting to connect phone: {phone}")
        if phone not in self.accounts:
            weechat.prnt("", f"Telegram: no account {phone}")
            if logger:
                logger.error(f"No account found for {phone}")
            return
        if phone in self.clients:
            weechat.prnt("", f"Telegram: already connected {phone}")
            if logger:
                logger.info(f"Already connected: {phone}")
            return

        api_id = weechat.config_get_plugin("api_id")
        api_hash = weechat.config_get_plugin("api_hash")
        session = os.path.join(SESSION_DIR, self.accounts[phone]["session"])
        try:
            client = TelegramClient(session, int(api_id), api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                weechat.prnt("", f"Telegram: re-auth needed for {phone}")
                if logger:
                    logger.error(f"Re-auth needed for {phone}")
                await client.disconnect()
                return
            client._phone = phone
            client.add_event_handler(self._on_message, NewMessage(incoming=True))
            self.clients[phone] = client
            weechat.prnt("", f"Telegram: connected {phone}")
            if logger:
                logger.info(f"Connected: {phone}")
        except Exception as e:
            weechat.prnt("", f"Telegram: failed to connect {phone}: {e}")
            if logger:
                logger.exception(f"Connect error for {phone}: {e}")

    async def disconnect(self, phone):
        if logger:
            logger.debug(f"Disconnecting phone: {phone}")
        client = self.clients.pop(phone, None)
        if client:
            await client.disconnect()
            weechat.prnt("", f"Telegram: disconnected {phone}")
            if logger:
                logger.info(f"Disconnected: {phone}")

    def list(self):
        weechat.prnt("", "Telegram: connected accounts:")
        for ph in self.clients:
            weechat.prnt("", f" - {ph}")

    async def dialogs(self, phone=None):
        if logger:
            logger.debug(f"Listing dialogs for phone: {phone}")
        phones = [phone] if phone and phone in self.clients else list(self.clients)
        for ph in phones:
            client = self.clients[ph]
            try:
                chats = await client.get_dialogs()
                weechat.prnt("", f"Dialogs for {ph}:")
                for dlg in chats:
                    weechat.prnt("", f"  {dlg.title or dlg.name} ({dlg.id})")
            except Exception as e:
                weechat.prnt("", f"Telegram: failed to get dialogs for {ph}: {e}")
                if logger:
                    logger.exception(f"Dialogs error for {ph}: {e}")

    async def send(self, phone, chat_id, text):
        if logger:
            logger.debug(f"Sending message to {chat_id} from {phone}: {text}")
        client = self.clients.get(phone)
        if not client:
            weechat.prnt("", f"Telegram: {phone} not connected")
            if logger:
                logger.error(f"Phone not connected: {phone}")
            return
        try:
            await client.send_message(int(chat_id), text)
            if logger:
                logger.info(f"Message sent to {chat_id} from {phone}")
        except ValueError:
            weechat.prnt("", f"Telegram: invalid chat_id {chat_id}")
            if logger:
                logger.error(f"Invalid chat_id: {chat_id}")
        except Exception as e:
            weechat.prnt("", f"Telegram: failed to send message: {e}")
            if logger:
                logger.exception(f"Send message error: {e}")

    async def _on_message(self, event):
        try:
            phone = getattr(event.client, '_phone', None)
            if not phone:
                if logger:
                    logger.error("No phone attribute in client")
                return
            chat = event.chat if hasattr(event, 'chat') else None
            if not chat:
                if logger:
                    logger.error("No chat in event")
                return
            cid = str(chat.id)
            sender = chat.title or chat.username or cid
            text = event.message.text or ''
            if text:
                self.queue.put((phone, cid, sender, text))
                if logger:
                    logger.debug(f"Message queued: {phone}, {cid}, {sender}, {text}")
        except Exception as e:
            if logger:
                logger.exception(f"Error processing message: {e}")
            else:
                weechat.prnt("", f"Telegram: Error processing message: {e}")

    def buffer(self, phone, chat_id):
        key = (phone, chat_id)
        if key not in self.buffers:
            name = f"telegram.{phone}.{chat_id}"
            buf = weechat.buffer_new(name, "buffer_input_cb", "", "buffer_close_cb", "")
            weechat.buffer_set(buf, "title", f"Telegram {phone}:{chat_id}")
            self.buffers[key] = buf
            if logger:
                logger.info(f"Buffer created: {name}")
        return self.buffers[key]

# --- Callbacks --------------------------------------------------------------

def process_cb(data, remaining):
    while not manager.queue.empty():
        phone, cid, sender, msg = manager.queue.get()
        buf = manager.buffer(phone, cid)
        weechat.prnt(buf, f"{sender}: {msg}")
    return weechat.WEECHAT_RC_OK

def asyncio_cb(data, remaining):
    """Run asyncio loop for a short time to process tasks."""
    try:
        start = time.time()
        loop.run_until_complete(asyncio.sleep(0.2))  # Process tasks for 200ms
        if logger:
            logger.debug(f"Asyncio loop ran for {time.time() - start:.3f} seconds, tasks pending: {len(tasks)}")
    except Exception as e:
        if logger:
            logger.exception(f"Error in asyncio loop: {e}")
        else:
            weechat.prnt("", f"Telegram: Error in asyncio loop: {e}")
    return weechat.WEECHAT_RC_OK

def cmd_cb(data, buf, args):
    if logger:
        logger.debug(f"Command received: {args}")
    parts = args.strip().split(maxsplit=3)
    cmd = parts[0].lower() if parts else ''
    if logger:
        logger.debug(f"Parsed command: cmd={cmd}, parts={parts}")

    if cmd == 'add' and len(parts) == 2:
        phone = parts[1]
        if logger:
            logger.info(f"Executing add for phone: {phone}")
        try:
            task = loop.create_task(manager.add(phone))
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for add: {phone}, total tasks: {len(tasks)}")
            weechat.prnt("", f"Telegram: processing add for {phone}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing add: {e}")
            if logger:
                logger.exception(f"Error in add command: {e}")
    elif cmd == 'code' and len(parts) == 3:
        phone, code = parts[1], parts[2]
        if logger:
            logger.info(f"Executing code for phone: {phone}")
        try:
            task = loop.create_task(manager.code(phone, code))
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for code: {phone}, total tasks: {len(tasks)}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing code: {e}")
            if logger:
                logger.exception(f"Error in code command: {e}")
    elif cmd == 'password' and len(parts) == 3:
        phone, password = parts[1], parts[2]
        if logger:
            logger.info(f"Executing password for phone: {phone}")
        try:
            task = loop.create_task(manager.password(phone, password))
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for password: {phone}, total tasks: {len(tasks)}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing password: {e}")
            if logger:
                logger.exception(f"Error in password command: {e}")
    elif cmd == 'connect' and len(parts) == 2:
        phone = parts[1]
        if logger:
            logger.info(f"Executing connect for phone: {phone}")
        try:
            task = loop.create_task(manager.connect(phone))
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for connect: {phone}, total tasks: {len(tasks)}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing connect: {e}")
            if logger:
                logger.exception(f"Error in connect command: {e}")
    elif cmd == 'disconnect' and len(parts) == 2:
        phone = parts[1]
        if logger:
            logger.info(f"Executing disconnect for phone: {phone}")
        try:
            task = loop.create_task(manager.disconnect(phone))
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for disconnect: {phone}, total tasks: {len(tasks)}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing disconnect: {e}")
            if logger:
                logger.exception(f"Error in disconnect command: {e}")
    elif cmd == 'list':
        if logger:
            logger.info("Executing list command")
        manager.list()
    elif cmd == 'dialogs':
        if logger:
            logger.info(f"Executing dialogs command, phone: {parts[1] if len(parts) > 1 else 'all'}")
        try:
            if len(parts) == 2:
                task = loop.create_task(manager.dialogs(parts[1]))
            else:
                task = loop.create_task(manager.dialogs())
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for dialogs, total tasks: {len(tasks)}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing dialogs: {e}")
            if logger:
                logger.exception(f"Error in dialogs command: {e}")
    elif cmd == 'send' and len(parts) >= 4:
        phone, chat_id = parts[1], parts[2]
        text = parts[3]
        if logger:
            logger.info(f"Executing send for phone: {phone}, chat_id: {chat_id}")
        try:
            task = loop.create_task(manager.send(phone, chat_id, text))
            tasks.append(task)
            if logger:
                logger.debug(f"Task created for send: {phone}, chat_id: {chat_id}, total tasks: {len(tasks)}")
        except Exception as e:
            weechat.prnt("", f"Telegram: error processing send: {e}")
            if logger:
                logger.exception(f"Error in send command: {e}")
    else:
        weechat.prnt(buf, "Usage: /telegram add <phone> | code <phone> <CODE> | password <phone> <PWD> | connect <phone> | disconnect <phone> | list | dialogs [phone] | send <phone> <chat> <msg>")
        if logger:
            logger.debug("Invalid command syntax")
    return weechat.WEECHAT_RC_OK

def buffer_input_cb(data, buf, inp):
    for (ph, c), b in manager.buffers.items():
        if b == buf:
            if logger:
                logger.debug(f"Sending message from buffer: {ph}, {c}, {inp}")
            try:
                task = loop.create_task(manager.send(ph, c, inp))
                tasks.append(task)
                if logger:
                    logger.debug(f"Task created for buffer input: {ph}, {c}, total tasks: {len(tasks)}")
            except Exception as e:
                if logger:
                    logger.exception(f"Error in buffer input: {e}")
                else:
                    weechat.prnt("", f"Telegram: Error in buffer input: {e}")
            break
    return weechat.WEECHAT_RC_OK

def buffer_close_cb(data, buf):
    for key, b in list(manager.buffers.items()):
        if b == buf:
            del manager.buffers[key]
            if logger:
                logger.info(f"Buffer closed: {key}")
    return weechat.WEECHAT_RC_OK

def shutdown_cb():
    if logger:
        logger.info("Shutting down plugin")
    try:
        for ph in list(manager.clients.keys()):
            task = loop.create_task(manager.disconnect(ph))
            tasks.append(task)
        # Wait for tasks to complete
        loop.run_until_complete(loop.shutdown_asyncgens())
        for task in tasks:
            if not task.done():
                task.cancel()
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
        if logger:
            logger.info("Asyncio loop closed")
    except Exception as e:
        if logger:
            logger.exception(f"Error during shutdown: {e}")
        else:
            weechat.prnt("", f"Telegram: Error during shutdown: {e}")
    if logger:
        logger.info("Plugin shutdown complete")
    return weechat.WEECHAT_RC_OK

# --- Initialization --------------------------------------------------------

def start_loop():
    global loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if logger:
            logger.info("Asyncio loop initialized")
        else:
            weechat.prnt("", "Telegram: Asyncio loop initialized (logger not available)")
    except Exception as e:
        if logger:
            logger.exception(f"Error initializing asyncio loop: {e}")
        else:
            weechat.prnt("", f"Telegram: Error initializing asyncio loop: {e}")
        raise

if __name__ == '__main__':
    try:
        setup_logging()  # Initialize logging first
        start_loop()
        if not weechat.register(
            SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE,
            SCRIPT_DESC, 'shutdown_cb', ''
        ):
            if logger:
                logger.error("Plugin registration failed")
            weechat.prnt("", "Telegram: Plugin registration failed")
            raise RuntimeError("Telegram plugin registration failed")

        update_weechat_dir()  # Update directory after registration
        setup_config()
        manager = TelegramAccountManager()

        weechat.hook_command(
            'telegram',
            'Telegram commands',
            'add <phone> | code <phone> <CODE> | password <phone> <PWD> | connect <phone> | disconnect <phone> | list | dialogs [phone] | send <phone> <chat> <msg>',
            'Manage Telegram accounts and chats',
            'add|code|password|connect|disconnect|list|dialogs|send',
            'cmd_cb', ''
        )

        interval = int(weechat.config_get_plugin('reconnect_interval')) * 1000
        weechat.hook_timer(interval, 0, 0, 'process_cb', '')
        weechat.hook_timer(100, 0, 0, 'asyncio_cb', '')  # Run asyncio every 100ms
        weechat.prnt("", f"Telegram plugin v{SCRIPT_VERSION} loaded")
        if logger:
            logger.info("Plugin loaded successfully")
    except Exception as e:
        if logger:
            logger.exception(f"Error during plugin initialization: {e}")
        else:
            weechat.prnt("", f"Telegram: Error during plugin initialization: {e}")
        raise
