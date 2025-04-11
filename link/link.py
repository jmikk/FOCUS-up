import discord
from redbot.core import commands, Config, checks
from discord.ext import tasks  
import aiohttp
import asyncio
from datetime import datetime, timedelta
import json


class link(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(None, identifier=345678654456, force_registration=True)
        self.config.register_user(
            linked_nations=[],
        )
        self.config.register_guild(
        welcome_message="This is a test",  # Message to send when a new user joins
        welcome_channel=1263079556420603935,
        resRole = "",
        visitorRole = ""
    )
    self.API_URL = "https://www.nationstates.net/cgi-bin/api.cgi?region=vibonia&q=nations"
    self.USER_AGENT = "Lionsroar"

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.daily_task.is_running():
            self.daily_task.start()

    def cog_unload(self):
        self.daily_task.cancel()

    @tasks.loop(hours=1)
    async def daily_task(self):
        now = datetime.utcnow()
        if now.hour == 20:
            channel = self.bot.get_channel(1096654774595756082)
            if channel:
                try:
                    message = await channel.send("Starting daily cycle")
                    ctx = await self.bot.get_context(message)
                    await self.resChk(channel)
                except Exception as e:
                        await channel.send(e)

    async def fetch_nations(self):
        """Fetch nations from the NationStates API asynchronously."""
        headers = {"User-Agent": self.USER_AGENT}
        async with aiohttp.ClientSession() as session:
            async with session.get(self.API_URL, headers=headers) as response:
                if response.status != 200:
                    return []

                xml_data = await response.text()
                start_tag, end_tag = "<NATIONS>", "</NATIONS>"
                start_index = xml_data.find(start_tag) + len(start_tag)
                end_index = xml_data.find(end_tag)
                nations = xml_data[start_index:end_index].split(":")
                return [n for n in nations if n]

    @commands.command()
    @commands.admin()
    async def start_loop(self, ctx):
        """Manually start the daily task loop if it's not running."""
        if self.daily_task.is_running():
            await ctx.send("✅ The daily task loop is already running.")
        else:
            self.daily_task.start()
            await ctx.send("🔄 Daily task loop has been started.")    

    @commands.command()
    @commands.admin()
    async def resChk(self, ctx):
        """Check if the daily_task loop is running and manage roles based on residency."""
        resendents = await self.fetch_nations()
        if not resendents:
            await ctx.send("Failed to retrieve resendents. Try again later.")
            return

        if not resendents:
            await ctx.send("No resendents found.")
            return
    
        # Role ID to be assigned/removed
        role_id = 1359604065998340238
        role_id_vis = 1096654774595756082
        role = ctx.guild.get_role(role_id)
        role_vis = ctx.guild.get_role(role_id)

        if not role or not role_vis:
            await ctx.send("Role not found. Please check the role ID.")
            return
    
        # Get all users from config
        all_users = await self.config.all_users()
        gained_role = 0
        lost_role = 0
    
        for user_id, data in all_users.items():
            linked_nations = data.get("linked_nations", [])
            user = ctx.guild.get_member(int(user_id))
            if not user:
                continue  # Skip users not found in the guild

            is_resident = any(nation in resendents for nation in linked_nations)
    
            if is_resident:

                if role not in user.roles:
                    await user.add_roles(role)
                    gained_role += 1
            else:
                # Remove role if they have it but no endorsed nation
                if role in user.roles:
                    await user.remove_roles(role)
                    lost_role += 1
    
        await ctx.send(f"✅ {gained_role} users gained the resident Role.\n❌ {lost_role} users lost the resident Role.")

   
    @commands.command()
    @commands.admin()
    async def check_loop(self, ctx):
        """Check if the daily_task loop is running."""
        is_running = self.daily_task.is_running()
        await ctx.send(f"🔄 Daily task running: **{is_running}**")    


    @commands.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command()
    async def set_daily_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where the daily message will be sent."""
        await self.config.guild(ctx.guild).daily_channel.set(channel.id)
        await ctx.send(f"Daily message channel set to {channel.mention}.")

    @commands.command()
    async def linknation(self, ctx, *nation_name: str):
        """Link your NationStates nation to your Discord account."""
        verify_url = f"https://www.nationstates.net/page=verify_login"
        await ctx.send(f"To verify your NationStates nation, visit {verify_url} and copy the code in the box.")
        await ctx.send(f"Then, DM me the following command to complete verification: `!verifynation <nation_name> <code>` \n For example `!verifynation {'_'.join(nation_name).replace('<','').replace('>','')} FWIXlb2dPZCHm1rq-4isM94FkCJ4RGPUXcjrMjFHsIc`")
    
    @commands.command()
    async def verifynation(self, ctx, nation_name: str, code: str):
        """Verify the NationStates nation using the provided verification code."""
        formatted_nation = nation_name.lower().replace(" ", "_")
    
        # Verify with NationStates API
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://www.nationstates.net/cgi-bin/api.cgi?a=verify&nation={formatted_nation}&checksum={code}",
                headers={"User-Agent": self.USER_AGENT}
            ) as response:
                result = await response.text()
                if result.strip() != "1":
                    await ctx.send("❌ Verification failed. Make sure you entered the correct code and try again.")
                    return
    
        # Save nation to user config if not already linked
        async with self.config.user(ctx.author).linked_nations() as nations:
            if formatted_nation not in nations:
                nations.append(formatted_nation)
    
        # Fetch residents from API
        async with aiohttp.ClientSession() as session:
            async with session.get(self.API_URL, headers={"User-Agent": self.USER_AGENT}) as response:
                if response.status != 200:
                    await ctx.send("Failed to retrieve residents. Try again later.")
                    return
    
                xml_data = await response.text()
                start_tag, end_tag = "<NATIONS>", "</NATIONS>"
                start_index = xml_data.find(start_tag) + len(start_tag)
                end_index = xml_data.find(end_tag)
                resident_list_raw = xml_data[start_index:end_index].split(":")
                residents = [n.strip().lower() for n in resident_list_raw if n]
    
        # Guild and Roles
        guild = self.bot.get_guild(1096547761136083074)  # Your server ID
        if not guild:
            await ctx.send("❌ Verification failed. Could not find the server.")
            return
    
        member = guild.get_member(ctx.author.id)
        if not member:
            await ctx.send("❌ You are not a member of the verification server.")
            return
    
        resident_role = guild.get_role(1098645868162338919)     # Resident role
        nonresident_role = guild.get_role(1098673447640518746)  # Visitor role
    
        if not resident_role or not nonresident_role:
            await ctx.send("❌ One or more roles not found. Please check the role IDs.")
            return
    
        # Assign roles based on residency
        if formatted_nation in residents:
            if resident_role not in member.roles:
                await member.add_roles(resident_role)
                await ctx.send("✅ You have been given the resident role.")
            if nonresident_role in member.roles:
                await member.remove_roles(nonresident_role)
        else:
            if nonresident_role not in member.roles:
                await member.add_roles(nonresident_role)
                await ctx.send("✅ You have been given the visitor role.")
            if resident_role in member.roles:
                await member.remove_roles(resident_role)
    
        await ctx.send(f"✅ Successfully linked your NationStates nation: **{nation_name}**")


    
    @commands.command()
    async def mynation(self, ctx, user: discord.Member = None):
        """Check which NationStates nation is linked to a Discord user."""
        user = user or ctx.author
        nations = await self.config.user(user).linked_nations()
        if nations:
            # Format each nation as a Discord hyperlink
            nation_list = "\n".join(
                f"[{n.replace('_', ' ').title()}](https://www.nationstates.net/nation={n})" for n in nations
            )
            await ctx.send(f"🌍 {user.display_name}'s linked NationStates nation(s):\n{nation_list}")
        else:
            await ctx.send(f"❌ {user.display_name} has not linked a NationStates nation yet.")

    
    @commands.command()
    async def unlinknation(self, ctx, nation_name: str):
        """Unlink a specific NationStates nation from your Discord account."""
        nation_name = nation_name.lower().replace(" ","_")
        async with self.config.user(ctx.author).linked_nations() as nations:
            if nation_name in nations:
                nations.remove(nation_name)
                await ctx.send(f"✅ Successfully unlinked the NationStates nation: **{nation_name}**")
            else:
                await ctx.send(f"❌ You do not have **{nation_name}** linked to your account.")

    @commands.command()
    @commands.admin()
    async def dump_users(self, ctx):
        """Dump all user data from config into a JSON file."""
        all_users = await self.config.all_users()
    
        if not all_users:
            await ctx.send("No user data found.")
            return
    
        # Create a filename with timestamp
        filename = f"user_dump_{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    
        # Save data to a file
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(all_users, f, indent=4)
    
        # Send file to Discord
        await ctx.send(file=discord.File(filename))
    
    @commands.guild_only()
    @commands.admin()
    @commands.command(name="setwelcome")
    async def set_welcome_message(self, ctx, *, message: str):
        """Set the welcome message for new members."""
        await self.config.guild(ctx.guild).welcome_message.set(message)
        await ctx.send(f"✅ Welcome message has been set to:\n\n{message}")

    @commands.guild_only()
    @commands.admin()
    @commands.command(name="setwelcomechannel")
    async def set_welcome_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where the welcome message will be sent."""
        await self.config.guild(ctx.guild).welcome_channel.set(channel.id)
        await ctx.send(f"✅ Welcome messages will be sent in {channel.mention}.")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        welcome_message = await self.config.guild(guild).welcome_message()
        welcome_channel_id = await self.config.guild(guild).welcome_channel()
        
        if not welcome_message:
            return  # No welcome message set
    
        # Format placeholders (e.g., {user}, {mention})
        formatted_message = welcome_message.replace("{user}", member.name).replace("{mention}", member.mention)
    
        if welcome_channel_id:
            channel = guild.get_channel(welcome_channel_id)
        else:
            # Default to system channel or first text channel
            channel = guild.system_channel or discord.utils.get(guild.text_channels, permissions__send_messages=True)
    
        if channel:
            try:
                await channel.send(formatted_message)
            except discord.Forbidden:
                print(f"Missing permissions to send messages in {channel.id}")

    
    
    @commands.guild_only()
    @commands.admin()
    @commands.command(name="viewwelcome")
    async def view_welcome_message(self, ctx):
        """View the current welcome message."""
        message = await self.config.guild(ctx.guild).welcome_message()
        channel_id = await self.config.guild(ctx.guild).welcome_channel()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
    
        if not message:
            await ctx.send("No welcome message set.")
            return
    
        await ctx.send(f"📜 Welcome Message:\n{message}\n\n📢 Channel: {channel.mention if channel else 'Default system/first available channel'}")

    
    @commands.guild_only()
    @commands.admin()
    @commands.command(name="dropnation")
    async def drop_nation(self, ctx, nation_name: str):
        """Admin command to remove a nation from all users' linked nations."""
        formatted_nation = nation_name.lower().replace(" ", "_")
        all_users = await self.config.all_users()
        dropped_count = 0
    
        for user_id, data in all_users.items():
            linked_nations = data.get("linked_nations", [])
            if formatted_nation in linked_nations:
                linked_nations.remove(formatted_nation)
                await self.config.user_from_id(user_id).linked_nations.set(linked_nations)
                dropped_count += 1
    
        await ctx.send(f"✅ Nation `{formatted_nation}` was removed from `{dropped_count}` user(s)' linked nations.")
