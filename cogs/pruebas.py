# cogs/pruebas.py - mi laboratorio para los experimentos

import discord
from discord import app_commands
from discord.ext import commands

class Pruebas(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="prueba",
        description="Comando de prueba.panel de pruebas"
    )
    async def prueba(self, interaction: discord.Interaction):
        await interaction.response.send_message("La prueba funciona. codigo 200")


async def setup(bot: commands.Bot):
    await bot.add_cog(Pruebas(bot))