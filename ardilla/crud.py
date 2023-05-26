from __future__ import annotations
from functools import wraps
import sqlite3
from sqlite3 import Row
from typing import Literal, Generic, Optional, Union

from .abc import CrudABC, AbstractEngine
from .models import M
from .errors import QueryExecutionError
from .logging import log
from .schemas import SQLFieldType
from . import queries


def verify_kws(f):
    """
    Decorator for sync Crud methods to prevent
    injection in the keys of the CRUD methods
    """
    @wraps(f)
    def wrapper(self: Crud, *ags, **kws):
        for key in kws:
            if key not in self.Model.__fields__:
                raise KeyError(f'"{key}" is not a field of the "{self.Model.__name__}" and cannot be used in queries')
        return f(self, *ags, **kws)
    return wrapper

class Crud(CrudABC, Generic[M]):
    """Abstracts CRUD actions for model associated tables"""

    engine: AbstractEngine

    def _do_insert(
        self,
        ignore: bool = False,
        returning: bool = True,
        /,
        **kws: SQLFieldType,
    ) -> Optional[M]:
        """private helper method for insertion methods

        Args:
            ignore (bool, optional): Ignores conflicts silently. Defaults to False.
            returning (bool, optional): Determines if the query should return the inserted row. Defaults to True.
            kws (SQLFieldType): the column name and values for the insert query

        Raises:
            QueryExecutionError: when sqlite3.IntegrityError happens because of a conflic

        Returns:
            An instance of model if any row is returned
        """
        q, vals = queries.for_do_insert(self.tablename, ignore, returning, kws)

        with self.engine as con:
            with self.engine.cursor(con) as cur:
                try:
                    cur.execute(q, vals)
                except sqlite3.IntegrityError as e:
                    raise QueryExecutionError(str(e))

                row = cur.fetchone()
                con.commit()
                if returning and row:
                    return self._row2obj(row, cur.lastrowid)

        return None

    @verify_kws
    def get_or_none(self, **kws: SQLFieldType) -> Optional[M]:
        """Returns a row as an instance of the model if one is found or none

        Args:
            kws (SQLFieldType): The keyword arguments are passed as column names and values to 
                a select query
            
        Example: 
            ```py
            crud.get_or_none(id=42)
            
            # returns an object with id of 42 or None if there isn't one in the database 
            ```
        
        Returns:
            The object found with the criteria if any
        """
        q, vals = queries.for_get_or_none(self.tablename, kws)
        with self.engine as con:
            ctxcur = self.engine.cursor(con)
            with ctxcur as cur:
                cur.execute(q, vals)
                row: Union[Row, None] = cur.fetchone()
                if row:
                    return self._row2obj(row)
        return None

    @verify_kws
    def insert(self, **kws: SQLFieldType) -> M:
        """Inserts a record into the database.
        
        Args:
            kws (SQLFieldType): The keyword arguments are passed as the column names and values
                to the insert query
        
        Returns:
            Creates a new entry in the database and returns the object
            
        Rises:
            `ardilla.error.QueryExecutionError`: if there's a conflict when inserting the record
        """
        return self._do_insert(False, True, **kws)

    @verify_kws
    def insert_or_ignore(self, **kws: SQLFieldType) -> Optional[M]:
        """Inserts a record to the database with the keywords passed. It ignores conflicts.
        
        Args:
            kws (SQLFieldType): The keyword arguments are passed as the column names and values
                to the insert query

        Returns:
            The newly created row as an instance of the model if there was no conflicts
        """
        return self._do_insert(True, True, **kws)


    @verify_kws
    def get_or_create(self, **kws: SQLFieldType) -> tuple[M, bool]:
        """Returns an object from the database with the spefied matching data
        Args:
            kws (SQLFieldType): the key value pairs will be used to query for an existing row
                if no record is found then a new row will be inserted
        Returns:
            A tuple with two values, the object and a boolean indicating if the 
                object was newly created or not
        """
        created = False
        result = self.get_or_none(**kws)
        if not result:
            result = self.insert_or_ignore(**kws)
            created = True
        return result, created

    def get_all(self) -> list[M]:
        """Gets all objects from the database
        Returns:
            A list with all the rows in table as instances of the model
        """
        return self.get_many()

    def get_many(
        self,
        order_by: Optional[dict[str, str]] = None,
        limit: Optional[int] = None,
        **kws: SQLFieldType,
    ) -> list[M]:
        """Queries the database and returns objects that meet the criteris

        Args:
            order_by (Optional[dict[str, str]], optional): An ordering dict. Defaults to None.
                The ordering should have the structure: `{'column_name': 'ASC' OR 'DESC'}`
                Case in values is insensitive
            
            limit (Optional[int], optional): The number of items to return. Defaults to None.
            kws (SQLFieldType): The column names and values for the select query

        Returns:
            a list of rows matching the criteria as intences of the model
        """
        for key in kws:
            if key not in self.Model.__fields__:
                raise KeyError(f'"{key}" is not a field of the "{self.Model.__name__}" and cannot be used in queries')
        q, vals = queries.for_get_many(self.Model, order_by=order_by, limit=limit, kws=kws)
        with self.engine as con:
            ctxcur = self.engine.cursor(con)
            with ctxcur as cur:
                cur.execute(q, vals)
                rows: list[Row] = cur.fetchall()
                return [self._row2obj(row) for row in rows]

    def save_one(self, obj: M) -> Literal[True]:
        """Saves one object to the database

        Args:
            obj (M): the object to persist

        Returns:
            The literal `True` if the method ran successfuly
        """
        q, vals = queries.for_save_one(obj)

        with self.engine as con:
            con.execute(q, vals)
            con.commit()
        return True

    def save_many(self, *objs: tuple[M]) -> Literal[True]:
        """Saves all the passed objects to the database

        Args:
            objs (M): the objects to persist

        Returns:
            The literal `True` if the method ran successfuly
        """        
        q, vals = queries.for_save_many(objs)
        with self.engine as con:
            con.executemany(q, vals)
            con.commit()

        return True

    def delete_one(self, obj: M) -> Literal[True]:
        """
        Deletes the object from the database (won't delete the actual object)
        If the object has a PK field or the rowid setup, those will be
        used to locate the obj and delete it.
        If not, this function will delete any row that meets the values of the object


        Args:
            obj (M): the object to delete

        Returns:
            The literal `True` if the method ran successfuly
            
        """
        
        q, vals = queries.for_delete_one(obj)
        with self.engine as con:
            con.execute(q, vals)
            con.commit()

        return True

    def delete_many(self, *objs: M) -> Literal[True]:
        """
        Deletes all the objects passed

        Args:
            objs (M): the object to delete

        Returns:
            The literal `True` if the method ran successfuly
            
        """
        q, vals = queries.for_delete_many(objs)
        with self.engine as con:
            con.execute(q, vals)
            con.commit()

        return True
