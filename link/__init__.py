from .link import link


async def setup(bot):
    await bot.add_cog(link(bot))
