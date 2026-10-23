# 📝 Python To-Do App

A full-stack productivity app built with **Flask**, **SQLite** and **vanilla JavaScript**. Each user gets a private account and task list.

🔗 **Live demo:** https://python-todo-app-uret.onrender.com

> Hosted on Render's free plan, so the first load can take up to a minute.

## Features

- 🔐 User accounts (sign up, log in, log out) with hashed passwords
- ✅ Add, edit, complete and delete tasks
- 🏷️ Categories (Study, Work, Personal, Projects) and priorities
- 📅 Due dates with overdue and due-today warnings
- ⏱️ Stopwatch on every task, plus countdown timers with a siren alert
- 📊 Dashboard: progress ring, stats by category and priority
- 📈 7-day work graph stacked by category
- 🎯 Daily goal and streak counter
- 🎉 Confetti on completion
- 🌗 Light and dark mode
- 🔍 Search, filters and sorting

## Tech stack

Python · Flask · SQLite · Jinja2 · HTML · CSS · JavaScript · Gunicorn · Render

## Run locally

```bash
git clone https://github.com/dinesh18341/python-todo-app.git
cd python-todo-app
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

## What I learned

Building a full web app from scratch: routing, templates, authentication, a SQL database, and deploying to the cloud.