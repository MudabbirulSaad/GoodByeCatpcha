import time
import os
import asyncio

from peewee import *
from playhouse.apsw_ext import *


database_filename = "proxy.db"
database = db = APSWDatabase(
    database_filename, pragmas=(("synchronous", "off"),)
)


def init_db(dbname, remove=False):
    database.connect()
    database.create_tables([Proxy])
    Proxy.update(active=False).execute()


class Proxy(Model):
    class Meta:
        database = database

    proxy = CharField(primary_key=True)
    active = BooleanField(default=False)
    alive = BooleanField(default=False)
    last_used = IntegerField(default=0)
    last_banned = IntegerField(default=0)


# if os.path.exists(database_filename): os.remove(database_filename)
init_db(database_filename)

class ProxyDB(object):
    _lock = asyncio.Lock()
    def __init__(self, last_used_timeout=300, last_banned_timeout=300):
        self.last_used_timeout = last_used_timeout
        self.last_banned_timeout = last_banned_timeout

    def add(self, proxies):
        def chunks(l, n):
            n = max(1, n)
            return (l[i : i + n] for i in range(0, len(l), n))

        q = [proxy.proxy for proxy in Proxy.select(Proxy.proxy)]
        proxies_up = list(set(q) & set(proxies))
        proxies_dead = list(set(q) - set(proxies))
        proxies_new = set(proxies) - set(q)
        rows = [{"proxy": proxy, "alive": True} for proxy in proxies_new]

        with db.atomic():
            for dead in chunks(proxies_dead, 500):
                Proxy.update(alive=False).where(Proxy.proxy << dead).execute()

            for up in chunks(proxies_up, 500):
                Proxy.update(alive=True).where(Proxy.proxy << up).execute()

            for row in chunks(rows, 100):
                Proxy.insert_many(row).execute()

    async def get(self):
        try:
            async with self._lock:
                proxy = Proxy.get(
                    (Proxy.active == False)
                    & (Proxy.alive == True)
                    & (Proxy.last_banned <= time.time())
                    & (Proxy.last_used <= time.time())
                ).proxy
                self.set_active(proxy)
        except Proxy.DoesNotExist:
            return
        return proxy

    def set_active(self, proxy):
        query = Proxy.update(active=True).where(Proxy.proxy == proxy)
        return query.execute()

    def set_used(self, proxy):
        query = Proxy.update(
            last_used=time.time() + self.last_used_timeout, active=False
        ).where(Proxy.proxy == proxy)
        return query.execute()

    def set_banned(self, proxy):
        query = Proxy.update(
            last_banned=time.time() + self.last_banned_timeout, active=False
        ).where(Proxy.proxy == proxy)
        return query.execute()

    def loaded_count(self):
        query = Proxy.select().where(Proxy.alive == True)
        return query.count()

    def banned_count(self):
        query = Proxy.select().where(Proxy.last_banned >= time.time())
        return query.count()

    def used_count(self):
        query = Proxy.select(Proxy.proxy).where(
            (Proxy.alive == True)
            & (Proxy.last_banned <= time.time())
            & ((Proxy.last_used >= time.time()) | (Proxy.active == True))
        )
        return query.count()

    def usable_count(self):
        query = Proxy.select(Proxy.proxy).where(
            (Proxy.active == False)
            & (Proxy.alive == True)
            & (Proxy.last_banned <= time.time())
            & (Proxy.last_used <= time.time())
        )
        return query.count()