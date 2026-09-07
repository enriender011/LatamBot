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
        description="Comprueba si el bot está funcionando y su latencia."
    )
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Latencia: {latency_ms} ms")

    @app_commands.command(
        name="userinfo",
        description="Muestra información de un usuario de Discord."
    )
    @app_commands.describe(
        usuario="Selecciona un usuario del servidor.",
        user_id="Introduce el ID de cualquier usuario de Discord."
    )
    async def userinfo(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
        user_id: str | None = None,
    ):
        if usuario is not None and user_id is not None:
            await interaction.response.send_message(
                "Selecciona un usuario o introduce un ID, pero no ambos.",
                ephemeral=True,
            )
            return

        if usuario is not None:
            user = usuario
        elif user_id is not None:
            try:
                user = await self.bot.fetch_user(int(user_id))
            except (ValueError, discord.NotFound):
                await interaction.response.send_message(
                    "El ID introducido no corresponde a ningún usuario de Discord",
                    ephemeral=True,
                )
                return
        else:
            await interaction.response.send_message(
                "Selecciona un usuario o introduce un ID.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Información del usuario",
            color=discord.Color(0x8A9A5B),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        embed.add_field(
            name="Nombre de visualización",
            value=user.display_name,
            inline=False,
        )
        embed.add_field(
            name="Cuenta creada el",
            value=discord.utils.format_dt(user.created_at, style="F"),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="serverinfo",
        description="Muestra información del servidor actual."
    )
    async def serverinfo(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede usarse dentro de un servidor.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        embed = discord.Embed(
            title=guild.name,
            color=discord.Color(0x8A9A5B),
        )

        if guild.icon is not None:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(
            name="Propietario",
            value=f"<@{guild.owner_id}>",
            inline=True,
        )
        embed.add_field(
            name="Miembros",
            value=f"`{guild.member_count:,}`",
            inline=True,
        )
        embed.add_field(
            name="Servidor creado el",
            value=discord.utils.format_dt(guild.created_at, style="F"),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))