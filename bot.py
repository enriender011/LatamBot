#cosas muy importantes
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

if TOKEN is None:
    raise RuntimeError("No se ha encontrado DISCORD_TOKEN en el archivo .env")

if GUILD_ID is None:
    raise RuntimeError("No se ha encontrado DISCORD_GUILD_ID en el archivo .env")

GUILD = discord.Object(id=int(GUILD_ID))

intents = discord.Intents.default()


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.pruebas")
        await self.load_extension("cogs.general")
        await self.load_extension("cogs.moderacion")
        await self.load_extension("cogs.utilidades")

        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)


bot = Bot()



@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} (ID: {bot.user.id})")


bot.run(TOKEN)
