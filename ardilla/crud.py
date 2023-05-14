import sqlite3
from sqlite3 import Row
from typing import Literal, Generic, Self

from .abc import CrudABC, AbstractEngine
from .models import M, Model as BaseModel
from .errors import BadQueryError, QueryExecutionError


class Crud(CrudABC, Generic[M]):
    """Abstracts CRUD actions for model associated tables"""

    engine: AbstractEngine

    def _get_or_none_any(self, many: bool, **kws) -> list[M] | M | None:
        """
        private helper to the get_or_none queries.
        if param "many" is true it will return a list of matches else will return only one record
        """
        keys, vals = zip(*kws.items())
        to_match = f" AND ".join(f"{k} = ?" for k in keys)

        limit = "LIMIT 1;" if not many else ";"
        q = f"SELECT rowid, * FROM {self.tablename} WHERE ({to_match}) {limit}"
        with self.engine as con:
            with self.engine.cursor(con) as cur:
                cur: sqlite3.Cursor
                cur.execute(q, vals)
                if many:
                    rows: list[Row] = cur.fetchall()
                    return [self._row2obj(row) for row in rows]
                else:
                    row: Row | None = cur.fetchone()
                    if row:
                        return self._row2obj(row)
        return

    def _do_insert(
        self, ignore: bool = False, returning: bool = True, /, **kws
    ) -> M | None:
        keys, vals = zip(*kws.items())
        placeholders = ", ".join("?" * len(keys))
        cols = ", ".join(keys)

        q = "INSERT OR IGNORE " if ignore else "INSERT "
        q += f"INTO {self.tablename} ({cols}) VALUES ({placeholders})"
        q += " RETURNING *;" if returning else ";"

        with self.engine as con:
            with self.engine.cursor(con) as cur:
                cur: sqlite3.Cursor
                try:
                    cur.execute(q, vals)
                except sqlite3.IntegrityError as e:
                    raise QueryExecutionError(str(e))

                row = cur.fetchone()
                con.commit()
                if returning and row:
                    return self._row2obj(row, cur.lastrowid)

    def get_or_none(self, **kws) -> M | None:
        """Gets an object from a database or None if not found"""
        return self._get_or_none_any(many=False, **kws)

    def insert(self, **kws):
        """
        Inserts a record into the database.
        Returns:
            Model | None: Returns a model only if newly created
        Rises:
            ardilla.error.QueryExecutionError: if there's a conflict when inserting the record
        """
        return self._do_insert(False, True, **kws)

    def insert_or_ignore(self, **kws) -> M | None:
        """inserts a the object of a row or ignores it if it already exists"""
        return self._do_insert(True, True, **kws)

    def get_or_create(self, **kws) -> tuple[M, bool]:
        """Returns object and bool indicated if it was created or not"""
        created = False
        result = self.get_or_none(**kws)
        if not result:
            result = self.insert_or_ignore(**kws)
            created = True
        return result, created

    def get_all(self) -> list[M]:
        """Gets all objects from the database"""
        q = f"SELECT rowid, * FROM {self.tablename};"
        with self.engine as con:
            with self.engine.cursor(con) as cur:
                cur: sqlite3.Cursor
                cur.execute(q)
                results: list[Row] = cur.fetchall()
                return [self._row2obj(res) for res in results]
            

    def get_many(self, **kws) -> list[M]:
        """Returns a list of objects that have the given conditions"""
        return self._get_or_none_any(many=True, **kws)

    def save_one(self, obj: M) -> Literal[True]:
        """Saves one object to the database"""
        cols, vals = zip(*obj.dict().items())

        if obj.__rowid__ is not None:
            upsert_query = f"""
            UPDATE {self.tablename} SET ({', '.join(f'{k} = ?' for k in cols)}) WHERE rowid = ?;
            """
            vals += obj.__rowid__

        else:
            placeholders = ", ".join("?" * len(cols))
            upsert_query = f"""
            INSERT OR REPLACE INTO {self.tablename} ({', '.join(cols)}) VALUES ({placeholders});
            """
        with self.engine as con:
            con.execute(upsert_query, vals)
            con.commit()
        return True

    def save_many(self, *objs: M) -> Literal[True]:
        """Saves all the given objects to the database"""
        placeholders = ", ".join("?" * len(self.columns))
        q = f'INSERT OR REPLACE INTO {self.tablename} ({", ".join(self.columns)}) VALUES ({placeholders});'
        vals = [tuple(obj.dict().values()) for obj in objs]
        with self.engine as con:
            con.executemany(q, vals)
            con.commit()

        return True

    def delete_one(self, obj: M) -> Literal[True]:
        """
        Deletes the object from the database (won't delete the actual object)
        If the object has a PK field or the rowid setup, those will be 
        used to locate the obj and delete it. 
        If not, this function will delete any object like this one.
        """
        
        if obj.__pk__:
            q = f'DELETE FROM {self.tablename} WHERE {obj.__pk__} = ?'
            vals = getattr(obj, obj.__pk__),
        elif obj.__rowid__:
            q = f'DELETE FROM {self.tablename} WHERE rowid = ?'
            vals = obj.__rowid__,
        else:
            obj_dict = obj.dict()
            id_cols = tuple([k for k in obj_dict if "id" in k])
            placeholders = ", ".join(f"{k} = ?" for k in id_cols)
            vals = tuple([obj_dict[k] for k in id_cols])
            q = f"""
            DELETE FROM {self.tablename} WHERE ({placeholders});
            """
        with self.engine as con:
            con.execute(q, vals)
            con.commit()

        return True

    def delete_many(self, *objs: M) -> Literal[True]:
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
        
        with self.engine as con:
            con.execute(q, vals)
            con.commit()

        return True
