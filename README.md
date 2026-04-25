# Bot de Gamificación — Telegram

Sistema de gamificación con puntos y recompensas para grupos de Telegram.
Los usuarios completan tareas de interacción en redes sociales y ganan puntos canjeables por premios en sitios aliados.

## Estructura del proyecto

```
├── bot.py              # Punto de entrada
├── config.py           # Configuración desde .env
├── database.py         # Capa de base de datos SQLite
├── scheduler.py        # Envío automático de tareas al grupo
├── validator.py        # Validación de screenshots con Claude Vision
├── voucher.py          # Generador de comprobantes visuales (PNG)
├── handlers/
│   ├── admin.py        # Comandos de administrador
│   └── user.py         # Comandos de usuario
├── screenshots/        # Screenshots de los usuarios (auto-creado)
├── vouchers/           # Vouchers generados (auto-creado)
├── requirements.txt
├── .env.example
└── .env                # Crear desde .env.example (NO subir a git)
```

## Configuración inicial

### 1. Crear el bot en Telegram
1. Abre Telegram y busca **@BotFather**
2. Escribe `/newbot` y sigue las instrucciones
3. Copia el **token** que te da

### 2. Obtener el ID del grupo
1. Añade **@userinfobot** a tu grupo
2. Escribe cualquier mensaje
3. El bot responderá con el ID del chat (número negativo)

### 3. Obtener tu ID de administrador
1. Escribe `/start` a **@userinfobot** en privado
2. Te dará tu ID numérico

### 4. Configurar el archivo .env
```bash
cp .env.example .env
```
Edita `.env` con tus datos:
```
BOT_TOKEN=tu_token_aqui
GROUP_CHAT_ID=-100XXXXXXXXXX
ADMIN_IDS=tu_id_aqui
ANTHROPIC_API_KEY=sk-ant-XXXXXXXX
PROJECT_NAME=Entre Montañas
TIMEZONE=America/Bogota
```

### 5. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 6. Ejecutar el bot
```bash
python bot.py
```

## Comandos disponibles

### Administrador
| Comando | Descripción |
|---------|-------------|
| `/admin` | Panel principal de administración |
| `/nueva_tarea` | Crear una nueva tarea |
| `/listar_tareas` | Ver tareas activas |
| `/programar` | Programar envío de tarea al grupo |
| `/proximos_envios` | Ver próximos envíos |
| `/nuevo_premio` | Agregar premio al catálogo |
| `/listar_premios` | Ver catálogo de premios |
| `/pendientes` | Revisar comprobantes pendientes |
| `/ranking` | Ver ranking de usuarios |
| `/validar_codigo` | Verificar un voucher de canje |

### Usuario
| Comando | Descripción |
|---------|-------------|
| `/start` | Registrarse y ver ayuda |
| `/tareas` | Ver tarea activa |
| `/mis_puntos` | Ver saldo de puntos |
| `/premios` | Ver catálogo de premios |
| `/canjear` | Canjear puntos por un premio |
| `/mis_canjes` | Ver historial de canjes |
| `/historial` | Ver historial de tareas |

## Flujo de uso

1. **Admin** crea una tarea con `/nueva_tarea`
2. **Admin** programa el envío con `/programar`
3. El **bot** envía la tarea al grupo automáticamente a la hora programada
4. Los **usuarios** ven la tarea en el grupo y la realizan en redes sociales
5. Los **usuarios** envían el screenshot al bot en privado
6. El **bot** valida el screenshot con IA (Claude Vision)
7. Si es válido, el usuario recibe los puntos automáticamente
8. Los **usuarios** pueden canjear puntos por premios con `/canjear`
9. El **bot** genera un voucher visual con código único
10. El usuario presenta el código al sitio aliado
