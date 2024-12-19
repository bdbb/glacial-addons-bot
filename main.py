import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import requests
import os
from datetime import datetime, timezone, timedelta

DISCORD_BOT_TOKEN = os.getenv("KEY")

# Set up bot intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

# Set up bot
class SkyblockBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Load settings and players at initialization
        self.settings = self.load_settings()
        self.players = self.load_players()
        self.sack_channel_id = self.settings.get("sack_channel_id", None)
        self.task_interval = self.settings.get("task_interval", 10)
        self.last_checked = None
        self.message_id = self.settings.get("message_id", None)  # Track the message ID

        # Start the background task
        self.sack_totals_task.start()

    PLAYER_FILE = "players.json"
    SETTINGS_FILE = "settings.json"
    API_BASE = "https://sky.shiiyu.moe/api/v2"
    DECIMAL_PLACES = 2

    def load_settings(self):
        try:
            with open(self.SETTINGS_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_settings(self):
        with open(self.SETTINGS_FILE, "w") as f:
            json.dump({"sack_channel_id": self.sack_channel_id, "task_interval": self.task_interval, "message_id": self.message_id}, f, indent=4)

    def load_players(self):
        try:
            with open(self.PLAYER_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_players(self, data):
        with open(self.PLAYER_FILE, "w") as f:
            json.dump(data, f, indent=4)

    # Helper function to format numbers with suffixes
    def format_number(self, value, decimals=None):
        decimals = decimals or self.DECIMAL_PLACES
        if value >= 1e9:
            return f"{value / 1e9:.{decimals}f}B"
        elif value >= 1e6:
            return f"{value / 1e6:.{decimals}f}M"
        elif value >= 1e3:
            return f"{value / 1e3:.{decimals}f}K"
        return f"{value:.{decimals}f}"

    def check_sack_totals(self):
        results = []
        for username, profiles in self.players.items():
            for profile in profiles:
                try:
                    response = requests.get(f"{self.API_BASE}/profile/{username}")
                    data = response.json()

                    # Find the profile matching the cute name
                    profile_data = next((p for p in data.get("profiles", {}).values() if p.get("cute_name") == profile), None)

                    if profile_data:
                        sack_total = profile_data.get("data", {}).get("networth", {}).get("types", {}).get("sacks", {}).get("total", 0)
                        formatted_total = self.format_number(sack_total)
                        results.append(f"{username} ({profile}): {formatted_total} coins")
                    else:
                        results.append(f"{username} ({profile}): Profile not found")

                except Exception as e:
                    results.append(f"Error retrieving data for {username} ({profile}): {e}")
        return results

    @app_commands.command(name="add_player", description="Add a player and their profile to the tracking list.")
    async def add_player(self, interaction: discord.Interaction, username: str, profile: str):
        if username in self.players and profile in self.players[username]:
            await interaction.response.send_message(f"{username} with profile {profile} is already being tracked.")
            return

        # Add player and profile
        self.players.setdefault(username, []).append(profile)
        self.save_players(self.players)
        await interaction.response.send_message(f"Added {username} with profile {profile} to the tracking list.")

    @app_commands.command(name="list_players", description="List all tracked players and their profiles.")
    async def list_players(self, interaction: discord.Interaction):
        if not self.players:
            await interaction.response.send_message("No players are being tracked.")
            return

        embed = discord.Embed(title="Tracked Players", color=discord.Color.blue())
        for username, profiles in self.players.items():
            embed.add_field(name=username, value=", ".join(profiles), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="sack_totals", description="Get the sack totals for all tracked players.")
    async def sack_totals(self, interaction: discord.Interaction):
        if not self.players:
            await interaction.response.send_message("No players are being tracked.")
            return

        # Defer the response to allow more time for processing
        await interaction.response.defer()

        results = self.check_sack_totals()

        # Convert to PST timezone
        pst_timezone = timezone(timedelta(hours=-8))
        self.last_checked = datetime.now(tz=pst_timezone).strftime("%Y-%m-%d %I:%M:%S %p PST")

        embed = discord.Embed(title="Sack Totals", color=discord.Color.green(), timestamp=datetime.now(tz=pst_timezone))
        for result in results:
            embed.add_field(name="Result", value=result, inline=False)
        embed.set_footer(text=f"Last checked: {self.last_checked}")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="help", description="Display all available commands.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Help - Available Commands", color=discord.Color.purple())
        embed.add_field(name="/add_player <username> <profile>", value="Add a player and their profile to the tracking list.", inline=False)
        embed.add_field(name="/list_players", value="List all tracked players and their profiles.", inline=False)
        embed.add_field(name="/sack_totals", value="Get the sack totals for all tracked players.", inline=False)
        embed.add_field(name="/set_sack_channel <channel> <interval>", value="Set a channel and interval for periodic sack totals updates.", inline=False)
        embed.add_field(name="/list_sack_channel", value="List the current sack totals channel and interval.", inline=False)
        embed.add_field(name="/remove_sack_channel", value="Remove the sack totals channel.", inline=False)
        embed.add_field(name="/edit_sack_interval <interval>", value="Edit the interval for sack totals updates.", inline=False)
        embed.set_footer(text="Use these commands to manage sack totals tracking.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="set_sack_channel", description="Set the channel to post sack totals periodically.")
    async def set_sack_channel(self, interaction: discord.Interaction, channel: discord.TextChannel, interval: int):
        self.sack_channel_id = channel.id
        self.task_interval = interval
        self.save_settings()
        self.sack_totals_task.change_interval(minutes=self.task_interval)
        await interaction.response.send_message(f"Sack totals will be posted in {channel.mention} every {interval} minutes.")

    @app_commands.command(name="list_sack_channel", description="List the current sack totals channel and interval.")
    async def list_sack_channel(self, interaction: discord.Interaction):
        if self.sack_channel_id:
            channel = self.bot.get_channel(self.sack_channel_id)
            if channel:
                embed = discord.Embed(title="Sack Totals Channel Info", color=discord.Color.orange())
                embed.add_field(name="Channel", value=channel.mention, inline=False)
                embed.add_field(name="Interval", value=f"{self.task_interval} minutes", inline=False)
                embed.set_footer(text=f"Last checked: {self.last_checked or 'Never'}")
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("The sack totals channel is not accessible.")
        else:
            await interaction.response.send_message("No sack totals channel is set.")

    @app_commands.command(name="remove_sack_channel", description="Remove the sack totals channel.")
    async def remove_sack_channel(self, interaction: discord.Interaction):
        self.sack_channel_id = None
        self.message_id = None
        self.save_settings()
        self.sack_totals_task.stop()
        await interaction.response.send_message("Sack totals channel has been removed and periodic updates stopped.")

    @app_commands.command(name="edit_sack_interval", description="Edit the interval for sack totals updates.")
    async def edit_sack_interval(self, interaction: discord.Interaction, interval: int):
        self.task_interval = interval
        self.save_settings()
        self.sack_totals_task.change_interval(minutes=self.task_interval)
        await interaction.response.send_message(f"Sack totals interval updated to {self.task_interval} minutes.")

    @tasks.loop(minutes=10)
    async def sack_totals_task(self):
        if not self.sack_channel_id:
            return

        channel = self.bot.get_channel(self.sack_channel_id)
        if not channel:
            return

        results = self.check_sack_totals()

        # Convert to PST timezone
        pst_timezone = timezone(timedelta(hours=-8))
        self.last_checked = datetime.now(tz=pst_timezone).strftime("%Y-%m-%d %I:%M:%S %p PST")

        embed = discord.Embed(title="Sack Totals", color=discord.Color.green(), timestamp=datetime.now(tz=pst_timezone))
        for result in results:
            embed.add_field(name="Result", value=result, inline=False)
        embed.set_footer(text=f"Last checked: {self.last_checked}")

        try:
            if self.message_id:
                message = await channel.fetch_message(self.message_id)
                await message.edit(embed=embed)
            else:
                message = await channel.send(embed=embed)
                self.message_id = message.id
                self.save_settings()
        except discord.NotFound:
            message = await channel.send(embed=embed)
            self.message_id = message.id
            self.save_settings()

    @sack_totals_task.before_loop
    async def before_sack_totals_task(self):
        await self.bot.wait_until_ready()

# Main bot setup
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.add_cog(SkyblockBot(self))
        await self.tree.sync()

# Run the bot
bot = MyBot()

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")

bot.run(DISCORD_BOT_TOKEN)
