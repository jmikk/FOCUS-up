import discord
from redbot.core import commands, Config
from discord.ext import tasks
import aiohttp
import asyncio
from datetime import datetime, timedelta
import json


class link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(None, identifier=345678654456, force_registration=True)
        self.config.register_user(linked_nations=[])
        self.config.register_guild(
            welcome_message="Welcome to the server, {mention}!",
            welcome_channel=None,
            resRole="",
            visitorRole="",
            daily_channel=None,
            verification_guild=None
        )
        self.config.register_global(
            user_agent=None,
            region=None
        )
        self.daily_task.start()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.await_setup()

    async def await_setup(self):
        owner = (await self.bot.application_info()).owner
        global_config = await self.config.all()

        if not global_config.get("user_agent") or not global_config.get("region"):
            try:
                def check(m):
                    return m.author == owner and isinstance(m.channel, discord.DMChannel)

                await owner.send("👋 Let's set up the NationStates link cog.\nEnter your **User-Agent**:")
                msg = await self.bot.wait_for("message", check=check, timeout=300)
                user_agent = msg.content.strip()

                await owner.send("🌍 Now enter your **Region Name**:")
                msg = await self.bot.wait_for("message", check=check, timeout=300)
                region = msg.content.strip()

                await self.config.user_agent.set(user_agent)
                await self.config.region.set(region)

                await owner.send(f"✅ Setup complete! User-Agent: `{user_agent}`, Region: `{region}`.")
            except asyncio.TimeoutError:
                await owner.send("⏰ Setup timed out. You can run `!setuseragent` and `!setregion` later.")


    @commands.command()
    async def linknation(self, ctx, *nation_name: str):
        """Link your NationStates nation to your Discord account."""
        verify_url = f"https://www.nationstates.net/page=verify_login"
        await ctx.send(f"To verify your NationStates nation, visit {verify_url} and copy the code in the box.")
        await ctx.send(f"Then, DM me the following command to complete verification: `!verifynation <nation_name> <code>` \n For example `!verifynation {'_'.join(nation_name).replace('<','').replace('>','')} FWIXlb2dPZCHm1rq-4isM94FkCJ4RGPUXcjrMjFHsIc`")
    

    @commands.command()
    @commands.is_owner()
    async def setuseragent(self, ctx, *, ua: str):
        await self.config.user_agent.set(ua.strip())
        await ctx.send(f"✅ User-Agent set to `{ua.strip()}`.")

    @commands.command()
    @commands.is_owner()
    async def setregion(self, ctx, *, region: str):
        await self.config.region.set(region.strip().replace(" ","_"))
        await ctx.send(f"✅ Region set to `{region.strip()}`.")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def setupserver(self, ctx, resrole: discord.Role, visitorrole: discord.Role, verify_guild: discord.Guild, daily_channel: discord.TextChannel):
        await self.config.guild(ctx.guild).resRole.set(str(resrole.id))
        await self.config.guild(ctx.guild).visitorRole.set(str(visitorrole.id))
        await self.config.guild(ctx.guild).verification_guild.set(verify_guild.id)
        await self.config.guild(ctx.guild).daily_channel.set(daily_channel.id)
        await ctx.send("✅ Server-specific configuration saved.")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def viewserverconfig(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        embed = discord.Embed(title="📋 Server Configuration", color=discord.Color.green())
        embed.add_field(name="Resident Role", value=f"<@&{conf['resRole']}>", inline=False) if conf['resRole'] else embed.add_field(name="Resident Role", value="Not set", inline=False)
        embed.add_field(name="Visitor Role", value=f"<@&{conf['visitorRole']}>", inline=False) if conf['visitorRole'] else embed.add_field(name="Visitor Role", value="Not set", inline=False)
        embed.add_field(name="Verification Guild", value=conf['verification_guild'] or "Not set", inline=False)
        embed.add_field(name="Daily Channel", value=f"<#{conf['daily_channel']}>" if conf['daily_channel'] else "Not set", inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    async def verifynation(self, ctx, nation_name: str, code: str):
        formatted_nation = nation_name.lower().replace(" ", "_")
        user_agent = await self.config.user_agent()
        guild_config = await self.config.guild(ctx.guild).all()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://www.nationstates.net/cgi-bin/api.cgi?a=verify&nation={formatted_nation}&checksum={code}",
                headers={"User-Agent": user_agent}
            ) as response:
                result = await response.text()
                if result.strip() != "1":
                    await ctx.send("❌ Verification failed. Make sure you entered the correct code.")
                    return

        async with self.config.user(ctx.author).linked_nations() as nations:
            if formatted_nation not in nations:
                nations.append(formatted_nation)

        residents = await self.fetch_nations()

        verify_guild = self.bot.get_guild(int(guild_config["verification_guild"])) if guild_config["verification_guild"] else None
        if not verify_guild:
            await ctx.send("❌ Verification failed. Could not find the server.")
            return

        member = verify_guild.get_member(ctx.author.id)
        if not member:
            await ctx.send("❌ You are not a member of the verification server.")
            return

        resident_role = verify_guild.get_role(int(guild_config["resRole"])) if guild_config["resRole"] else None
        visitor_role = verify_guild.get_role(int(guild_config["visitorRole"])) if guild_config["visitorRole"] else None

        if not resident_role or not visitor_role:
            await ctx.send("❌ One or more roles not found. Please check the role IDs.")
            return

        if formatted_nation in residents:
            if resident_role not in member.roles:
                await member.add_roles(resident_role)
                await ctx.send("✅ You have been given the resident role.")
            if visitor_role in member.roles:
                await member.remove_roles(visitor_role)
        else:
            if visitor_role not in member.roles:
                await member.add_roles(visitor_role)
                await ctx.send("✅ You have been given the visitor role.")
            if resident_role in member.roles:
                await member.remove_roles(resident_role)

        await ctx.send(f"✅ Linked NationStates nation: **{nation_name}**")

    async def fetch_nations(self):
        user_agent = await self.config.user_agent()
        region = await self.config.region()
        if not user_agent or not region:
            return []

        url = f"https://www.nationstates.net/cgi-bin/api.cgi?region={region}&q=nations"
        headers = {"User-Agent": user_agent}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return []
                xml_data = await response.text()
                start_tag, end_tag = "<NATIONS>", "</NATIONS>"
                start_index = xml_data.find(start_tag) + len(start_tag)
                end_index = xml_data.find(end_tag)
                nations = xml_data[start_index:end_index].split(":")
                return [n for n in nations if n]

    @tasks.loop(hours=1)
    async def daily_task(self):
        now = datetime.utcnow()
        if now.hour == 20:
            for guild in self.bot.guilds:
                channel_id = await self.config.guild(guild).daily_channel()
                if channel_id:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        try:
                            await channel.send("Starting daily cycle")
                            await self.residency_check(guild, channel)
                        except Exception as e:
                            print(f"Error sending daily message in {guild.name}: {e}")
                            
    async def residency_check(self, guild, channel):
        residents = await self.fetch_nations()
        if not residents:
            await channel.send("Failed to retrieve residents from the API.")
            return

        all_users = await self.config.all_users()
        gained_role = 0
        lost_role = 0

        res_role_id = await self.config.guild(guild).resRole()
        vis_role_id = await self.config.guild(guild).visitorRole()
        res_role = guild.get_role(int(res_role_id)) if res_role_id else None
        vis_role = guild.get_role(int(vis_role_id)) if vis_role_id else None

        for user_id, data in all_users.items():
            linked_nations = data.get("linked_nations", [])
            member = guild.get_member(int(user_id))
            if not member:
                continue

            is_resident = any(n in residents for n in linked_nations)

            if is_resident and res_role and res_role not in member.roles:
                await member.add_roles(res_role)
                gained_role += 1
            elif not is_resident and res_role and res_role in member.roles:
                await member.remove_roles(res_role)
                lost_role += 1

        await channel.send(f"✅ {gained_role} users gained the resident role.\n❌ {lost_role} users lost the resident role.")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild_config = await self.config.guild(member.guild).all()
        welcome_channel_id = guild_config["welcome_channel"]
        welcome_message = guild_config["welcome_message"]

        if welcome_channel_id and welcome_message:
            channel = member.guild.get_channel(welcome_channel_id)
            if channel:
                try:
                    formatted_message = welcome_message.replace("{mention}", member.mention).replace("{user}", member.name)
                    await channel.send(formatted_message)
                except discord.Forbidden:
                    print(f"Missing permissions to send welcome message in {channel.name}.")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def setwelcome(self, ctx, *, message: str):
        await self.config.guild(ctx.guild).welcome_message.set(message)
        await ctx.send("✅ Welcome message updated. Use `{mention}` or `{user}` as placeholders.")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def setwelcomechannel(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).welcome_channel.set(channel.id)
        await ctx.send(f"✅ Welcome channel set to {channel.mention}.")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def viewwelcome(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        msg = conf.get("welcome_message", "Not set")
        chan = conf.get("welcome_channel")
        ch = ctx.guild.get_channel(chan) if chan else None
        await ctx.send(f"📜 **Welcome Message:** {msg}\n📢 **Channel:** {ch.mention if ch else 'Not set'}")


    @commands.command()
    @commands.has_permissions(administrator=True)
    async def startloop(self, ctx):
        """Force start the daily task loop if it's not already running."""
        if self.daily_task.is_running():
            await ctx.send("🔁 The daily task loop is already running.")
        else:
            self.daily_task.start()
            await ctx.send("✅ Daily task loop started.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def checkloop(self, ctx):
        """Check if the daily task loop is currently running."""
        running = self.daily_task.is_running()
        await ctx.send(f"🔍 Daily task running: {'✅ Yes' if running else '❌ No'}")
