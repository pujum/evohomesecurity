# evohomesecurity

A Python wrapper for the evohome Security API, used by the Home Assistant integration.

## Example usage
```python
import asyncio
import aiohttp
from evohomesecurity import EvohomeSecurityApiClient


async def main():
    async with aiohttp.ClientSession() as session:
        client = EvohomeSecurityApiClient('name@domain.com', my_password', session=session)

        try:
            await client.async_login()
            await client.async_set_full_arm()
            await client.async_set_disarm()
            await client.async_set_partial_arm()      
            await client.async_get_state()
        finally:
           await client.async_logout()

if __name__ == '__main__':
    asyncio.run(main())
```
