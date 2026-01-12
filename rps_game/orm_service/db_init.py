import psycopg2
import json
import time
import subprocess
import sys

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def is_database_reachable(config):
    try:
        conn = psycopg2.connect(
            host=config['database']['host'],
            port=config['database']['port'],
            user=config['database']['user'],
            password=config['database']['password'],
            database='postgres'
        )
        conn.close()
        return True
    except:
        return False

def ensure_postgres_container(config):
    try:
        # Check if container exists
        result = subprocess.run(
            ['docker', 'ps', '-a', '--filter', 'name=rps-db', '--format', '{{.Names}}'],
            capture_output=True,
            text=True
        )
        
        if 'rps-db' in result.stdout:
            print("[Docker] Container exists, starting...")
            subprocess.run(['docker', 'start', 'rps-db'])
        else:
            print("[Docker] Creating new container with replication support...")
            port = config['database']['port']
            subprocess.run([
                'docker', 'run', '--name', 'rps-db',
                '-e', f"POSTGRES_USER={config['database']['user']}",
                '-e', f"POSTGRES_PASSWORD={config['database']['password']}",
                '-e', f"POSTGRES_DB={config['database']['database']}",
                '-p', f"{port}:5432",
                '-d', 'postgres',
                '-c', 'wal_level=logical',
                '-c', 'max_replication_slots=10',
                '-c', 'max_wal_senders=10'
            ])
    except Exception as e:
        print(f"[Docker Error] {e}")

def create_schema(config):
    try:
        # Connect to postgres database first
        conn = psycopg2.connect(
            host=config['database']['host'],
            port=config['database']['port'],
            user=config['database']['user'],
            password=config['database']['password'],
            database='postgres'
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config['database']['database'],))
        if not cursor.fetchone():
            cursor.execute(f"CREATE DATABASE {config['database']['database']}")
            print(f"[DB] Database '{config['database']['database']}' created.")
        
        cursor.close()
        conn.close()
        
        # Connect to the game database
        conn = psycopg2.connect(
            host=config['database']['host'],
            port=config['database']['port'],
            user=config['database']['user'],
            password=config['database']['password'],
            database=config['database']['database']
        )
        cursor = conn.cursor()
        
        # Create games table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id VARCHAR(50) PRIMARY KEY,
                player1 VARCHAR(100),
                player2 VARCHAR(100),
                player1_choice VARCHAR(20),
                player2_choice VARCHAR(20),
                status VARCHAR(20),
                player1_score INTEGER DEFAULT 0,
                player2_score INTEGER DEFAULT 0
            )
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        print("[DB] Schema ready.")
        
    except Exception as e:
        print(f"[DB Error] {e}")

def initialize():
    print("[DB] Initializing...")
    config = load_config()
    
    if not is_database_reachable(config):
        print("[DB] Database not reachable. Starting Docker container...")
        ensure_postgres_container(config)
        
        # Wait for database to be ready
        for i in range(15):
            if is_database_reachable(config):
                break
            time.sleep(1)
    
    create_schema(config)

if __name__ == '__main__':
    initialize()
