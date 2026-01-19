"""
User authentication utilities for the AI Language Tutor app.
This module handles user login, password hashing, and user management with Supabase.
"""

import hashlib
from datetime import datetime
from typing import Optional, Dict, List
from supabase import Client

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    return hash_password(password) == password_hash

def authenticate_user(supabase: Client, username: str, password: str) -> Optional[Dict]:
    """
    Authenticate a user against the database.
    Returns user data if successful, None otherwise.
    """
    try:
        # Query user by username
        result = supabase.table('users').select('*').eq('username', username).execute()
        
        if not result.data:
            return None
        
        user = result.data[0]
        
        # Check if user is active
        if not user.get('is_active', True):
            return None
        
        # Verify password
        if verify_password(password, user['password_hash']):
            # Update last login
            supabase.table('users').update({
                'last_login': datetime.now().isoformat()
            }).eq('id', user['id']).execute()
            
            return user
        
        return None
        
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

def create_user(
    supabase: Client,
    username: str,
    password: str,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    is_admin: bool = False
) -> Optional[Dict]:
    """
    Create a new user in the database.
    Returns user data if successful, None otherwise.
    """
    try:
        # Check if username already exists
        existing = supabase.table('users').select('id').eq('username', username).execute()
        if existing.data:
            raise ValueError(f"Username '{username}' already exists")
        
        user_data = {
            'username': username,
            'password_hash': hash_password(password),
            'email': email,
            'full_name': full_name,
            'is_admin': is_admin,
            'is_active': True
        }
        
        result = supabase.table('users').insert(user_data).execute()
        return result.data[0] if result.data else None
        
    except Exception as e:
        print(f"Error creating user: {e}")
        return None

def get_all_users(supabase: Client) -> List[Dict]:
    """Get all users from the database (admin only)"""
    try:
        result = supabase.table('users').select('id, username, email, full_name, is_admin, is_active, created_at, last_login').execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"Error fetching users: {e}")
        return []

def update_user(
    supabase: Client,
    user_id: int,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    is_admin: Optional[bool] = None,
    is_active: Optional[bool] = None
) -> bool:
    """Update user information (admin only)"""
    try:
        update_data = {}
        if email is not None:
            update_data['email'] = email
        if full_name is not None:
            update_data['full_name'] = full_name
        if is_admin is not None:
            update_data['is_admin'] = is_admin
        if is_active is not None:
            update_data['is_active'] = is_active
        
        if update_data:
            supabase.table('users').update(update_data).eq('id', user_id).execute()
        return True
    except Exception as e:
        print(f"Error updating user: {e}")
        return False

def change_password(supabase: Client, user_id: int, new_password: str) -> bool:
    """Change user password"""
    try:
        supabase.table('users').update({
            'password_hash': hash_password(new_password)
        }).eq('id', user_id).execute()
        return True
    except Exception as e:
        print(f"Error changing password: {e}")
        return False

def delete_user(supabase: Client, user_id: int) -> bool:
    """Delete a user (admin only)"""
    try:
        supabase.table('users').delete().eq('id', user_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting user: {e}")
        return False
