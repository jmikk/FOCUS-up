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
        self.config.register_global(channel=None, whitelist=[], blacklist=[], region="the_wellspring", user_agent="Redbot-SSE-Listener")
        self.session = aiohttp.ClientSession()
        self.sse_task = None
        self.last_event_time = datetime.utcnow()

    def cog_unload(self):
        if self.sse_task:
            self.sse_task.cancel()
        self.bot.loop.create_task(self.session.close())

    @commands.admin()
    @commands.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        await self.config.channel.set(channel.id)
        await ctx.send(f"Set event output channel to {channel.mention}")

    @commands.admin()
    @commands.command()
    async def setregion(self, ctx, *, region: str):
        await self.config.region.set(region.lower().replace(" ", "_"))
        await ctx.send(f"Set SSE region to `{region}`.")
        channel_id = await self.config.channel
        agent = await self.config.user_agent()
        if all([channel_id, agent]):
            if self.sse_task:
                self.sse_task.cancel()
            self.sse_task = self.bot.loop.create_task(self.sse_listener())
            await ctx.send("Reconnected to new stream.")

    @commands.admin()
    @commands.command()
    async def setuseragent(self, ctx, *, agent: str):
        await self.config.user_agent.set(agent)
        await ctx.send(f"User-Agent set to: `{agent}`.")
        region = await self.config.region()
        channel_id = await self.config.channel()
        if all([region, channel_id]):
            if self.sse_task:
                self.sse_task.cancel()
            self.sse_task = self.bot.loop.create_task(self.sse_listener())
            await ctx.send("Reconnected to new stream.")

    @commands.admin()
    @commands.command()
    async def startsse(self, ctx):
        if self.sse_task and not self.sse_task.done():
            await ctx.send("SSE listener is already running.")
            return

        region = await self.config.region()
        agent = await self.config.user_agent()
        channel_id = await self.config.channel()

        if not all([region, agent, channel_id]):
            await ctx.send("❌ Cannot start SSE: Missing configuration. Please ensure region, user agent, and output channel are set.")
            return

        self.sse_task = self.bot.loop.create_task(self.sse_listener())
        await ctx.send("✅ Started SSE listener.")

    @commands.admin()
    @commands.command()
    async def stopsse(self, ctx):
        if self.sse_task:
            self.sse_task.cancel()
            self.sse_task = None
            await ctx.send("Stopped SSE listener.")
        else:
            await ctx.send("SSE listener is not running.")

    @commands.command()
    async def sstatus(self, ctx):
        region = await self.config.region
        agent = await self.config.user_agent
        channel_id = await self.config.channel
        channel = self.bot.get_channel(channel_id) if channel_id else None
        running = self.sse_task and not self.sse_task.done()
        await ctx.send(
            f"**SSE Status:** {'🟢 Running' if running else '🔴 Not Running'}"+
            f"**Region:** `{region}`"+
            f"**User-Agent:** `{agent}`"+
            f"**Output Channel:** {channel.mention if channel else 'Not Set'}"
        )

    @commands.command()
    async def viewsseurl(self, ctx):
        region = await self.config.region()
        url = f"https://www.nationstates.net/api/region:{region}"
        await ctx.send(f"Current SSE URL: <{url}>")

    @commands.command()
    async def viewfilters(self, ctx):
        wl = await self.config.whitelist()
        bl = await self.config.blacklist()
        region = await self.config.region()
        await ctx.send(f"**Region:** {region}\n**Whitelist:** {wl}\n**Blacklist:** {bl}")

    @commands.admin()
    @commands.command()
    async def addwhitelist(self, ctx, *, word):
        wl = await self.config.whitelist()
        wl.append(word)
        await self.config.whitelist.set(wl)
        await ctx.send(f"Added `{word}` to whitelist.")

    @commands.admin()
    @commands.command()
    async def removewhitelist(self, ctx, *, word):
        wl = await self.config.whitelist()
        if word in wl:
            wl.remove(word)
            await self.config.whitelist.set(wl)
            await ctx.send(f"Removed `{word}` from whitelist.")
        else:
            await ctx.send("Word not in whitelist.")

    @commands.admin()
    @commands.command()
    async def addblacklist(self, ctx, *, word):
        bl = await self.config.blacklist()
        bl.append(word)
        await self.config.blacklist.set(bl)
        await ctx.send(f"Added `{word}` to blacklist.")

    @commands.admin()
    @commands.command()
    async def removeblacklist(self, ctx, *, word):
        bl = await self.config.blacklist()
        if word in bl:
            bl.remove(word)
            await self.config.blacklist.set(bl)
            await ctx.send(f"Removed `{word}` from blacklist.")
        else:
            await ctx.send("Word not in blacklist.")

    async def sse_listener(self):
        try:
            region = await self.config.region()
            agent = await self.config.user_agent()
            url = f"https://www.nationstates.net/api/region:{region}"

            async with self.session.get(url, headers={"User-Agent": agent}) as resp:
                async for line in resp.content:
                    if line == b'\n':
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
            channel_id = await self.config.channel()
            if channel_id:
                channel = self.bot.get_channel(channel_id)
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

            match = re.search(r'src=\"(/images/flags/uploads/[^\"]+\.png|/images/flags/[^\"/]+\.svg)\"', html)
            flag_url = f"https://www.nationstates.net{match.group(1)}" if match else None
            flag_url = flag_url.replace(".svg", ".png").replace("t2", "") if flag_url else None

            channel_id = await self.config.channel()
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                return

            whitelist = await self.config.whitelist()
            blacklist = await self.config.blacklist()

            if whitelist and not any(word.lower() in message.lower() for word in whitelist):
                return
            if any(word.lower() in message.lower() for word in blacklist):
                return

            embed = discord.Embed(description=message, timestamp=datetime.utcnow())
            if flag_url:
                embed.set_thumbnail(url=flag_url)
            await channel.send(embed=embed)

        except Exception as e:
            print("[Event Handler] Error:", e)

