import psycopg2
from sqlalchemy import create_engine
from config.settings import DB_CONFIG

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def get_engine():
    return create_engine(
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}/{DB_CONFIG['dbname']}"
    )