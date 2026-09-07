# cogs/general.py - Cositas generales del bot , comandos básicos que no van en
# ninguna categoría

import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Comprueba si el bot está funcionando."
    )
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("Pong!")


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))