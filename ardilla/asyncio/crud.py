from typing import Literal, Generic, Self

import aiosqlite
from aiosqlite import Row

from ..errors import BadQueryError, QueryExecutionError
from ..models import M
from ..abc import CrudABC
from ..logging import log, log_query

from .abc import AbstractAsyncEngine

class AsyncCrud(CrudABC, Generic[M]):
    """Abstracts CRUD actions for model associated tables"""

    engine: AbstractAsyncEngine

    async def _get_or_none_any(self, many: bool, **kws) -> list[M] | M | None:
        """
        private helper to the get_or_none queries.
        if param "many" is true it will return a list of matches else will return only one record
        """
        keys, vals = zip(*kws.items())
        to_match = f" AND ".join(f"{k} = ?" for k in keys)

        limit = "LIMIT 1;" if not many else ";"
        q = f"SELECT rowid, * FROM {self.tablename} WHERE ({to_match}) {limit}"
        log_query(q, vals)
        async with self.engine as con:
            async with con.execute(q, vals) as cur:
                if many:
                    rows: list[Row] = await cur.fetchall()
                    return [self._row2obj(row) for row in rows]

                else:
                    row: Row | None = await cur.fetchone()
                    if row:
                        return self._row2obj(row)
        return

    async def get_or_none(self, **kws) -> M | None:
        """Gets an object from a database or None if not found"""
        return await self._get_or_none_any(many=False, **kws)

    async def _do_insert(self, ignore: bool = False, returning: bool = True, /, **kws):
        keys, vals = zip(*kws.items())
        placeholders = ", ".join("?" * len(keys))
        cols = ", ".join(keys)

        q = "INSERT OR IGNORE " if ignore else "INSERT "
        q += f"INTO {self.tablename} ({cols}) VALUES ({placeholders})"
        q += " RETURNING *;" if returning else ";"
        log_query(q, vals)
        async with self.engine as con:
            con = await self.engine.connect()
            cur = None
            try:
                cur = await con.execute(q, vals)
            except aiosqlite.IntegrityError as e:
                raise QueryExecutionError(str(e))
            else:
                row = await cur.fetchone()
                await con.commit()
                if returning and row:
                    return self._row2obj(row, cur.lastrowid)
            finally:
                if cur is not None:
                    await cur.close()
                await con.close()

    async def insert(self, **kws):
        """
        Inserts a record into the database.
        Returns:
            Model | None: Returns a model only if newly created
        Rises:
            ardilla.error.QueryExecutionError: if there's a conflict when inserting the record
        """
        return await self._do_insert(False, True, **kws)

    async def insert_or_ignore(self, **kws) -> M | None:
        """inserts a the object of a row or ignores it if it already exists"""
        return await self._do_insert(True, True, **kws)

    async def get_or_create(self, **kws) -> tuple[M, bool]:
        """Returns object and bool indicated if it was created or not"""
        created = False
        result = await self.get_or_none(**kws)
        if not result:
            result = await self.insert_or_ignore(**kws)
            created = True
        return result, created

    async def get_all(self) -> list[M]:
        """Gets all objects from the database"""
        async with self.engine as con:
            async with con.execute(f"SELECT rowid, * FROM {self.tablename};") as cur:
                return [self._row2obj(row) for row in await cur.fetchall()]

    async def get_many(self, **kws) -> list[M]:
        """Returns a list of objects that have the given conditions"""
        return await self._get_or_none_any(many=True, **kws)

    async def save_one(self, obj: M) -> Literal[True]:
        """Saves one object to the database"""
        cols, vals = zip(*obj.dict().items())
        placeholders = ", ".join("?" * len(cols))

        q = f"""
        INSERT OR REPLACE INTO {self.tablename} ({', '.join(cols)}) VALUES ({placeholders});
        """
        log_query(q, vals)
        async with self.engine as con:
            await con.execute(q, vals)
            await con.commit()
        return True

    async def save_many(self, *objs: M) -> Literal[True]:
        """Saves all the given objects to the database"""
        placeholders = ", ".join("?" * len(self.columns))
        q = f'INSERT OR REPLACE INTO {self.tablename} ({", ".join(self.columns)}) VALUES ({placeholders});'
        vals = [tuple(obj.dict().values()) for obj in objs]
        log_query(q, vals)
        async with self.engine as con:
            await con.executemany(q, vals)
            await con.commit()

        return True

    async def delete_one(self, obj: M) -> Literal[True]:
        """
        Deletes the object from the database (won't delete the actual object)
        queries only by the Model id fields (fields suffixed with 'id')
        """
        obj_dict = obj.dict()
        id_cols = tuple([k for k in obj_dict if "id" in k])
        placeholders = ", ".join(f"{k} = ?" for k in id_cols)
        vals = tuple([obj_dict[k] for k in id_cols])
        q = f"DELETE FROM {self.tablename} WHERE ({placeholders});"
        log_query(q, vals)
        async with self.engine as con:
            await con.execute(q, vals)
            await con.commit()
        return True

    async def delete_many(self, *objs: M) -> Literal[True]:
        if not objs:
            raise IndexError('param "objs" is empty, pass at least one object')

        placeholders = ', '.join('?' for _ in objs)
        if all(obj.__rowid__ for obj in objs):
            vals = [obj.__rowid__ for obj in objs]    
            q = f'DELETE FROM {self.tablename} WHERE rowid IN ({placeholders})'

        elif pk := self.Model.__pk__:
            vals = [getattr(obj, pk) for obj in objs]
            q = f'DELETE FROM {self.tablename} WHERE id IN ({placeholders})'
            
        else:
            raise BadQueryError('Objects requiere either a primary key or the rowid set for mass deletion')
        
        async with self.engine as con:
            await con.execute(q, vals)
            await con.commit()

        return 