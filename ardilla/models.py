"""
Contains the Model object and typing alias to work with the engines and Cruds
"""

from typing import TypeVar
from pydantic import BaseModel, PrivateAttr

from .schemas import make_table_schema, FIELD_MAPPING, get_tablename, get_pk
from .errors import ModelIntegrityError


class Model(BaseModel):
    """
    The base model representing SQLite tables
    Inherits directly from pydantic.BaseModel
    
    Additional Attributes:
        __rowid__ (int | None): when an object is returned by a query it will 
            contain the rowid field that can be used for update and deletion.
        __pk__ (str | None): Holds the primary key column name of the table
        __tablename__ (str): the name of the table in the database
        __schema__(str): the schema for the table. Should start with `CREATE TABLE IF NOT EXISTS`
        
    Usage Example:
        from ardilla import Model, Field
        # Field is actually pydantic.Field but it's imported here for the convenience of the developer
        
        class User(Model):
            __tablename__ = 'users' # by default the tablename is just the model's name in lowercase
            id: int = Field(primary=True) # sets this field as the primary key
            name: str
    """
    __rowid__: int | None = PrivateAttr(default=None)
    __pk__: str | None  # tells the model which key to idenfity as primary
    __tablename__: str  # will default to the lowercase name of the subclass
    __schema__: str  # best effort will be made if it's missing
    # there's no support for constrains or foreign fields yet but you can
    # define your own schema to support them

    def __init_subclass__(cls, **kws) -> None:
        pk = None
        for field in cls.__fields__.values():
            if field.type_ not in FIELD_MAPPING:
                raise ModelIntegrityError(
                    f'Field "{field.name}" of model "{cls.__name__}" is of unsupported type "{field.type_}"'
                )
            if (field.field_info.extra.get('primary') 
                or field.field_info.extra.get('primary_key')):
                if getattr(cls, '__pk__', None) is not None:
                    raise ModelIntegrityError('More than one fields defined as primary')
                
                cls.__pk__ = field.name 

        if not hasattr(cls, "__schema__"):
            cls.__schema__ = make_table_schema(cls)
        
        if not hasattr(cls, '__pk__'):
            cls.__pk__ = get_pk(cls.__schema__)

        if not hasattr(cls, "__tablename__"):
            tablename = get_tablename(cls)
            setattr(cls, "__tablename__", tablename)

        super().__init_subclass__(**kws)

    def __str__(self) -> str:
        return f"{self!r}"


M = TypeVar("M", bound=Model)
