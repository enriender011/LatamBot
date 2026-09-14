import asyncio
import base64
import html
import os
import io
import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands


PROJECT_ROOT = Path(__file__).resolve().parent.parent
configured_database_path = Path(
	os.getenv("TICKETS_DATABASE_PATH", "data/tickets.sqlite3")
)
configured_staff_role_id = os.getenv("TICKETS_STAFF_ROLE_ID")
configured_panel_channel_id = os.getenv("TICKETS_PANEL_CHANNEL_ID")
configured_category_id = os.getenv("TICKETS_CATEGORY_ID")
configured_rating_channel_id = os.getenv("TICKETS_RATING_CHANNEL_ID")
configured_transcript_channel_id = os.getenv("TICKETS_TRANSCRIPT_CHANNEL_ID")
DATABASE_PATH = (
	configured_database_path
	if configured_database_path.is_absolute()
	else PROJECT_ROOT / configured_database_path
)


class TicketDatabase:
	def __init__(self, path: Path):
		path.parent.mkdir(parents=True, exist_ok=True)
		self.connection = sqlite3.connect(path)
		self.connection.row_factory = sqlite3.Row
		self.connection.executescript(
			"""
			CREATE TABLE IF NOT EXISTS ticket_config (
				guild_id INTEGER PRIMARY KEY,
				category_id INTEGER NOT NULL,
				staff_role_id INTEGER NOT NULL,
				panel_channel_id INTEGER NOT NULL,
				rating_channel_id INTEGER,
				transcript_channel_id INTEGER
			);
			CREATE TABLE IF NOT EXISTS ticket_counter (
				guild_id INTEGER PRIMARY KEY,
				next_number INTEGER NOT NULL DEFAULT 1
			);
			CREATE TABLE IF NOT EXISTS tickets (
				channel_id INTEGER PRIMARY KEY,
				guild_id INTEGER NOT NULL,
				number INTEGER NOT NULL,
				owner_id INTEGER NOT NULL,
				claimed_by INTEGER,
				status TEXT NOT NULL DEFAULT 'open'
			);
			CREATE TABLE IF NOT EXISTS ticket_members (
				channel_id INTEGER NOT NULL,
				user_id INTEGER NOT NULL,
				PRIMARY KEY (channel_id, user_id)
			);
			"""
		)
		columns = {
			row["name"]
			for row in self.connection.execute("PRAGMA table_info(ticket_config)")
		}
		if "rating_channel_id" not in columns:
			self.connection.execute("ALTER TABLE ticket_config ADD COLUMN rating_channel_id INTEGER")
		if "transcript_channel_id" not in columns:
			self.connection.execute("ALTER TABLE ticket_config ADD COLUMN transcript_channel_id INTEGER")
		self.connection.commit()

	def configure(
		self,
		guild_id: int,
		category_id: int,
		staff_role_id: int,
		panel_channel_id: int,
		rating_channel_id: int | None,
		transcript_channel_id: int | None,
	) -> None:
		self.connection.execute(
			"""
			INSERT INTO ticket_config (
				guild_id, category_id, staff_role_id, panel_channel_id,
				rating_channel_id, transcript_channel_id
			) VALUES (?, ?, ?, ?, ?, ?)
			ON CONFLICT(guild_id) DO UPDATE SET
				category_id = excluded.category_id,
				staff_role_id = excluded.staff_role_id,
				panel_channel_id = excluded.panel_channel_id,
				rating_channel_id = excluded.rating_channel_id,
				transcript_channel_id = excluded.transcript_channel_id
			""",
			(
				guild_id,
				category_id,
				staff_role_id,
				panel_channel_id,
				rating_channel_id,
				transcript_channel_id,
			),
		)
		self.connection.commit()

	def get_config(self, guild_id: int) -> sqlite3.Row | None:
		return self.connection.execute(
			"SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
		).fetchone()

	def next_ticket_number(self, guild_id: int) -> int:
		row = self.connection.execute(
			"SELECT next_number FROM ticket_counter WHERE guild_id = ?", (guild_id,)
		).fetchone()
		number = row["next_number"] if row else 1
		self.connection.execute(
			"""
			INSERT INTO ticket_counter (guild_id, next_number) VALUES (?, ?)
			ON CONFLICT(guild_id) DO UPDATE SET next_number = excluded.next_number
			""",
			(guild_id, number + 1),
		)
		self.connection.commit()
		return number

	def create_ticket(self, channel_id: int, guild_id: int, number: int, owner_id: int) -> None:
		self.connection.execute(
			"INSERT INTO tickets (channel_id, guild_id, number, owner_id) VALUES (?, ?, ?, ?)",
			(channel_id, guild_id, number, owner_id),
		)
		self.connection.commit()

	def get_ticket(self, channel_id: int) -> sqlite3.Row | None:
		return self.connection.execute(
			"SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
		).fetchone()

	def get_active_tickets(self) -> list[sqlite3.Row]:
		return self.connection.execute(
			"SELECT * FROM tickets WHERE status != 'deleted'"
		).fetchall()

	def get_ticket_members(self, channel_id: int) -> list[int]:
		rows = self.connection.execute(
			"SELECT user_id FROM ticket_members WHERE channel_id = ?", (channel_id,)
		).fetchall()
		return [row["user_id"] for row in rows]

	def set_claimed(self, channel_id: int, user_id: int) -> None:
		self.connection.execute(
			"UPDATE tickets SET claimed_by = ? WHERE channel_id = ?",
			(user_id, channel_id),
		)
		self.connection.commit()

	def clear_claimed(self, channel_id: int) -> None:
		self.connection.execute(
			"UPDATE tickets SET claimed_by = NULL WHERE channel_id = ?", (channel_id,)
		)
		self.connection.commit()

	def set_status(self, channel_id: int, status: str) -> None:
		self.connection.execute(
			"UPDATE tickets SET status = ? WHERE channel_id = ?", (status, channel_id)
		)
		self.connection.commit()

	def has_open_ticket(self, guild_id: int, owner_id: int) -> bool:
		return self.connection.execute(
			"SELECT 1 FROM tickets WHERE guild_id = ? AND owner_id = ? AND status = 'open'",
			(guild_id, owner_id),
		).fetchone() is not None

	def add_member(self, channel_id: int, user_id: int) -> None:
		self.connection.execute(
			"INSERT OR IGNORE INTO ticket_members (channel_id, user_id) VALUES (?, ?)",
			(channel_id, user_id),
		)
		self.connection.commit()

	def remove_member(self, channel_id: int, user_id: int) -> None:
		self.connection.execute(
			"DELETE FROM ticket_members WHERE channel_id = ? AND user_id = ?",
			(channel_id, user_id),
		)
		self.connection.commit()


