

---

## 🛠️ Integración de Matrix y Telegram en WeeChat (Guía Completa)

### ✅ Requisitos generales

- **Sistema operativo**: Linux, macOS o Windows con WSL2
    
- **WeeChat**: v3.0+ (con soporte para scripts Python)
    
- **Python**: v3.7+
    
- **Herramientas**: `git`, `pip`, `python3-venv`
    
- **Dependencias Python**:
    
    - `aiohttp` (para Matrix)
        
    - `telethon` (para Telegram)
        
- **Cuentas activas**:
    
    - [Matrix](https://matrix.org)
        
    - [Telegram](https://my.telegram.org)
        

---

## 🔗 Configurar Matrix en WeeChat

### 1. Preparar entorno

#### Linux/macOS

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y         # Debian/Ubuntu
brew update && brew upgrade                    # macOS

# Instalar herramientas
sudo apt install weechat weechat-python python3 python3-pip python3-venv git -y
```

#### Crear entorno virtual

```bash
python3 -m venv ~/weechat-matrix-env
source ~/weechat-matrix-env/bin/activate
pip install aiohttp
```

---

### 2. Descargar y configurar el script

```bash
mkdir -p ~/.weechat/python
cp matrix_http.py ~/.weechat/python/           # Asegúrate de tener este archivo
```

En WeeChat:

```weechat
/python load ~/.weechat/python/matrix_http.py
```

---

### 3. Configurar credenciales

```weechat
/set plugins.var.python.matrix.homeserver "https://matrix.org"
/set plugins.var.python.matrix.username "@tu_usuario:matrix.org"
/set plugins.var.python.matrix.password "tu_contraseña"
/set plugins.var.python.matrix.reconnect_interval 30
```

---

### 4. Comandos útiles

|Comando|Descripción|
|---|---|
|`/matrix connect`|Conectar a Matrix|
|`/matrix list`|Ver salas unidas|
|`/matrix join <room>`|Unirse a una sala específica|
|`/matrix send <room> <msg>`|Enviar mensaje a una sala|
|`/matrix disconnect`|Desconectar de Matrix|

---

### 5. Depuración

- Log: `~/.weechat/matrix/matrix.log`
    
- Verifica: conexión al homeserver, credenciales y compatibilidad con Python
    

---

### ☁️ Subir a GitHub

```bash
git clone https://github.com/tu-usuario/weechat-matrix.git
cd weechat-matrix
cp ~/.weechat/python/matrix_http.py .
touch README.md     # O crea uno detallado como el ejemplo de abajo
git add .
git commit -m "Inicializa plugin Matrix para WeeChat"
git push origin main
```

---

## 📦 Ejemplo de README.md para Matrix

```markdown
# WeeChat Matrix Plugin

Integración avanzada de Matrix en WeeChat.

## Características
- Soporte para múltiples salas
- Reconexión automática
- Comandos simples y potentes

## Instalación
1. Crea entorno virtual y activa:
   ```bash
   python3 -m venv ~/weechat-matrix-env
   source ~/weechat-matrix-env/bin/activate
   pip install aiohttp
```

2. Copia el script a `~/.weechat/python/` y cárgalo desde WeeChat.
    
3. Configura tus credenciales Matrix.
    

## Licencia

MIT

---

## 💬 Configurar Telegram en WeeChat

### 1. Preparar entorno

```bash
# Ya instalado en pasos previos:
python3 -m venv ~/weechat-telegram-env
source ~/weechat-telegram-env/bin/activate
pip install telethon
````

---

### 2. Obtener credenciales

1. Ve a [my.telegram.org](https://my.telegram.org)
    
2. Inicia sesión y crea una aplicación
    
3. Guarda tu `api_id` y `api_hash`
    

---

### 3. Configurar el script

```bash
mkdir -p ~/.weechat/python
cp telegram_http.py ~/.weechat/python/
```

En WeeChat:

```weechat
/python load ~/.weechat/python/telegram_http.py
```

---

### 4. Añadir cuenta y comandos

```weechat
/telegram add_account +1234567890 12345678 your_api_hash
/telegram code +1234567890 12345
/telegram password +1234567890 tu_contraseña     # Si usas 2FA
/telegram connect +1234567890
```

|Comando|Descripción|
|---|---|
|`/telegram send <tel> <id> <msg>`|Enviar mensaje|
|`/telegram list`|Ver cuentas configuradas|
|`/telegram disconnect <tel>`|Desconectar cuenta|

---

### 5. Subir a GitHub

```bash
git clone https://github.com/tu-usuario/weechat-telegram.git
cd weechat-telegram
cp ~/.weechat/python/telegram_http.py .
touch README.md
git add .
git commit -m "Inicializa plugin Telegram para WeeChat"
git push origin main
```

---

## 📝 Ejemplo de README.md para Telegram

```markdown
# WeeChat Telegram Plugin

Plugin para gestionar múltiples cuentas de Telegram desde la terminal con WeeChat.

## Características
- Soporte para múltiples cuentas
- Soporte para 2FA
- Envío/recepción de mensajes

## Instalación
1. Instala dependencias: `telethon`
2. Copia el script y configúralo en WeeChat
3. Usa los comandos `/telegram` para gestionar cuentas

## Licencia
MIT
```

---

Si lo deseas, también puedo ayudarte a convertir esto en un archivo Markdown (`.md`) listo para subir a GitHub. ¿Te gustaría eso?