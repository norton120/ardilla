from __future__ import annotations
import sqlite3
from pydantic import BaseModel

from .models import M, Model
from .crud import Crud
from .abc import AbstractEngine, ContextCursorProtocol
from .logging import log

class ContextCursor(ContextCursorProtocol):
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def __enter__(self) -> sqlite3.Cursor:
        self.cur = self.con.cursor()
        return self.cur

    def __exit__(self, *_) -> None:
        self.cur.close()


class Engine(AbstractEngine):
    
    def __init__(self, path: str):
        self.path = path
        self.schemas: set[str] = set()
        self._cruds: dict[type[Model], Crud[Model]] = {}
        self.tables_created: set[str] = set()
        log.info(f'Instantiating {self.__class__.__name__}')

    def __enter__(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        self.con = con
        return con

    def __exit__(self, *_):
        self.con.close()

    def cursor(self, con: sqlite3.Connection) -> ContextCursor:
        return ContextCursor(con)

    def setup(self):
        with self as con:
            con.execute("PRAGMA foreign_keys = ON;")
            for table in self.schemas:
                con.execute(table)
                self.tables_created.add(table)
            con.commit()
            
    
    def crud(self, Model: type[M]) -> Crud[M]:
        crud = self._cruds.setdefault(Model, Crud(Model, self))
        if Model.__schema__ not in self.tables_created:
            with self as con:
                con.execute(Model.__schema__)
                con.commit()
            self.tables_created.add(Model.__schema__)
        return crud