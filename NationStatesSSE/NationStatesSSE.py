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
from discord.ext import tasks




class NationStatesSSE(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1357908642, force_registration=True)
        self.config.register_guild(channel=None, whitelist=[], blacklist=[], region="the_wellspring", user_agent="Redbot-SSE-Listener")
        self.session = aiohttp.ClientSession()
        self.sse_tasks = {}
        self.last_event_time = {}
        self.stop_flags = {}
        self.check_sse_tasks.start()


    def cog_unload(self):
        for guild_id, task in list(self.sse_tasks.items()):
            task.cancel()
            del self.sse_tasks[guild_id]
        if not self.session.closed:
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
    async def SSEsetuseragent(self, ctx, *, agent: str):
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
        self.stop_flags[ctx.guild.id] = True
        await ctx.send("SSE listener will stop shortly.")

    @tasks.loop(minutes=1)
    async def check_sse_tasks(self):
        for guild_id, task in list(self.sse_tasks.items()):
            if task.done():
                try:
                    exc = task.exception()
                    print(f"[Watchdog] SSE for guild {guild_id} crashed with exception: {exc}")
                except asyncio.CancelledError:
                    continue
                guild = self.bot.get_guild(guild_id)
                if guild and not self.stop_flags.get(guild.id, False):
                    print(f"[Watchdog] Restarting SSE for guild {guild_id}")
                    await self.restart_sse(guild)
    
    @check_sse_tasks.before_loop
    async def before_check_sse_tasks(self):
        await self.bot.wait_until_ready()


    async def restart_sse(self, guild, ctx=None):
        if guild.id in self.sse_tasks:
            self.sse_tasks[guild.id].cancel()
        self.sse_tasks[guild.id] = asyncio.create_task(self.sse_listener(guild))
        if ctx:
            await ctx.send("🔁 Reconnected to updated SSE stream.")
    
    async def sse_listener(self, guild):
        cfg = self.config.guild(guild)
        self.stop_flags[guild.id] = False  # Reset flag when starting
    
        while not self.stop_flags.get(guild.id, False):
            try:
                region = await cfg.region()
                agent = await cfg.user_agent()
                url = f"https://www.nationstates.net/api/region:{region}"
                async with self.session.get(url, headers={"User-Agent": agent}) as resp:
                    async for line in resp.content:
                        if self.stop_flags.get(guild.id, False):
                            break
                        if line == b'\n':
                            continue
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            self.last_event_time[guild.id] = datetime.utcnow()
                            await self.handle_event(guild, line[6:])
                        elif line.startswith("heartbeat: "):
                            self.last_event_time[guild.id] = datetime.utcnow()
    
            except asyncio.CancelledError:
                print(f"[SSE] SSE listener manually cancelled for {guild.name}")
                break
    
            except Exception as e:
                print(f"[SSE] Error for {guild.name}:", e)
                channel_id = await cfg.channel()
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        try:
                            if str(e):
                                await channel.send(f"⚠️ SSE Error: `{e}`")
                        except Exception:
                            pass
                await asyncio.sleep(5)  # Wait before retrying
    
        # Clean up if stop flag is set
        print(f"[SSE] SSE loop exited for {guild.name}")
        self.sse_tasks.pop(guild.id, None)
        self.stop_flags.pop(guild.id, None)



                
    async def handle_event(self, guild, data):
        try:

            payload = json.loads(data)
            message = payload.get("str")
            html = payload.get("htmlStr", "")
            message = re.sub(r"@@(.*?)@@", lambda m: f"[{m.group(1)}](https://www.nationstates.net/nation={m.group(1).replace(' ', '_')})", message)
            message = re.sub(r"%%(.*?)%%", lambda m: f"[{m.group(1)}](https://www.nationstates.net/region={m.group(1).replace(' ', '_')})", message)
            message = message.replace("&eacute;","é").replace("[/i]","*").replace("[i]","*").replace("[/b]","**").replace("[b]","**").replace("[spoiler=","||").replace("[/spoiler]","||")        
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
                        message_text.replace("[i]","*").replace("[/i]","*").replace("[b]","**").replace("[/b]","**")
                          # Extract quote blocks
                        quotes = re.findall(r"\[quote=(.*?);(\d+)](.*?)\[/quote]", message_text, re.DOTALL)
                        clean_text = re.sub(r"\[quote=(.*?);(\d+)](.*?)\[/quote]", "", message_text, flags=re.DOTALL).strip()
                          
                        embed = discord.Embed(title="New RMB Post", timestamp=datetime.utcnow())
                        if flag_url:
                            embed.set_thumbnail(url=flag_url) 
                          # Add quotes as separate fields
                        for author, _, quote in quotes:
                            embed.add_field(name=f"Quoted from {author}", value=quote.strip()[:1024], inline=False)
                          
                          # Add remaining message
                        if clean_text:
                            embed.add_field(name="Message", value=clean_text[:1024], inline=False)

                          # Updated post link format
                        post_url = f"https://www.nationstates.net/region={region}/page=display_region_rmb?postid={post_id}#p{post_id}"
                        embed.set_footer(text=f"Posted by {nation}")
                        embed.url = post_url

                        cfg = self.config.guild(guild)
                        channel_id = await cfg.channel()
                        if channel_id:
                            channel = self.bot.get_channel(channel_id)
                            if channel:
                                await channel.send(embed=embed)
                        return  # Don't continue with normal handling

            dispatch_match = re.search(r'published \"<a href=\"page=dispatch/id=(\d+)\">(.*?)<\/a>\" \((.*?)\)', message)
            if dispatch_match:
                dispatch_id = dispatch_match.group(1)
                dispatch_title = dispatch_match.group(2)
                dispatch_type = dispatch_match.group(3)
                dispatch_url = f"https://www.nationstates.net/page=dispatch/id={dispatch_id}"


                message = message.replace(f'"<a href="page=dispatch/id={dispatch_id}">{dispatch_title}</a>"', 'a new dispatch ')

                embed = discord.Embed(title=dispatch_title, url=dispatch_url, description=message, timestamp=datetime.utcnow())
                if flag_url:
                    embed.set_thumbnail(url=flag_url)
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
                message = message.replace("Following new legislation in","In")
            elif re.search(r"@@.*?@@ endorsed @@.*?@@", message, re.IGNORECASE):
                embed_title = "New Endorsement"

            embed = discord.Embed(title=embed_title, description=message, timestamp=datetime.utcnow())
            if flag_url:
                embed.set_thumbnail(url=flag_url)
            await channel.send(embed=embed)

        except Exception as e:
            print(f"[Event Handler] Error in {guild.name}:", e)
