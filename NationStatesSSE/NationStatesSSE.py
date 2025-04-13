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
        self.sse_tasks = {}
        self.last_event_time = {}

    def cog_unload(self):
        for task in self.sse_tasks.values():
            task.cancel()
        self.bot.loop.create_task(self.session.close())

    async def _ensure_configured(self, guild):
        cfg = self.config.guild(guild)
        channel = await cfg.channel()
        region = await cfg.region()
        agent = await cfg.user_agent()
        return all([channel, region, agent])

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
        await ctx.send(f"Set SSE region to `{region}`.")
        if await self._ensure_configured(ctx.guild):
            await self.restart_sse(ctx.guild, ctx)

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def setuseragent(self, ctx, *, agent: str):
        await self.config.guild(ctx.guild).user_agent.set(agent)
        await ctx.send(f"User-Agent set to: `{agent}`.")
        if await self._ensure_configured(ctx.guild):
            await self.restart_sse(ctx.guild, ctx)

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def startsse(self, ctx):
        if ctx.guild.id in self.sse_tasks and not self.sse_tasks[ctx.guild.id].done():
            await ctx.send("SSE listener is already running.")
            return
        if not await self._ensure_configured(ctx.guild):
            await ctx.send("❌ Missing configuration: set region, user agent, and channel first.")
            return
        self.sse_tasks[ctx.guild.id] = asyncio.create_task(self.sse_listener(ctx.guild))
        await ctx.send("✅ Started SSE listener.")

    @commands.guild_only()
    @commands.admin()
    @commands.command()
    async def stopsse(self, ctx):
        task = self.sse_tasks.get(ctx.guild.id)
        if task:
            task.cancel()
            del self.sse_tasks[ctx.guild.id]
            await ctx.send("SSE listener stopped.")
        else:
            await ctx.send("No SSE listener running.")

    async def restart_sse(self, guild, ctx=None):
        if guild.id in self.sse_tasks:
            self.sse_tasks[guild.id].cancel()
        self.sse_tasks[guild.id] = asyncio.create_task(self.sse_listener(guild))
        if ctx:
            await ctx.send("🔁 Reconnected to updated SSE stream.")

    async def sse_listener(self, guild):
        cfg = self.config.guild(guild)
        region = await cfg.region()
        agent = await cfg.user_agent()
        url = f"https://www.nationstates.net/api/region:{region}"
        self.last_event_time[guild.id] = datetime.utcnow()
        try:
            async with self.session.get(url, headers={"User-Agent": agent}) as resp:
                async for line in resp.content:
                    if line == b'\n':
                        continue
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        self.last_event_time[guild.id] = datetime.utcnow()
                        await self.handle_event(guild, line[6:])
        except asyncio.CancelledError:
            print(f"[SSE] SSE listener cancelled for {guild.name}")
        except Exception as e:
            print(f"[SSE] Error for {guild.name}:", e)
            await asyncio.sleep(10)

        if datetime.utcnow() - self.last_event_time[guild.id] > timedelta(hours=1):
            channel_id = await cfg.channel()
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await channel.send("No events received in over an hour. Attempting to reconnect...")
            self.last_event_time[guild.id] = datetime.utcnow()

    async def handle_event(self, guild, data):
        try:
            import json
            payload = json.loads(data)
            message = payload.get("str")
            message = re.sub(r"@@(.*?)@@", lambda m: f"[{m.group(1)}](https://www.nationstates.net/nation={m.group(1).replace(' ', '_')})", message)
            html = payload.get("htmlStr", "")

            match = re.search(r'src=\"(/images/flags/uploads/[^\"]+\.png|/images/flags/[^\"/]+\.svg)\"', html)
            flag_url = f"https://www.nationstates.net{match.group(1)}" if match else None
            flag_url = flag_url.replace(".svg", ".png").replace("t2", "") if flag_url else None

            cfg = self.config.guild(guild)
            channel_id = await cfg.channel()
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                return

            whitelist = await cfg.whitelist()
            blacklist = await cfg.blacklist()

            if whitelist and not any(word.lower() in message.lower() for word in whitelist):
                return
            if any(word.lower() in message.lower() for word in blacklist):
                return

            embed = discord.Embed(description=message, timestamp=datetime.utcnow())
            if flag_url:
                embed.set_thumbnail(url=flag_url)
            await channel.send(embed=embed)

        except Exception as e:
            print(f"[Event Handler] Error in {guild.name}:", e)
