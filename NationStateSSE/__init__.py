from .NationStateSSE import NationStateSSE


async def setup(bot):
    await bot.add_cog(NationStateSSE(bot))