def is_admin(member: discord.Member) -> bool:
	return member.guild_permissions.administrator


def permission_error_embed() -> discord.Embed:
	return discord.Embed(
		description="No tienes permiso para usar ese botón.",
		color=discord.Color.red(),
	)


class TicketPanelView(discord.ui.View):
	def __init__(self, cog: "Tickets"):
		super().__init__(timeout=None)
		self.cog = cog

	@discord.ui.button(label="Crear ticket", style=discord.ButtonStyle.success, custom_id="tickets:create")
	async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
		await interaction.response.send_modal(CreateTicketModal(self.cog))


class CreateTicketModal(discord.ui.Modal, title="Incidencias externas"):
	reason = discord.ui.TextInput(
		label="Explica el motivo de la creación del ticket.",
		placeholder="Explica detalladamente el motivo de tu ticket...",
		style=discord.TextStyle.paragraph,
		required=True,
		max_length=4000,
	)

	def __init__(self, cog: "Tickets"):
		super().__init__()
		self.cog = cog

	async def on_submit(self, interaction: discord.Interaction) -> None:
		if interaction.guild is None or not isinstance(interaction.user, discord.Member):
			await interaction.response.send_message(
				"Este formulario solo puede usarse dentro de un servidor.", ephemeral=True
			)
			return
		if self.cog.database.has_open_ticket(interaction.guild.id, interaction.user.id):
			await interaction.response.send_message("Ya tienes un ticket abierto.", ephemeral=True)
			return

		config = self.cog.database.get_config(interaction.guild.id)
		category = interaction.guild.get_channel(config["category_id"]) if config else None
		staff_role = interaction.guild.get_role(config["staff_role_id"]) if config else None
		if not isinstance(category, discord.CategoryChannel) or staff_role is None:
			await interaction.response.send_message(
				"El sistema de tickets todavía no está configurado.", ephemeral=True
			)
			return

		number = self.cog.database.next_ticket_number(interaction.guild.id)
		overwrites = {
			interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
			interaction.user: discord.PermissionOverwrite(
				view_channel=True, send_messages=True, read_message_history=True
			),
			staff_role: discord.PermissionOverwrite(
				view_channel=True, send_messages=True, read_message_history=True
			),
			interaction.guild.me: discord.PermissionOverwrite(
				view_channel=True, send_messages=True, manage_channels=True
			),
		}
		channel = await interaction.guild.create_text_channel(
			name=f"ticket-{number:04d}",
			category=category,
			overwrites=overwrites,
			reason=f"Ticket creado por {interaction.user}",
		)
		self.cog.database.create_ticket(channel.id, interaction.guild.id, number, interaction.user.id)
		await interaction.response.send_message(
			f"Tu ticket ha sido creado: {channel.mention}", ephemeral=True
		)
		embed = discord.Embed(
			title="Su ticket ha sido abierto correctamente",
			description=(
				"「![🎫](https://discord.com/assets/0668ca7859b5ab1a.svg) 」ᴛɪᴄᴋᴇᴛ\n"
				"Bienvenido a tu ticket! ⭐️\n"
				f"{interaction.user.mention}. Espere a que el **equipo administrativo** lo atienda.\n\n"
				"**Motivo de la creación del ticket**\n"
				f"{self.reason.value}"
			),
			color=discord.Color(0x8A9A5B),
		)
		await channel.send(
			f"{staff_role.mention} {interaction.user.mention}",
			embed=embed,
			view=TicketControlsView(self.cog),
			allowed_mentions=discord.AllowedMentions(roles=True, users=True),
		)


