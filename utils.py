import streamlit as st
from supabase import create_client, Client

# Initialize the connection once and cache it
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

# Create the client instance
supabase = init_supabase()