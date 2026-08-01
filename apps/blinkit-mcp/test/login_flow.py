import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server import check_login, ctx, enter_otp, login


async def main():
    try:
        print(await login(sys.argv[1]))
        otp = await asyncio.to_thread(input, "OTP: ")
        print(await enter_otp(otp))
        print("STATUS:", await check_login())
    finally:
        await ctx.auth.close()


if __name__ == "__main__":
    asyncio.run(main())
