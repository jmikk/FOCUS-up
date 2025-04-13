import discord
import aiohttp
import asyncio
import re
from redbot.core import commands, Config
from redbot.core.bot import Red
from datetime import datetime, timedelta

class NationStatesSSE(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1357908642, force_registration=True)
        self.config.register_guild(channel=None, whitelist=[], blacklist=[], region="the_wellspring", user_agent="Redbot-SSE-Listener")
        self.session = aiohttp.ClientSession()
        self.sse_task = self.bot.loop.create_task(self.sse_listener())
        self.last_event_time = datetime.utcnow()

    def cog_unload(self):
        self.sse_task.cancel()
        self.sse_task = None
        self.bot.loop.create_task(self.session.close())

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.send(f"Set event output channel to {channel.mention}")

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def setregion(self, ctx, *, region: str):
        await self.config.guild(ctx.guild).region.set(region.lower().replace(" ", "_"))
        await ctx.send(f"Set SSE region to `{region}`. Reconnecting to new stream...")
        if self.sse_task:
            self.sse_task.cancel()
        self.sse_task = self.bot.loop.create_task(self.sse_listener())

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def addwhitelist(self, ctx, *, word):
        wl = await self.config.guild(ctx.guild).whitelist()
        wl.append(word)
        await self.config.guild(ctx.guild).whitelist.set(wl)
        await ctx.send(f"Added `{word}` to whitelist.")

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def removewhitelist(self, ctx, *, word):
        wl = await self.config.guild(ctx.guild).whitelist()
        if word in wl:
            wl.remove(word)
            await self.config.guild(ctx.guild).whitelist.set(wl)
            await ctx.send(f"Removed `{word}` from whitelist.")
        else:
            await ctx.send("Word not in whitelist.")

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def addblacklist(self, ctx, *, word):
        bl = await self.config.guild(ctx.guild).blacklist()
        bl.append(word)
        await self.config.guild(ctx.guild).blacklist.set(bl)
        await ctx.send(f"Added `{word}` to blacklist.")

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def removeblacklist(self, ctx, *, word):
        bl = await self.config.guild(ctx.guild).blacklist()
        if word in bl:
            bl.remove(word)
            await self.config.guild(ctx.guild).blacklist.set(bl)
            await ctx.send(f"Removed `{word}` from blacklist.")
        else:
            await ctx.send("Word not in blacklist.")

    @commands.guild_only()
    @commands.command()
    async def startsse(self, ctx):
        if self.sse_task and not self.sse_task.done():
            await ctx.send("SSE listener is already running.")
        else:
            self.sse_task = self.bot.loop.create_task(self.sse_listener())
            await ctx.send("Started SSE listener.")

    @commands.command()
    async def stopsse(self, ctx):
        if self.sse_task:
            self.sse_task.cancel()
            await ctx.send("Stopped SSE listener.")
        else:
            await ctx.send("SSE listener is not running.")

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def setuseragent(self, ctx, *, agent: str):
        await self.config.guild(ctx.guild).user_agent.set(agent)
        await ctx.send(f"User-Agent set to: `{agent}`. Reconnecting stream...")
        if self.sse_task:
            self.sse_task.cancel()
        self.sse_task = self.bot.loop.create_task(self.sse_listener())

    @commands.command()
    async def viewsseurl(self, ctx):
        region = await self.config.guild(ctx.guild).region()
        url = f"https://www.nationstates.net/api/region:{region}"
        await ctx.send(f"Current SSE URL: <{url}>")

    @commands.command()
    async def viewfilters(self, ctx):
        wl = await self.config.guild(ctx.guild).whitelist()
        bl = await self.config.guild(ctx.guild).blacklist()
        region = await self.config.guild(ctx.guild).region()
        await ctx.send(f"**Region:** {region}\n**Whitelist:** {wl}\n**Blacklist:** {bl}")

    async def sse_listener(self):
        try:
            guilds = [g async for g in self.config.all_guilds()]
            if not guilds:
                print("[SSE] No guilds configured for SSE listening.")
                return
            guild_id = list(guilds.keys())[0]  # just using the first guild's settings
            region = guilds[guild_id].get("region", "the_wellspring")
            agent = guilds[guild_id].get("user_agent", "Redbot-SSE-Listener")
            url = f"https://www.nationstates.net/api/region:{region}"

            async with self.session.get(url, headers={"User-Agent": agent}) as resp:
                async for line in resp.content:
                    if line == b'
':
                        continue
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        self.last_event_time = datetime.utcnow()
                        await self.handle_event(line[6:])

        except asyncio.CancelledError:
            print("[SSE] SSE listener cancelled.")
        except Exception as e:
            print("[SSE] Error:", e)
            await asyncio.sleep(10)

        if datetime.utcnow() - self.last_event_time > timedelta(hours=1):
            for guild in self.bot.guilds:
                channel_id = await self.config.guild(guild).channel()
                if channel_id:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        await channel.send("No events received in over an hour. Attempting to reconnect...")
            self.last_event_time = datetime.utcnow()

    async def handle_event(self, data):
        try:
            import json
            payload = json.loads(data)
            message = payload.get("str")
            message = re.sub(r"@@(.*?)@@", lambda m: f"[{m.group(1)}](https://www.nationstates.net/nation={m.group(1).replace(' ', '_')})", message)
            html = payload.get("htmlStr", "")
            
            # Extract image URL (supports both PNG and SVG formats)
            match = re.search(r'src=\"(/images/flags/uploads/[^\"]+\.png|/images/flags/[^\"/]+\.svg)\"', html)
            flag_url = f"https://www.nationstates.net{match.group(1)}" if match else None
            flag_url = flag_url.replace(".svg",".png").replace("t2","")
            # Go through all guilds
            for guild in self.bot.guilds:
                channel_id = await self.config.guild(guild).channel()
                if not channel_id:
                    continue
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue

                whitelist = await self.config.guild(guild).whitelist()
                blacklist = await self.config.guild(guild).blacklist()

                if whitelist and not any(word.lower() in message.lower() for word in whitelist):
                    continue
                if any(word.lower() in message.lower() for word in blacklist):
                    continue

                embed = discord.Embed(description=message, timestamp=datetime.utcnow())
                if flag_url:
                    embed.set_thumbnail(url=flag_url)
                await channel.send(embed=embed)

        except Exception as e:
            print("[Event Handler] Error:", e)
