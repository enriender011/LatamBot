# LatamBot

Un bot de moderación y asistencia para LatamCity RP. Puedes unirte al servidor [pulsando aquí.](https://discord.gg/S9veQYRxG2)

## Características

Comandos de barra diagonal

## Despliegue

El archivo `.env` y la base de datos de tickets no forman parte del repositorio.
En el servidor deben configurarse al menos `DISCORD_TOKEN` y `DISCORD_GUILD_ID`.
Para este servidor, añade también:

```env
TICKETS_STAFF_ROLE_ID=1408855611285831690
TICKETS_PANEL_CHANNEL_ID=1547701624804347934
TICKETS_CATEGORY_ID=1432759312408772629
TICKETS_RATING_CHANNEL_ID=1492992178505519224
TICKETS_TRANSCRIPT_CHANNEL_ID=1409585758872014888
```

La base de datos se crea por defecto en `data/tickets.sqlite3`. Para conservarla
en una ubicación persistente del servidor se puede definir `TICKETS_DATABASE_PATH`
con una ruta absoluta, por ejemplo `/var/lib/latambot/tickets.sqlite3`.

### Contenedor Docker

El contenedor debe recibir `DISCORD_TOKEN`, `DISCORD_GUILD_ID` y, preferiblemente,
`TICKETS_DATABASE_PATH=/data/tickets.sqlite3`. La ruta `/data` debe estar montada
como un volumen persistente del servidor. De esta forma, al recrear o actualizar
el contenedor desde GitHub se conserva la configuración, la numeración y el estado
de los tickets.

Ejemplo de volumen en Docker Compose:

```yaml
services:
	latambot:
		environment:
			TICKETS_DATABASE_PATH: /data/tickets.sqlite3
		volumes:
			- latambot-data:/data

volumes:
	latambot-data:
```

## Próximamente...