class TicketControlsView(discord.ui.View):
	def __init__(
		self, cog: "Tickets", include_claim: bool = True, include_close: bool = True
	):
		super().__init__(timeout=None)
		self.cog = cog
		if not include_claim:
			self.remove_item(next(item for item in self.children if item.custom_id == "tickets:claim"))
		if not include_close:
			self.remove_item(next(item for item in self.children if item.custom_id == "tickets:start-close"))

	@discord.ui.button(
		label="Cerrar ticket",
		style=discord.ButtonStyle.primary,
		custom_id="tickets:start-close",
	)
	async def start_close(
		self, interaction: discord.Interaction, button: discord.ui.Button
	) -> None:
		ticket = await self.cog.can_manage_ticket(interaction)
		if ticket is None:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if ticket["status"] != "open":
			await interaction.response.send_message(
				"Este ticket ya está en proceso de cierre.", ephemeral=True
			)
			return
		self.cog.database.set_status(interaction.channel_id, "pending_rating")
		button.disabled = True
		await interaction.response.edit_message(view=self)
		claimed_staff = await self.cog.resolve_member(
			interaction.guild, ticket["claimed_by"]
		)
		claimed_staff_name = claimed_staff.name if claimed_staff else "el staff asignado"
		owner = await self.cog.resolve_member(interaction.guild, ticket["owner_id"])
		owner_name = owner.name if owner else "Usuario"
		embed = discord.Embed(
			description=(
				f"**{owner_name}** "
				"por favor valore la atención recibida en el ticket por parte del staff "
				f"**{claimed_staff_name}**."
			),
			color=discord.Color(0xF2F244),
		)
		await interaction.channel.send(
			embed=embed,
			view=TicketRatingView(self.cog),
			allowed_mentions=discord.AllowedMentions(users=True),
		)

	@discord.ui.button(
		label="Reclamar ticket",
		style=discord.ButtonStyle.danger,
		custom_id="tickets:claim",
	)
	async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
		ticket = self.cog.database.get_ticket(interaction.channel_id)
		if ticket is None or interaction.guild is None:
			await interaction.response.send_message("Este canal no es un ticket.", ephemeral=True)
			return
		if not isinstance(interaction.user, discord.Member):
			return
		config = self.cog.database.get_config(interaction.guild.id)
		staff_role = interaction.guild.get_role(config["staff_role_id"]) if config else None
		if interaction.user.id == ticket["owner_id"]:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if staff_role is None or staff_role not in interaction.user.roles:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if ticket["claimed_by"] is not None:
			await interaction.response.send_message("Este ticket ya ha sido reclamado.", ephemeral=True)
			return

		channel = interaction.channel
		if not isinstance(channel, discord.TextChannel) or staff_role is None:
			return
		await channel.set_permissions(staff_role, view_channel=False)
		await channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
		self.cog.database.set_claimed(channel.id, interaction.user.id)
		button.disabled = True
		await interaction.response.edit_message(view=self)
		await channel.send(f"Ticket reclamado por {interaction.user.mention}.")


class UnclaimedTicketView(discord.ui.View):
	def __init__(self, cog: "Tickets"):
		super().__init__(timeout=None)
		self.cog = cog

	@discord.ui.button(
		label="Reclamar ticket",
		style=discord.ButtonStyle.success,
		custom_id="tickets:claim-again",
	)
	async def claim_again(
		self, interaction: discord.Interaction, button: discord.ui.Button
	) -> None:
		ticket = self.cog.database.get_ticket(interaction.channel_id)
		if ticket is None or interaction.guild is None:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if not isinstance(interaction.user, discord.Member):
			return
		config = self.cog.database.get_config(interaction.guild.id)
		staff_role = interaction.guild.get_role(config["staff_role_id"]) if config else None
		if interaction.user.id == ticket["owner_id"]:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if staff_role is None or staff_role not in interaction.user.roles:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if ticket["claimed_by"] is not None:
			await interaction.response.send_message(
				"Este ticket ya ha sido reclamado.", ephemeral=True
			)
			return
		if not isinstance(interaction.channel, discord.TextChannel):
			return
		await interaction.channel.set_permissions(
			staff_role, view_channel=False, send_messages=False
		)
		await interaction.channel.set_permissions(
			interaction.user, view_channel=True, send_messages=True, read_message_history=True
		)
		self.cog.database.set_claimed(interaction.channel.id, interaction.user.id)
		button.disabled = True
		await interaction.response.edit_message(view=self)
		await interaction.channel.send(f"Ticket reclamado por {interaction.user.mention}.")

