import discord
import aiohttp
import asyncio
import re
from redbot.core import commands, Config
from redbot.core.bot import Red
from datetime import datetime, timedelta
import json
import xml.etree.ElementTree as ET
import html


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
        self.last_event_time[guild.id] = datetime.utcnow()
        while True:
            try:
                region = await cfg.region()
                agent = await cfg.user_agent()
                url = f"https://www.nationstates.net/api/region:{region}"
                timeout = aiohttp.ClientTimeout(total=None, sock_read=65)
                async with self.session.get(url, headers={"User-Agent": agent}, timeout=timeout) as resp:
                    print(f"[SSE] Connected to SSE feed for region {region}")
                    async for line in resp.content:
                        if line == b'\n':
                            continue
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            self.last_event_time[guild.id] = datetime.utcnow()
                            await self.handle_event(guild, line[6:])
                        elif line.startswith("heartbeat: "):
                            self.last_event_time[guild.id] = datetime.utcnow()
            except asyncio.CancelledError:
                print(f"[SSE] SSE listener cancelled for {guild.name}")
            except Exception as e:
                    print(f"[SSE] Error for {guild.name}:", e)
                    channel_id = await cfg.channel()
                    if channel_id:
                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            await channel.send(f"⚠️ SSE Error: `{e}` Reconnecting in 10 seconds...")
                    await asyncio.sleep(10)
                    continue    
                
    async def handle_event(self, guild, data):
        try:
            payload = json.loads(data)
            message = payload.get("str")
            html = payload.get("htmlStr", "")
            message = re.sub(r"@@(.*?)@@", lambda m: f"[{m.group(1)}](https://www.nationstates.net/nation={m.group(1).replace(' ', '_')})", message)
            message = re.sub(r"%%(.*?)%%", lambda m: f"[{m.group(1)}](https://www.nationstates.net/region={m.group(1).replace(' ', '_')})", message)

            message = message.replace("&quot;",'"')
            # Special handling for RMB messages
            rmb_match = re.search(r'<a href="/region=(.*?)/page=display_region_rmb\?postid=(\d+)', html)
            if rmb_match:
                region = rmb_match.group(1)
                post_id = rmb_match.group(2)
                url = f"https://www.nationstates.net/cgi-bin/api.cgi?region={region}&q=messages&fromid={post_id}"
                async with self.session.get(url, headers={"User-Agent": "Redbot-SSE-Listener"}) as r:
                    xml_text = await r.text()
                    root = ET.fromstring(xml_text)
                    post_elem = root.find(".//POST")
                    if post_elem is not None:
                        message_text = post_elem.findtext("MESSAGE")
                        nation = post_elem.findtext("NATION")
                          
                          # Extract quote blocks
                        quotes = re.findall(r"\[quote=(.*?);(\d+)](.*?)\[/quote]", message_text, re.DOTALL)
                        clean_text = re.sub(r"\[quote=(.*?);(\d+)](.*?)\[/quote]", "", message_text, flags=re.DOTALL).strip()
                          
                        embed = discord.Embed(title="New RMB Post", timestamp=datetime.utcnow())
                          
                          # Add quotes as separate fields
                        for author, _, quote in quotes:
                            embed.add_field(name=f"Quoted from {author}", value=quote.strip()[:1024], inline=False)
                          
                          # Add remaining message
                        if clean_text:
                            embed.add_field(name="Message", value=clean_text[:1024], inline=False)

                          # Updated post link format
                        post_url = f"https://www.nationstates.net/region={region}/page=display_region_rmb?postid={post_id}#p{post_id}"
                        embed.set_footer(text=f"Posted by {nation} | View Post", icon_url="https://www.nationstates.net/images/nation_icon.png")
                        embed.url = post_url

                        cfg = self.config.guild(guild)
                        channel_id = await cfg.channel()
                        if channel_id:
                            channel = self.bot.get_channel(channel_id)
                            if channel:
                                await channel.send(embed=embed)
                        return  # Don't continue with normal handling
            
            message = html.unescape(message)
            dispatch_match = re.search(r'([a-z0-9_]+) published "<a href="page=dispatch/id=(\d+)">(.*?)</a>" \((.*?)\)', message, re.IGNORECASE)
            if dispatch_match:
                author = dispatch_match.group(1)
                dispatch_id = dispatch_match.group(2)
                dispatch_title = dispatch_match.group(3)
                dispatch_type = dispatch_match.group(4)
                dispatch_url = f"https://www.nationstates.net/nation={author}/detail={dispatch_type.split(':')[0].strip().lower()}/id={dispatch_id}"

                embed = discord.Embed(title=dispatch_title, url=dispatch_url, timestamp=datetime.utcnow())
                embed.set_footer(text=f"{dispatch_type} Dispatch")
                cfg = self.config.guild(guild)
                channel_id = await cfg.channel()
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)
                return

            embed_title = "News from around the Well"
            if message.lower().startswith("following new legislation"):
                embed_title = "FOLLOWING NEW LEGISLATION"
            elif re.search(r"@@.*?@@ endorsed @@.*?@@", message, re.IGNORECASE):
                embed_title = "New Endorsement"

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

            embed = discord.Embed(title=embed_title, description=message, timestamp=datetime.utcnow())
            if flag_url:
                embed.set_thumbnail(url=flag_url)
            await channel.send(embed=embed)

        except Exception as e:
            print(f"[Event Handler] Error in {guild.name}:", e)
