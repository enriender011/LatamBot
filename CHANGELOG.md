# Versión 0.1

Cambios:

- Nuevo sistema de tickets con panel configurable.
- Nuevo modal de creación de tickets para indicar el motivo mediante texto largo.
- Creación de canales numerados dentro de la categoría configurada.
- Sistema de permisos para el usuario creador, el rol de staff, el staff reclamante, administradores y usuarios añadidos.
- Nuevo botón para reclamar tickets y comando /unclaim para retirar una reclamación.
- El ticket deja de ser visible para el resto del staff cuando queda reclamado.
- Nuevos comandos /adduser y /deluser para gestionar usuarios del ticket.
- Flujo completo de cierre, valoración, reapertura y eliminación del ticket.
- Valoraciones de 1 a 5 con comentario opcional y envío de un embed al canal configurado.
- Transcripciones HTML con mensajes, embeds, archivos e imágenes incrustadas, enviadas al canal configurado.
- Persistencia mediante SQLite para configuración, numeración, estados, reclamaciones y usuarios añadidos.
- Restauración automática de permisos después de reiniciar el bot.
- Configuración de IDs y ruta de SQLite mediante variables de entorno para despliegues con Docker y GitHub.
- Activado el intent `message_content` para poder leer los mensajes en las transcripciones.

**Atención** - Este nuevo sistema de tickets está en fase beta y esta es su primera versión. A lo largo de los días pueden ir añadiéndose parches y arreglos a fallos.