class TicketRatingView(discord.ui.View):
	def __init__(self, cog: "Tickets"):
		super().__init__(timeout=None)
		self.cog = cog

	@discord.ui.button(
		label="Valorar ticket",
		style=discord.ButtonStyle.success,
		custom_id="tickets:rate",
	)
	async def rate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
		ticket = self.cog.database.get_ticket(interaction.channel_id)
		if ticket is None or ticket["status"] != "pending_rating":
			await interaction.response.send_message("Este ticket no admite valoraciones ahora.", ephemeral=True)
			return
		if interaction.user.id != ticket["owner_id"]:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if isinstance(interaction.user, discord.Member):
			config = self.cog.database.get_config(interaction.guild.id) if interaction.guild else None
			staff_role = interaction.guild.get_role(config["staff_role_id"]) if config and interaction.guild else None
			if staff_role is not None and staff_role in interaction.user.roles:
				await interaction.response.send_message(
					embed=permission_error_embed(), ephemeral=True
				)
				return
		await interaction.response.send_modal(RatingModal(self.cog, self, interaction.message))

	@discord.ui.button(
		label="Cancelar valoracion",
		style=discord.ButtonStyle.danger,
		custom_id="tickets:cancel-rating",
	)
	async def cancel_rating(
		self, interaction: discord.Interaction, button: discord.ui.Button
	) -> None:
		ticket = await self.cog.can_manage_ticket(interaction)
		if ticket is None or ticket["status"] != "pending_rating":
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		self.cog.database.set_status(interaction.channel_id, "ready_to_close")
		button.disabled = True
		for child in self.children:
			child.disabled = True
		await interaction.response.edit_message(view=self)
		staff = (
			await self.cog.resolve_member(interaction.guild, ticket["claimed_by"])
			if interaction.guild
			else None
		)
		staff_name = staff.name if staff else str(ticket["claimed_by"])
		embed = discord.Embed(
			description=f"**{staff_name}** ha cancelado la valoración del ticket.",
			color=discord.Color(0x8A9A5B),
		)
		await interaction.channel.send(
			embed=embed,
			view=FinalCloseView(self.cog),
		)


class RatingModal(discord.ui.Modal, title="Valorar atención"):
	score = discord.ui.TextInput(
		label="Valoración (1-5)", required=True, max_length=1
	)
	comment = discord.ui.TextInput(
		label="Comentarios", style=discord.TextStyle.paragraph, required=False, max_length=1000
	)

	def __init__(
		self,
		cog: "Tickets",
		rating_view: TicketRatingView,
		rating_message: discord.Message | None,
	):
		super().__init__()
		self.cog = cog
		self.rating_view = rating_view
		self.rating_message = rating_message

	async def on_submit(self, interaction: discord.Interaction) -> None:
		ticket = self.cog.database.get_ticket(interaction.channel_id)
		if ticket is None or ticket["status"] != "pending_rating":
			await interaction.response.send_message("Este ticket ya no admite valoraciones.", ephemeral=True)
			return
		if interaction.user.id != ticket["owner_id"]:
			await interaction.response.send_message("Solo puede valorar el creador del ticket.", ephemeral=True)
			return
		if self.score.value not in {"1", "2", "3", "4", "5"}:
			await interaction.response.send_message(
				"El número que has introducido no es válido", ephemeral=True
			)
			return

		for child in self.rating_view.children:
			child.disabled = True
		if self.rating_message is not None:
			await self.rating_message.edit(view=self.rating_view)
		self.cog.database.set_status(interaction.channel_id, "ready_to_close")
		owner = interaction.guild.get_member(ticket["owner_id"]) if interaction.guild else None
		owner_name = owner.name if owner else str(ticket["owner_id"])
		if interaction.guild is not None:
			config = self.cog.database.get_config(interaction.guild.id)
			rating_channel = (
				interaction.guild.get_channel(config["rating_channel_id"])
				if config and config["rating_channel_id"]
				else None
			)
			if isinstance(rating_channel, discord.TextChannel):
				claimed_staff = interaction.guild.get_member(ticket["claimed_by"])
				staff_name = claimed_staff.name if claimed_staff else str(ticket["claimed_by"])
				comment = self.comment.value or "Sin comentarios"
				embed = discord.Embed(
					title="• Valoración",
					description=(
						f"Ticket valorado por **{owner_name}**\n\n"
						"➦ Ticket\n"
						f"#《![🎟️](https://discord.com/assets/dde8a9804160342c.svg)》{interaction.channel.name} ({interaction.channel.id})\n\n"
						"➦ Panel\n"
						"Incidencias externas\n\n"
						f"➦ Staff\n{staff_name} ({ticket['claimed_by']})\n\n"
						f"➦ Estrellas\n**{self.score.value}**![:star:](https://discord.com/assets/6dcab1360be157d5.svg)\n\n"
						f"➦ Comentarios\n{comment}"
					),
					color=discord.Color(0x8A9A5B),
				)
				await rating_channel.send(embed=embed)

		embed = discord.Embed(
			description=(
				f"**{owner_name}** ha valorado la atención del ticket con "
				f"**{self.score.value}** estrellas."
			),
			color=discord.Color(0x8A9A5B),
		)
		await interaction.channel.send(
			embed=embed,
			view=FinalCloseView(self.cog),
		)
		await interaction.response.send_message("La valoración se ha enviado correctamente.")


