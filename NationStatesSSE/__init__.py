from .NationStatesSSE import NationStatesSSE


async def setup(bot):
    await bot.add_cog(NationStatesSSE(bot))
