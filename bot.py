import os

import discord
from discord import app_commands
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


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)


bot = Bot()


@bot.tree.command(
    name="ping",
    description="Comprueba si el bot está funcionando."
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} (ID: {bot.user.id})")


bot.run(TOKEN)