class FinalCloseView(discord.ui.View):
	def __init__(self, cog: "Tickets"):
		super().__init__(timeout=None)
		self.cog = cog

	@discord.ui.button(
		label="Cerrar ticket",
		style=discord.ButtonStyle.danger,
		custom_id="tickets:final-close",
	)
	async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
		ticket = await self.cog.can_manage_ticket(interaction)
		if ticket is None:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if not isinstance(interaction.channel, discord.TextChannel):
			return
		self.cog.database.set_status(interaction.channel.id, "closed")
		owner = interaction.guild.get_member(ticket["owner_id"]) if interaction.guild else None
		if owner is not None:
			await interaction.channel.set_permissions(owner, send_messages=False)
		button.disabled = True
		await interaction.response.edit_message(view=self)
		closed_embed = discord.Embed(
			description=f"➦ **{interaction.user.name}** ha cerrado el ticket.",
			color=discord.Color.red(),
		)
		await interaction.channel.send(embed=closed_embed, view=ClosedTicketView(self.cog))


class ClosedTicketView(discord.ui.View):
	def __init__(self, cog: "Tickets"):
		super().__init__(timeout=None)
		self.cog = cog

	@discord.ui.button(
		label="Reabrir", style=discord.ButtonStyle.secondary, custom_id="tickets:reopen"
	)
	async def reopen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
		ticket = await self.cog.can_manage_ticket(interaction)
		if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		owner = interaction.guild.get_member(ticket["owner_id"]) if interaction.guild else None
		if owner is not None:
			await interaction.channel.set_permissions(owner, send_messages=True)
		self.cog.database.set_status(interaction.channel.id, "open")
		for child in self.children:
			child.disabled = True
		await interaction.response.edit_message(view=self)
		reopened_embed = discord.Embed(
			description="Ticket reabierto",
			color=discord.Color.yellow(),
		)
		await interaction.channel.send(
			embed=reopened_embed,
			view=TicketControlsView(self.cog, include_claim=False),
		)

	@discord.ui.button(
		label="Guardar y eliminar", style=discord.ButtonStyle.danger, custom_id="tickets:save-delete"
	)
	async def save_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
		ticket = await self.cog.can_manage_ticket(interaction)
		if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		await interaction.response.send_message("Preparando la transcripción...", ephemeral=True)
		config = self.cog.database.get_config(interaction.guild.id) if interaction.guild else None
		transcript_channel = (
			interaction.guild.get_channel(config["transcript_channel_id"])
			if config and config["transcript_channel_id"] and interaction.guild
			else None
		)
		if not isinstance(transcript_channel, discord.TextChannel):
			await interaction.followup.send(
				"No hay un canal de transcripciones configurado; el ticket no se eliminará.", ephemeral=True
			)
			return

		lines = [
			"<!doctype html><html><head><meta charset=\"utf-8\">",
			f"<title>Transcripción de {html.escape(interaction.channel.name)}</title>",
			"<style>body{background:#000;color:#f2f2f2;font-family:Arial,sans-serif;"
			"max-width:900px;margin:2rem auto;padding:0 1rem}"
			"h1{color:#8A9A5B}.message{border-bottom:1px solid #333;padding:1rem 0}"
			".meta{color:#aaa;margin-bottom:.5rem}.content{color:#f2f2f2;"
			"white-space:normal;overflow-wrap:anywhere}.empty{color:#888;font-style:italic}"
			".discord-embed{border-left:4px solid #8A9A5B;background:#181818;"
			"padding:.75rem;margin-top:.75rem}.attachment{margin-top:.5rem}"
			"a{color:#7db7ff}img{max-width:100%;height:auto}</style></head><body>",
			f"<h1>Transcripción de {html.escape(interaction.channel.name)}</h1>",
		]
		messages = []
		participants = {}
		async for message in interaction.channel.history(limit=None, oldest_first=True):
			messages.append(message)
			participants[message.author.id] = message.author
			content = html.escape(message.content).replace("\n", "<br>")
			content_block = (
				f"<div class='content'>{content}</div>"
				if content
				else "<div class='content empty'>(sin contenido de texto)</div>"
			)
			lines.append(
				f"<article class='message'><div class='meta'><strong>{html.escape(message.author.display_name)}</strong> "
				f"{html.escape(message.created_at.isoformat())}</div>"
				f"{content_block}"
			)
			for message_embed in message.embeds:
				if message_embed.title or message_embed.description:
					lines.append(
						"<section class='discord-embed'>"
						f"<strong>{html.escape(message_embed.title or '')}</strong>"
						f"<p>{html.escape(message_embed.description or '').replace(chr(10), '<br>')}</p>"
						"</section>"
					)
			for attachment in message.attachments:
				if attachment.content_type and attachment.content_type.startswith("image/"):
					try:
						image_data = await attachment.read()
						embedded_image = base64.b64encode(image_data).decode("ascii")
						source = f"data:{attachment.content_type};base64,{embedded_image}"
					except (discord.HTTPException, discord.NotFound):
						source = attachment.url
					lines.append(
						f"<div class='attachment'><img src='{html.escape(source, quote=True)}' "
						"alt='Imagen adjunta'></div>"
					)
				else:
					lines.append(
						f"<p class='attachment'><a href='{html.escape(attachment.url, quote=True)}'>"
						f"{html.escape(attachment.filename)}</a></p>"
					)
			lines.append("</article>")
		lines.append("</body></html>")
		owner = (
			await self.cog.resolve_member(interaction.guild, ticket["owner_id"])
			if interaction.guild
			else None
		)
		claimed_staff = (
			await self.cog.resolve_member(interaction.guild, ticket["claimed_by"])
			if interaction.guild and ticket["claimed_by"]
			else None
		)
		owner_name = owner.name if owner else str(ticket["owner_id"])
		staff_name = claimed_staff.name if claimed_staff else str(ticket["claimed_by"])
		participant_mentions = " ".join(
			f"<@{user_id}>" for user_id in participants
		) or "Ninguno"
		transcript_embed = discord.Embed(
			title="• Transcripción",
			description=(
				f"Transcripción del ticket {interaction.channel.name} creada.\n\n"
				"➦ Ticket\n"
				f"{interaction.channel.name} ({interaction.channel.id})\n\n"
				"➦ Panel\n"
				"Incidencias externas\n\n"
				"➦ Usuario que lo crea\n"
				f"{owner_name} ({ticket['owner_id']})\n\n"
				"➦ Staff que reclama\n"
				f"{staff_name} ({ticket['claimed_by']})\n\n"
				"➦ Usuarios en transcripción\n"
				f"{participant_mentions}\n\n"
				"➦ Cantidad de mensajes\n"
				f"{len(messages)}"
			),
			color=discord.Color(0x8A9A5B),
		)
		file = discord.File(
			io.BytesIO("\n".join(lines).encode("utf-8")),
			filename=f"transcripcion-{interaction.channel.name}.html",
		)
		await transcript_channel.send(
			embed=transcript_embed,
			file=file,
		)
		button.disabled = True
		for child in self.children:
			child.disabled = True
		if interaction.message is not None:
			await interaction.message.edit(view=self)
		await interaction.channel.send("Transcripción generada. Eliminando ticket en 5 segundos")
		await asyncio.sleep(5)
		await interaction.channel.delete(reason="Ticket cerrado y transcripción guardada")


