import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import DialogFilterDefault
import os

from dotenv import load_dotenv

load_dotenv()

async def main():
    client = TelegramClient('sessions/sess_2114098498', int(os.getenv('API_ID')), os.getenv('API_HASH'))
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Not authorized.")
        return
        
    filters = await client(GetDialogFiltersRequest())
    print("Filters:", len(filters))
    for f in filters:
        if isinstance(f, DialogFilterDefault):
            print("Default folder")
            continue
        print("Folder:", getattr(f, 'title', None), f.id)
        
        # Test how to get chats from this folder manually
        included = set(client.get_peer_id(p) for p in f.include_peers)
        excluded = set(client.get_peer_id(p) for p in f.exclude_peers)
        
        print("Included:", included)
        print("Excluded:", excluded)
        print(f"Bools: bots={f.bots}, groups={f.groups}, channels={f.broadcasts}, contacts={f.contacts}, non_contacts={f.non_contacts}")

asyncio.run(main())
