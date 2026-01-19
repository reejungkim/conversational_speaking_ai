# User Management System - Setup Guide

## Overview

The AI Language Tutor now includes a complete user authentication system using Supabase. This allows you to:

- Create multiple user accounts
- Manage users through an admin panel
- Grant admin privileges to specific users
- Activate/deactivate user accounts
- Works both locally and on Streamlit Cloud

## Quick Start

### 1. Create the Users Table in Supabase

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor**
3. Copy and paste this SQL:

```sql
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
```

4. Click **Run** to create the table

### 2. Create Your First Admin User

After creating the table, add your first admin user by running this SQL:

```sql
INSERT INTO users (username, password_hash, email, full_name, is_admin, is_active)
VALUES (
    'admin',
    'ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f',  -- password: password123
    'admin@example.com',
    'Administrator',
    true,
    true
);
```

**⚠️ IMPORTANT:** Change the admin password immediately after first login!

### 3. Access the Admin Panel

Run the admin panel locally:

```bash
streamlit run admin_panel.py
```

Log in with:
- Username: `admin`
- Password: `password123`

### 4. Add More Users

#### Option A: Through Admin Panel (Recommended)
1. Open the admin panel
2. Go to the "Add User" tab
3. Fill in the user details
4. Click "Create User"

#### Option B: Through SQL
```sql
-- Example: Add a regular user
INSERT INTO users (username, password_hash, email, full_name, is_admin)
VALUES (
    'johndoe',
    -- Use user_auth.py hash_password() to generate this
    'HASHED_PASSWORD_HERE',
    'john@example.com',
    'John Doe',
    false
);
```

## How It Works

### Authentication Flow

1. User enters username and password in `app.py`
2. System checks Supabase `users` table first
3. If not found, falls back to `secrets.toml` (for backward compatibility)
4. On successful login:
   - User session is created
   - Last login timestamp is updated
   - User info is stored in `st.session_state`

### Password Security

- Passwords are hashed using SHA-256
- Only hashes are stored in the database
- Original passwords are never stored
- Passwords are immediately deleted from session state after authentication

## Admin Panel Features

### View Users
- See all registered users
- View user details (email, name, status)
- See last login times
- Toggle user active/inactive status
- Toggle admin privileges
- Delete users (except main admin)

### Add Users
- Create new user accounts
- Set email and full name
- Grant admin privileges
- Users can immediately log in to the main app

### Database Setup
- Test database connection
- View setup instructions
- SQL code for manual setup

## User Management Tasks

### Change User Password

Use the admin panel or run this in Python:

```python
from user_auth import change_password
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
change_password(supabase, user_id=1, new_password="new_secure_password")
```

### Deactivate a User

Through admin panel or SQL:

```sql
UPDATE users SET is_active = false WHERE username = 'username';
```

### Make a User Admin

Through admin panel or SQL:

```sql
UPDATE users SET is_admin = true WHERE username = 'username';
```

## Deployment on Streamlit Cloud

### Main App (app.py)

The main app will automatically use the Supabase authentication when deployed. Make sure your `secrets.toml` is configured in Streamlit Cloud settings.

### Admin Panel (admin_panel.py)

To deploy the admin panel separately on Streamlit Cloud:

1. Create a new app in Streamlit Cloud
2. Point it to `admin_panel.py`
3. Use the same secrets configuration
4. Share the URL only with admin users

## Troubleshooting

### "No users found" in admin panel

**Solution:** Create the users table in Supabase (Step 1)

### "Connection failed" error

**Solution:** 
- Check Supabase credentials in secrets.toml
- Verify table exists: `SELECT * FROM users LIMIT 1;`

### Can't log in with new user

**Solutions:**
- Verify user is active: `SELECT username, is_active FROM users;`
- Check password was set correctly
- Try resetting password through admin panel

### Users table not found

**Solution:** Run the CREATE TABLE SQL in Supabase SQL Editor

## Security Best Practices

1. **Change default admin password immediately**
2. **Use strong passwords** (min 12 characters, mix of letters, numbers, symbols)
3. **Keep admin panel URL private** (don't share publicly)
4. **Regularly review user access** through admin panel
5. **Deactivate unused accounts** instead of deleting
6. **Limit admin privileges** to trusted users only

## API Reference

### user_auth.py Functions

```python
# Authenticate user
user = authenticate_user(supabase, username, password)

# Create new user
user = create_user(supabase, username, password, email, full_name, is_admin)

# Get all users
users = get_all_users(supabase)

# Update user
update_user(supabase, user_id, email, full_name, is_admin, is_active)

# Change password
change_password(supabase, user_id, new_password)

# Delete user
delete_user(supabase, user_id)

# Hash password
hashed = hash_password("plain_text_password")

# Verify password
is_valid = verify_password("plain_text", hashed_password)
```

## Files

- `user_auth.py` - Authentication utilities
- `admin_panel.py` - Admin interface for user management
- `app.py` - Main application (updated with Supabase auth)
- `USER_MANAGEMENT.md` - This guide

## Support

For issues or questions:
1. Check troubleshooting section above
2. Verify Supabase connection and table structure
3. Check Streamlit logs for error details

## Future Enhancements

Possible additions:
- Email verification
- Password reset functionality
- Role-based permissions (beyond admin/user)
- User activity logging
- Password strength requirements
- Two-factor authentication