class Tickets(commands.Cog):
	def __init__(self, bot: commands.Bot):
		self.bot = bot
		self.database = TicketDatabase(DATABASE_PATH)

	async def cog_load(self) -> None:
		self.bot.add_view(TicketPanelView(self))
		self.bot.add_view(TicketControlsView(self))
		self.bot.add_view(TicketRatingView(self))
		self.bot.add_view(FinalCloseView(self))
		self.bot.add_view(ClosedTicketView(self))
		self.bot.add_view(UnclaimedTicketView(self))
		await self.restore_ticket_permissions()

	async def resolve_member(
		self, guild: discord.Guild, user_id: int | None
	) -> discord.Member | None:
		if user_id is None:
			return None
		member = guild.get_member(user_id)
		if member is not None:
			return member
		try:
			return await guild.fetch_member(user_id)
		except (discord.NotFound, discord.HTTPException):
			return None

	async def restore_ticket_permissions(self) -> None:
		for ticket in self.database.get_active_tickets():
			guild = self.bot.get_guild(ticket["guild_id"])
			if guild is None:
				continue
			channel = guild.get_channel(ticket["channel_id"])
			if not isinstance(channel, discord.TextChannel):
				continue
			config = self.database.get_config(guild.id)
			staff_role = guild.get_role(config["staff_role_id"]) if config else None
			owner = guild.get_member(ticket["owner_id"])
			claimed_staff = (
				guild.get_member(ticket["claimed_by"])
				if ticket["claimed_by"]
				else None
			)
			if staff_role is not None:
				await channel.set_permissions(
					staff_role,
					view_channel=ticket["claimed_by"] is None,
					send_messages=ticket["claimed_by"] is None,
				)
			if owner is not None:
				await channel.set_permissions(
					owner,
					view_channel=True,
					send_messages=ticket["status"] not in {"closed", "deleted"},
					read_message_history=True,
				)
			if claimed_staff is not None:
				await channel.set_permissions(
					claimed_staff,
					view_channel=True,
					send_messages=True,
					read_message_history=True,
				)
			for user_id in self.database.get_ticket_members(channel.id):
				member = guild.get_member(user_id)
				if member is not None:
					await channel.set_permissions(
						member,
						view_channel=True,
						send_messages=ticket["status"] not in {"closed", "deleted"},
						read_message_history=True,
					)

	@app_commands.command(name="ticket-configurar", description="Configura y publica el panel de tickets en este canal.")
	@app_commands.describe(
		categoria="Categoría donde se crearán los tickets. Si se omite, usa TICKETS_CATEGORY_ID.",
		rol_staff="Rol que podrá ver y reclamar tickets. Si se omite, usa TICKETS_STAFF_ROLE_ID.",
		canal_valoraciones="Canal donde se publicarán las valoraciones.",
		canal_transcripciones="Canal donde se guardarán las transcripciones.",
	)
	@app_commands.checks.has_permissions(administrator=True)
	async def configure(
		self,
		interaction: discord.Interaction,
		categoria: discord.CategoryChannel | None = None,
		rol_staff: discord.Role | None = None,
		canal_valoraciones: discord.TextChannel | None = None,
		canal_transcripciones: discord.TextChannel | None = None,
	) -> None:
		if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
			await interaction.response.send_message(
				"Este comando debe usarse en un canal de texto de un servidor.", ephemeral=True
			)
			return
		if categoria is None and configured_category_id is not None:
			try:
				configured_category = interaction.guild.get_channel(int(configured_category_id))
			except ValueError:
				configured_category = None
			if isinstance(configured_category, discord.CategoryChannel):
				categoria = configured_category
		if categoria is None:
			await interaction.response.send_message(
				"Debes seleccionar la categoría o configurar TICKETS_CATEGORY_ID.",
				ephemeral=True,
			)
			return
		if rol_staff is None and configured_staff_role_id is not None:
			try:
				rol_staff = interaction.guild.get_role(int(configured_staff_role_id))
			except ValueError:
				rol_staff = None
		if rol_staff is None:
			await interaction.response.send_message(
				"Debes seleccionar el rol de staff o configurar TICKETS_STAFF_ROLE_ID.",
				ephemeral=True,
			)
			return
		if canal_valoraciones is None and configured_rating_channel_id is not None:
			try:
				configured_channel = interaction.guild.get_channel(int(configured_rating_channel_id))
			except ValueError:
				configured_channel = None
			if isinstance(configured_channel, discord.TextChannel):
				canal_valoraciones = configured_channel
		if canal_transcripciones is None and configured_transcript_channel_id is not None:
			try:
				configured_channel = interaction.guild.get_channel(int(configured_transcript_channel_id))
			except ValueError:
				configured_channel = None
			if isinstance(configured_channel, discord.TextChannel):
				canal_transcripciones = configured_channel
		panel_channel = interaction.channel
		if configured_panel_channel_id is not None:
			try:
				configured_channel = interaction.guild.get_channel(int(configured_panel_channel_id))
			except ValueError:
				configured_channel = None
			if isinstance(configured_channel, discord.TextChannel):
				panel_channel = configured_channel
			else:
				await interaction.response.send_message(
					"TICKETS_PANEL_CHANNEL_ID no corresponde a un canal de texto válido.",
					ephemeral=True,
				)
				return
		self.database.configure(
			interaction.guild.id,
			categoria.id,
			rol_staff.id,
			panel_channel.id,
			canal_valoraciones.id if canal_valoraciones else None,
			canal_transcripciones.id if canal_transcripciones else None,
		)
		embed = discord.Embed(
			title="🇨🇱🇨🇴 𝙇𝙖𝙩𝙖𝙢𝘾𝙞𝙩𝙮ᴿᴾ © 🇲🇽🇦🇷+🇪🇸 ☀",
			description=(
				"Tickets\n"
				"「![🔖](https://discord.com/assets/ff2512a3e35f4796.svg) 」ᴛɪᴄᴋᴇᴛ\n"
				"Soporte de LatamCity RP × Tickets ![🎟️](https://discord.com/assets/dde8a9804160342c.svg)\n"
				"¿Necesitas ayuda? ![🌟](https://discord.com/assets/b113e8e4659eb292.svg)\n\n"
				"# Bienvenido al sistema de tickets de LatamCity RP.\n"
				"Mediante este canal podrás crear un ticket para cualquier duda que tengas.\n\n"
				"![⚠️](https://discord.com/assets/fb6fd920c79bd504.svg) Atención:\n"
				"Crear un ticket sin un motivo válido, o solo para molestar, puede resultar en una sanción.\n\n"
				"¿Eres miembro del staff? Entonces crea el ticket desde "
				"https://discord.com/channels/1376351887007289455/1527715778231537775"
			),
			color=discord.Color(0x8A9A5B),
		)
		await panel_channel.send(embed=embed, view=TicketPanelView(self))
		await interaction.response.send_message("Panel de tickets publicado.", ephemeral=True)

	async def can_manage_ticket(self, interaction: discord.Interaction) -> sqlite3.Row | None:
		if interaction.guild is None or not isinstance(interaction.user, discord.Member):
			return None
		ticket = self.database.get_ticket(interaction.channel_id)
		if ticket is None:
			return None
		if is_admin(interaction.user) or ticket["claimed_by"] == interaction.user.id:
			return ticket
		return None

	@app_commands.command(name="unclaim", description="Retira tu reclamación del ticket actual.")
	async def unclaim(self, interaction: discord.Interaction) -> None:
		if (
			interaction.guild is None
			or not isinstance(interaction.user, discord.Member)
			or not isinstance(interaction.channel, discord.TextChannel)
		):
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		ticket = self.database.get_ticket(interaction.channel.id)
		if ticket is None or ticket["claimed_by"] != interaction.user.id:
			await interaction.response.send_message(
				embed=permission_error_embed(), ephemeral=True
			)
			return
		if ticket["status"] != "open":
			await interaction.response.send_message(
				"El ticket no puede dejar de estar reclamado en este estado.", ephemeral=True
			)
			return
		config = self.database.get_config(interaction.guild.id)
		staff_role = interaction.guild.get_role(config["staff_role_id"]) if config else None
		if staff_role is None:
			await interaction.response.send_message(
				"El sistema de tickets todavía no está configurado.", ephemeral=True
			)
			return

		await interaction.channel.set_permissions(
			staff_role,
			view_channel=True,
			send_messages=True,
			read_message_history=True,
		)
		await interaction.channel.set_permissions(interaction.user, overwrite=None)
		self.database.clear_claimed(interaction.channel.id)
		embed = discord.Embed(
			description="Reclamación del ticket retirada.",
			color=discord.Color(0x8A9A5B),
		)
		await interaction.response.send_message(embed=embed, view=UnclaimedTicketView(self))

	@app_commands.command(name="adduser", description="Añadir un usuario al ticket.")
	@app_commands.describe(usuario="Usuario existente en el servidor que tendrá acceso al ticket.")
	async def add_member(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
		ticket = await self.can_manage_ticket(interaction)
		if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
			await interaction.response.send_message(
				"Solo el staff que reclamó el ticket o un administrador puede usar esto.", ephemeral=True
			)
			return
		await interaction.channel.set_permissions(
			usuario, view_channel=True, send_messages=True, read_message_history=True
		)
		self.database.add_member(interaction.channel.id, usuario.id)
		await interaction.response.send_message(f"{usuario.mention} ha sido añadido al ticket.")

	@app_commands.command(name="deluser", description="Eliminar un usuario del ticket.")
	@app_commands.describe(usuario="Usuario existente en el servidor al que se retirará el acceso.")
	async def remove_member(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
		ticket = await self.can_manage_ticket(interaction)
		if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
			await interaction.response.send_message(
				"Solo el staff que reclamó el ticket o un administrador puede usar esto.", ephemeral=True
			)
			return
		if is_admin(usuario):
			await interaction.response.send_message(
				"El usuario es administrador, no puede ser eliminado del ticket.",
				ephemeral=True,
			)
			return
		if usuario.id == ticket["claimed_by"]:
			await interaction.response.send_message(
				"El usuario es el staff que tiene el ticket reclamado, no puede ser eliminado del ticket.",
				ephemeral=True,
			)
			return
		if usuario.id == ticket["owner_id"]:
			await interaction.response.send_message(
				"El usuario es el que creó el ticket, no puede ser eliminado del ticket.",
				ephemeral=True,
			)
			return
		if interaction.channel.overwrites_for(usuario) == discord.PermissionOverwrite():
			await interaction.response.send_message(
				f"El usuario {usuario.mention} no está en el ticket.", ephemeral=True
			)
			return
		await interaction.channel.set_permissions(usuario, overwrite=None)
		self.database.remove_member(interaction.channel.id, usuario.id)
		await interaction.response.send_message(f"Usuario {usuario.mention} eliminado del ticket.")


async def setup(bot: commands.Bot):
	await bot.add_cog(Tickets(bot))
