"""
Run this script ONCE to create the users table in Supabase.
This creates the table structure needed for user authentication.
"""

from supabase import create_client, Client
import os
from dotenv import load_dotenv
import hashlib

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials not found!")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# SQL to create users table
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(64) NOT NULL,
    email VARCHAR(100),
    full_name VARCHAR(100),
    is_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);
"""

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_table():
    try:
        print("Copy this SQL into Supabase SQL Editor:")
        print("="*70)
        print(CREATE_USERS_TABLE)
        print("="*70)
        
        try:
            result = supabase.table('users').select('*').limit(1).execute()
            print("\nUsers table exists!")
            return True
        except Exception:
            print("\nUsers table doesn't exist yet.")
            return False
            
    except Exception as e:
        print(f"Error: {e}")
        return False

def add_initial_admin():
    try:
        result = supabase.table('users').select('*').eq('username', 'admin').execute()
        
        if result.data:
            print("\nAdmin user already exists!")
            return
        
        admin_data = {
            'username': 'admin',
            'password_hash': hash_password('password123'),
            'email': 'admin@example.com',
            'full_name': 'Administrator',
            'is_admin': True,
            'is_active': True
        }
        
        supabase.table('users').insert(admin_data).execute()
        print("\nAdmin user created!")
        print("Username: admin")
        print("Password: password123")
        
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    print("Setting up Users Table...\n")
    table_exists = create_table()
    
    if table_exists:
        add_initial_admin()
        print("\nSetup complete!")
