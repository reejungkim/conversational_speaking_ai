"""
Admin panel for managing users in the AI Language Tutor app.
Access this page at: streamlit run admin_panel.py
"""

import streamlit as st
from supabase import create_client, Client
import os
from user_auth import (
    create_user, get_all_users, update_user, 
    delete_user, change_password, authenticate_user
)

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Admin Panel - User Management",
    page_icon="🔐",
    layout="wide"
)

# --- CREDENTIALS ---
def get_supabase_creds():
    try:
        if "supabase" in st.secrets:
            url = st.secrets["supabase"].get("url")
            key = st.secrets["supabase"].get("key")
            if url and key:
                return url, key
    except Exception:
        pass
    return os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")

SUPABASE_URL, SUPABASE_KEY = get_supabase_creds()

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Missing Supabase Credentials!")
    st.stop()

supabase = Client(SUPABASE_URL, SUPABASE_KEY)

# --- ADMIN LOGIN ---
def check_admin_login():
    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False
        st.session_state.admin_user = None

    if st.session_state.admin_logged_in:
        return True

    st.markdown("## 🔐 Admin Login")
    st.markdown("Please log in with an admin account to access the user management panel.")
    
    with st.form("admin_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
        
        if submitted:
            user = authenticate_user(supabase, username, password)
            if user and user.get('is_admin'):
                st.session_state.admin_logged_in = True
                st.session_state.admin_user = user
                st.rerun()
            else:
                st.error("Invalid credentials or not an admin account")
    
    return False

if not check_admin_login():
    st.stop()

# --- MAIN ADMIN PANEL ---
st.title("🔐 User Management Panel")
st.markdown(f"Welcome, **{st.session_state.admin_user['full_name'] or st.session_state.admin_user['username']}**!")

# Logout button
if st.button("Logout", type="secondary"):
    st.session_state.admin_logged_in = False
    st.session_state.admin_user = None
    st.rerun()

st.markdown("---")

# Tabs for different actions
tab1, tab2, tab3 = st.tabs(["📋 View Users", "➕ Add User", "📊 Database Setup"])

# --- TAB 1: View & Manage Users ---
with tab1:
    st.subheader("Registered Users")
    
    users = get_all_users(supabase)
    
    if users:
        for user in users:
            with st.expander(f"👤 {user['username']} ({user['full_name'] or 'No name'})"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**ID:** {user['id']}")
                    st.write(f"**Username:** {user['username']}")
                    st.write(f"**Email:** {user['email'] or 'Not set'}")
                    st.write(f"**Full Name:** {user['full_name'] or 'Not set'}")
                
                with col2:
                    st.write(f"**Admin:** {'Yes' if user['is_admin'] else 'No'}")
                    st.write(f"**Active:** {'Yes' if user['is_active'] else 'No'}")
                    st.write(f"**Created:** {user['created_at'][:10] if user['created_at'] else 'N/A'}")
                    st.write(f"**Last Login:** {user['last_login'][:10] if user['last_login'] else 'Never'}")
                
                st.markdown("---")
                
                # Action buttons
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if st.button(f"Toggle Active", key=f"active_{user['id']}"):
                        new_status = not user['is_active']
                        if update_user(supabase, user['id'], is_active=new_status):
                            st.success(f"User {'activated' if new_status else 'deactivated'}!")
                            st.rerun()
                
                with col2:
                    if st.button(f"Toggle Admin", key=f"admin_{user['id']}"):
                        new_status = not user['is_admin']
                        if update_user(supabase, user['id'], is_admin=new_status):
                            st.success(f"Admin status updated!")
                            st.rerun()
                
                with col3:
                    if user['username'] != 'admin':  # Prevent deleting main admin
                        if st.button(f"Delete User", key=f"delete_{user['id']}", type="primary"):
                            if delete_user(supabase, user['id']):
                                st.success(f"User deleted!")
                                st.rerun()
                            else:
                                st.error("Failed to delete user")
    else:
        st.info("No users found. Create the users table first in Tab 3.")

# --- TAB 2: Add New User ---
with tab2:
    st.subheader("Add New User")
    
    with st.form("add_user_form"):
        new_username = st.text_input("Username *", help="Unique username for login")
        new_password = st.text_input("Password *", type="password", help="User's password")
        new_email = st.text_input("Email", help="Optional email address")
        new_full_name = st.text_input("Full Name", help="Optional full name")
        new_is_admin = st.checkbox("Admin privileges", help="Grant admin access")
        
        submitted = st.form_submit_button("Create User")
        
        if submitted:
            if not new_username or not new_password:
                st.error("Username and password are required!")
            else:
                user = create_user(
                    supabase,
                    new_username,
                    new_password,
                    new_email if new_email else None,
                    new_full_name if new_full_name else None,
                    new_is_admin
                )
                
                if user:
                    st.success(f"✅ User '{new_username}' created successfully!")
                    st.info("The user can now log in to the main app.")
                else:
                    st.error("Failed to create user. Username might already exist.")

# --- TAB 3: Database Setup ---
with tab3:
    st.subheader("Database Setup Instructions")
    
    st.markdown("""
    ### Initial Setup
    
    If this is your first time using the user management system, follow these steps:
    
    1. **Create the users table** in your Supabase database
    2. **Add your first admin user**
    3. Start managing users through this panel
    """)
    
    st.markdown("---")
    
    st.markdown("### Step 1: Create Users Table")
    st.markdown("Copy and paste this SQL into your **Supabase SQL Editor**:")
    
    sql_code = """
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
    
    st.code(sql_code, language="sql")
    
    st.markdown("---")
    
    st.markdown("### Step 2: Test Connection")
    if st.button("Test Database Connection"):
        try:
            users = get_all_users(supabase)
            st.success(f"✅ Connection successful! Found {len(users)} users.")
        except Exception as e:
            st.error(f"❌ Connection failed: {e}")
            st.info("Make sure you've created the users table first (Step 1)")
