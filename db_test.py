import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv("/Users/reejungkim/Documents/00_Git/01_conversational_speaking_ai/.venv/.env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(url, key)

def get_todos():
    response = supabase.table('todos').select('*').execute()
    return response.data


def add_todo(task):
    supabase.table('todos').insert({'task': task}).execute()

st.title("Supabase Todo App")

task = st.text_input("Add a new task:")
if st.button("Add Task"):
    if task:
        add_todo(task)
        st.success("Task added!")
    else:
        st.error("Please enter a task.")

st.write("### Todo List:")
todos = get_todos()
if todos:
    for todo in todos:
        st.write(f"- {todo['task']}")
else:
    st.write("No tasks available.")