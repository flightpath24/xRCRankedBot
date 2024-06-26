import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import requests
from dotenv import load_dotenv
import logging
import os
import threading
import aiohttp
from PIL import Image
import random
from io import BytesIO
from config import *

FALLBACK_AVATAR_URL = 'https://i0.wp.com/sbcf.fr/wp-content/uploads/2018/03/sbcf-default-avatar.png'  # Replace with your fallback avatar URL

logger = logging.getLogger('discord')

HEADER = {"x-api-key": SRC_API_TOKEN}

games = requests.get("https://secondrobotics.org/api/ranked/").json()

short_codes = [games['short_code'] for games in games]
short_codes_sorted = sorted(short_codes)


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="Ping the bot")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000, 2)
        await interaction.response.send_message(f"Pong! Latency: {latency}ms")

    @app_commands.command(description="Player Info")
    async def playerinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer()
        logger.info(f"/playerinfo by {interaction.user.display_name}")
        if user is None:
            user = interaction.user
        user_id = user.id

        url = f'https://secondrobotics.org/api/ranked/player/{user_id}'
        async with aiohttp.ClientSession(headers=HEADER) as session:
            async with session.get(url) as response:
                res = await response.json()

                # Get a random pixel color from the thumbnail image or use a default color if failed
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(res['avatar']) as response:
                            thumbnail_bytes = await response.read()

                    thumbnail_image = Image.open(BytesIO(thumbnail_bytes))
                    thumbnail_width, thumbnail_height = thumbnail_image.size
                    random_pixel = thumbnail_image.getpixel(
                        (random.randint(0, thumbnail_width - 1), random.randint(0, thumbnail_height - 1)))
                    random_color = discord.Color.from_rgb(*random_pixel[:3])
                except Exception as e:
                    logger.error(f"Failed to fetch avatar: {e}")
                    random_color = discord.Color.blue()

        if not res["exists"]:
            await interaction.followup.send(
                "The player you requested register for an account at <https://www.secondrobotics.org/login> before you can get info.",
                ephemeral=True)
            return

        embed = discord.Embed(title="Player Information", color=random_color)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url)
        embed.set_thumbnail(url=res.get('avatar', FALLBACK_AVATAR_URL))
        embed.add_field(name="Display Name",
                        value=f"[{res['display_name']}](https://secondrobotics.org/user/{user_id})", inline=False)

        total_wins = 0
        total_losses = 0
        total_ties = 0
        total_points = 0
        best_elo = 0
        best_game = None
        elos = []

        async def process_game(game):
            url = f'https://secondrobotics.org/api/ranked/{game}/player/{user_id}'
            async with session.get(url) as response:
                gamedata = await response.json()

            if "error" not in gamedata:
                total_score = "{:,}".format(gamedata['total_score'])
                record = f"{gamedata['matches_won']}-{gamedata['matches_lost']}-{gamedata['matches_drawn']}"
                win_rate = (gamedata['matches_won'] / gamedata['matches_played']) * 100 if gamedata[
                                                                                               'matches_played'] > 0 else 0
                win_rate = round(win_rate, 2)

                nonlocal total_wins, total_losses, total_ties, total_points, best_elo, best_game
                total_wins += gamedata['matches_won']
                total_losses += gamedata['matches_lost']
                total_ties += gamedata['matches_drawn']
                total_points += gamedata['total_score']

                if gamedata['elo'] > best_elo:
                    best_elo = gamedata['elo']
                    best_game = gamedata['name']

                elos.append(gamedata['elo'])  # Store the ELO value

                return (
                    gamedata['name'], round(gamedata['elo'], 2), record, gamedata['matches_played'], win_rate,
                    total_score
                )
            else:
                elos.append(0)
                return None

        tasks = []
        game_results = []

        async with aiohttp.ClientSession(headers=HEADER) as session:
            for game in short_codes_sorted:
                tasks.append(process_game(game))

            game_results = await asyncio.gather(*tasks)

        favorite_game = None
        favorite_game_matches_played = 0

        column_data = [[] for _ in range(3)]  # Three columns for balanced layout
        column_index = 0

        for result in game_results:
            if result is not None:
                name, elo, record, matches_played, win_rate, total_score = result
                win_rate_str = f"{win_rate}%"
                if win_rate > 60:
                    win_rate_str += " :crown:"
                game_info = (
                    f"**{name} [{elo}]**\n"
                    f"{record} [{matches_played}] {win_rate_str}\n"
                    f"Total Points Scored: {total_score}\n\n"
                )
                column_data[column_index].append(game_info)
                column_index = (column_index + 1) % 3

                if matches_played > favorite_game_matches_played:
                    favorite_game = name
                    favorite_game_matches_played = matches_played

        for index, column in enumerate(column_data):
            embed.add_field(name=f"Games (Column {index + 1})", value="".join(column), inline=True)

        total_matches = total_wins + total_losses + total_ties
        win_rate = (total_wins / total_matches) * 100 if total_matches > 0 else 0
        win_rate_str = f"{round(win_rate, 2)}%"
        if win_rate > 60:
            win_rate_str += " :crown:"

        summary = (
            f"Record: {total_wins}-{total_losses}-{total_ties} [{total_matches}]\n"
            f"Total Points Scored: {total_points:,}\n"
            f"Win Rate: {win_rate_str}\n"
            f"Favorite Game: {favorite_game}\n"
            f"Best Game: {best_game} ({round(best_elo, 2)})"
        )

        average_elo = None
        if elos:
            average_elo = round(sum(elos) / len(elos), 2)

        if average_elo is not None:
            summary += f"\nAverage ELO: {average_elo}"
        else:
            summary += "\nAverage ELO: Unknown"

        embed.add_field(name="Summary", value=summary, inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    cog = General(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
